# SPDX-License-Identifier: Apache-2.0
"""The studentized range distribution, for Tukey's honestly significant difference.

Computed natively (decision 0002) by the method of Copenhaver and Holland (1988,
Journal of Statistical Computation and Simulation 30:1-15), the one R's ptukey follows:
the probability that the range of k independent standard normals, divided by an
independent estimate of their standard deviation on df degrees of freedom, is below q.
The inner integral over the range uses 12-point Gauss-Legendre quadrature on two or three
intervals; the outer integral over the chi distribution of the standard deviation uses
16-point Gauss-Legendre quadrature on unit (or shorter) intervals until they stop
contributing. The quantile is found by bisection on the probability. Validated against
scipy.stats.studentized_range in the tests.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy

from openfurrow.analysis.distributions import normalCdf

_innerNodes, _innerWeights = numpy.polynomial.legendre.leggauss(12)
_outerNodes, _outerWeights = numpy.polynomial.legendre.leggauss(16)
_inverseSqrtTwoPi = 1.0 / math.sqrt(2.0 * math.pi)


def _rangeProbability(w: float, groups: int) -> float:
  """P(range of `groups` standard normals < w), by Hartley's form of the integral."""
  half = 0.5 * w
  if half >= 8.0:
    return 1.0
  probability = 2.0 * normalCdf(half) - 1.0
  probability = probability ** groups if probability >= math.exp(-50.0 / groups) else 0.0
  intervals = 2 if w > 3.0 else 3
  lower = half
  width = (8.0 - half) / intervals
  integral = 0.0
  for _ in range(intervals):
    middle, halfWidth = lower + 0.5 * width, 0.5 * width
    total = 0.0
    for node, weight in zip(_innerNodes, _innerWeights):
      point = middle + halfWidth * node
      if point * point > 60.0:
        continue
      inner = normalCdf(point) - normalCdf(point - w)
      if inner >= math.exp(-30.0 / (groups - 1)):
        total += weight * math.exp(-0.5 * point * point) * inner ** (groups - 1)
    integral += total * 2.0 * halfWidth * groups * _inverseSqrtTwoPi
    lower += width
  probability += integral
  if probability <= math.exp(-30.0):
    return 0.0
  return min(probability, 1.0)


def overErrorDegreesOfFreedom(inner: Callable[[float], float], scale: float, degreesOfFreedom: float) -> float:
  """E[inner(scale * s)] for s the ratio of an error estimate on `degreesOfFreedom` to the true sigma.

  s^2 is chi-square over its degrees of freedom; the expectation is taken over x = 2 s^2,
  whose density is proportional to x^(df/2 - 1) exp(-df x / 4), by 16-point
  Gauss-Legendre quadrature on intervals of width 2, 1, 0.5 or 0.25 by df, until they stop
  contributing. Near zero the integrand can grow like a square root, which Gauss-Legendre
  integrates poorly on one interval, so the first interval is cut into pieces that shrink
  by a factor of four towards zero, as small error df need.
  """
  halfDf = 0.5 * degreesOfFreedom
  logConstant = halfDf * math.log(degreesOfFreedom) - degreesOfFreedom * math.log(2.0) - math.lgamma(halfDf)
  if degreesOfFreedom <= 100.0:
    length = 1.0
  elif degreesOfFreedom <= 800.0:
    length = 0.5
  elif degreesOfFreedom <= 5000.0:
    length = 0.25
  else:
    length = 0.125

  def piece(start: float, end: float) -> float:
    middle, halfWidth = 0.5 * (start + end), 0.5 * (end - start)
    total = 0.0
    for node, weight in zip(_outerNodes, _outerWeights):
      point = middle + node * halfWidth
      logTerm = logConstant + (halfDf - 1.0) * math.log(point) - point * degreesOfFreedom * 0.25
      if logTerm >= -30.0:
        total += weight * math.exp(logTerm) * inner(scale * math.sqrt(0.5 * point))
    return total * halfWidth

  first = 2.0 * length
  answer = sum(piece(first * 4.0 ** -(j + 1), first * 4.0 ** -j) for j in range(12)) + piece(0.0, first * 4.0 ** -12)
  for interval in range(2, 51):
    contribution = piece((interval - 1) * first, interval * first)
    if interval * length >= 1.0 and contribution <= 1.0e-14:
      break
    answer += contribution
  return min(answer, 1.0)


def studentizedRangeCdf(q: float, groups: int, degreesOfFreedom: float) -> float:
  """P(Q < q) for the studentized range of `groups` means with `degreesOfFreedom` for the error."""
  if groups < 2 or degreesOfFreedom < 2:
    raise ValueError(f"the studentized range needs at least 2 groups and 2 df, got {groups} and {degreesOfFreedom}")
  if q <= 0.0:
    return 0.0
  if math.isinf(q):
    return 1.0
  if degreesOfFreedom > 25000.0:
    return _rangeProbability(q, groups)
  return overErrorDegreesOfFreedom(lambda w: _rangeProbability(w, groups), q, degreesOfFreedom)


def quantileOf(cdf: Callable[[float], float], probability: float) -> float:
  """The x with cdf(x) = probability for an increasing cdf from 0 at x = 0, by the Illinois method."""
  if not 0.0 < probability < 1.0:
    raise ValueError(f"probability must be in (0, 1), got {probability}")

  def gap(x: float) -> float:
    return cdf(x) - probability

  low, high = 0.0, 1.0
  gapLow, gapHigh = -probability, gap(high)
  while gapHigh < 0.0:
    low, gapLow = high, gapHigh
    high *= 2.0
    gapHigh = gap(high)
  side = 0
  for _ in range(200):
    middle = (low * gapHigh - high * gapLow) / (gapHigh - gapLow)
    gapMiddle = gap(middle)
    if gapMiddle == 0.0 or high - low <= 1.0e-10 * high:
      return middle
    if (gapMiddle > 0.0) == (gapHigh > 0.0):
      high, gapHigh = middle, gapMiddle
      if side == -1:
        gapLow *= 0.5
      side = -1
    else:
      low, gapLow = middle, gapMiddle
      if side == 1:
        gapHigh *= 0.5
      side = 1
  raise ArithmeticError(f"the quantile did not converge for probability {probability}")


def studentizedRangeQuantile(probability: float, groups: int, degreesOfFreedom: float) -> float:
  """The q with P(Q < q) = probability."""
  return quantileOf(lambda q: studentizedRangeCdf(q, groups, degreesOfFreedom), probability)