# SPDX-License-Identifier: Apache-2.0
"""RCBD analysis of variance.

Computes the analysis-of-variance table (block / treatment / error / total),
treatment means, the grand mean, and the coefficient of variation for one numeric
assessment of a randomized complete block design -- the statistical core of the
AOV Means Table. The math is native (numpy); the p-values come from the
self-authored F-distribution (decision 0002). statsmodels and published tables
validate it in the tests, never at runtime.

Per decision 0003 the MVP requires a complete table: if any plot x assessment
cell is missing, the analysis is rejected with an error that names the missing
cells rather than silently analyzing an incomplete design.
"""

from __future__ import annotations

import math

import numpy
from pydantic import BaseModel, ConfigDict

from openfurrow.analysis.distributions import fDistributionSurvival
from openfurrow.analysis.transforms import TransformError, applyTransform, checkTransformKind
from openfurrow.schema.layout import TrialLayout
from openfurrow.schema.observation import Observation
from openfurrow.schema.trialPackage import AssessmentDataType, DesignType, Transform, TrialPackage


class AnalysisError(ValueError):
  """The requested analysis cannot be performed on the given inputs."""


class AnovaSource(BaseModel):
  """One row of the ANOVA table (a source of variation)."""

  model_config = ConfigDict(extra="forbid")

  source: str
  degreesOfFreedom: int
  sumOfSquares: float
  meanSquare: float | None = None
  fStatistic: float | None = None
  pValue: float | None = None


class TreatmentMean(BaseModel):
  """A treatment's mean response and the number of observations behind it."""

  model_config = ConfigDict(extra="forbid")

  treatmentCode: str
  mean: float
  observationCount: int


class AnovaResult(BaseModel):
  """The AOV result for one assessment: the table plus summary statistics."""

  model_config = ConfigDict(extra="forbid")

  assessmentCode: str
  designType: DesignType
  transform: Transform
  treatmentCount: int
  blockCount: int
  grandMean: float
  coefficientOfVariation: float
  errorMeanSquare: float
  errorDegreesOfFreedom: int
  table: list[AnovaSource]
  treatmentMeans: list[TreatmentMean]


def buildRcbdMatrix(
  assessmentCode: str,
  package: TrialPackage,
  layout: TrialLayout,
  observations: list[Observation],
) -> tuple[numpy.ndarray, list[str], list[int]]:
  """Validate inputs and build the block-by-treatment value matrix for an RCBD.

  Shared by the ANOVA and its assumption diagnostics so the structural checks and
  the transform live in one place: the assessment's declared transform (decision
  0006) is applied here, so both paths run on the same scale. Returns the transformed
  matrix (rows = blocks, columns = treatments, in package treatment order and block
  order 1..b), the treatment codes, the block numbers, and the transform that was
  applied. Raises AnalysisError -- naming missing cells, or the offending values for a
  transform domain or kind violation -- rather than proceeding on an incomplete,
  non-numeric, or ill-transformed design.
  """
  assessment = next((a for a in package.assessments if a.assessmentCode == assessmentCode), None)
  if assessment is None:
    raise AnalysisError(f"assessment '{assessmentCode}' is not defined in the trial package")
  if assessment.dataType is not AssessmentDataType.numeric:
    raise AnalysisError(
      f"assessment '{assessmentCode}' is {assessment.dataType.value}; RCBD ANOVA requires a numeric assessment"
    )
  if layout.designType is not DesignType.rcbd:
    raise AnalysisError(f"analyzeRcbd requires an RCBD layout, got {layout.designType.value}")
  if layout.trialCode != package.trial.trialCode:
    raise AnalysisError(
      f"layout trialCode '{layout.trialCode}' does not match package trial '{package.trial.trialCode}'"
    )

  treatmentCodes = [treatment.treatmentCode for treatment in package.treatments]
  blocks = list(range(1, layout.replications + 1))
  treatmentCount = len(treatmentCodes)
  blockCount = len(blocks)

  plotCellByNumber = {plot.plotNumber: (plot.treatmentCode, plot.block) for plot in layout.plots}
  plotNumberByCell = {cell: plotNumber for plotNumber, cell in plotCellByNumber.items()}

  cellValue: dict[tuple[str, int], float] = {}
  for observation in observations:
    if observation.assessmentCode != assessmentCode:
      continue
    cell = plotCellByNumber.get(observation.plotNumber)
    if cell is None:
      raise AnalysisError(f"observation references plot {observation.plotNumber} not in the layout")
    if observation.value is None:
      continue  # explicitly missing; caught by the completeness check below
    cellValue[cell] = float(observation.value)

  missing = [
    (plotNumberByCell.get((treatmentCode, block)), treatmentCode, block)
    for treatmentCode in treatmentCodes
    for block in blocks
    if (treatmentCode, block) not in cellValue
  ]
  if missing:
    named = ", ".join(
      f"plot {plotNumber} (treatment {treatmentCode}, block {block})"
      for plotNumber, treatmentCode, block in sorted(missing, key=lambda item: (item[2], item[1]))
    )
    raise AnalysisError(
      f"assessment '{assessmentCode}' has missing values; RCBD ANOVA requires a complete table. "
      f"Missing: {named}"
    )

  matrix = numpy.empty((blockCount, treatmentCount), dtype=float)
  for treatmentIndex, treatmentCode in enumerate(treatmentCodes):
    for blockIndex, block in enumerate(blocks):
      matrix[blockIndex, treatmentIndex] = cellValue[(treatmentCode, block)]

  # Analysis and diagnostics run on the declared scale (decision 0006): apply the
  # assessment's transform here, at the single shared matrix boundary, so both paths
  # see identical data. A domain or kind violation becomes an AnalysisError naming the
  # assessment -- the same fail-loud path as a missing cell.
  try:
    checkTransformKind(assessment.transform, assessment.measurementKind)
    if assessment.transform is not Transform.none:
      transformedValues = applyTransform(assessment.transform, matrix.ravel().tolist())
      matrix = numpy.array(transformedValues, dtype=float).reshape(matrix.shape)
  except TransformError as error:
    raise AnalysisError(f"assessment '{assessmentCode}': {error}") from error
  return matrix, treatmentCodes, blocks, assessment.transform


