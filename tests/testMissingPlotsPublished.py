# SPDX-License-Identifier: Apache-2.0
"""Missing plots against published worked examples (decision 0043).

Gomez and Gomez (1984), Statistical Procedures for Agricultural Research, 2nd edition:

- section 7.1.2.1, pages 276 to 279, Tables 7.1 to 7.3: the rice seeding-rate trial of
  Table 2.5 (fixture `gomezSeedRate.csv`) with the fourth treatment's value in
  replication II taken as missing, estimated by the missing data formula, with its
  analysis of variance and the standard error of a difference;
- section 7.1.2.6, pages 287 to 292, Tables 7.9 and 7.10: the same trial with the first
  treatment's value in replication I missing as well, estimated by iteration;
- section 2.1.2.2, pages 17 to 20, Tables 2.3 and 2.4: a completely randomized trial of
  herbicides with unequal replication (fixture `gomezHerbicide.csv`).

Read from an openly posted scan of the book. The book rounds each estimate to the whole
kg/ha before its analysis of variance and OpenFurrow does not, which moves the replication
and total sums of squares by a first-order amount and the error and corrected treatment
sums of squares hardly at all; each test says which figure it holds to which precision.
"""

import math

import numpy
import pytest

from openfurrow import TrialPackage, schemaVersion
from openfurrow.analysis import (
  MeanComparison,
  MissingPlotPolicy,
  analyzeCrd,
  analyzeRcbd,
  differenceStandardError,
  separateMeans,
)
from openfurrow.analysis.anova import anovaFromMatrix
from openfurrow.design import generateLayout
from openfurrow.schema.assessment import Transform
from openfurrow.schema.observation import Observation

from testMissingPlots import (
  assertBlockAnalysisMatchesStatsmodels,
  blockTrial,
  frameOf,
  readFixture,
  registryDatasets,
)

rates = ["R25", "R50", "R75", "R100", "R125", "R150"]
oneMissing = {("R100", 2)}
twoMissing = {("R100", 2), ("R25", 1)}


def seedRateCells():
  return registryDatasets()["gomezSeedRate"][2]


def seedRate(missing, policy):
  return analyzeRcbd("Y", *blockTrial(rates, 4, seedRateCells(), missing), policy)


def rowsOf(result):
  return {row.source: row for row in result.table}


def classicalTable(replacements):
  """The usual arithmetic on the book's own completed table, with its estimates as it rounded them."""
  cells = seedRateCells() | replacements
  matrix = numpy.array([[cells[(rate, block)] for rate in rates] for block in range(1, 5)])
  return rowsOf(anovaFromMatrix("Y", matrix, rates, Transform.none, 0.0, MissingPlotPolicy.refuse))


# ---- section 7.1.2.1: one missing value -----------------------------------------

def testTable71TotalsAreThoseOfTheFixture():
  cells = seedRateCells()
  present = {cell: value for cell, value in cells.items() if cell not in oneMissing}
  assert cells[("R100", 2)] == 4831
  assert [sum(value for (_, block), value in present.items() if block == wanted) for wanted in (1, 2, 3, 4)] == [
    30953, 26453, 29846, 26947]
  assert [sum(value for (rate, _), value in present.items() if rate == wanted) for wanted in rates] == [
    20496, 20281, 21217, 14560, 18832, 18813]
  assert sum(present.values()) == 114199


def testOneMissingValueIsEstimatedAsTheBookDoes():
  result = seedRate(oneMissing, MissingPlotPolicy.estimate)
  estimate = result.missingCells[0].estimate
  # X = (4(26,453) + 6(14,560) - 114,199) / ((4 - 1)(6 - 1)) = 5,265 kg/ha.
  assert estimate == pytest.approx((4 * 26453 + 6 * 14560 - 114199) / 15, rel=1e-13)
  assert round(estimate) == 5265
  assert result.estimation.cycles == 1


def testTable73IsReproduced():
  result = seedRate(oneMissing, MissingPlotPolicy.estimate)
  rows = rowsOf(result)
  assert {source: row.degreesOfFreedom for source, row in rows.items()} == {
    "block": 3, "treatment": 5, "error": 14, "total": 22}
  # The error is at its minimum in the estimate, so rounding the estimate does not move it.
  assert rows["error"].sumOfSquares == pytest.approx(1540726, abs=0.5)
  assert rows["error"].meanSquare == pytest.approx(110052, abs=0.5)
  # The book's adjusted treatment SS is 1,140,501 - 546, both worked from the rounded estimate.
  assert rows["treatment"].sumOfSquares == pytest.approx(1139955, abs=1.0)
  assert rows["treatment"].meanSquare == pytest.approx(227991, abs=0.5)
  assert round(rows["treatment"].fStatistic, 2) == 2.07
  # Not significant: the tabular F at 5% is 2.96.
  assert rows["treatment"].pValue > 0.05
  assert rows["block"].fStatistic is None


