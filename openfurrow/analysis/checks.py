# SPDX-License-Identifier: Apache-2.0
"""Analyses against untreated checks beside the plots (decision 0022).

Every treated plot of a trial with a check arrangement is compared with its own check:

- **Percent control**, plot by plot, when the assessment asks for it. Abbott:
  100 (1 - T / C). Henderson-Tilton, with T and C also counted before application:
  100 (1 - (Ta Cb) / (Tb Ca)). The percentages are then analysed as an RCBD and their
  means separated, like any other assessment. A check with nothing to compare against
  (C or Tb Ca of zero) has no percentage, and the analysis stops naming the plot.
- **Treated against untreated halves** (adjacent checks): each plot is a main plot whose
  two halves are the subplots, so the analysis has two strata, as EPPO PP 1/152 says.
- **Each treatment against its checks** (paired checks): a paired t-test of the treated
  plots against their partners, one pair per block.

The ANOVA and the paired comparisons run on the assessment's declared scale (decision
0006). Percent control is worked out from the values as recorded.
"""

from __future__ import annotations

import math

import numpy
from pydantic import BaseModel, ConfigDict

from openfurrow.analysis.subsamples import plotValues
from openfurrow.analysis.anova import AnalysisError, AnovaResult, TreatmentMean, anovaFromMatrix
from openfurrow.analysis.distributions import tDistributionSurvival
from openfurrow.analysis.missingPlots import MissingPlotPolicy, coveredDesigns
from openfurrow.analysis.splitPlot import SplitPlotResult, twoStrataAnova
from openfurrow.analysis.transforms import TransformError, applyTransform
from openfurrow.schema.assessment import AssessmentDataType, EfficacyMethod, Transform
from openfurrow.schema.layout import TrialLayout
from openfurrow.schema.observation import Observation
from openfurrow.schema.trialPackage import CheckArrangement, DesignType, TrialPackage

treatedLevel = "treated"
untreatedLevel = "untreated"


class CheckPair(BaseModel):
  """A treated plot's value and its check's, as recorded."""

  model_config = ConfigDict(extra="forbid")

  plotNumber: int
  checkPlotNumber: int
  treatmentCode: str
  block: int
  treated: float
  check: float


class PlotEfficacy(BaseModel):
  """Percent control on one treated plot, against its own check."""

  model_config = ConfigDict(extra="forbid")

  plotNumber: int
  treatmentCode: str
  block: int
  efficacy: float


class PairedComparison(BaseModel):
  """One treatment's plots against their checks: a paired t-test over the blocks."""

  model_config = ConfigDict(extra="forbid")

  treatmentCode: str
  pairCount: int
  treatedMean: float
  checkMean: float
  meanDifference: float
  standardError: float
  tStatistic: float
  degreesOfFreedom: int
  pValue: float


def checkPairs(
  assessmentCode: str, package: TrialPackage, layout: TrialLayout, observations: list[Observation],
) -> list[CheckPair]:
  """Every treated plot with its check, for one numeric assessment; all values must be there."""
  if layout.checkArrangement is CheckArrangement.none:
    raise AnalysisError(f"trial '{layout.trialCode}' has no untreated checks beside its plots")
  try:
    rating = package.ratingFor(assessmentCode)
  except KeyError as error:
    raise AnalysisError(error.args[0]) from error
  if rating.dataType is not AssessmentDataType.numeric:
    raise AnalysisError(f"assessment '{assessmentCode}' is {rating.dataType.value}; checks are compared on numbers")
  values = {
    plotNumber: value for plotNumber, value in plotValues(assessmentCode, package, observations).items()
    if value is not None
  }
  needed = [plot.plotNumber for plot in layout.plots] + [check.plotNumber for check in layout.checkPlots]
  missing = sorted(number for number in needed if number not in values)
  if missing:
    raise AnalysisError(
      f"assessment '{assessmentCode}' has missing values; comparing with the checks needs every plot "
      f"and every check plot under every policy: {coveredDesigns}. Missing: {missing}"
    )
  pairs = []
  for plot in sorted(layout.plots, key=lambda plot: plot.plotNumber):
    check = layout.checkFor(plot.plotNumber)
    pairs.append(CheckPair(
      plotNumber=plot.plotNumber, checkPlotNumber=check.plotNumber, treatmentCode=plot.treatmentCode,
      block=plot.block, treated=float(values[plot.plotNumber]), check=float(values[check.plotNumber]),
    ))
  return pairs


def plotEfficacies(
  assessmentCode: str, package: TrialPackage, layout: TrialLayout, observations: list[Observation],
) -> list[PlotEfficacy]:
  """Percent control on every treated plot, by the method the assessment declares."""
  efficacy = package.assessmentFor(assessmentCode).efficacy
  if efficacy is None:
    raise AnalysisError(f"assessment '{assessmentCode}' does not ask for percent control")
  after = checkPairs(assessmentCode, package, layout, observations)
  before = None
  if efficacy.method is EfficacyMethod.hendersonTilton:
    before = {pair.plotNumber: pair for pair in checkPairs(efficacy.baselineAssessmentCode, package, layout, observations)}
  results = []
  for pair in after:
    if efficacy.method is EfficacyMethod.abbott:
      numerator, denominator = pair.treated, pair.check
    else:
      baseline = before[pair.plotNumber]
      numerator, denominator = pair.treated * baseline.check, baseline.treated * pair.check
    if denominator == 0.0:
      raise AnalysisError(
        f"assessment '{assessmentCode}': plot {pair.plotNumber} has no percent control by "
        f"{efficacy.method.value}; its check gives nothing to compare against (a zero divisor)"
      )
    results.append(PlotEfficacy(
      plotNumber=pair.plotNumber, treatmentCode=pair.treatmentCode, block=pair.block,
      efficacy=100.0 * (1.0 - numerator / denominator),
    ))
  return results


