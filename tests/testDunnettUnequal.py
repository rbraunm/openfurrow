# SPDX-License-Identifier: Apache-2.0
"""Dunnett's test when replication is unequal (decision 0043).

With unequal replication the comparisons with the check are no longer correlated 1/2.
The critical value is computed where their correlations are products of one loading per
treatment, and refused by name where they are not. Oracles: the two-sided t with one
comparison; scipy.stats.dunnett for unequally replicated groups; scipy's multivariate t
for the level the critical value holds on a given correlation matrix, the matrix taken
from statsmodels for a block design with a missing plot. scipy integrates by quasi-Monte
Carlo, so those agree to about 1e-4 and are held to 5e-4.
"""

import math

import numpy
import pytest
import statsmodels.formula.api as statsmodelsFormula
from scipy import stats

from openfurrow.analysis import AnalysisError, MissingPlotPolicy, analyzeCrd, analyzeRcbd, compareWithControl
from openfurrow.analysis.dunnett import dunnettCdf, dunnettQuantile, equalLoadings, productLoadings, sharedGrid

from testMissingPlots import blockTrial, crdTrial, frameOf, meanContrast


@pytest.mark.parametrize("loading", [0.0, 0.3, -0.6, 0.95, 0.99])
def testOneComparisonIsTheTwoSidedTWhateverItsLoading(loading):
  for degreesOfFreedom in (3, 12, 40):
    for d in (0.8, 2.0, 3.5):
      assert dunnettCdf(d, [loading], degreesOfFreedom) == pytest.approx(
        1 - 2 * stats.t.sf(d, degreesOfFreedom), abs=1e-10)


def testTheGridOfTheSharedFactorCoversTheNormalDensity():
  for loadings in (equalLoadings(1), equalLoadings(30), [0.2, 0.97, 0.5], [0.0]):
    grid = sharedGrid(loadings)
    assert sum(weight for _, weight in grid) == pytest.approx(1.0, abs=1e-13)
    assert (grid[0][0], grid[-1][0]) == (-8.5, pytest.approx(8.5, abs=1e-12))
  # A steeper comparison and more comparisons both call for a finer grid.
  assert len(sharedGrid([0.97] * 3)) > len(sharedGrid(equalLoadings(3))) > len(sharedGrid([0.2] * 3))
  assert len(sharedGrid(equalLoadings(30))) > len(sharedGrid(equalLoadings(3)))


@pytest.mark.parametrize("sizes", [(5, 3, 6, 2, 4), (2, 6, 6, 6), (8, 3, 3), (3, 3, 9, 4, 2, 7, 5)])
def testUnequalGroupsAgreeWithScipy(sizes):
  generator = numpy.random.default_rng(sum(sizes))
  groups = [generator.normal(10 + index * 0.5, 1.0, size) for index, size in enumerate(sizes)]
  result = stats.dunnett(*groups[1:], control=groups[0], random_state=numpy.random.default_rng(1))
  loadings = [math.sqrt(size / (size + sizes[0])) for size in sizes[1:]]
  errorDegreesOfFreedom = sum(sizes) - len(sizes)
  for statistic, pValue in zip(result.statistic, result.pvalue):
    assert 1 - dunnettCdf(abs(statistic), loadings, errorDegreesOfFreedom) == pytest.approx(pValue, abs=5e-4)


@pytest.mark.parametrize("loadings, degreesOfFreedom", [
  (equalLoadings(4), 12),
  ([0.0, 0.0, 0.0], 9),
  ([0.58, 0.71, 0.82], 14),
  ([0.93, 0.93, 0.93, 0.5], 20),
  ([0.6, -0.4, 0.7], 10),
])
def testTheCriticalValueHoldsItsLevelOnTheMultivariateT(loadings, degreesOfFreedom):
  critical = dunnettQuantile(0.95, loadings, degreesOfFreedom)
  correlation = numpy.outer(loadings, loadings)
  numpy.fill_diagonal(correlation, 1.0)
  distribution = stats.multivariate_t(loc=numpy.zeros(len(loadings)), shape=correlation, df=degreesOfFreedom, seed=3)
  inside = distribution.cdf(numpy.full(len(loadings), critical), lower_limit=numpy.full(len(loadings), -critical))
  assert inside == pytest.approx(0.95, abs=5e-4)


def testProductLoadingsAreRecoveredAndAnythingElseIsNot():
  assert productLoadings([[1.0]]) == [0.0]
  assert productLoadings([[1.0, 0.36], [0.36, 1.0]]) == pytest.approx([0.6, 0.6])
  assert productLoadings([[1.0, -0.36], [-0.36, 1.0]]) == pytest.approx([0.6, -0.6])
  half = [[1.0 if row == column else 0.5 for column in range(4)] for row in range(4)]
  assert productLoadings(half) == [math.sqrt(0.5)] * 4
  loadings = [0.82, 0.41, -0.63, 0.7, 0.15]
  correlation = [[1.0 if row == column else loadings[row] * loadings[column] for column in range(5)] for row in range(5)]
  assert productLoadings(correlation) == pytest.approx(loadings, abs=1e-12)
  correlation[1][3] = correlation[3][1] = correlation[1][3] + 0.01
  assert productLoadings(correlation) is None
  # 0.9 between each pair but one, 0.1: the loadings that would give it are beyond 1.
  assert productLoadings([[1.0, 0.9, 0.9], [0.9, 1.0, 0.1], [0.9, 0.1, 1.0]]) is None


