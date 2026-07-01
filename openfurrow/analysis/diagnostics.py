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

from openfurrow.analysis.distributions import inverseNormalCdf, normalCdf

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
