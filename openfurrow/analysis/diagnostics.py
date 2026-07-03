# SPDX-License-Identifier: Apache-2.0
"""Assumption diagnostics for the RCBD ANOVA (decision 0006).

These are report-only: they never change the analysis. This module starts with
the Shapiro-Wilk normality test on a sample; the variance-homogeneity
(Brown-Forsythe) and non-additivity (Tukey) tests, and the report assembly, are
added alongside it.

Shapiro-Wilk follows Royston's AS R94 (the algorithm R's shapiro.test and
scipy.stats.shapiro use), which needs only the normal CDF and its inverse -- no
order-statistic covariance matrix and no incomplete gamma. It is validated
against scipy in the tests.
"""

from __future__ import annotations

import math

import numpy
from pydantic import BaseModel, ConfigDict

from openfurrow.analysis.anova import buildRcbdMatrix
from openfurrow.analysis.distributions import fDistributionSurvival, inverseNormalCdf, normalCdf

shapiroWilkMinimum = 3

# AS R94 weight-correction polynomials (ascending powers of 1/sqrt(n)).
_weightPoly1 = (0.0, 0.221157, -0.147981, -2.071190, 4.434685, -2.706056)
_weightPoly2 = (0.0, 0.042981, -0.293762, -1.752461, 5.682633, -3.582633)
# AS R94 p-value polynomials.
_muPolySmall = (0.5440, -0.39978, 0.025054, -6.714e-4)      # 4 <= n <= 11, in n
_sigmaPolySmall = (1.3822, -0.77857, 0.062767, -0.0020322)  # 4 <= n <= 11, in n
_muPolyLarge = (-1.5861, -0.31082, -0.083751, 0.0038915)    # n >= 12, in ln(n)
_sigmaPolyLarge = (-0.4803, -0.082676, 0.0030302)           # n >= 12, in ln(n)
_gammaPoly = (-2.273, 0.459)                                 # 4 <= n <= 11, in n
_pi6 = 1.90985931710274      # 6 / pi, for the exact n = 3 p-value
_stqr = 1.04719755119660     # asin(sqrt(3/4))


def _poly(coefficients, x):
  """Evaluate a polynomial given ascending-power coefficients."""
  result = 0.0
  for coefficient in reversed(coefficients):
    result = result * x + coefficient
  return result


def shapiroWilk(values):
  """Shapiro-Wilk W and p-value for a sample, via Royston AS R94.

  Returns (w, pValue). Requires at least three values and non-zero spread; both
  failures raise, so a caller never gets a silent pass.
  """
  sample = sorted(float(value) for value in values)
  n = len(sample)
  if n < shapiroWilkMinimum:
    raise ValueError(f"Shapiro-Wilk needs at least {shapiroWilkMinimum} values, got {n}")
  if sample[-1] - sample[0] <= 0.0:
    raise ValueError("Shapiro-Wilk is undefined for a constant sample (zero spread)")

  weights = _shapiroWilkWeights(n)
  mean = sum(sample) / n
  numerator = sum(weight * (value - mean) for weight, value in zip(weights, sample)) ** 2
  denominator = sum((value - mean) ** 2 for value in sample)
  w = numerator / denominator
  return w, _shapiroWilkPValue(w, n)


def _shapiroWilkWeights(n):
  """The antisymmetric AS R94 weight vector, normalized to sum of squares 1."""
  weights = [0.0] * n
  if n == 3:
    weights[0] = -math.sqrt(0.5)
    weights[2] = math.sqrt(0.5)
    return weights
  half = n // 2
  orderStatistics = [inverseNormalCdf((i - 0.375) / (n + 0.25)) for i in range(1, half + 1)]
  summ2 = 2.0 * sum(value * value for value in orderStatistics)
  rootSumm2 = math.sqrt(summ2)
  rsn = 1.0 / math.sqrt(n)
  weight1 = _poly(_weightPoly1, rsn) - orderStatistics[0] / rootSumm2
  if n > 5:
    weight2 = _poly(_weightPoly2, rsn) - orderStatistics[1] / rootSumm2
    factor = math.sqrt(
      (summ2 - 2.0 * orderStatistics[0] ** 2 - 2.0 * orderStatistics[1] ** 2)
      / (1.0 - 2.0 * weight1 ** 2 - 2.0 * weight2 ** 2))
    magnitudes = [weight1, weight2] + [-orderStatistics[i] / factor for i in range(2, half)]
  else:
    factor = math.sqrt((summ2 - 2.0 * orderStatistics[0] ** 2) / (1.0 - 2.0 * weight1 ** 2))
    magnitudes = [weight1] + [-orderStatistics[i] / factor for i in range(1, half)]
  for index, magnitude in enumerate(magnitudes):
    weights[n - 1 - index] = magnitude
    weights[index] = -magnitude
  return weights


