# SPDX-License-Identifier: Apache-2.0
"""Known-answer tests against two more published RCBD analyses.

Each trial's numbers are checked twice, as the test-data registry requires: against the
table printed with the data, to the precision it was printed at, and against statsmodels
at full precision. The wheat trial comes with the layout it was grown in, so it is
entered as a trial laid out elsewhere (decision 0015) rather than re-randomized.
"""

import csv
from pathlib import Path

import pandas
import pytest
import statsmodels.api as statsmodelsApi
import statsmodels.formula.api as statsmodelsFormula
from scipy import stats

from openfurrow import schemaVersion
from openfurrow.analysis import analyzeRcbd, separateMeans
from openfurrow.design import generateRcbdLayout
from openfurrow.schema import Observation, TrialDocument, TrialLayout, TrialPackage

fixturesDirectory = Path(__file__).parent / "fixtures"


def readFixture(name):
  with (fixturesDirectory / name).open(newline="", encoding="utf-8") as handle:
    return list(csv.DictReader(handle))


def sourceRow(result, source):
  return next(row for row in result.table if row.source == source)


def statsmodelsTable(rows, treatmentColumn, blockColumn):
  frame = pandas.DataFrame({
    "treatment": [row[treatmentColumn] for row in rows],
    "block": [row[blockColumn] for row in rows],
    "response": [float(row["yield"]) for row in rows],
  })
  model = statsmodelsFormula.ols("response ~ C(block) + C(treatment)", data=frame).fit()
  return statsmodelsApi.stats.anova_lm(model, typ=1)


def assertMatchesStatsmodels(result, table):
  for source, label in (("block", "C(block)"), ("treatment", "C(treatment)"), ("error", "Residual")):
    row = sourceRow(result, source)
    assert row.degreesOfFreedom == int(table.loc[label, "df"])
    assert row.sumOfSquares == pytest.approx(table.loc[label, "sum_sq"], rel=1e-10)
    assert row.meanSquare == pytest.approx(table.loc[label, "mean_sq"], rel=1e-10)
  for source, label in (("block", "C(block)"), ("treatment", "C(treatment)")):
    row = sourceRow(result, source)
    assert row.fStatistic == pytest.approx(table.loc[label, "F"], rel=1e-10)
    assert row.pValue == pytest.approx(table.loc[label, "PR(>F)"], rel=1e-8)


# ---- Clewer & Scarisbrick (2001), Example 10.1: four wheat varieties ---------

def clewerWheatTrial():
  """The trial as it stood in the field: plot numbers from row and column, no seed."""
  rows = readFixture("clewerWheat.csv")
  package = TrialPackage.model_validate({
    "schemaVersion": schemaVersion,
    "trial": {"trialCode": "CLEWER-WHEAT", "title": "Wheat varieties", "crop": "Wheat",
              "season": "2001", "site": "Example 10.1", "objective": "Compare three new varieties with a standard"},
    "treatments": [{"treatmentCode": code, "name": code} for code in ["V1", "V2", "V3", "V4"]],
    "design": {"designType": "rcbd", "replications": 3, "randomizationMethod": "imported"},
    "ratings": [
      {"ratingCode": "YIELD", "name": "Grain yield", "dataType": "numeric", "unit": "t/ha"}
    ],
    "assessments": [
      {"assessmentCode": "YIELD", "ratingCode": "YIELD"}
    ],
  })
  layout = [
    {"plotNumber": int(row["row"]) * 100 + int(row["col"]), "block": int(row["block"][1:]),
     "positionInBlock": int(row["col"]), "treatmentCode": row["gen"]}
    for row in rows
  ]
  observations = [
    {"plotNumber": int(row["row"]) * 100 + int(row["col"]), "assessmentCode": "YIELD", "value": float(row["yield"])}
    for row in rows
  ]
  document = TrialDocument.model_validate({"package": package.model_dump(mode="json"), "layout": layout, "observations": observations})
  return rows, document


def clewerWheatResult():
  rows, document = clewerWheatTrial()
  layout = TrialLayout.forPackage(document.package, document.layout)
  return rows, analyzeRcbd("YIELD", document.package, layout, document.observations)