def testTheBooksReplicationAndTotalFollowFromItsRoundedEstimate():
  """Table 7.3 prints 2,188,739 and 4,869,420: the completed table with 5,265 in it, as Table 7.2 has."""
  book = classicalTable({("R100", 2): 5265.0})
  assert book["block"].sumOfSquares == pytest.approx(2188739, abs=0.5)
  assert book["block"].meanSquare == pytest.approx(729580, abs=0.5)
  assert book["treatment"].sumOfSquares == pytest.approx(1140501, abs=1.0)
  assert book["total"].sumOfSquares == pytest.approx(4869966, abs=1.0)
  bias = (26453 - (6 - 1) * 5265) ** 2 / (6 * (6 - 1))
  assert round(bias) == 546
  assert book["treatment"].sumOfSquares - bias == pytest.approx(1139955, abs=1.0)
  assert book["total"].sumOfSquares - bias == pytest.approx(4869420, abs=1.0)
  # With the estimate unrounded, 5,264.87, the same arithmetic gives the figures OpenFurrow reports.
  rows = rowsOf(seedRate(oneMissing, MissingPlotPolicy.estimate))
  exact = classicalTable({("R100", 2): (4 * 26453 + 6 * 14560 - 114199) / 15})
  assert rows["block"].sumOfSquares == pytest.approx(exact["block"].sumOfSquares, rel=1e-12)
  assert rows["block"].sumOfSquares == pytest.approx(2188656.69, abs=0.01)
  assert rows["total"].sumOfSquares == pytest.approx(4869336.89, abs=0.01)


def testTheBiasCorrectionIsTheBooksFormula():
  """B = (B0 - (t - 1) X)^2 / (t (t - 1)), at the estimate as OpenFurrow holds it."""
  result = seedRate(oneMissing, MissingPlotPolicy.estimate)
  estimate = result.missingCells[0].estimate
  assert result.estimation.treatmentBias == pytest.approx((26453 - 5 * estimate) ** 2 / 30, rel=1e-9)
  completed = classicalTable({("R100", 2): estimate})
  assert rowsOf(result)["treatment"].sumOfSquares == pytest.approx(
    completed["treatment"].sumOfSquares - result.estimation.treatmentBias, rel=1e-12)


@pytest.mark.parametrize("policy", [MissingPlotPolicy.estimate, MissingPlotPolicy.leastSquares])
def testStandardErrorOfADifferenceAndItsLsdAreTheBooks(policy):
  result = seedRate(oneMissing, policy)
  short = rates.index("R100")
  # s_d = sqrt(110,052 (2/4 + 6 / ((4)(3)(5)))) = 257 kg/ha for a pair with the fourth treatment.
  for other in range(len(rates)):
    if other != short:
      assert differenceStandardError(result, short, other) == pytest.approx(
        math.sqrt(result.errorMeanSquare * (2 / 4 + 6 / (4 * 3 * 5))), rel=1e-12)
      assert round(differenceStandardError(result, short, other)) == 257
  # Any other pair is on the usual sqrt(2 s^2 / r).
  assert differenceStandardError(result, 0, 1) == pytest.approx(math.sqrt(2 * result.errorMeanSquare / 4), rel=1e-12)
  # LSD.05 = (2.145)(257) = 551 and LSD.01 = (2.977)(257) = 765 kg/ha.
  for level, printed in ((0.05, 551), (0.01, 765)):
    separation = separateMeans(result, significanceLevel=level, meanComparison=MeanComparison.lsd)
    withShort = [pair for pair in separation.comparisons if "R100" in (pair.firstTreatmentCode, pair.secondTreatmentCode)]
    assert len(withShort) == 5
    assert {round(pair.criticalDifference) for pair in withShort} == {printed}
  assert round(separateMeans(result, meanComparison=MeanComparison.lsd).criticalValue, 3) == 2.145


def testLeastSquaresGivesTheBooksTreatmentTest():
  rows = rowsOf(seedRate(oneMissing, MissingPlotPolicy.leastSquares))
  assert rows["treatment"].sumOfSquares == pytest.approx(1139955, abs=1.0)
  assert rows["error"].sumOfSquares == pytest.approx(1540726, abs=0.5)
  assert (rows["error"].degreesOfFreedom, rows["total"].degreesOfFreedom) == (14, 22)
  assert round(rows["treatment"].fStatistic, 2) == 2.07