def _shapiroWilkPValue(w, n):
  if n == 3:
    probability = _pi6 * (math.asin(math.sqrt(w)) - _stqr)
    return min(1.0, max(0.0, probability))
  y = math.log(1.0 - w)
  if n <= 11:
    gamma = _poly(_gammaPoly, n)
    if y >= gamma:
      return 0.0
    y = -math.log(gamma - y)
    mu = _poly(_muPolySmall, n)
    sigma = math.exp(_poly(_sigmaPolySmall, n))
  else:
    logN = math.log(n)
    mu = _poly(_muPolyLarge, logN)
    sigma = math.exp(_poly(_sigmaPolyLarge, logN))
  return 1.0 - normalCdf((y - mu) / sigma)


# ---- assumption diagnostics for the RCBD (decision 0006) -----------------
# All three are report-only: they never change the ANOVA. Brown-Forsythe and
# Tukey reuse the native F-distribution; Shapiro-Wilk runs on the model residuals.


class DiagnosticOutcome(BaseModel):
  """One assumption check: its statistic and a plain-language reading.

  When a check cannot be run (too few degrees of freedom, no variation), computed
  is False and interpretation carries the reason -- never a silent pass.
  """

  model_config = ConfigDict(extra="forbid")

  name: str
  computed: bool
  statisticName: str | None = None
  statistic: float | None = None
  numeratorDegreesOfFreedom: int | None = None
  denominatorDegreesOfFreedom: int | None = None
  pValue: float | None = None
  interpretation: str


class Assumptions(BaseModel):
  """The report-only ANOVA assumption diagnostics for one assessment."""

  model_config = ConfigDict(extra="forbid")

  assessmentCode: str
  significanceLevel: float
  equalVariance: DiagnosticOutcome
  nonAdditivity: DiagnosticOutcome
  normality: DiagnosticOutcome


def _formatProbability(pValue):
  return "< 0.0001" if pValue < 1.0e-4 else f"{pValue:.4f}"


def _reading(significant, pValue, flagged, clear):
  verdict = flagged if significant else clear
  return f"{verdict} (p = {_formatProbability(pValue)})."


def brownForsythe(matrix, significanceLevel=0.05):
  """Brown-Forsythe equal-variance test across treatments (columns of matrix).

  Levene's test on absolute deviations from each treatment's median -- an F-test
  robust to non-normality. Returns a DiagnosticOutcome.
  """
  name = "Equal variance across treatments (Brown-Forsythe)"
  blockCount, treatmentCount = matrix.shape
  if treatmentCount < 2 or blockCount < 2:
    return DiagnosticOutcome(
      name=name, computed=False,
      interpretation="not computed: needs at least two treatments and two blocks")
  deviations = numpy.abs(matrix - numpy.median(matrix, axis=0))
  groupMeans = deviations.mean(axis=0)
  grandMean = float(deviations.mean())
  numeratorDf = treatmentCount - 1
  denominatorDf = treatmentCount * (blockCount - 1)
  sumSquaresBetween = float(blockCount * ((groupMeans - grandMean) ** 2).sum())
  sumSquaresWithin = float(((deviations - groupMeans) ** 2).sum())
  if sumSquaresWithin <= 0.0:
    return DiagnosticOutcome(
      name=name, computed=False,
      interpretation="not computed: no within-treatment variation in absolute deviations")
  fStatistic = (sumSquaresBetween / numeratorDf) / (sumSquaresWithin / denominatorDf)
  pValue = fDistributionSurvival(fStatistic, numeratorDf, denominatorDf)
  return DiagnosticOutcome(
    name=name, computed=True, statisticName="F", statistic=fStatistic,
    numeratorDegreesOfFreedom=numeratorDf, denominatorDegreesOfFreedom=denominatorDf,
    pValue=pValue,
    interpretation=_reading(
      pValue < significanceLevel, pValue,
      "Unequal error variance across treatments", "No evidence of unequal variance"))


