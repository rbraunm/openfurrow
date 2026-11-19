# SPDX-License-Identifier: Apache-2.0
"""The split-plot design: its package rules, its layout, and its analysis (decision 0020).

The analysis is pinned against Gomez and Gomez (1984), Table 3.10, the ANOVA of the
nitrogen-by-variety rice trial in their Table 3.7 (fixture `gomezSplitPlot.csv`), and
cross-checked against statsmodels, which fits the same model as ordinary least squares
with the replication-by-nitrogen term standing for Error(a).
"""

import csv
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from openfurrow import schemaVersion
from openfurrow.analysis import AnalysisError, analyzeSplitPlot, separateFactorMeans
from openfurrow.design import generateLayout
from openfurrow.reports import buildReport
from openfurrow.schema import TrialLayout, TrialPackage
from openfurrow.schema.observation import Observation
from storeHelpers import standardStudy

fixturesDirectory = Path(__file__).parent / "fixtures"
nitrogenLevels = [f"N{index}" for index in range(6)]
varietyLevels = [f"V{index}" for index in range(1, 5)]


def gomezPackageDict():
  return {
    "schemaVersion": schemaVersion,
    "trial": {"trialCode": "GOMEZ-3.7", "title": "Rice nitrogen by variety", "crop": "Rice",
              "season": "1984", "site": "IRRI", "objective": "Gomez and Gomez Table 3.7"},
    "factors": [
      {"factorCode": "N", "name": "Nitrogen", "levels": [{"levelCode": code, "name": code} for code in nitrogenLevels]},
      {"factorCode": "V", "name": "Variety", "levels": [{"levelCode": code, "name": code} for code in varietyLevels]},
    ],
    "treatments": [
      {"treatmentCode": f"{n}{v}", "name": f"{n} {v}", "factorLevels": {"N": n, "V": v}}
      for n in nitrogenLevels for v in varietyLevels
    ],
    "design": {"designType": "splitPlot", "replications": 3, "mainPlotFactor": "N", "subPlotFactor": "V",
               "randomizationMethod": "sha256FisherYates1", "randomizationSeed": 37},
    "ratings": [{"ratingCode": "Y", "name": "Grain yield", "dataType": "numeric", "unit": "kg/ha"}],
    "assessments": [{"assessmentCode": "Y", "ratingCode": "Y"}],
  }


def gomezInputs():
  package = TrialPackage.model_validate(gomezPackageDict())
  layout = generateLayout(package)
  with (fixturesDirectory / "gomezSplitPlot.csv").open(encoding="utf-8") as handle:
    yields = {(row["nitrogen"] + row["variety"], int(row["replication"])): float(row["yield"])
              for row in csv.DictReader(handle)}
  observations = [
    Observation(plotNumber=plot.plotNumber, assessmentCode="Y", value=yields[(plot.treatmentCode, plot.block)])
    for plot in layout.plots
  ]
  return package, layout, observations


def rowsBySource(result):
  return {row.source: row for row in result.table}


# ---- the published table -----------------------------------------------------

def testSplitPlotMatchesGomezTable310():
  rows = rowsBySource(analyzeSplitPlot("Y", *gomezInputs()))
  # Sums of squares as printed, to the unit.
  printed = {"block": 1082577, "mainPlot": 30429200, "subPlot": 89888101,
             "interaction": 69343487, "subPlotError": 12584873, "total": 204747916}
  assert {source: round(rows[source].sumOfSquares) for source in printed} == printed
  # Error(a) is exactly 1,419,678.81. The book prints 1,419,678 because it subtracts its
  # already-rounded replication and nitrogen sums of squares; done that way, it agrees.
  mainPlotTerms = rows["block"].sumOfSquares + rows["mainPlot"].sumOfSquares + rows["mainPlotError"].sumOfSquares
  assert round(mainPlotTerms - printed["block"] - printed["mainPlot"]) == 1419678
  assert {source: row.degreesOfFreedom for source, row in rows.items()} == {
    "block": 2, "mainPlot": 5, "mainPlotError": 10, "subPlot": 3, "interaction": 15, "subPlotError": 36, "total": 71,
  }
  assert [round(rows[source].fStatistic, 2) for source in ("mainPlot", "subPlot", "interaction")] == [42.87, 85.71, 13.22]
  assert rows["block"].fStatistic is None


