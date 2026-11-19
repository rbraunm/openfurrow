# SPDX-License-Identifier: Apache-2.0
"""The analysis-of-variance result, and the arithmetic of a complete table of blocks and treatments.

Holds what every single-error analysis shares: the result (the table of sources, the
treatment means with the covariance their standard errors come from, the grand mean and
the coefficient of variation), the collection of an assessment's plot values into a
block-by-treatment table on the analysed scale, and the classical sums of squares of a
complete table. The math is native (numpy); the p-values come from the self-authored
F-distribution (decision 0002). statsmodels and published tables validate it in the
tests, never at runtime.

A table with a missing plot is not analysed here: `rcbd` and `crd` apply the missing-plot
policy (decisions 0003, 0043), and every other analysis refuses it by name.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy
from pydantic import BaseModel, ConfigDict

from openfurrow.analysis.distributions import fDistributionSurvival
from openfurrow.analysis.missingPlots import (
  MissingCell,
  MissingPlotEstimation,
  MissingPlotPolicy,
  SumsOfSquares,
  coveredDesigns,
)
from openfurrow.analysis.transforms import TransformError, applyTransform, checkTransformKind
from openfurrow.schema.layout import TrialLayout
from openfurrow.schema.observation import Observation
from openfurrow.schema.assessment import AssessmentDataType, Transform
from openfurrow.schema.trialPackage import DesignType, TrialPackage


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
  """The AOV result for one assessment: the table plus summary statistics.

  `missingCells` lists every plot that had no value and how it was handled under
  `missingPlotPolicy`; when it is not empty the treatment means are adjusted means and the
  grand mean is their mean. `meanCovariance` is the covariance matrix of the treatment
  means in units of the error variance, in the order of `treatmentMeans`: every standard
  error of a mean or of a difference is the square root of the error mean square times a
  combination of its entries (`meanStandardError`, `differenceStandardError`).
  """

  model_config = ConfigDict(extra="forbid")

  assessmentCode: str
  designType: DesignType
  transform: Transform
  transformOffset: float
  treatmentCount: int
  blockCount: int
  grandMean: float
  coefficientOfVariation: float
  errorMeanSquare: float
  errorDegreesOfFreedom: int
  sumsOfSquares: SumsOfSquares
  table: list[AnovaSource]
  treatmentMeans: list[TreatmentMean]
  meanCovariance: list[list[float]]
  missingPlotPolicy: MissingPlotPolicy
  missingCells: list[MissingCell]
  estimation: MissingPlotEstimation | None = None


def meanStandardError(result: AnovaResult, index: int) -> float:
  """The standard error of the treatment mean at `index` of the result's means."""
  return math.sqrt(result.errorMeanSquare * result.meanCovariance[index][index])


def differenceStandardError(result: AnovaResult, first: int, second: int) -> float:
  """The standard error of the difference between two of the result's treatment means."""
  covariance = result.meanCovariance
  return math.sqrt(
    result.errorMeanSquare * (covariance[first][first] + covariance[second][second] - 2.0 * covariance[first][second])
  )


@dataclass(frozen=True)
class BlockTreatmentCells:
  """One assessment's plot values as a block-by-treatment table on the analysed scale.

  `values` and `plotNumbers` are indexed [block, treatment], in block order 1..b and
  package treatment order; a plot without a value holds nan and is listed in `missing`
  as (plot number, treatment code, block).
  """

  values: numpy.ndarray
  plotNumbers: numpy.ndarray
  treatmentCodes: list[str]
  blocks: list[int]
  transform: Transform
  transformOffset: float
  missing: list[tuple[int, str, int]]


def missingValuesError(assessmentCode: str, missing: list[tuple[int, str, int | None]], why: str) -> AnalysisError:
  """The refusal of a table with missing plots: why, and every missing plot by number, treatment and block."""
  named = ", ".join(
    f"plot {plotNumber} (treatment {treatmentCode}" + ("" if block is None else f", block {block}") + ")"
    for plotNumber, treatmentCode, block in missing
  )
  return AnalysisError(f"assessment '{assessmentCode}' has missing values; {why}. Missing: {named}")


def numericRating(assessmentCode: str, package: TrialPackage, analysis: str):
  """The rating of a numeric assessment; an unknown or non-numeric assessment is refused, naming the analysis."""
  try:
    rating = package.ratingFor(assessmentCode)
  except KeyError as error:
    raise AnalysisError(error.args[0]) from error
  if rating.dataType is not AssessmentDataType.numeric:
    raise AnalysisError(
      f"assessment '{assessmentCode}' is {rating.dataType.value}; {analysis} requires a numeric assessment"
    )
  return rating


