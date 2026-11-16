# SPDX-License-Identifier: Apache-2.0
"""Dunnett's test: every treatment against the untreated check (decision 0029).

With equal replication the differences of p treatment means from the check's mean,
divided by sqrt(2 MS error / n), are t variables correlated 1/2 with one another. Writing
each as sqrt(1/2) V + sqrt(1/2) W_i with V shared, the chance that none exceeds d in
absolute value, for a known sigma, is

    G(d) = E_V [ (Phi((d - V / sqrt 2) * sqrt 2) - Phi((-d - V / sqrt 2) * sqrt 2)) ^ p ],

taken by Gauss-Hermite quadrature over V; with sigma estimated on the error df it is the
average of G(d s) over the distribution of s, the same outer integral as the studentized
range. The two-sided critical value is the d where that chance is 1 - alpha. Computed
natively (decision 0002) and checked against the two-sided t when p = 1 and against
scipy.stats.dunnett in the tests.
"""

from __future__ import annotations

import math

import numpy
from pydantic import BaseModel, ConfigDict

from openfurrow.analysis.anova import AnalysisError, AnovaResult
from openfurrow.analysis.distributions import normalCdf
from openfurrow.analysis.studentizedRange import overErrorDegreesOfFreedom, quantileOf
from openfurrow.schema.treatment import TreatmentRole
from openfurrow.schema.trialPackage import TrialPackage

_hermiteNodes, _hermiteWeights = numpy.polynomial.hermite.hermgauss(64)
_sqrtTwo = math.sqrt(2.0)


def _knownSigmaProbability(d: float, comparisons: int) -> float:
  total = 0.0
  for node, weight in zip(_hermiteNodes, _hermiteWeights):
    shared = _sqrtTwo * node
    inside = normalCdf(_sqrtTwo * d - shared) - normalCdf(-_sqrtTwo * d - shared)
    total += weight * inside ** comparisons
  return min(total / math.sqrt(math.pi), 1.0)


def dunnettCdf(d: float, comparisons: int, degreesOfFreedom: float) -> float:
  """P(max |T_i| < d) for `comparisons` treatments against one check, equal replication."""
  if comparisons < 1 or degreesOfFreedom < 2:
    raise ValueError(f"Dunnett's test needs at least 1 comparison and 2 df, got {comparisons} and {degreesOfFreedom}")
  if d <= 0.0:
    return 0.0
  return overErrorDegreesOfFreedom(lambda value: _knownSigmaProbability(value, comparisons), d, degreesOfFreedom)


def dunnettQuantile(probability: float, comparisons: int, degreesOfFreedom: float) -> float:
  """The two-sided critical value d with P(max |T_i| < d) = probability."""
  return quantileOf(lambda d: dunnettCdf(d, comparisons, degreesOfFreedom), probability)


class CheckComparison(BaseModel):
  """One treatment's mean against the check's."""

  model_config = ConfigDict(extra="forbid")

  treatmentCode: str
  mean: float
  difference: float
  significant: bool


class DunnettResult(BaseModel):
  """Every treatment against the untreated check, by Dunnett's two-sided test."""

  model_config = ConfigDict(extra="forbid")

  checkCode: str
  checkMean: float
  significanceLevel: float
  criticalValue: float
  criticalDifference: float
  standardError: float
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
  means = {mean.treatmentCode: mean.mean for mean in anovaResult.treatmentMeans}
  if checkCode not in means:
    raise AnalysisError(
      f"the untreated check '{checkCode}' is left out of this assessment's analysis, so Dunnett's test has "
      f"nothing to compare with"
    )
  critical = dunnettQuantile(1.0 - significanceLevel, len(means) - 1, anovaResult.errorDegreesOfFreedom)
  difference = critical * math.sqrt(2.0 * anovaResult.errorMeanSquare / anovaResult.blockCount)
  return DunnettResult(
    checkCode=checkCode,
    checkMean=means[checkCode],
    significanceLevel=significanceLevel,
    criticalValue=critical,
    criticalDifference=difference,
    standardError=math.sqrt(anovaResult.errorMeanSquare / anovaResult.blockCount),
    comparisons=[
      CheckComparison(
        treatmentCode=code, mean=mean, difference=mean - means[checkCode],
        significant=abs(mean - means[checkCode]) > difference,
      )
      for code, mean in means.items() if code != checkCode
    ],
  )