def testSplitPlotCoefficientsOfVariationMatchGomez():
  result = analyzeSplitPlot("Y", *gomezInputs())
  assert round(result.grandMean) == 5479
  assert (round(result.mainPlotCoefficientOfVariation, 1), round(result.subPlotCoefficientOfVariation, 1)) == (6.9, 10.8)


def testSplitPlotAgreesWithStatsmodels():
  pandas = pytest.importorskip("pandas")
  formula = pytest.importorskip("statsmodels.formula.api")
  anovaModule = pytest.importorskip("statsmodels.stats.anova")
  package, layout, observations = gomezInputs()
  treatments = {treatment.treatmentCode: treatment.factorLevels for treatment in package.treatments}
  blockOf = {plot.plotNumber: (plot.block, plot.treatmentCode) for plot in layout.plots}
  frame = pandas.DataFrame([
    {"rep": blockOf[o.plotNumber][0], "N": treatments[blockOf[o.plotNumber][1]]["N"],
     "V": treatments[blockOf[o.plotNumber][1]]["V"], "y": o.value}
    for o in observations
  ])
  fitted = formula.ols("y ~ C(rep) + C(N) + C(rep):C(N) + C(V) + C(N):C(V)", data=frame).fit()
  table = anovaModule.anova_lm(fitted, typ=1)
  expected = {
    "block": table.loc["C(rep)", "sum_sq"], "mainPlot": table.loc["C(N)", "sum_sq"],
    "mainPlotError": table.loc["C(rep):C(N)", "sum_sq"], "subPlot": table.loc["C(V)", "sum_sq"],
    "interaction": table.loc["C(N):C(V)", "sum_sq"], "subPlotError": table.loc["Residual", "sum_sq"],
  }
  rows = rowsBySource(analyzeSplitPlot("Y", package, layout, observations))
  for source, sumOfSquares in expected.items():
    assert rows[source].sumOfSquares == pytest.approx(sumOfSquares, rel=1e-9), source


def testEachFactorIsSeparatedOnItsOwnError():
  scipyStats = pytest.importorskip("scipy.stats")
  result = analyzeSplitPlot("Y", *gomezInputs())
  nitrogen = separateFactorMeans(result, "N")
  variety = separateFactorMeans(result, "V")
  # Nitrogen on Error(a): 10 df, 12 plots per level; variety on Error(b): 36 df, 18 plots per level.
  assert nitrogen.criticalDifference == pytest.approx(
    scipyStats.t.ppf(0.975, 10) * math.sqrt(2 * result.mainPlotErrorMeanSquare / 12), rel=1e-9)
  assert variety.criticalDifference == pytest.approx(
    scipyStats.t.ppf(0.975, 36) * math.sqrt(2 * result.subPlotErrorMeanSquare / 18), rel=1e-9)
  assert nitrogen.factorSignificant and variety.factorSignificant
  # The variety totals in the book: V1 117,964 down to V4 65,558, over 18 plots each.
  assert [group.levelCode for group in variety.groups][0] == "V1"
  assert variety.groups[0].mean == pytest.approx(117964 / 18)
  assert variety.groups[-1].levelCode == "V4" and variety.groups[-1].mean == pytest.approx(65558 / 18)


def testSeparatingAFactorTheTrialLacksRejected():
  with pytest.raises(AnalysisError, match="'X' is neither the main-plot factor 'N' nor the subplot factor 'V'"):
    separateFactorMeans(analyzeSplitPlot("Y", *gomezInputs()), "X")


def testSplitPlotReportShowsBothErrorStrata():
  report = buildReport(*gomezInputs())
  assert (
    "| Block | 2 | 1082576.6944 | 541288.3472 | - | - |\n"
    "| Nitrogen | 5 | 30429199.5694 | 6085839.9139 | 42.87 | < 0.0001 |\n"
    "| Main-plot error (a) | 10 | 1419678.8056 | 141967.8806 | - | - |\n"
    "| Variety | 3 | 89888101.1528 | 29962700.3843 | 85.71 | < 0.0001 |\n"
    "| Nitrogen \u00d7 Variety | 15 | 69343486.9306 | 4622899.1287 | 13.22 | < 0.0001 |\n"
    "| Subplot error (b) | 36 | 12584873.1667 | 349579.8102 | - | - |\n"
    "| Total | 71 | 204747916.3194 | - | - | - |\n"
  ) in report
  assert "- Coefficient of variation, main plots (a): 6.88%" in report
  assert "- Coefficient of variation, subplots (b): 10.79%" in report
  assert "### Means of Nitrogen" in report and "### Means of Variety" in report
  assert "| N | V1 | V2 | V3 | V4 |" in report