def onAnalysedScale(assessmentCode: str, rating, values: list[float]) -> list[float]:
  """Values on the scale the rating declares (decision 0006); a domain or kind violation names the assessment."""
  try:
    checkTransformKind(rating.transform, rating.measurementKind)
    if rating.transform is Transform.none:
      return values
    return applyTransform(rating.transform, values, rating.transformOffset)
  except TransformError as error:
    raise AnalysisError(f"assessment '{assessmentCode}': {error}") from error


def collectBlockTreatmentCells(
  assessmentCode: str,
  package: TrialPackage,
  layout: TrialLayout,
  observations: list[Observation],
) -> BlockTreatmentCells:
  """Validate inputs and lay one assessment's plot values out by block and treatment.

  Shared by the ANOVAs and the assumption diagnostics so the structural checks and the
  transform live in one place: the assessment's declared transform (decision 0006) is
  applied here to every value present, so a plot is missing on the analysed scale exactly
  when its recorded value is missing. The treatments are those the assessment analyses
  (decision 0030).
  """
  rating = numericRating(assessmentCode, package, "RCBD ANOVA")
  if layout.trialCode != package.trial.trialCode:
    raise AnalysisError(
      f"layout trialCode '{layout.trialCode}' does not match package trial '{package.trial.trialCode}'"
    )

  treatmentCodes = package.analysedTreatmentCodes(assessmentCode)
  blocks = list(range(1, layout.replications + 1))
  plotCellByNumber = {plot.plotNumber: (plot.treatmentCode, plot.block) for plot in layout.plots}
  plotNumberByCell = {cell: plotNumber for plotNumber, cell in plotCellByNumber.items()}

  from openfurrow.analysis.subsamples import plotValues

  checkNumbers = {check.plotNumber for check in layout.checkPlots}
  cellValue: dict[tuple[str, int], float] = {}
  for plotNumber, value in plotValues(assessmentCode, package, observations).items():
    if plotNumber in checkNumbers:
      continue
    cell = plotCellByNumber.get(plotNumber)
    if cell is None:
      raise AnalysisError(f"observation references plot {plotNumber} not in the layout")
    if value is not None:
      cellValue[cell] = float(value)

  cells = [(block, treatmentCode) for block in blocks for treatmentCode in treatmentCodes]
  present = [cell for cell in cells if (cell[1], cell[0]) in cellValue]
  scaled = onAnalysedScale(assessmentCode, rating, [cellValue[(treatmentCode, block)] for block, treatmentCode in present])
  values = numpy.full((len(blocks), len(treatmentCodes)), numpy.nan, dtype=float)
  for (block, treatmentCode), value in zip(present, scaled):
    values[block - 1, treatmentCodes.index(treatmentCode)] = value
  plotNumbers = numpy.array(
    [[plotNumberByCell[(treatmentCode, block)] for treatmentCode in treatmentCodes] for block in blocks], dtype=int,
  )
  return BlockTreatmentCells(
    values=values,
    plotNumbers=plotNumbers,
    treatmentCodes=treatmentCodes,
    blocks=blocks,
    transform=rating.transform,
    transformOffset=rating.transformOffset,
    missing=[
      (plotNumberByCell[(treatmentCode, block)], treatmentCode, block)
      for block, treatmentCode in cells if (treatmentCode, block) not in cellValue
    ],
  )


def buildBlockTreatmentMatrix(
  assessmentCode: str,
  package: TrialPackage,
  layout: TrialLayout,
  observations: list[Observation],
) -> tuple[numpy.ndarray, list[str], list[int], Transform]:
  """The complete block-by-treatment matrix an analysis without a missing-plot method needs.

  Returns the matrix on the analysed scale (rows = blocks, columns = treatments), the
  treatment codes, the block numbers and the transform applied. A missing plot is refused
  under every missing-plot policy, naming the plots and the designs that are covered.
  """
  cells = collectBlockTreatmentCells(assessmentCode, package, layout, observations)
  if cells.missing:
    raise missingValuesError(
      assessmentCode, cells.missing, f"this analysis requires a complete table under every policy: {coveredDesigns}",
    )
  return cells.values, cells.treatmentCodes, cells.blocks, cells.transform


@dataclass(frozen=True)
class CompleteTableSums:
  """The classical sums of squares and means of a complete block-by-treatment matrix."""

  grandMean: float
  treatmentMeans: numpy.ndarray
  total: float
  block: float
  treatment: float
  error: float