def checkValues(blockCount=5):
  generator = numpy.random.default_rng(29)
  treatments = ["UTC", "A", "B", "C", "D"]
  cells = {
    (treatment, block): float(round(30.0 - 4.0 * index + 1.5 * block + generator.normal(0.0, 2.0), 2))
    for index, treatment in enumerate(treatments) for block in range(1, blockCount + 1)
  }
  return treatments, cells


@pytest.mark.parametrize("missing", [{("B", 2)}, {("UTC", 4)}])
@pytest.mark.parametrize("policy", [MissingPlotPolicy.leastSquares, MissingPlotPolicy.estimate])
def testOneMissingPlotInBlocksAgainstStatsmodelsAndTheMultivariateT(missing, policy):
  treatments, cells = checkValues()
  package, layout, observations = blockTrial(treatments, 5, cells, missing, roles={"UTC": "untreatedControl"})
  result = analyzeRcbd("Y", package, layout, observations, policy)
  comparison = compareWithControl(result, package)
  frame = frameOf(treatments, cells, missing, None)
  fit = statsmodelsFormula.ols("y ~ C(block) + C(treatment, levels=treatments)", data=frame).fit()
  check = meanContrast(fit, treatments, [1, 2, 3, 4, 5], "UTC")
  contrasts = numpy.array([meanContrast(fit, treatments, [1, 2, 3, 4, 5], code) - check for code in treatments[1:]])
  covariance = contrasts @ fit.cov_params().to_numpy() @ contrasts.T
  errors = numpy.sqrt(numpy.diag(covariance))
  assert comparison.checkCode == "UTC" and comparison.standardError is None
  if missing == {("UTC", 4)}:
    # Short of a plot of the check itself, every comparison with it has the same standard error still.
    assert comparison.criticalDifference == pytest.approx(comparison.criticalValue * float(errors[0]), rel=1e-9)
    assert errors == pytest.approx(numpy.full(4, errors[0]), rel=1e-12)
  else:
    assert comparison.criticalDifference is None
  for row, contrast, error in zip(comparison.comparisons, contrasts, errors):
    assert row.difference == pytest.approx(float(contrast @ fit.params.to_numpy()), rel=1e-9)
    assert row.differenceStandardError == pytest.approx(float(error), rel=1e-9)
    assert row.criticalDifference == pytest.approx(comparison.criticalValue * float(error), rel=1e-9)
    assert row.significant == (abs(row.difference) > row.criticalDifference)
  correlation = covariance / numpy.outer(errors, errors)
  distribution = stats.multivariate_t(loc=numpy.zeros(4), shape=correlation, df=fit.df_resid, seed=5)
  inside = distribution.cdf(numpy.full(4, comparison.criticalValue), lower_limit=numpy.full(4, -comparison.criticalValue))
  assert inside == pytest.approx(0.95, abs=5e-4)
  # The correlations are no longer all 1/2, so the equal-replication value is not the one that holds 0.95.
  assert comparison.criticalValue != pytest.approx(dunnettQuantile(0.95, equalLoadings(4), int(fit.df_resid)), abs=1e-4)


def testAPatternWhoseCorrelationsAreNotProductsIsRefusedByName():
  treatments, cells = checkValues(blockCount=4)
  missing = {("UTC", 1), ("A", 1), ("B", 1), ("A", 4)}
  package, layout, observations = blockTrial(treatments, 4, cells, missing, roles={"UTC": "untreatedControl"})
  for policy in (MissingPlotPolicy.leastSquares, MissingPlotPolicy.estimate):
    result = analyzeRcbd("Y", package, layout, observations, policy)
    with pytest.raises(AnalysisError) as raised:
      compareWithControl(result, package)
    assert "the comparisons with the check 'UTC' are correlated in a way that is not one loading per treatment" in str(raised.value)
    assert "it is not approximated" in str(raised.value)


@pytest.mark.parametrize("sizes", [(4, 3, 4, 2), (2, 4, 4, 3, 4)])
def testCRDWithUnequalReplicationAgreesWithScipy(sizes):
  package, layout, observations, frame, treatments, _ = crdTrial(sizes, seed=12, check="T1")
  result = analyzeCrd("Y", package, layout, observations, MissingPlotPolicy.leastSquares)
  comparison = compareWithControl(result, package)
  groups = [frame.loc[frame["treatment"] == code, "y"].to_numpy() for code in treatments]
  oracle = stats.dunnett(*groups[1:], control=groups[0], random_state=numpy.random.default_rng(2))
  loadings = [math.sqrt(size / (size + sizes[0])) for size in sizes[1:]]
  assert comparison.criticalValue == pytest.approx(dunnettQuantile(0.95, loadings, sum(sizes) - len(sizes)), rel=1e-9)
  for row, statistic, pValue in zip(comparison.comparisons, oracle.statistic, oracle.pvalue):
    ours = row.difference / row.differenceStandardError
    assert ours == pytest.approx(statistic, rel=1e-9)
    assert 1 - dunnettCdf(abs(ours), loadings, result.errorDegreesOfFreedom) == pytest.approx(pValue, abs=5e-4)
    if abs(pValue - 0.05) > 2e-3:
      assert row.significant == (pValue < 0.05)
  assert comparison.criticalDifference is None
  assert len({round(row.criticalDifference, 9) for row in comparison.comparisons}) > 1
