# SPDX-License-Identifier: Apache-2.0
"""Distribution functions needed for the ANOVA, computed natively.

Per decision 0002 the analysis owns its math and does not take scipy as a runtime
dependency. The only special function the RCBD ANOVA needs is the upper-tail
F-distribution probability, which reduces to the regularized incomplete beta
function. The incomplete beta is evaluated by the standard continued-fraction
(Lentz's method); these are validated against scipy in the tests.
"""

from __future__ import annotations

import math

_maxIterations = 300
_epsilon = 3.0e-16
_tiny = 1.0e-300  # guards against division by zero in the continued fraction


def regularizedIncompleteBeta(x: float, a: float, b: float) -> float:
  """The regularized incomplete beta function I_x(a, b), for 0 <= x <= 1."""
  if x < 0.0 or x > 1.0:
    raise ValueError(f"x must be in [0, 1], got {x}")
  if a <= 0.0 or b <= 0.0:
    raise ValueError(f"a and b must be positive, got a={a}, b={b}")
  if x == 0.0:
    return 0.0
  if x == 1.0:
    return 1.0
  logFront = (
    math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    + a * math.log(x) + b * math.log1p(-x)
  )
  front = math.exp(logFront)
  # The continued fraction converges quickly for x < (a+1)/(a+b+2); otherwise use
  # the reflection I_x(a, b) = 1 - I_{1-x}(b, a), which moves into that region.
  if x < (a + 1.0) / (a + b + 2.0):
    return front * _betaContinuedFraction(x, a, b) / a
  return 1.0 - front * _betaContinuedFraction(1.0 - x, b, a) / b


def _betaContinuedFraction(x: float, a: float, b: float) -> float:
  qab = a + b
  qap = a + 1.0
  qam = a - 1.0
  c = 1.0
  d = 1.0 - qab * x / qap
  if abs(d) < _tiny:
    d = _tiny
  d = 1.0 / d
  result = d
  for iteration in range(1, _maxIterations + 1):
    even = 2 * iteration
    numerator = iteration * (b - iteration) * x / ((qam + even) * (a + even))
    d = 1.0 + numerator * d
    if abs(d) < _tiny:
      d = _tiny
    c = 1.0 + numerator / c
    if abs(c) < _tiny:
      c = _tiny
    d = 1.0 / d
    result *= d * c
    numerator = -(a + iteration) * (qab + iteration) * x / ((a + even) * (qap + even))
    d = 1.0 + numerator * d
    if abs(d) < _tiny:
      d = _tiny
    c = 1.0 + numerator / c
    if abs(c) < _tiny:
      c = _tiny
    d = 1.0 / d
    delta = d * c
    result *= delta
    if abs(delta - 1.0) < _epsilon:
      return result
  raise ValueError(f"incomplete beta continued fraction did not converge for x={x}, a={a}, b={b}")


def fDistributionSurvival(fStatistic: float, numeratorDf: int, denominatorDf: int) -> float:
  """Upper-tail probability P(F > fStatistic) for F(numeratorDf, denominatorDf).

  This is the ANOVA p-value: the probability of an F at least this large under the
  null hypothesis.
  """
  if numeratorDf <= 0 or denominatorDf <= 0:
    raise ValueError(f"degrees of freedom must be positive, got {numeratorDf}, {denominatorDf}")
  if fStatistic <= 0.0:
    return 1.0
  x = denominatorDf / (denominatorDf + numeratorDf * fStatistic)
  return regularizedIncompleteBeta(x, denominatorDf / 2.0, numeratorDf / 2.0)


def tDistributionSurvival(t: float, df: int) -> float:
  """Upper-tail probability P(T > t) for a Student t with df degrees of freedom."""
  if df <= 0:
    raise ValueError(f"degrees of freedom must be positive, got {df}")
  half = 0.5 * regularizedIncompleteBeta(df / (df + t * t), df / 2.0, 0.5)
  return half if t >= 0.0 else 1.0 - half


def tCriticalValue(probabilityUpperTail: float, df: int) -> float:
  """The positive t with P(T > t) = probabilityUpperTail for a t with df df.

  For a two-sided test at level alpha, pass alpha / 2. The survival is strictly
  decreasing in t, so the value is found by bracketing then bisection.
  """
  if df <= 0:
    raise ValueError(f"degrees of freedom must be positive, got {df}")
  if not 0.0 < probabilityUpperTail < 0.5:
    raise ValueError(f"upper-tail probability must be in (0, 0.5), got {probabilityUpperTail}")
  low = 0.0
  high = 1.0
  while tDistributionSurvival(high, df) > probabilityUpperTail:
    high *= 2.0
    if high > 1.0e12:
      raise ValueError("failed to bracket the t critical value")
  for _ in range(200):
    middle = 0.5 * (low + high)
    if tDistributionSurvival(middle, df) > probabilityUpperTail:
      low = middle
    else:
      high = middle
    if high - low < 1.0e-12 * max(1.0, high):
      break
  return 0.5 * (low + high)