# ---- section 7.1.2.6: two missing values, by iteration ---------------------------

def testTwoMissingValuesConvergeOnTheBooksEstimates():
  result = seedRate(twoMissing, MissingPlotPolicy.estimate)
  estimates = {(cell.treatmentCode, cell.block): cell.estimate for cell in result.missingCells}
  # The book stops after its second cycle at 5,244 and 5,422 kg/ha.
  assert round(estimates[("R100", 2)]) == 5244
  assert round(estimates[("R25", 1)]) == 5422
  assert result.estimation.cycles > 2
  # Each estimate satisfies the missing data formula with the other in place.
  cells = seedRateCells() | estimates
  for rate, block in twoMissing:
    blockTotal = sum(cells[(other, block)] for other in rates if other != rate)
    treatmentTotal = sum(cells[(rate, other)] for other in range(1, 5) if other != block)
    grandTotal = sum(cells.values()) - cells[(rate, block)]
    assert estimates[(rate, block)] == pytest.approx((4 * blockTotal + 6 * treatmentTotal - grandTotal) / 15, rel=1e-11)


def testTable710IsReproducedFromTheBooksEstimates():
  book = classicalTable({("R100", 2): 5244.0, ("R25", 1): 5422.0})
  assert book["block"].sumOfSquares == pytest.approx(2300267, abs=0.5)
  assert book["treatment"].sumOfSquares == pytest.approx(1252358, abs=0.5)
  assert book["error"].sumOfSquares == pytest.approx(1481374, abs=0.5)
  assert book["total"].sumOfSquares == pytest.approx(5033999, abs=0.5)
  # The book leaves the treatment line uncorrected: F = 250,472 / 113,952 = 2.20 on 5 and 13 df.
  assert round((book["treatment"].sumOfSquares / 5) / (book["error"].sumOfSquares / 13), 2) == 2.20


def testTwoMissingValuesAreCorrectedWhereTheBookIsNot():
  result = seedRate(twoMissing, MissingPlotPolicy.estimate)
  rows = rowsOf(result)
  assert (rows["error"].degreesOfFreedom, rows["total"].degreesOfFreedom) == (13, 21)
  assert rows["error"].sumOfSquares == pytest.approx(1481374, abs=0.5)
  assert rows["error"].meanSquare == pytest.approx(113952, abs=0.5)
  # The completed table's treatment SS, uncorrected, is the book's 1,252,358 but for its rounded estimates.
  uncorrected = rows["treatment"].sumOfSquares + result.estimation.treatmentBias
  assert uncorrected == pytest.approx(1252358, abs=100.0)
  assert result.estimation.treatmentBias == pytest.approx(55487.3, abs=0.05)
  assert round(rows["treatment"].fStatistic, 2) == 2.10
  cells = seedRateCells()
  assertBlockAnalysisMatchesStatsmodels(result, frameOf(rates, cells, twoMissing, None), rates, 4, twoMissing, cells)


def testTheExactStandardErrorReplacesTheBooksEffectiveReplication():
  """For two treatments short of a plot each, the book takes 2.5 effective replications apiece: 301.930."""
  result = seedRate(twoMissing, MissingPlotPolicy.estimate)
  approximate = math.sqrt(113952 * (1 / 2.5 + 1 / 2.5))
  assert approximate == pytest.approx(301.930, abs=0.0005)
  exact = differenceStandardError(result, rates.index("R25"), rates.index("R100"))
  # The least-squares value, which the statsmodels comparison above confirms pair by pair.
  assert exact == pytest.approx(285.297, abs=0.0005)
  assert exact < approximate


# ---- section 2.1.2.2: a completely randomized design with unequal replication -----------------

herbicides = [
  "PropanilBromoxynil21", "Propanil24DB28", "PropanilBromoxynil14", "PropanilIoxynil14", "PropanilCHCH21",
  "Phenyedipham14", "PropanilBromoxynil28", "Propanil24DIPE28", "PropanilIoxynil28", "Handweeded", "Control",
]


def herbicideYields():
  yields = {code: [] for code in herbicides}
  for row in readFixture("gomezHerbicide.csv"):
    yields[row["treatment"]].append(float(row["yield"]))
  return yields


