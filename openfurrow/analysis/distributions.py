# SPDX-License-Identifier: Apache-2.0
"""Distribution functions for the ANOVA and its diagnostics, computed natively.

Per decision 0002 the analysis owns its math and takes no scipy runtime
dependency. The RCBD ANOVA needs the upper-tail F-distribution probability, which
reduces to the regularized incomplete beta (evaluated by the standard
continued-fraction, Lentz's method), plus the Student t survival and critical
value. The assumption diagnostics of decision 0006 add the standard normal CDF
(from the standard library's erfc) and its inverse (Wichura's AS 241). All are
validated against scipy in the tests.
"""

from __future__ import annotations

import math

_maxIterations = 300
_epsilon = 3.0e-16
_tiny = 1.0e-300  # guards against division by zero in the continued fraction

_sqrt2 = math.sqrt(2.0)

# Wichura AS 241 coefficients for the inverse normal CDF. Numerator polynomials
# (_a, _c, _e) carry the constant term; denominator polynomials (_b, _d, _f) have
# an implicit trailing 1, so they hold one fewer coefficient.
_a = (3.3871328727963666080e0, 1.3314166789178437745e2, 1.9715909503065514427e3,
      1.3731693765509461125e4, 4.5921953931549871457e4, 6.7265770927008700853e4,
      3.3430575583588128105e4, 2.5090809287301226727e3)
_b = (4.2313330701600911252e1, 6.8718700749205790830e2, 5.3941960214247511077e3,
      2.1213794301586595867e4, 3.9307895800092710610e4, 2.8729085735721942674e4,
      5.2264952788528545610e3)
_c = (1.42343711074968357734e0, 4.63033784156545415920e0, 5.76949722146069140550e0,
      3.64784832476320453730e0, 1.27045825245236838258e0, 2.41780725177450611770e-1,
      2.27238449892691845833e-2, 7.74545014278341407640e-4)
_d = (2.05319162663775882187e0, 1.67638483018380384940e0, 6.89767334985100004550e-1,
      1.48103976427480074590e-1, 1.51986665636164571966e-2, 5.47593808499534494600e-4,
      1.05075007164441684324e-9)
_e = (6.65790464350110377720e0, 5.46378491116411436990e0, 1.78482653991729133580e0,
      2.96560571828504891230e-1, 2.65321895265761230930e-2, 1.24266094738807843860e-3,
      2.71155556874348757815e-5, 2.01033439929228813265e-7)
_f = (5.99832206555887937690e-1, 1.36929880922735805310e-1, 1.48753612908506148525e-2,
      7.86869131145613259100e-4, 1.84631831751005468180e-5, 1.42151175831644588870e-7,
      2.04426310338993978564e-15)


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


def normalCdf(x: float) -> float:
  """Standard normal CDF Phi(x) = P(Z <= x).

  Computed from the complementary error function in the standard library, which
  is exact to double precision; the erfc form keeps accuracy in the left tail.
  """
  return 0.5 * math.erfc(-x / _sqrt2)


def inverseNormalCdf(p: float) -> float:
  """Standard normal quantile: the z with Phi(z) = p, for 0 < p < 1.

  Wichura's algorithm AS 241 (the rational approximation R and scipy use),
  accurate to full double precision. Fails loudly outside the open interval.
  """
  if not 0.0 < p < 1.0:
    raise ValueError(f"p must be in (0, 1), got {p}")
  q = p - 0.5
  if abs(q) <= 0.425:
    r = 0.180625 - q * q
    numerator = (((((((_a[7] * r + _a[6]) * r + _a[5]) * r + _a[4]) * r + _a[3]) * r
                   + _a[2]) * r + _a[1]) * r + _a[0])
    denominator = (((((((_b[6] * r + _b[5]) * r + _b[4]) * r + _b[3]) * r + _b[2]) * r
                     + _b[1]) * r + _b[0]) * r + 1.0)
    return q * numerator / denominator
  r = p if q < 0.0 else 1.0 - p
  r = math.sqrt(-math.log(r))
  if r <= 5.0:
    r -= 1.6
    numerator = (((((((_c[7] * r + _c[6]) * r + _c[5]) * r + _c[4]) * r + _c[3]) * r
                   + _c[2]) * r + _c[1]) * r + _c[0])
    denominator = (((((((_d[6] * r + _d[5]) * r + _d[4]) * r + _d[3]) * r + _d[2]) * r
                     + _d[1]) * r + _d[0]) * r + 1.0)
  else:
    r -= 5.0
    numerator = (((((((_e[7] * r + _e[6]) * r + _e[5]) * r + _e[4]) * r + _e[3]) * r
                   + _e[2]) * r + _e[1]) * r + _e[0])
    denominator = (((((((_f[6] * r + _f[5]) * r + _f[4]) * r + _f[3]) * r + _f[2]) * r
                     + _f[1]) * r + _f[0]) * r + 1.0)
  value = numerator / denominator
  return -value if q < 0.0 else value