def tukeyNonAdditivity(matrix, significanceLevel=0.05):
  """Tukey's one-degree-of-freedom test for block-by-treatment non-additivity.

  Partitions a single non-additivity term out of the RCBD error and tests it
  against the remainder. Returns a DiagnosticOutcome.
  """
  name = "Non-additivity (Tukey one df)"
  blockCount, treatmentCount = matrix.shape
  denominatorDf = (treatmentCount - 1) * (blockCount - 1) - 1
  if denominatorDf < 1:
    return DiagnosticOutcome(
      name=name, computed=False,
      interpretation="not computed: too few error degrees of freedom for the one-df test")
  grand = float(matrix.mean())
  treatmentEffects = matrix.mean(axis=0) - grand
  blockEffects = matrix.mean(axis=1) - grand
  sumTreatmentSquares = float((treatmentEffects ** 2).sum())
  sumBlockSquares = float((blockEffects ** 2).sum())
  if sumTreatmentSquares <= 0.0 or sumBlockSquares <= 0.0:
    return DiagnosticOutcome(
      name=name, computed=False,
      interpretation="not computed: no treatment or no block variation")
  crossProduct = float((matrix * blockEffects[:, None] * treatmentEffects[None, :]).sum())
  sumSquaresNonadditivity = crossProduct * crossProduct / (sumTreatmentSquares * sumBlockSquares)
  sumSquaresTotal = float(((matrix - grand) ** 2).sum())
  sumSquaresError = sumSquaresTotal - blockCount * sumTreatmentSquares - treatmentCount * sumBlockSquares
  sumSquaresRemainder = sumSquaresError - sumSquaresNonadditivity
  if sumSquaresRemainder <= 1.0e-12 * max(1.0, sumSquaresError):
    return DiagnosticOutcome(
      name=name, computed=False,
      interpretation="not computed: no residual variation after the non-additivity term")
  fStatistic = sumSquaresNonadditivity / (sumSquaresRemainder / denominatorDf)
  pValue = fDistributionSurvival(fStatistic, 1, denominatorDf)
  return DiagnosticOutcome(
    name=name, computed=True, statisticName="F", statistic=fStatistic,
    numeratorDegreesOfFreedom=1, denominatorDegreesOfFreedom=denominatorDf, pValue=pValue,
    interpretation=_reading(
      pValue < significanceLevel, pValue,
      "Significant non-additivity; the additive RCBD model may be inadequate",
      "No evidence of non-additivity"))


def shapiroWilkResiduals(matrix, significanceLevel=0.05):
  """Shapiro-Wilk normality test on the additive-model residuals.

  Residual_ij = y_ij - (treatment mean + block mean - grand mean). Standard
  practice runs the test on these fitted residuals; they are constrained rather
  than independent, a caveat the report states. Returns a DiagnosticOutcome.
  """
  name = "Normality of residuals (Shapiro-Wilk)"
  grand = float(matrix.mean())
  fitted = matrix.mean(axis=0)[None, :] + matrix.mean(axis=1)[:, None] - grand
  residuals = (matrix - fitted).flatten()
  count = int(residuals.size)
  if count < shapiroWilkMinimum:
    return DiagnosticOutcome(
      name=name, computed=False,
      interpretation=f"not computed: only {count} residuals (need at least {shapiroWilkMinimum})")
  if float(residuals.max() - residuals.min()) <= 0.0:
    return DiagnosticOutcome(
      name=name, computed=False, interpretation="not computed: residuals have zero spread")
  w, pValue = shapiroWilk(residuals.tolist())
  return DiagnosticOutcome(
    name=name, computed=True, statisticName="W", statistic=w, pValue=pValue,
    interpretation=_reading(
      pValue < significanceLevel, pValue,
      "Residuals depart from normality", "No evidence against normal residuals"))


def assessAssumptions(assessmentCode, package, layout, observations, significanceLevel=0.05):
  """Compute the report-only ANOVA assumption diagnostics for one assessment.

  Diagnostics never change the analysis (decision 0006). Reuses the validated
  RCBD matrix, so a non-numeric or incomplete design raises the same
  AnalysisError as the ANOVA.
  """
  if not 0.0 < significanceLevel < 1.0:
    raise ValueError(f"significanceLevel must be in (0, 1), got {significanceLevel}")
  matrix, _, _, _ = buildRcbdMatrix(assessmentCode, package, layout, observations)
  return Assumptions(
    assessmentCode=assessmentCode,
    significanceLevel=significanceLevel,
    equalVariance=brownForsythe(matrix, significanceLevel),
    nonAdditivity=tukeyNonAdditivity(matrix, significanceLevel),
    normality=shapiroWilkResiduals(matrix, significanceLevel),
  )
