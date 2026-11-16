# SPDX-License-Identifier: Apache-2.0
"""Tests for the native distribution functions.

The continued-fraction incomplete beta and the F-distribution survival are
cross-checked against scipy (available as a statsmodels dependency in the test
environment) and against analytic values that hold independently of any library.
"""

import pytest
from scipy import special, stats

from openfurrow.analysis.distributions import (
  fDistributionSurvival,
  inverseNormalCdf,
  normalCdf,
  regularizedIncompleteBeta,
  tCriticalValue,
  tDistributionSurvival,
)


# ---- analytic sanity (independent of scipy) ------------------------------

def testBetaUniformEqualsX():
  # I_x(1, 1) = x exactly.
  for x in (0.1, 0.25, 0.5, 0.75, 0.9):
    assert regularizedIncompleteBeta(x, 1.0, 1.0) == pytest.approx(x, abs=1e-12)


def testBetaSymmetricMidpoint():
  # I_0.5(a, a) = 0.5 by symmetry.
  for a in (2.0, 3.0, 5.5):
    assert regularizedIncompleteBeta(0.5, a, a) == pytest.approx(0.5, abs=1e-12)


def testBetaEndpoints():
  assert regularizedIncompleteBeta(0.0, 2.0, 3.0) == 0.0
  assert regularizedIncompleteBeta(1.0, 2.0, 3.0) == 1.0


def testFSurvivalEqualDfAtOneIsHalf():
  # For F(d, d), P(F > 1) = 0.5.
  for df in (3, 5, 10, 20):
    assert fDistributionSurvival(1.0, df, df) == pytest.approx(0.5, abs=1e-12)


def testFSurvivalNonPositiveIsOne():
  assert fDistributionSurvival(0.0, 2, 10) == 1.0
  assert fDistributionSurvival(-3.0, 2, 10) == 1.0


# ---- cross-check against scipy -------------------------------------------

def testBetaMatchesScipy():
  cases = [
    (0.2, 0.5, 0.5), (0.7, 2.0, 3.0), (0.05, 5.0, 1.0), (0.95, 1.0, 5.0),
    (0.4, 10.0, 2.0), (0.6, 2.5, 7.5), (0.99, 0.5, 50.0), (0.01, 50.0, 0.5),
  ]
  for x, a, b in cases:
    assert regularizedIncompleteBeta(x, a, b) == pytest.approx(special.betainc(a, b, x), rel=1e-10, abs=1e-12)


def testFSurvivalMatchesScipy():
  cases = [
    (1.485, 2, 10), (5.28, 5, 10), (0.5, 3, 12), (4.0, 1, 30),
    (2.5, 4, 4), (10.0, 6, 20), (0.1, 2, 2), (25.0, 3, 3),
  ]
  for f, df1, df2 in cases:
    assert fDistributionSurvival(f, df1, df2) == pytest.approx(stats.f.sf(f, df1, df2), rel=1e-9, abs=1e-12)


def testTSurvivalAtZeroIsHalf():
  for df in (1, 5, 30):
    assert tDistributionSurvival(0.0, df) == pytest.approx(0.5, abs=1e-12)


def testTSurvivalMatchesScipy():
  cases = [(0.5, 5), (2.0, 10), (-1.5, 8), (3.0, 20), (-0.25, 3), (1.96, 100)]
  for t, df in cases:
    assert tDistributionSurvival(t, df) == pytest.approx(stats.t.sf(t, df), rel=1e-9, abs=1e-12)


def testTCriticalValueMatchesScipy():
  cases = [(0.025, 10), (0.025, 6), (0.005, 20), (0.05, 3), (0.025, 100), (0.1, 4)]
  for upperTail, df in cases:
    assert tCriticalValue(upperTail, df) == pytest.approx(stats.t.ppf(1 - upperTail, df), rel=1e-9, abs=1e-10)


# ---- fail-loud edges -----------------------------------------------------

def testBetaRejectsOutOfRangeX():
  with pytest.raises(ValueError, match="x must be in"):
    regularizedIncompleteBeta(1.5, 2.0, 2.0)


def testBetaRejectsNonPositiveParameters():
  with pytest.raises(ValueError, match="must be positive"):
    regularizedIncompleteBeta(0.5, 0.0, 2.0)


def testFSurvivalRejectsNonPositiveDf():
  with pytest.raises(ValueError, match="degrees of freedom must be positive"):
    fDistributionSurvival(2.0, 0, 10)


# ---- normal CDF and its inverse (decision 0006) --------------------------

def testNormalCdfAnalytic():
  # Phi(0) = 0.5, and Phi(x) + Phi(-x) = 1 by symmetry.
  assert normalCdf(0.0) == pytest.approx(0.5, abs=1e-15)
  for x in (0.3, 1.0, 2.5, 4.0):
    assert normalCdf(x) + normalCdf(-x) == pytest.approx(1.0, abs=1e-15)


def testNormalCdfMatchesScipy():
  for x in (-6.0, -3.0, -1.5, -0.5, 0.0, 0.3, 1.0, 2.5, 4.0, 6.0):
    assert normalCdf(x) == pytest.approx(stats.norm.cdf(x), rel=1e-12, abs=1e-15)


def testInverseNormalCdfAnalytic():
  assert inverseNormalCdf(0.5) == pytest.approx(0.0, abs=1e-12)
  # The 97.5th percentile of the standard normal.
  assert inverseNormalCdf(0.975) == pytest.approx(1.9599639845400545, abs=1e-9)


def testInverseNormalCdfMatchesScipy():
  for p in (1e-8, 1e-4, 0.001, 0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99, 0.9999, 1 - 1e-8):
    assert inverseNormalCdf(p) == pytest.approx(stats.norm.ppf(p), rel=1e-8, abs=1e-8)


def testNormalRoundTrip():
  for p in (0.001, 0.02, 0.3, 0.7, 0.98, 0.999):
    assert normalCdf(inverseNormalCdf(p)) == pytest.approx(p, abs=1e-9)


def testInverseNormalCdfRejectsOutOfRange():
  for bad in (0.0, 1.0, -0.1, 1.5):
    with pytest.raises(ValueError, match="p must be in"):
      inverseNormalCdf(bad)
