# SPDX-License-Identifier: Apache-2.0
"""Dunnett's test: every treatment against the untreated check (decisions 0029, 0043).

The differences of p treatment means from the check's mean, each divided by its standard
error, are t variables correlated with one another through the check they share. When
the correlation of every pair is the product of one loading for each, rho_ij = l_i l_j,
each can be written l_i V + sqrt(1 - l_i^2) W_i with V shared, and the chance that none
exceeds d in absolute value, for a known sigma, is

    G(d) = E_V [ prod_i ( Phi((d - l_i V) / sqrt(1 - l_i^2)) - Phi((-d - l_i V) / sqrt(1 - l_i^2)) ) ].

The expectation over V is taken by the trapezoid rule on an even grid, which for an
integrand this smooth that dies away at both ends converges faster than any power of the
step. The integrand's steepest feature is sqrt(1 - l^2) / |l| wide for the largest
loading and narrows with the square root of the number of comparisons, so the step is a
fixed fraction of that width. With sigma estimated on the error df, the chance is the
average of G(d s) over the distribution of s, the same outer integral as the studentized
range. The two-sided critical value is the d where that chance is 1 - alpha.

With equal replication every loading is sqrt(1/2) (correlations of 1/2). With unequal
replication the loadings differ: without blocks they are sqrt(n_i / (n_i + n_0)) for
treatments on n_i plots and a check on n_0, and in blocks with missing plots they come
from the analysis' covariance of the adjusted means. A set of correlations that is not of
the product form has no such single integral, and the test is refused by name rather
than approximated.

Computed natively (decision 0002) and checked against the two-sided t when p = 1, against
scipy.stats.dunnett with equal and unequal replication, and against scipy's multivariate
t in the tests.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from openfurrow.analysis.anova import AnalysisError, AnovaResult, differenceStandardError, meanStandardError
from openfurrow.analysis.distributions import normalCdf
from openfurrow.analysis.meanSeparation import commonValue
from openfurrow.analysis.studentizedRange import overErrorDegreesOfFreedom, quantileOf
from openfurrow.schema.treatment import TreatmentRole
from openfurrow.schema.trialPackage import TrialPackage

sharedLimit = 8.5  # the standard normal density beyond it is below 1e-16
largestStep = 0.5
stepPerFeature = 0.6
productTolerance = 1.0e-9


def equalLoadings(comparisons: int) -> list[float]:
  """The loadings of `comparisons` treatments against one check when all are equally replicated."""
  return [math.sqrt(0.5)] * comparisons


def sharedGrid(loadings: Sequence[float]) -> list[tuple[float, float]]:
  """Values of the shared factor V and their weights: the trapezoid rule on the standard normal density.

  The step is `stepPerFeature` of the steepest comparison's width sqrt(1 - l^2) / |l|
  divided by the square root of the number of comparisons, and never above `largestStep`.
  """
  steepest = max(abs(loading) / math.sqrt(1.0 - loading * loading) for loading in loadings)
  step = largestStep
  if steepest > 0.0:
    step = min(largestStep, stepPerFeature / (steepest * math.sqrt(len(loadings))))
  intervals = math.ceil(2.0 * sharedLimit / step)
  step = 2.0 * sharedLimit / intervals
  grid = []
  for index in range(intervals + 1):
    value = -sharedLimit + index * step
    weight = step * math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)
    grid.append((value, 0.5 * weight if index in (0, intervals) else weight))
  return grid


def _knownSigmaProbability(d: float, loadings: Counter, grid: list[tuple[float, float]]) -> float:
  total = 0.0
  for shared, weight in grid:
    inside = 1.0
    for loading, count in loadings.items():
      spread = math.sqrt(1.0 - loading * loading)
      inside *= (normalCdf((d - loading * shared) / spread) - normalCdf((-d - loading * shared) / spread)) ** count
    total += weight * inside
  return min(total, 1.0)


def dunnettCdf(d: float, loadings: Sequence[float], degreesOfFreedom: float) -> float:
  """P(max |T_i| < d) for comparisons with one check whose correlations are the products of `loadings`."""
  if len(loadings) < 1 or degreesOfFreedom < 2:
    raise ValueError(f"Dunnett's test needs at least 1 comparison and 2 df, got {len(loadings)} and {degreesOfFreedom}")
  if any(not -1.0 < loading < 1.0 for loading in loadings):
    raise ValueError(f"Dunnett's loadings must be inside (-1, 1), got {list(loadings)}")
  if d <= 0.0:
    return 0.0
  counted = Counter(loadings)
  grid = sharedGrid(loadings)
  return overErrorDegreesOfFreedom(lambda value: _knownSigmaProbability(value, counted, grid), d, degreesOfFreedom)


def dunnettQuantile(probability: float, loadings: Sequence[float], degreesOfFreedom: float) -> float:
  """The two-sided critical value d with P(max |T_i| < d) = probability."""
  return quantileOf(lambda d: dunnettCdf(d, loadings, degreesOfFreedom), probability)


def productLoadings(correlation: list[list[float]]) -> list[float] | None:
  """One loading per comparison whose products are the correlations, or None when they have no such form.

  With one comparison nothing is correlated and the loading is zero; with two any
  correlation is a product; with more, each loading follows from the three correlations
  among it and two others, and every pair is then checked against the product.
  """
  count = len(correlation)
  if count == 1:
    return [0.0]
  if count == 2:
    size = math.sqrt(abs(correlation[0][1]))
    return [size, math.copysign(size, correlation[0][1])]
  loadings = []
  for index in range(count):
    one, two = (index + 1) % count, (index + 2) % count
    if correlation[one][two] == 0.0:
      return None
    squared = correlation[index][one] * correlation[index][two] / correlation[one][two]
    if squared < 0.0:
      return None
    loadings.append(math.sqrt(squared) if index == 0 else math.copysign(math.sqrt(squared), correlation[0][index]))
  if any(abs(loading) >= 1.0 for loading in loadings):
    return None
  for first in range(count):
    for second in range(first + 1, count):
      if abs(correlation[first][second] - loadings[first] * loadings[second]) > productTolerance:
        return None
  return loadings


class CheckComparison(BaseModel):
  """One treatment's mean against the check's."""

  model_config = ConfigDict(extra="forbid")

  treatmentCode: str
  mean: float
  meanStandardError: float
  difference: float
  differenceStandardError: float
  criticalDifference: float
  significant: bool


class DunnettResult(BaseModel):
  """Every treatment against the untreated check, by Dunnett's two-sided test.

  `criticalDifference` is the one difference every treatment is held to and
  `standardError` the one standard error of every mean; each is None when replication is
  unequal, and then each comparison carries its own.
  """

  model_config = ConfigDict(extra="forbid")

  checkCode: str
  checkMean: float
  checkStandardError: float
  significanceLevel: float
  criticalValue: float
  criticalDifference: float | None
  standardError: float | None
  comparisons: list[CheckComparison]


def theCheck(package: TrialPackage) -> str:
  """The one treatment whose role is the untreated control; Dunnett's test compares against it."""
  checks = [t.treatmentCode for t in package.treatments if t.role is TreatmentRole.untreatedControl]
  if len(checks) != 1:
    raise AnalysisError(
      f"Dunnett's test compares against the one treatment whose role is untreatedControl; "
      f"trial '{package.trial.trialCode}' has {len(checks)}: {checks}"
    )
  return checks[0]


