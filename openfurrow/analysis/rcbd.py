# SPDX-License-Identifier: Apache-2.0
"""Analysis of variance of a single-factor randomized complete block design.

A complete table is analysed by the classical arithmetic (`anova.anovaFromMatrix`). A
table with a missing plot follows the missing-plot policy in force (decisions 0003 and
0043):

- `refuse` stops and names the missing plots;
- `leastSquares` fits blocks and treatments to the plots present: Type III sums of
  squares, adjusted treatment means and their covariance (`leastSquares`);
- `estimate` completes the table with Yates' estimates (`yates`): the completed table's
  sums of squares with the error and total degrees of freedom reduced by the number of
  estimates and the treatment line corrected for their bias. Its treatment means are the
  completed table's, which equal the adjusted means, so their covariance is the same.

Under either method the design must be estimable first, and a two-factor trial, a trial
with untreated checks beside its plots or an assessment that takes subsamples refuses a
missing plot whatever the policy.
"""

from __future__ import annotations

import math

import numpy

from openfurrow.analysis.anova import (
  AnalysisError,
  AnovaResult,
  AnovaSource,
  BlockTreatmentCells,
  TreatmentMean,
  additiveResiduals,
  anovaFromMatrix,
  collectBlockTreatmentCells,
  completeTableSums,
  missingValuesError,
  requireErrorAndMean,
  tested,
)
from openfurrow.analysis.leastSquares import (
  TreatmentFit,
  fitTreatments,
  meanCovariance,
  requireEstimableBlocks,
  withoutRoundingResidue,
)
from openfurrow.analysis.missingPlots import (
  MissingCell,
  MissingHandling,
  MissingPlotEstimation,
  MissingPlotPolicy,
  SumsOfSquares,
  coveredDesigns,
)
from openfurrow.analysis.yates import estimateMissingValues, sumOfSquaresWithinBlocks, tolerance
from openfurrow.schema.layout import TrialLayout
from openfurrow.schema.observation import Observation
from openfurrow.schema.trialPackage import CheckArrangement, DesignType, TrialPackage


def collectRcbdCells(
  assessmentCode: str,
  package: TrialPackage,
  layout: TrialLayout,
  observations: list[Observation],
  missingPlots: MissingPlotPolicy,
) -> BlockTreatmentCells:
  """An RCBD assessment's table of values, refused unless it is complete or its missing plots can be handled.

  The cells returned hold nan where a plot is missing only when the policy handles
  missing plots, the design is one the methods cover, and it is estimable.
  """
  if layout.designType is not DesignType.rcbd:
    raise AnalysisError(f"analyzeRcbd requires an RCBD layout, got {layout.designType.value}")
  cells = collectBlockTreatmentCells(assessmentCode, package, layout, observations)
  if not cells.missing:
    return cells
  if package.factors:
    uncovered = "a two-factor RCBD"
  elif layout.checkArrangement is not CheckArrangement.none:
    uncovered = "a trial with untreated checks beside its plots"
  elif package.assessmentFor(assessmentCode).subsamples is not None:
    uncovered = "an assessment that takes subsamples"
  else:
    uncovered = None
  if uncovered is not None:
    raise missingValuesError(
      assessmentCode, cells.missing, f"{uncovered} requires a complete table under every policy: {coveredDesigns}",
    )
  if missingPlots is MissingPlotPolicy.refuse:
    raise missingValuesError(
      assessmentCode, cells.missing,
      "RCBD ANOVA requires a complete table while the setting analysis.missingPlots is 'refuse'",
    )
  requireEstimableBlocks(
    assessmentCode, ~numpy.isnan(cells.values), cells.treatmentCodes, cells.blocks, cells.plotNumbers,
  )
  return cells


def fitRcbdCells(cells: BlockTreatmentCells) -> TreatmentFit:
  """The least-squares fit of blocks and treatments to the plots of `cells` that have a value."""
  blockIndex, treatmentIndex = numpy.nonzero(~numpy.isnan(cells.values))
  return fitTreatments(
    cells.values[blockIndex, treatmentIndex], treatmentIndex, len(cells.treatmentCodes), blockIndex, len(cells.blocks),
  )


def analyzeRcbd(
  assessmentCode: str,
  package: TrialPackage,
  layout: TrialLayout,
  observations: list[Observation],
  missingPlots: MissingPlotPolicy = MissingPlotPolicy.refuse,
) -> AnovaResult:
  """Run the RCBD ANOVA for one numeric assessment, under the missing-plot policy given."""
  cells = collectRcbdCells(assessmentCode, package, layout, observations, missingPlots)
  if not cells.missing:
    return anovaFromMatrix(
      assessmentCode, cells.values, cells.treatmentCodes, cells.transform, cells.transformOffset, missingPlots,
    )
  if missingPlots is MissingPlotPolicy.leastSquares:
    return _leastSquaresResult(assessmentCode, cells)
  return _estimatedResult(assessmentCode, cells)


