# SPDX-License-Identifier: Apache-2.0
"""Analysis of variance of a completely randomized design (decision 0027).

Without blocks the analysis has two lines, after Gomez and Gomez (1984), section 2.1.2:
treatment (t - 1 df) tested against experimental error (t (r - 1) df). The means are
separated as in the RCBD, on the error, with r plots per treatment.
"""

from __future__ import annotations

import math

import numpy

from openfurrow.analysis.anova import AnalysisError, AnovaResult, AnovaSource, TreatmentMean
from openfurrow.analysis.distributions import fDistributionSurvival
from openfurrow.analysis.transforms import TransformError, applyTransform, checkTransformKind
from openfurrow.schema.assessment import AssessmentDataType, Transform
from openfurrow.schema.layout import TrialLayout
from openfurrow.schema.observation import Observation
from openfurrow.schema.trialPackage import DesignType, TrialPackage


def analyzeCrd(
  assessmentCode: str, package: TrialPackage, layout: TrialLayout, observations: list[Observation],
) -> AnovaResult:
  """Run the one-way ANOVA of a completely randomized design for one numeric assessment."""
  if layout.designType is not DesignType.crd:
    raise AnalysisError(f"analyzeCrd requires a completely randomized layout, got {layout.designType.value}")
  try:
    rating = package.ratingFor(assessmentCode)
  except KeyError as error:
    raise AnalysisError(error.args[0]) from error
  if rating.dataType is not AssessmentDataType.numeric:
    raise AnalysisError(f"assessment '{assessmentCode}' is {rating.dataType.value}; the ANOVA requires a numeric assessment")
  treatmentOf = {plot.plotNumber: plot.treatmentCode for plot in layout.plots}
  values = {
    o.plotNumber: float(o.value) for o in observations
    if o.assessmentCode == assessmentCode and o.value is not None and o.plotNumber in treatmentOf
  }
  missing = sorted(number for number in treatmentOf if number not in values)
  if missing:
    raise AnalysisError(f"assessment '{assessmentCode}' has missing values; the ANOVA requires every plot. Missing: {missing}")
  treatmentCodes = [treatment.treatmentCode for treatment in package.treatments]
  plotsOf = {code: sorted(number for number, treatment in treatmentOf.items() if treatment == code) for code in treatmentCodes}
  matrix = numpy.array([[values[number] for number in plotsOf[code]] for code in treatmentCodes], dtype=float).T
  try:
    checkTransformKind(rating.transform, rating.measurementKind)
    if rating.transform is not Transform.none:
      matrix = numpy.array(
        applyTransform(rating.transform, matrix.ravel().tolist(), rating.transformOffset), dtype=float,
      ).reshape(matrix.shape)
  except TransformError as error:
    raise AnalysisError(f"assessment '{assessmentCode}': {error}") from error

  replicates, treatmentCount = matrix.shape
  grandMean = float(matrix.mean())
  means = matrix.mean(axis=0)
  sumOfSquaresTotal = float(((matrix - grandMean) ** 2).sum())
  sumOfSquaresTreatment = float(replicates * ((means - grandMean) ** 2).sum())
  sumOfSquaresError = max(sumOfSquaresTotal - sumOfSquaresTreatment, 0.0)
  dfTreatment = treatmentCount - 1
  dfError = treatmentCount * (replicates - 1)
  meanSquareError = sumOfSquaresError / dfError
  if meanSquareError == 0.0:
    raise AnalysisError(f"assessment '{assessmentCode}': error mean square is zero; AOV cannot be computed")
  if grandMean == 0.0:
    raise AnalysisError(f"assessment '{assessmentCode}': grand mean is zero; coefficient of variation is undefined")
  meanSquareTreatment = sumOfSquaresTreatment / dfTreatment
  fTreatment = meanSquareTreatment / meanSquareError
  return AnovaResult(
    assessmentCode=assessmentCode,
    designType=DesignType.crd,
    transform=rating.transform,
    transformOffset=rating.transformOffset,
    treatmentCount=treatmentCount,
    blockCount=replicates,
    grandMean=grandMean,
    coefficientOfVariation=100.0 * math.sqrt(meanSquareError) / abs(grandMean),
    errorMeanSquare=meanSquareError,
    errorDegreesOfFreedom=dfError,
    table=[
      AnovaSource(source="treatment", degreesOfFreedom=dfTreatment, sumOfSquares=sumOfSquaresTreatment,
                  meanSquare=meanSquareTreatment, fStatistic=fTreatment,
                  pValue=fDistributionSurvival(fTreatment, dfTreatment, dfError)),
      AnovaSource(source="error", degreesOfFreedom=dfError, sumOfSquares=sumOfSquaresError, meanSquare=meanSquareError),
      AnovaSource(source="total", degreesOfFreedom=replicates * treatmentCount - 1, sumOfSquares=sumOfSquaresTotal),
    ],
    treatmentMeans=[
      TreatmentMean(treatmentCode=code, mean=float(means[index]), observationCount=replicates)
      for index, code in enumerate(treatmentCodes)
    ],
  )