def analyzeRcbd(
  assessmentCode: str,
  package: TrialPackage,
  layout: TrialLayout,
  observations: list[Observation],
) -> AnovaResult:
  """Run the RCBD ANOVA for one numeric assessment."""
  matrix, treatmentCodes, blocks, transform = buildRcbdMatrix(assessmentCode, package, layout, observations)
  treatmentCount = len(treatmentCodes)
  blockCount = len(blocks)

  grandMean = float(matrix.mean())
  treatmentMeansArray = matrix.mean(axis=0)
  blockMeansArray = matrix.mean(axis=1)

  sumOfSquaresTotal = float(((matrix - grandMean) ** 2).sum())
  sumOfSquaresTreatment = float(blockCount * ((treatmentMeansArray - grandMean) ** 2).sum())
  sumOfSquaresBlock = float(treatmentCount * ((blockMeansArray - grandMean) ** 2).sum())
  sumOfSquaresError = sumOfSquaresTotal - sumOfSquaresTreatment - sumOfSquaresBlock
  if sumOfSquaresError < -1.0e-7 * max(1.0, sumOfSquaresTotal):
    raise AnalysisError("internal error: negative error sum of squares")
  sumOfSquaresError = max(sumOfSquaresError, 0.0)

  dfTreatment = treatmentCount - 1
  dfBlock = blockCount - 1
  dfError = dfTreatment * dfBlock
  dfTotal = treatmentCount * blockCount - 1

  meanSquareTreatment = sumOfSquaresTreatment / dfTreatment
  meanSquareBlock = sumOfSquaresBlock / dfBlock
  meanSquareError = sumOfSquaresError / dfError

  if meanSquareError == 0.0:
    raise AnalysisError(
      f"assessment '{assessmentCode}': error mean square is zero (no residual variation); "
      f"AOV cannot be computed"
    )
  if grandMean == 0.0:
    raise AnalysisError(
      f"assessment '{assessmentCode}': grand mean is zero; coefficient of variation is undefined"
    )

  fTreatment = meanSquareTreatment / meanSquareError
  fBlock = meanSquareBlock / meanSquareError
  pTreatment = fDistributionSurvival(fTreatment, dfTreatment, dfError)
  pBlock = fDistributionSurvival(fBlock, dfBlock, dfError)
  coefficientOfVariation = 100.0 * math.sqrt(meanSquareError) / abs(grandMean)

  table = [
    AnovaSource(
      source="block", degreesOfFreedom=dfBlock, sumOfSquares=sumOfSquaresBlock,
      meanSquare=meanSquareBlock, fStatistic=fBlock, pValue=pBlock,
    ),
    AnovaSource(
      source="treatment", degreesOfFreedom=dfTreatment, sumOfSquares=sumOfSquaresTreatment,
      meanSquare=meanSquareTreatment, fStatistic=fTreatment, pValue=pTreatment,
    ),
    AnovaSource(
      source="error", degreesOfFreedom=dfError, sumOfSquares=sumOfSquaresError,
      meanSquare=meanSquareError,
    ),
    AnovaSource(source="total", degreesOfFreedom=dfTotal, sumOfSquares=sumOfSquaresTotal),
  ]
  treatmentMeans = [
    TreatmentMean(treatmentCode=treatmentCode, mean=float(treatmentMeansArray[treatmentIndex]), observationCount=blockCount)
    for treatmentIndex, treatmentCode in enumerate(treatmentCodes)
  ]

  return AnovaResult(
    assessmentCode=assessmentCode,
    designType=DesignType.rcbd,
    transform=transform,
    treatmentCount=treatmentCount,
    blockCount=blockCount,
    grandMean=grandMean,
    coefficientOfVariation=coefficientOfVariation,
    errorMeanSquare=meanSquareError,
    errorDegreesOfFreedom=dfError,
    table=table,
    treatmentMeans=treatmentMeans,
  )