def completeTableSums(matrix: numpy.ndarray) -> CompleteTableSums:
  """Total, block and treatment sums of squares of a complete matrix, and the error left over."""
  blockCount, treatmentCount = matrix.shape
  grandMean = float(matrix.mean())
  treatmentMeans = matrix.mean(axis=0)
  total = float(((matrix - grandMean) ** 2).sum())
  treatment = float(blockCount * ((treatmentMeans - grandMean) ** 2).sum())
  block = float(treatmentCount * ((matrix.mean(axis=1) - grandMean) ** 2).sum())
  error = total - treatment - block
  if error < -1.0e-7 * max(1.0, total):
    raise AnalysisError("internal error: negative error sum of squares")
  return CompleteTableSums(
    grandMean=grandMean, treatmentMeans=treatmentMeans, total=total, block=block, treatment=treatment,
    error=max(error, 0.0),
  )


def additiveResiduals(matrix: numpy.ndarray) -> numpy.ndarray:
  """Each value of a complete block-by-treatment matrix less its treatment mean and block mean, plus the grand mean."""
  return matrix - matrix.mean(axis=0)[None, :] - matrix.mean(axis=1)[:, None] + float(matrix.mean())


def tested(source: str, degreesOfFreedom: int, sumOfSquares: float, errorMeanSquare: float, errorDegreesOfFreedom: int) -> AnovaSource:
  """A line of the table tested against the error."""
  meanSquare = sumOfSquares / degreesOfFreedom
  fStatistic = meanSquare / errorMeanSquare
  return AnovaSource(
    source=source, degreesOfFreedom=degreesOfFreedom, sumOfSquares=sumOfSquares, meanSquare=meanSquare,
    fStatistic=fStatistic, pValue=fDistributionSurvival(fStatistic, degreesOfFreedom, errorDegreesOfFreedom),
  )


def requireErrorAndMean(assessmentCode: str, errorMeanSquare: float, grandMean: float) -> None:
  """An analysis needs residual variation to test against and a grand mean the CV can be taken on."""
  if errorMeanSquare == 0.0:
    raise AnalysisError(
      f"assessment '{assessmentCode}': error mean square is zero (no residual variation); "
      f"AOV cannot be computed"
    )
  if grandMean == 0.0:
    raise AnalysisError(
      f"assessment '{assessmentCode}': grand mean is zero; coefficient of variation is undefined"
    )


def anovaFromMatrix(
  assessmentCode: str, matrix: numpy.ndarray, treatmentCodes: list[str], transform: Transform, transformOffset: float,
  missingPlots: MissingPlotPolicy,
) -> AnovaResult:
  """The RCBD ANOVA of a complete block-by-treatment matrix of values on the analysed scale.

  `missingPlots` is the policy in force, recorded with the result; a complete table has no
  plot for it to act on.
  """
  blockCount, treatmentCount = matrix.shape
  sums = completeTableSums(matrix)
  dfTreatment = treatmentCount - 1
  dfBlock = blockCount - 1
  dfError = dfTreatment * dfBlock
  meanSquareError = sums.error / dfError
  requireErrorAndMean(assessmentCode, meanSquareError, sums.grandMean)
  return AnovaResult(
    assessmentCode=assessmentCode,
    designType=DesignType.rcbd,
    transform=transform,
    transformOffset=transformOffset,
    treatmentCount=treatmentCount,
    blockCount=blockCount,
    grandMean=sums.grandMean,
    coefficientOfVariation=100.0 * math.sqrt(meanSquareError) / abs(sums.grandMean),
    errorMeanSquare=meanSquareError,
    errorDegreesOfFreedom=dfError,
    sumsOfSquares=SumsOfSquares.balanced,
    table=[
      tested("block", dfBlock, sums.block, meanSquareError, dfError),
      tested("treatment", dfTreatment, sums.treatment, meanSquareError, dfError),
      AnovaSource(source="error", degreesOfFreedom=dfError, sumOfSquares=sums.error, meanSquare=meanSquareError),
      AnovaSource(source="total", degreesOfFreedom=treatmentCount * blockCount - 1, sumOfSquares=sums.total),
    ],
    treatmentMeans=[
      TreatmentMean(treatmentCode=treatmentCode, mean=float(sums.treatmentMeans[index]), observationCount=blockCount)
      for index, treatmentCode in enumerate(treatmentCodes)
    ],
    meanCovariance=equalReplicationCovariance(treatmentCount, blockCount),
    missingPlotPolicy=missingPlots,
    missingCells=[],
  )


def equalReplicationCovariance(treatmentCount: int, replications: int) -> list[list[float]]:
  """Means of `replications` plots each, independent of one another: 1 / replications on the diagonal."""
  return [
    [1.0 / replications if row == column else 0.0 for column in range(treatmentCount)]
    for row in range(treatmentCount)
  ]