def testClewerWheatMatchesThePrintedTable():
  _, result = clewerWheatResult()
  block, variety, error, total = (sourceRow(result, source) for source in ("block", "treatment", "error", "total"))
  assert (block.degreesOfFreedom, variety.degreesOfFreedom, error.degreesOfFreedom, total.degreesOfFreedom) == (2, 3, 6, 11)
  assert block.sumOfSquares == pytest.approx(9.78, abs=0.005)
  assert variety.sumOfSquares == pytest.approx(6.63, abs=0.005)
  assert error.sumOfSquares == pytest.approx(2.40, abs=0.005)
  assert total.sumOfSquares == pytest.approx(18.81, abs=0.005)
  assert block.meanSquare == pytest.approx(4.89, abs=0.005)
  assert variety.meanSquare == pytest.approx(2.21, abs=0.005)
  assert error.meanSquare == pytest.approx(0.40, abs=0.005)
  # The book prints 12.22 and 5.52; the exact ratios are 12.225 and 5.525.
  assert block.fStatistic == pytest.approx(12.22, abs=0.0055)
  assert variety.fStatistic == pytest.approx(5.52, abs=0.0055)
  assert result.grandMean == pytest.approx(7.25, abs=1e-9)
  means = {mean.treatmentCode: mean.mean for mean in result.treatmentMeans}
  assert means == pytest.approx({"V1": 6.50, "V2": 7.60, "V3": 6.60, "V4": 8.30}, abs=1e-9)


def testClewerWheatMatchesStatsmodels():
  rows, result = clewerWheatResult()
  assertMatchesStatsmodels(result, statsmodelsTable(rows, "gen", "block"))


def testClewerWheatSeparatesIntoOverlappingGroups():
  """The variety effect is significant, and the LSD leaves one variety in both groups."""
  _, result = clewerWheatResult()
  separation = separateMeans(result, significanceLevel=0.05, protected=True)
  expectedLsd = stats.t.ppf(0.975, 6) * (2 * 0.40 / 3) ** 0.5
  assert separation.treatmentSignificant is True
  assert separation.leastSignificantDifference == pytest.approx(expectedLsd, rel=1e-9)
  # 8.30 and 7.60 are within the LSD of 1.264; so are 7.60, 6.60 and 6.50; 8.30 and 6.60 are not.
  assert [(group.treatmentCode, group.group) for group in separation.groups] == [
    ("V4", "a"), ("V2", "ab"), ("V3", "b"), ("V1", "b"),
  ]


# ---- Gomez & Gomez (1984), Tables 2.5 and 2.6: six rice seeding rates --------

def gomezSeedRateResult():
  rows = readFixture("gomezSeedRate.csv")
  rates = ["25", "50", "75", "100", "125", "150"]
  package = TrialPackage.model_validate({
    "schemaVersion": schemaVersion,
    "trial": {"trialCode": "GOMEZ-SEEDRATE", "title": "Rice seeding rates", "crop": "Rice",
              "season": "1984", "site": "Table 2.5", "objective": "Compare six seeding rates"},
    "treatments": [{"treatmentCode": rate, "name": f"{rate} kg seed/ha"} for rate in rates],
    "design": {"designType": "rcbd", "replications": 4, "randomizationMethod": "sha256FisherYates1", "randomizationSeed": 1984},
    "ratings": [
      {"ratingCode": "YIELD", "name": "Grain yield", "dataType": "numeric", "unit": "kg/ha"}
    ],
    "assessments": [
      {"assessmentCode": "YIELD", "ratingCode": "YIELD"}
    ],
  })
  layout = generateRcbdLayout(package)
  cells = {(row["rate"], int(row["rep"][1:])): float(row["yield"]) for row in rows}
  observations = [
    Observation(plotNumber=plot.plotNumber, assessmentCode="YIELD", value=cells[(plot.treatmentCode, plot.block)])
    for plot in layout.plots
  ]
  return rows, analyzeRcbd("YIELD", package, layout, observations)


def testGomezSeedRateMatchesThePrintedTable():
  _, result = gomezSeedRateResult()
  treatment, error = sourceRow(result, "treatment"), sourceRow(result, "error")
  assert (treatment.degreesOfFreedom, error.degreesOfFreedom) == (5, 15)
  assert treatment.sumOfSquares == pytest.approx(1198331, abs=0.5)
  assert error.sumOfSquares == pytest.approx(1658376, abs=0.5)
  assert error.meanSquare == pytest.approx(110558, abs=0.5)
  assert treatment.fStatistic == pytest.approx(2.17, abs=0.005)
  assert result.coefficientOfVariation == pytest.approx(6.7, abs=0.05)


def testGomezSeedRateMatchesStatsmodels():
  rows, result = gomezSeedRateResult()
  assertMatchesStatsmodels(result, statsmodelsTable(rows, "rate", "rep"))


def testGomezSeedRateIsNotSeparatedUnderProtection():
  """The treatment effect is not significant, so the protected LSD separates nothing."""
  _, result = gomezSeedRateResult()
  separation = separateMeans(result, significanceLevel=0.05, protected=True)
  assert separation.treatmentSignificant is False
  assert {group.group for group in separation.groups} == {"a"}
