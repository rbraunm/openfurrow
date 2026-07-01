# SPDX-License-Identifier: Apache-2.0
"""Tests for the Shapiro-Wilk normality diagnostic (decision 0006).

Shapiro-Wilk uses Royston's AS R94, the same algorithm as scipy.stats.shapiro,
so W and the p-value are cross-checked against scipy across a range of sample
sizes and distributions. The n = 3 case has an exact closed form, checked
independently of scipy, and the fail-loud edges are checked directly.
"""

import numpy as np
import pytest
from scipy import stats

from openfurrow.analysis.diagnostics import shapiroWilk, shapiroWilkMinimum


# ---- analytic (independent of scipy) -------------------------------------

def testThreeEquallySpacedPointsAreMaximallyNormal():
  # For n = 3 the weights are (-1, 0, 1)/sqrt(2); three equally spaced points
  # give W = 1 exactly, and the exact n=3 p-value is then 1.
  w, pValue = shapiroWilk([0.0, 1.0, 2.0])
  assert w == pytest.approx(1.0, abs=1e-12)
  assert pValue == pytest.approx(1.0, abs=1e-12)


def testClearlyNonNormalSampleIsRejected():
  # Nine tight values and one far outlier: strongly non-normal, tiny p.
  sample = [0.0, 0.1, 0.2, 0.15, 0.05, 0.12, 0.08, 0.18, 0.03, 1000.0]
  _, pValue = shapiroWilk(sample)
  assert pValue < 0.01


# ---- cross-check against scipy -------------------------------------------

def testShapiroWilkMatchesScipy():
  rng = np.random.default_rng(20260701)
  generators = {
    "normal": lambda n: rng.normal(50.0, 10.0, n),
    "uniform": lambda n: rng.uniform(0.0, 1.0, n),
    "exponential": lambda n: rng.exponential(1.0, n),
  }
  for n in (3, 4, 5, 6, 7, 10, 11, 12, 15, 20, 30, 50, 100):
    for generate in generators.values():
      sample = list(generate(n))
      w, pValue = shapiroWilk(sample)
      reference = stats.shapiro(sample)
      assert w == pytest.approx(reference.statistic, abs=1e-7)
      assert pValue == pytest.approx(reference.pvalue, abs=1e-6)


# ---- fail-loud edges -----------------------------------------------------

def testRejectsTooFewValues():
  with pytest.raises(ValueError, match="at least"):
    shapiroWilk([1.0, 2.0])
  assert shapiroWilkMinimum == 3


def testRejectsConstantSample():
  with pytest.raises(ValueError, match="constant"):
    shapiroWilk([5.0, 5.0, 5.0, 5.0])