# ---- the package --------------------------------------------------------------

def rejected(packageDict):
  with pytest.raises(ValidationError) as excInfo:
    TrialPackage.model_validate(packageDict)
  return " | ".join(error["msg"] for error in excInfo.value.errors())


def testMissingCombinationRejected():
  data = gomezPackageDict()
  data["treatments"] = data["treatments"][:-1]
  assert "repeated [], absent [('N5', 'V4')]" in rejected(data)


def testRepeatedCombinationRejected():
  data = gomezPackageDict()
  data["treatments"][-1]["factorLevels"] = {"N": "N5", "V": "V3"}
  assert "repeated [('N5', 'V3')], absent [('N5', 'V4')]" in rejected(data)


def testUnknownLevelRejected():
  data = gomezPackageDict()
  data["treatments"][0]["factorLevels"]["N"] = "N9"
  assert "treatment 'N0V1': 'N9' is not a level of factor 'N'" in rejected(data)


def testSplitPlotMustNameBothFactors():
  data = gomezPackageDict()
  del data["design"]["subPlotFactor"]
  assert "a split-plot design names its mainPlotFactor and its subPlotFactor" in rejected(data)


def testFactorsOnAnRcbdNeedTheirCombinationsAsTreatments(validPackageDict):
  # Two factors on an RCBD are a factorial trial (decision 0025); its treatments must be the combinations.
  validPackageDict["factors"] = gomezPackageDict()["factors"]
  assert "treatment 'T1' must state its level of each of ['N', 'V']" in rejected(validPackageDict)


# ---- the layout ---------------------------------------------------------------

def testGeneratedLayoutKeepsEachMainPlotToOneLevel():
  package = TrialPackage.model_validate(gomezPackageDict())
  plots = generateLayout(package).plots
  levels = {treatment.treatmentCode: treatment.factorLevels for treatment in package.treatments}
  for block in (1, 2, 3):
    mainPlots = {}
    for plot in plots:
      if plot.block == block:
        mainPlots.setdefault(plot.mainPlot, []).append(plot)
    assert sorted(mainPlots) == [1, 2, 3, 4, 5, 6]
    for mainPlot, members in mainPlots.items():
      assert len({levels[p.treatmentCode]["N"] for p in members}) == 1
      assert sorted(levels[p.treatmentCode]["V"] for p in members) == varietyLevels
      assert sorted(p.positionInBlock for p in members) == list(range((mainPlot - 1) * 4 + 1, mainPlot * 4 + 1))


def testFirstBlockInTreatmentOrderAppliesToSplitPlots():
  data = gomezPackageDict()
  data["design"]["firstBlockInTreatmentOrder"] = True
  plots = sorted(generateLayout(TrialPackage.model_validate(data)).plots, key=lambda plot: plot.plotNumber)
  assert [plot.treatmentCode for plot in plots if plot.block == 1] == [f"{n}{v}" for n in nitrogenLevels for v in varietyLevels]


def testLayoutMixingMainPlotLevelsRejected():
  package = TrialPackage.model_validate(gomezPackageDict())
  plots = [plot.model_dump() for plot in generateLayout(package).plots]
  first, second = (plot for plot in plots if plot["block"] == 1 and plot["mainPlot"] in (1, 2) and plot["positionInBlock"] in (1, 5))
  first["treatmentCode"], second["treatmentCode"] = second["treatmentCode"], first["treatmentCode"]
  with pytest.raises(ValidationError, match="block 1, main plot 1 must hold the 4 subplots of one main-plot level"):
    TrialLayout.forPackage(package, plots, [])


def testRcbdAnalysisRefusesASplitPlot():
  from openfurrow.analysis import analyzeRcbd
  with pytest.raises(AnalysisError, match="analyzeRcbd requires an RCBD layout, got splitPlot"):
    analyzeRcbd("Y", *gomezInputs())