def _result(
  assessmentCode: str, cells: BlockTreatmentCells, missingPlots: MissingPlotPolicy, sumsOfSquares: SumsOfSquares,
  table: list[AnovaSource], treatmentMeans: numpy.ndarray, covariance: numpy.ndarray,
  missingCells: list[MissingCell], estimation: MissingPlotEstimation | None,
) -> AnovaResult:
  error = next(row for row in table if row.source == "error")
  grandMean = float(treatmentMeans.mean())
  present = ~numpy.isnan(cells.values)
  return AnovaResult(
    assessmentCode=assessmentCode,
    designType=DesignType.rcbd,
    transform=cells.transform,
    transformOffset=cells.transformOffset,
    treatmentCount=len(cells.treatmentCodes),
    blockCount=len(cells.blocks),
    grandMean=grandMean,
    coefficientOfVariation=100.0 * math.sqrt(error.meanSquare) / abs(grandMean),
    errorMeanSquare=error.meanSquare,
    errorDegreesOfFreedom=error.degreesOfFreedom,
    sumsOfSquares=sumsOfSquares,
    table=table,
    treatmentMeans=[
      TreatmentMean(treatmentCode=code, mean=float(treatmentMeans[index]), observationCount=int(present[:, index].sum()))
      for index, code in enumerate(cells.treatmentCodes)
    ],
    meanCovariance=covariance.tolist(),
    missingPlotPolicy=missingPlots,
    missingCells=missingCells,
    estimation=estimation,
  )


def _leastSquaresResult(assessmentCode: str, cells: BlockTreatmentCells) -> AnovaResult:
  fit = fitRcbdCells(cells)
  errorDf = fit.errorDegreesOfFreedom
  errorMeanSquare = fit.errorSumOfSquares / errorDf
  requireErrorAndMean(assessmentCode, errorMeanSquare, float(fit.treatmentMeans.mean()))
  valueCount = int((~numpy.isnan(cells.values)).sum())
  table = [
    tested("block", len(cells.blocks) - 1, fit.blockSumOfSquares, errorMeanSquare, errorDf),
    tested("treatment", len(cells.treatmentCodes) - 1, fit.treatmentSumOfSquares, errorMeanSquare, errorDf),
    AnovaSource(source="error", degreesOfFreedom=errorDf, sumOfSquares=fit.errorSumOfSquares, meanSquare=errorMeanSquare),
    AnovaSource(source="total", degreesOfFreedom=valueCount - 1, sumOfSquares=fit.totalSumOfSquares),
  ]
  missingCells = [
    MissingCell(plotNumber=plotNumber, treatmentCode=treatmentCode, block=block, handling=MissingHandling.leftOut)
    for plotNumber, treatmentCode, block in cells.missing
  ]
  return _result(
    assessmentCode, cells, MissingPlotPolicy.leastSquares, SumsOfSquares.typeIII, table, fit.treatmentMeans,
    fit.meanCovariance, missingCells, None,
  )


def _estimatedResult(assessmentCode: str, cells: BlockTreatmentCells) -> AnovaResult:
  completed, cycles = estimateMissingValues(cells.values)
  sums = completeTableSums(completed)
  blockCount, treatmentCount = completed.shape
  errorDf = (blockCount - 1) * (treatmentCount - 1) - len(cells.missing)
  errorSumOfSquares = withoutRoundingResidue(float((additiveResiduals(completed) ** 2).sum()), completed.ravel())
  errorMeanSquare = errorSumOfSquares / errorDf
  requireErrorAndMean(assessmentCode, errorMeanSquare, float(sums.treatmentMeans.mean()))
  treatmentAdjusted = sumOfSquaresWithinBlocks(cells.values) - errorSumOfSquares
  blockIndex, treatmentIndex = numpy.nonzero(~numpy.isnan(cells.values))
  table = [
    AnovaSource(
      source="block", degreesOfFreedom=blockCount - 1, sumOfSquares=sums.block, meanSquare=sums.block / (blockCount - 1),
    ),
    tested("treatment", treatmentCount - 1, treatmentAdjusted, errorMeanSquare, errorDf),
    AnovaSource(source="error", degreesOfFreedom=errorDf, sumOfSquares=errorSumOfSquares, meanSquare=errorMeanSquare),
    AnovaSource(
      source="total", degreesOfFreedom=blockCount * treatmentCount - 1 - len(cells.missing),
      sumOfSquares=sums.block + treatmentAdjusted + errorSumOfSquares,
    ),
  ]
  missingCells = [
    MissingCell(
      plotNumber=plotNumber, treatmentCode=treatmentCode, block=block, handling=MissingHandling.estimated,
      estimate=float(completed[cells.blocks.index(block), cells.treatmentCodes.index(treatmentCode)]),
    )
    for plotNumber, treatmentCode, block in cells.missing
  ]
  return _result(
    assessmentCode, cells, MissingPlotPolicy.estimate, SumsOfSquares.completedTable, table, sums.treatmentMeans,
    meanCovariance(treatmentIndex, treatmentCount, blockIndex, blockCount), missingCells,
    MissingPlotEstimation(cycles=cycles, tolerance=tolerance, treatmentBias=sums.treatment - treatmentAdjusted),
  )
