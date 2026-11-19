# SPDX-License-Identifier: Apache-2.0
"""Analysis of variance of a completely randomized design (decision 0027).

Without blocks the analysis has two lines, after Gomez and Gomez (1984), section 2.1.2:
treatment (t - 1 df) tested against experimental error (t (r - 1) df). The means are
separated as in the RCBD, on the error, with r plots per treatment.

A missing plot leaves the treatments unequally replicated (decision 0043). Under the
`leastSquares` policy the treatments are fitted to the plots present, which is the
analysis of section 2.1.2.2 of the same book: each mean is that of its own plots, the
error has n - t degrees of freedom, and the standard errors follow each treatment's
number of plots. Yates' estimates complete a table of blocks, which this design does not
have, so the `estimate` policy refuses a missing plot here by name.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy

from openfurrow.analysis.anova import (
  AnalysisError,
  AnovaResult,
  AnovaSource,
  TreatmentMean,
  equalReplicationCovariance,
  missingValuesError,
  numericRating,
  onAnalysedScale,
  requireErrorAndMean,
  tested,
)
from openfurrow.analysis.leastSquares import TreatmentFit, fitTreatments, requireEstimableGroups
from openfurrow.analysis.missingPlots import (
  MissingCell,
  MissingHandling,
  MissingPlotPolicy,
  SumsOfSquares,
  coveredDesigns,
)
from openfurrow.analysis.subsamples import plotValues
from openfurrow.schema.assessment import Transform
from openfurrow.schema.layout import TrialLayout
from openfurrow.schema.observation import Observation
from openfurrow.schema.trialPackage import DesignType, TrialPackage


@dataclass(frozen=True)
class CRDGroups:
  """One assessment's plot values by treatment, on the analysed scale.

  `values` holds each treatment's values present, in plot order; `plotNumbers` every plot
  of each treatment; `missing` the plots without a value as (plot number, treatment code, None).
  """

  values: list[numpy.ndarray]
  plotNumbers: list[list[int]]
  treatmentCodes: list[str]
  transform: Transform
  transformOffset: float
  missing: list[tuple[int, str, None]]


def collectCRDGroups(
  assessmentCode: str, package: TrialPackage, layout: TrialLayout, observations: list[Observation],
  missingPlots: MissingPlotPolicy,
) -> CRDGroups:
  """A CRD assessment's values by treatment, refused unless complete or its missing plots can be handled."""
  if layout.designType is not DesignType.crd:
    raise AnalysisError(f"analyzeCrd requires a completely randomized layout, got {layout.designType.value}")
  rating = numericRating(assessmentCode, package, "the ANOVA")
  treatmentCodes = package.analysedTreatmentCodes(assessmentCode)
  plotNumbers = [
    sorted(plot.plotNumber for plot in layout.plots if plot.treatmentCode == code) for code in treatmentCodes
  ]
  recorded = {
    plotNumber: float(value) for plotNumber, value in plotValues(assessmentCode, package, observations).items()
    if value is not None
  }
  present = [[number for number in numbers if number in recorded] for numbers in plotNumbers]
  scaled = iter(onAnalysedScale(assessmentCode, rating, [recorded[number] for numbers in present for number in numbers]))
  groups = CRDGroups(
    values=[numpy.array([next(scaled) for _ in numbers], dtype=float) for numbers in present],
    plotNumbers=plotNumbers,
    treatmentCodes=treatmentCodes,
    transform=rating.transform,
    transformOffset=rating.transformOffset,
    missing=[
      (number, code, None) for code, numbers in zip(treatmentCodes, plotNumbers) for number in numbers
      if number not in recorded
    ],
  )
  if not groups.missing:
    return groups
  if package.assessmentFor(assessmentCode).subsamples is not None:
    raise missingValuesError(
      assessmentCode, groups.missing,
      f"an assessment that takes subsamples requires every plot under every policy: {coveredDesigns}",
    )
  if missingPlots is MissingPlotPolicy.refuse:
    raise missingValuesError(
      assessmentCode, groups.missing,
      "the ANOVA requires every plot while the setting analysis.missingPlots is 'refuse'",
    )
  if missingPlots is MissingPlotPolicy.estimate:
    raise missingValuesError(
      assessmentCode, groups.missing,
      "the setting analysis.missingPlots is 'estimate', and Yates' estimates complete a table of blocks and "
      "treatments, which a completely randomized design does not have; its missing plots are unequal replication, "
      "which 'leastSquares' analyses",
    )
  requireEstimableGroups(assessmentCode, [values.size for values in groups.values], treatmentCodes, plotNumbers)
  return groups


def fitCRDGroups(groups: CRDGroups) -> TreatmentFit:
  """The least-squares fit of the treatments to the plots of `groups` that have a value."""
  treatmentIndex = numpy.concatenate([numpy.full(values.size, index) for index, values in enumerate(groups.values)])
  return fitTreatments(numpy.concatenate(groups.values), treatmentIndex, len(groups.treatmentCodes))