def herbicideResult():
  """Table 2.3 as a CRD laid out with four plots of each treatment, the plots without a yield missing."""
  package = TrialPackage.model_validate({
    "schemaVersion": schemaVersion,
    "trial": {"trialCode": "GOMEZ-2.3", "title": "Postemergence herbicides in dryland rice", "crop": "Rice",
              "season": "1984", "site": "IRRI", "objective": "Gomez and Gomez Table 2.3"},
    "treatments": [{"treatmentCode": code, "name": code} for code in herbicides],
    "design": {"designType": "crd", "replications": 4, "randomizationMethod": "sha256FisherYates1",
               "randomizationSeed": 23},
    "ratings": [{"ratingCode": "Y", "name": "Grain yield", "dataType": "numeric", "unit": "kg/ha"}],
    "assessments": [{"assessmentCode": "Y", "ratingCode": "Y"}],
  })
  layout = generateLayout(package)
  yields = herbicideYields()
  observations = []
  for code in herbicides:
    plots = sorted(plot.plotNumber for plot in layout.plots if plot.treatmentCode == code)
    observations += [Observation(plotNumber=plot, assessmentCode="Y", value=value) for plot, value in zip(plots, yields[code])]
  return analyzeCrd("Y", package, layout, observations, MissingPlotPolicy.leastSquares)


def testTable23TotalsAreThoseOfTheFixture():
  yields = herbicideYields()
  assert [sum(yields[code]) for code in herbicides] == [
    14576, 9040, 11793, 11638, 7703, 7694, 9934, 6618, 8164, 11192, 4949]
  assert [len(yields[code]) for code in herbicides] == [4, 3, 4, 4, 3, 3, 4, 3, 4, 4, 4]
  assert sum(sum(values) for values in yields.values()) == 103301


def testTable24IsReproduced():
  result = herbicideResult()
  rows = rowsOf(result)
  assert {source: row.degreesOfFreedom for source, row in rows.items()} == {"treatment": 10, "error": 29, "total": 39}
  assert rows["total"].sumOfSquares == pytest.approx(20209724, abs=0.5)
  assert rows["treatment"].sumOfSquares == pytest.approx(15090304, abs=0.5)
  assert rows["treatment"].meanSquare == pytest.approx(1509030, abs=0.5)
  # The book takes the error as total less treatment as printed, 5,119,420; exactly it is 5,119,419.5.
  assert rows["error"].sumOfSquares == pytest.approx(5119420, abs=1.0)
  assert rows["error"].meanSquare == pytest.approx(176532, abs=0.5)
  assert round(rows["treatment"].fStatistic, 2) == 8.55
  assert rows["treatment"].pValue < 0.01
  assert len(result.missingCells) == 4
  assert {cell.treatmentCode for cell in result.missingCells} == {"Propanil24DB28", "PropanilCHCH21", "Phenyedipham14", "Propanil24DIPE28"}


def testTable23MeansAndTheCoefficientOfVariation():
  result = herbicideResult()
  printed = [3644, 3013, 2948, 2910, 2568, 2565, 2484, 2206, 2041, 2798, 1237]
  assert [mean.mean for mean in result.treatmentMeans] == pytest.approx(printed, abs=0.5)
  assert [mean.observationCount for mean in result.treatmentMeans] == [4, 3, 4, 4, 3, 3, 4, 3, 4, 4, 4]
  # The book's cv of 16.3% is on the mean of the 40 yields, 2,583; on the mean of the eleven
  # treatment means, which OpenFurrow reports and labels, it is 16.3% as well.
  assert round(100 * math.sqrt(result.errorMeanSquare) / (103301 / 40), 1) == 16.3
  assert round(result.coefficientOfVariation, 1) == 16.3
  assert result.grandMean == pytest.approx(sum(mean.mean for mean in result.treatmentMeans) / 11, rel=1e-12)
  assert result.grandMean != pytest.approx(103301 / 40, abs=0.1)


def testUnequallyReplicatedPairsHaveTheirOwnStandardError():
  result = herbicideResult()
  error = result.errorMeanSquare
  fourAndFour = differenceStandardError(result, herbicides.index("Handweeded"), herbicides.index("Control"))
  fourAndThree = differenceStandardError(result, herbicides.index("Control"), herbicides.index("Phenyedipham14"))
  threeAndThree = differenceStandardError(result, herbicides.index("Propanil24DB28"), herbicides.index("Phenyedipham14"))
  assert fourAndFour == pytest.approx(math.sqrt(error * (1 / 4 + 1 / 4)), rel=1e-12)
  assert fourAndThree == pytest.approx(math.sqrt(error * (1 / 4 + 1 / 3)), rel=1e-12)
  assert threeAndThree == pytest.approx(math.sqrt(error * (1 / 3 + 1 / 3)), rel=1e-12)
  separation = separateMeans(result)
  assert separation.criticalDifference is None and separation.treatmentSignificant is True
  assert len({round(pair.criticalDifference, 6) for pair in separation.comparisons}) == 3
  assert separation.groups[0].treatmentCode == "PropanilBromoxynil21" and separation.groups[-1].treatmentCode == "Control"
