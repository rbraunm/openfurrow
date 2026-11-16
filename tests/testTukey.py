# SPDX-License-Identifier: Apache-2.0
"""Tukey's honestly significant difference and the studentized range behind it (decision 0028).

The distribution is computed natively and checked against scipy; the separation is checked
pair by pair against statsmodels' pairwise_tukeyhsd on the completely randomized trial of
Gomez and Gomez Table 2.1.
"""

import math

import pytest

from openfurrow.analysis import MeanComparison, analyzeCrd, analyzeSplitPlot, separateFactorMeans, separateMeans
from openfurrow.analysis.studentizedRange import studentizedRangeCdf, studentizedRangeQuantile
from openfurrow.reports import buildReport

from testCrd import gomezInputs as insecticideInputs
from testSplitPlot import gomezInputs as splitPlotInputs


@pytest.mark.parametrize("groups", [2, 3, 7, 15])
@pytest.mark.parametrize("degreesOfFreedom", [3, 5, 21, 120])
def testDistributionAgreesWithScipy(groups, degreesOfFreedom):
  studentizedRange = pytest.importorskip("scipy.stats").studentized_range
  for q in (0.8, 2.5, 4.0, 7.5):
    assert studentizedRangeCdf(q, groups, degreesOfFreedom) == pytest.approx(
      studentizedRange.cdf(q, groups, degreesOfFreedom), abs=1e-7)
  assert studentizedRangeQuantile(0.95, groups, degreesOfFreedom) == pytest.approx(
    studentizedRange.ppf(0.95, groups, degreesOfFreedom), rel=1e-7)


def testTwoGroupsAreATwoSidedT():
  """With two means the studentized range is |t| times the square root of two."""
  tDistribution = pytest.importorskip("scipy.stats").t
  q = 3.1
  assert studentizedRangeCdf(q, 2, 2) == pytest.approx(1 - 2 * tDistribution.sf(q / math.sqrt(2), 2), abs=1e-7)


def testDistributionRefusesTooFewGroupsOrDegrees():
  with pytest.raises(ValueError, match="at least 2 groups and 2 df"):
    studentizedRangeCdf(2.0, 1, 10)
  with pytest.raises(ValueError, match="at least 2 groups and 2 df"):
    studentizedRangeCdf(2.0, 3, 1)


def testHsdMatchesStatsmodelsPairByPair():
  studentizedRange = pytest.importorskip("scipy.stats").studentized_range
  multicomp = pytest.importorskip("statsmodels.stats.multicomp")
  package, layout, observations = insecticideInputs()
  result = analyzeCrd("Y", package, layout, observations)
  separation = separateMeans(result, meanComparison=MeanComparison.tukeyHSD)
  assert separation.criticalDifference == pytest.approx(
    studentizedRange.ppf(0.95, 7, 21) * math.sqrt(result.errorMeanSquare / 4), rel=1e-7)
  assert separation.methodKey == "report.method.tukeyHSD"
  treatmentOf = {plot.plotNumber: plot.treatmentCode for plot in layout.plots}
  tukey = multicomp.pairwise_tukeyhsd([o.value for o in observations], [treatmentOf[o.plotNumber] for o in observations])
  letters = {group.treatmentCode: set(group.group) for group in separation.groups}
  checked = 0
  for row in tukey.summary().data[1:]:
    first, second, reject = row[0], row[1], row[-1]
    assert bool(letters[first] & letters[second]) == (not reject), (first, second)
    checked += 1
  assert checked == 21


def testTukeyIsWiderThanTheLsd():
  result = analyzeCrd("Y", *insecticideInputs())
  tukey = separateMeans(result, meanComparison=MeanComparison.tukeyHSD).criticalDifference
  lsd = separateMeans(result, meanComparison=MeanComparison.lsd).criticalDifference
  assert tukey > lsd


def testFactorMeansOfASplitPlotByTukeyUseTheirOwnError():
  studentizedRange = pytest.importorskip("scipy.stats").studentized_range
  result = analyzeSplitPlot("Y", *splitPlotInputs())
  nitrogen = separateFactorMeans(result, "N", meanComparison=MeanComparison.tukeyHSD)
  assert nitrogen.criticalDifference == pytest.approx(
    studentizedRange.ppf(0.95, 6, 10) * math.sqrt(result.mainPlotErrorMeanSquare / 12), rel=1e-7)


def testReportNamesTukey():
  report = buildReport(*insecticideInputs(), meanComparison=MeanComparison.tukeyHSD)
  assert "Mean separation: Tukey's HSD (alpha = 0.05)" in report
  assert "- HSD (alpha = 0.05): " in report and "- LSD (alpha" not in report
  assert "One-way ANOVA (completely randomized); Tukey's HSD (alpha = 0.05)" in report