def analyzeCrd(
  assessmentCode: str, package: TrialPackage, layout: TrialLayout, observations: list[Observation],
  missingPlots: MissingPlotPolicy = MissingPlotPolicy.refuse,
) -> AnovaResult:
  """Run the one-way ANOVA of a completely randomized design for one numeric assessment."""
  groups = collectCRDGroups(assessmentCode, package, layout, observations, missingPlots)
  if groups.missing:
    return _leastSquaresResult(assessmentCode, groups, layout.replications)
  matrix = numpy.array(groups.values, dtype=float).T
  replicates, treatmentCount = matrix.shape
  grandMean = float(matrix.mean())
  means = matrix.mean(axis=0)
  sumOfSquaresTotal = float(((matrix - grandMean) ** 2).sum())
  sumOfSquaresTreatment = float(replicates * ((means - grandMean) ** 2).sum())
  sumOfSquaresError = max(sumOfSquaresTotal - sumOfSquaresTreatment, 0.0)
  dfTreatment = treatmentCount - 1
  dfError = treatmentCount * (replicates - 1)
  meanSquareError = sumOfSquaresError / dfError
  requireErrorAndMean(assessmentCode, meanSquareError, grandMean)
  return AnovaResult(
    assessmentCode=assessmentCode,
    designType=DesignType.crd,
    transform=groups.transform,
    transformOffset=groups.transformOffset,
    treatmentCount=treatmentCount,
    blockCount=replicates,
    grandMean=grandMean,
    coefficientOfVariation=100.0 * math.sqrt(meanSquareError) / abs(grandMean),
    errorMeanSquare=meanSquareError,
    errorDegreesOfFreedom=dfError,
    sumsOfSquares=SumsOfSquares.balanced,
    table=[
      tested("treatment", dfTreatment, sumOfSquaresTreatment, meanSquareError, dfError),
      AnovaSource(source="error", degreesOfFreedom=dfError, sumOfSquares=sumOfSquaresError, meanSquare=meanSquareError),
      AnovaSource(source="total", degreesOfFreedom=replicates * treatmentCount - 1, sumOfSquares=sumOfSquaresTotal),
    ],
    treatmentMeans=[
      TreatmentMean(treatmentCode=code, mean=float(means[index]), observationCount=replicates)
      for index, code in enumerate(groups.treatmentCodes)
    ],
    meanCovariance=equalReplicationCovariance(treatmentCount, replicates),
    missingPlotPolicy=missingPlots,
    missingCells=[],
  )


def _leastSquaresResult(assessmentCode: str, groups: CRDGroups, replicates: int) -> AnovaResult:
  fit = fitCRDGroups(groups)
  treatmentCount = len(groups.treatmentCodes)
  errorDegreesOfFreedom = fit.errorDegreesOfFreedom
  errorMeanSquare = fit.errorSumOfSquares / errorDegreesOfFreedom
  grandMean = float(fit.treatmentMeans.mean())
  requireErrorAndMean(assessmentCode, errorMeanSquare, grandMean)
  valueCount = sum(values.size for values in groups.values)
  return AnovaResult(
    assessmentCode=assessmentCode,
    designType=DesignType.crd,
    transform=groups.transform,
    transformOffset=groups.transformOffset,
    treatmentCount=treatmentCount,
    blockCount=replicates,
    grandMean=grandMean,
    coefficientOfVariation=100.0 * math.sqrt(errorMeanSquare) / abs(grandMean),
    errorMeanSquare=errorMeanSquare,
    errorDegreesOfFreedom=errorDegreesOfFreedom,
    sumsOfSquares=SumsOfSquares.typeIII,
    table=[
      tested("treatment", treatmentCount - 1, fit.treatmentSumOfSquares, errorMeanSquare, errorDegreesOfFreedom),
      AnovaSource(source="error", degreesOfFreedom=errorDegreesOfFreedom, sumOfSquares=fit.errorSumOfSquares, meanSquare=errorMeanSquare),
      AnovaSource(source="total", degreesOfFreedom=valueCount - 1, sumOfSquares=fit.totalSumOfSquares),
    ],
    treatmentMeans=[
      TreatmentMean(treatmentCode=code, mean=float(fit.treatmentMeans[index]), observationCount=int(groups.values[index].size))
      for index, code in enumerate(groups.treatmentCodes)
    ],
    meanCovariance=fit.meanCovariance.tolist(),
    missingPlotPolicy=MissingPlotPolicy.leastSquares,
    missingCells=[
      MissingCell(plotNumber=plotNumber, treatmentCode=code, block=1, handling=MissingHandling.leftOut)
      for plotNumber, code, _ in groups.missing
    ],
  )