def analyzeEfficacy(
  assessmentCode: str, package: TrialPackage, layout: TrialLayout, observations: list[Observation],
  missingPlots: MissingPlotPolicy = MissingPlotPolicy.refuse,
) -> AnovaResult:
  """The RCBD ANOVA of percent control, plot by plot.

  `missingPlots` is the policy in force, recorded with the result; percent control needs
  every plot and its check under every policy.
  """
  treatmentCodes = package.analysedTreatmentCodes(assessmentCode)
  efficacies = [result for result in plotEfficacies(assessmentCode, package, layout, observations)
                if result.treatmentCode in treatmentCodes]
  matrix = numpy.empty((layout.replications, len(treatmentCodes)), dtype=float)
  for result in efficacies:
    matrix[result.block - 1, treatmentCodes.index(result.treatmentCode)] = result.efficacy
  return anovaFromMatrix(assessmentCode, matrix, treatmentCodes, Transform.none, 0.0, missingPlots)


def _onDeclaredScale(
  assessmentCode: str, package: TrialPackage, values: list[float],
) -> tuple[list[float], Transform, float]:
  rating = package.ratingFor(assessmentCode)
  if rating.transform is Transform.none:
    return values, rating.transform, rating.transformOffset
  try:
    return applyTransform(rating.transform, values, rating.transformOffset), rating.transform, rating.transformOffset
  except TransformError as error:
    raise AnalysisError(f"assessment '{assessmentCode}': {error}") from error


def analyzeHalves(
  assessmentCode: str, package: TrialPackage, layout: TrialLayout, observations: list[Observation],
) -> SplitPlotResult:
  """Treated and untreated halves as subplots of each plot (adjacent checks)."""
  if layout.checkArrangement is not CheckArrangement.adjacent:
    raise AnalysisError("treated and untreated halves are analysed together only for adjacent checks")
  pairs = checkPairs(assessmentCode, package, layout, observations)
  treatmentCodes = [treatment.treatmentCode for treatment in package.treatments]
  scaled, transform, offset = _onDeclaredScale(
    assessmentCode, package, [value for pair in pairs for value in (pair.treated, pair.check)],
  )
  values = numpy.empty((layout.replications, len(treatmentCodes), 2), dtype=float)
  for index, pair in enumerate(pairs):
    position = (pair.block - 1, treatmentCodes.index(pair.treatmentCode))
    values[position + (0,)] = scaled[2 * index]
    values[position + (1,)] = scaled[2 * index + 1]
  treatmentMeans = [
    TreatmentMean(treatmentCode=code, mean=float(values[:, index, 0].mean()), observationCount=layout.replications)
    for index, code in enumerate(treatmentCodes)
  ]
  return twoStrataAnova(
    assessmentCode, values, treatmentCodes, [treatedLevel, untreatedLevel], "treatment", "half",
    transform, offset, treatmentMeans, DesignType.rcbd,
  )


def compareWithChecks(
  assessmentCode: str, package: TrialPackage, layout: TrialLayout, observations: list[Observation],
) -> list[PairedComparison]:
  """For each treatment, a paired t-test of its plots against their checks."""
  pairs = checkPairs(assessmentCode, package, layout, observations)
  scaled, _, _ = _onDeclaredScale(
    assessmentCode, package, [value for pair in pairs for value in (pair.treated, pair.check)],
  )
  byTreatment: dict[str, list[tuple[float, float]]] = {}
  for index, pair in enumerate(pairs):
    byTreatment.setdefault(pair.treatmentCode, []).append((scaled[2 * index], scaled[2 * index + 1]))
  comparisons = []
  for treatment in package.treatments:
    members = byTreatment[treatment.treatmentCode]
    count = len(members)
    differences = [treated - check for treated, check in members]
    meanDifference = sum(differences) / count
    variance = sum((difference - meanDifference) ** 2 for difference in differences) / (count - 1)
    if variance == 0.0:
      raise AnalysisError(
        f"assessment '{assessmentCode}', treatment '{treatment.treatmentCode}': every plot differs from its "
        f"check by the same amount, so the paired t-test has no variation to test against"
      )
    standardError = math.sqrt(variance / count)
    tStatistic = meanDifference / standardError
    comparisons.append(PairedComparison(
      treatmentCode=treatment.treatmentCode,
      pairCount=count,
      treatedMean=sum(treated for treated, _ in members) / count,
      checkMean=sum(check for _, check in members) / count,
      meanDifference=meanDifference,
      standardError=standardError,
      tStatistic=tStatistic,
      degreesOfFreedom=count - 1,
      pValue=min(1.0, 2.0 * tDistributionSurvival(abs(tStatistic), count - 1)),
    ))
  return comparisons