def compareWithControl(
  anovaResult: AnovaResult, package: TrialPackage, significanceLevel: float = 0.05,
) -> DunnettResult:
  """Dunnett's two-sided test of every treatment mean against the untreated check's."""
  if not 0.0 < significanceLevel < 1.0:
    raise AnalysisError(f"significance level must be in (0, 1), got {significanceLevel}")
  checkCode = theCheck(package)
  means = anovaResult.treatmentMeans
  codes = [mean.treatmentCode for mean in means]
  if checkCode not in codes:
    raise AnalysisError(
      f"the untreated check '{checkCode}' is left out of this assessment's analysis, so Dunnett's test has "
      f"nothing to compare with"
    )
  check = codes.index(checkCode)
  others = [index for index in range(len(means)) if index != check]
  covariance = anovaResult.meanCovariance

  def shared(first: int, second: int) -> float:
    return covariance[first][second] - covariance[first][check] - covariance[second][check] + covariance[check][check]

  correlation = [
    [shared(first, second) / math.sqrt(shared(first, first) * shared(second, second)) for second in others]
    for first in others
  ]
  loadings = productLoadings(correlation)
  if loadings is None:
    raise AnalysisError(
      f"assessment '{anovaResult.assessmentCode}': with these missing plots the comparisons with the check "
      f"'{checkCode}' are correlated in a way that is not one loading per treatment, the only form Dunnett's "
      f"critical value is computed for so far; it is not approximated. Fisher's LSD and Tukey's test "
      f"(setting analysis.meanComparison) compare every pair on its own standard error"
    )
  critical = dunnettQuantile(1.0 - significanceLevel, loadings, anovaResult.errorDegreesOfFreedom)
  comparisons = []
  for index in others:
    difference = means[index].mean - means[check].mean
    standardError = differenceStandardError(anovaResult, index, check)
    comparisons.append(CheckComparison(
      treatmentCode=codes[index], mean=means[index].mean, meanStandardError=meanStandardError(anovaResult, index),
      difference=difference, differenceStandardError=standardError, criticalDifference=critical * standardError,
      significant=abs(difference) > critical * standardError,
    ))
  checkStandardError = meanStandardError(anovaResult, check)
  return DunnettResult(
    checkCode=checkCode,
    checkMean=means[check].mean,
    checkStandardError=checkStandardError,
    significanceLevel=significanceLevel,
    criticalValue=critical,
    criticalDifference=commonValue([comparison.criticalDifference for comparison in comparisons]),
    standardError=commonValue([checkStandardError] + [comparison.meanStandardError for comparison in comparisons]),
    comparisons=comparisons,
  )