def testSplitPlotTrialServesItsPages(tmp_path, newStore):
  from openfurrow import ImportProfile, Workspace
  from openfurrow.service import createApp
  databasePath = newStore("trials")
  workspace = Workspace.create(databasePath)
  package, layout, observations = gomezInputs()
  workspace.addPackage(package, standardStudy(workspace))
  csvPath = tmp_path / "yields.csv"
  csvPath.write_text(
    "plotNumber,assessmentCode,value\n" + "".join(f"{o.plotNumber},Y,{o.value}\n" for o in observations),
    encoding="utf-8",
  )
  workspace.importObservations("GOMEZ-3.7", str(csvPath), ImportProfile())
  client = createApp(databasePath).test_client()
  for locale, fStatistic in (("en-US", "42.87"), ("es", "42,87"), ("ar", "42.87")):
    assert client.get(f"/trials/GOMEZ-3.7?locale={locale}").status_code == 200
    report = client.get(f"/trials/GOMEZ-3.7/report?locale={locale}")
    assert report.status_code == 200 and fStatistic in report.get_data(as_text=True)
  analysis = client.get("/api/trials/GOMEZ-3.7/analysis/Y").get_json()
  assert analysis["designType"] == "splitPlot"
  assert [round(row["fStatistic"], 2) for row in analysis["table"] if row["source"] == "interaction"] == [13.22]
  means = client.get("/api/trials/GOMEZ-3.7/means/Y")
  assert means.status_code == 400
  assert "its means are separated for each factor" in means.get_data(as_text=True)


def testComparisonsInsideTheInteractionMatchGomezSection5():
  """Gomez and Gomez section 5.1.1.4: two varieties at one nitrogen rate differ by sqrt(2 Eb / r)."""
  scipyStats = pytest.importorskip("scipy.stats")
  from openfurrow.analysis import splitPlotInteractionComparisons
  result = analyzeSplitPlot("Y", *gomezInputs())
  five, one = splitPlotInteractionComparisons(result, 0.05), splitPlotInteractionComparisons(result, 0.01)
  assert round(five.secondWithinFirst.standardError, 1) == 482.8
  # The book multiplies by its tabulated t (2.029 and 2.722 for 36 df) and prints 980 and 1,314;
  # the exact t values are 2.0281 and 2.7195.
  assert five.secondWithinFirst.criticalT == pytest.approx(scipyStats.t.ppf(0.975, 36), rel=1e-6)
  assert round(2.029 * five.secondWithinFirst.standardError) == 980
  assert round(2.722 * one.secondWithinFirst.standardError) == 1314
  # Two nitrogen rates within one variety: Table 5.5, type 4, with the weighted t of Table 5.6.
  errorA, errorB = result.mainPlotErrorMeanSquare, result.subPlotErrorMeanSquare
  assert five.firstWithinSecond.standardError == pytest.approx(math.sqrt(2 * (3 * errorB + errorA) / 12), rel=1e-12)
  weighted = (3 * errorB * scipyStats.t.ppf(0.975, 36) + errorA * scipyStats.t.ppf(0.975, 10)) / (3 * errorB + errorA)
  assert five.firstWithinSecond.criticalT == pytest.approx(weighted, rel=1e-6)
  assert five.interactionSignificant


def testWeightedTMatchesGomezWorkedExample():
  """Gomez and Gomez section 5.1.1.5 weights 2.086 and 2.228 by 2 x 411,646 and 1,492,262."""
  from openfurrow.analysis import weightedCriticalT
  assert round(weightedCriticalT([(2 * 411646, 2.086), (1492262, 2.228)]), 3) == 2.178
  assert round(weightedCriticalT([(2 * 411646, 2.845), (1492262, 3.169)]), 3) == 3.054


def testCombinationTableIsLetteredWithinRows():
  report = buildReport(*gomezInputs())
  # Peta and IR8 at 0 kg N differ by 228 kg/ha, under the LSD: the book calls them not different.
  assert "| N0 | 4252.667 a | 4306.000 a | 3183.333 b | 4481.333 a |" in report
  assert "Letters in a row compare the Variety levels at that Nitrogen level." in report
  assert "- LSD (alpha = 0.05) between two Variety levels at the same Nitrogen level: 979.074" in report