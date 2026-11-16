# SPDX-License-Identifier: Apache-2.0
"""Untreated checks beside the plots, in all three arrangements (decision 0022).

Percent control is checked against values worked by hand, the two ANOVAs against
statsmodels, and the paired comparison against scipy's paired t-test.
"""

import csv
import json

import pytest
from pydantic import ValidationError

from openfurrow import ExchangeError, Workspace, schemaVersion
from openfurrow.analysis import (
  AnalysisError,
  analyzeEfficacy,
  analyzeHalves,
  compareWithChecks,
  plotEfficacies,
)
from openfurrow.design import generateLayout
from openfurrow.interop.fieldbook import writeFieldImport
from openfurrow.reports import buildReport
from openfurrow.schema import TrialLayout, TrialPackage
from openfurrow.schema.observation import Observation

# Pest counts after application on the treated plots and on their checks, by treatment and
# block; before application for Henderson-Tilton. Chosen so no two treatments look alike.
treatedAfter = {"A": [4, 6, 3, 5], "B": [10, 12, 9, 14], "UTC": [21, 18, 25, 22]}
checkAfter = {"A": [20, 24, 18, 22], "B": [19, 25, 21, 23], "UTC": [22, 20, 24, 21]}
treatedBefore = {"A": [18, 20, 17, 19], "B": [21, 19, 20, 22], "UTC": [20, 19, 23, 21]}
checkBefore = {"A": [19, 21, 18, 20], "B": [20, 22, 19, 21], "UTC": [21, 20, 22, 20]}


def packageDict(arrangement, efficacy=None):
  return {
    "schemaVersion": schemaVersion,
    "trial": {"trialCode": "CHK-1", "title": "Checks", "crop": "Wheat", "season": "2026",
              "site": "Field 2", "objective": "Aphid control"},
    "treatments": [{"treatmentCode": code, "name": code} for code in ("A", "B", "UTC")],
    "design": {"designType": "rcbd", "replications": 4, "randomizationMethod": "sha256FisherYates1",
               "randomizationSeed": 11, "checkArrangement": arrangement},
    "ratings": [{"ratingCode": "APH", "name": "Aphids per tiller", "dataType": "numeric", "minValue": 0}],
    "assessments": [
      {"assessmentCode": "PRE", "ratingCode": "APH"},
      {"assessmentCode": "D7", "ratingCode": "APH", **({"efficacy": efficacy} if efficacy else {})},
    ],
  }


def trial(arrangement, efficacy=None, change=None):
  package = TrialPackage.model_validate(packageDict(arrangement, efficacy))
  layout = generateLayout(package)
  observations = []
  for plot in layout.plots:
    check = layout.checkFor(plot.plotNumber)
    index = plot.block - 1
    for code, treated, untreated in (("PRE", treatedBefore, checkBefore), ("D7", treatedAfter, checkAfter)):
      observations.append(Observation(plotNumber=plot.plotNumber, assessmentCode=code,
                                      value=float(treated[plot.treatmentCode][index])))
      observations.append(Observation(plotNumber=check.plotNumber, assessmentCode=code,
                                      value=float(untreated[plot.treatmentCode][index])))
  if change:
    observations = change(observations, layout)
  return package, layout, observations


# ---- percent control ---------------------------------------------------------

def testAbbottIsWorkedPlotByPlot():
  package, layout, observations = trial("paired", {"method": "abbott"})
  byPlot = {result.plotNumber: result for result in plotEfficacies("D7", package, layout, observations)}
  plot = next(plot for plot in layout.plots if plot.treatmentCode == "A" and plot.block == 1)
  # 100 (1 - 4 / 20)
  assert byPlot[plot.plotNumber].efficacy == pytest.approx(80.0)
  plot = next(plot for plot in layout.plots if plot.treatmentCode == "B" and plot.block == 4)
  # 100 (1 - 14 / 23)
  assert byPlot[plot.plotNumber].efficacy == pytest.approx(100 * (1 - 14 / 23))


def testHendersonTiltonUsesTheCountsBeforeApplication():
  package, layout, observations = trial("paired", {"method": "hendersonTilton", "baselineAssessmentCode": "PRE"})
  byPlot = {result.plotNumber: result for result in plotEfficacies("D7", package, layout, observations)}
  plot = next(plot for plot in layout.plots if plot.treatmentCode == "A" and plot.block == 2)
  # 100 (1 - (Ta Cb) / (Tb Ca)) = 100 (1 - (6 x 21) / (20 x 24)) = 73.75
  assert byPlot[plot.plotNumber].efficacy == pytest.approx(73.75)


def testPercentControlIsAnalysedAsAnRcbd():
  pandas = pytest.importorskip("pandas")
  formula = pytest.importorskip("statsmodels.formula.api")
  anova = pytest.importorskip("statsmodels.stats.anova")
  package, layout, observations = trial("imbricated", {"method": "abbott"})
  result = analyzeEfficacy("D7", package, layout, observations)
  frame = pandas.DataFrame([
    {"block": r.block, "treatment": r.treatmentCode, "y": r.efficacy}
    for r in plotEfficacies("D7", package, layout, observations)
  ])
  table = anova.anova_lm(formula.ols("y ~ C(block) + C(treatment)", data=frame).fit(), typ=1)
  rows = {row.source: row for row in result.table}
  assert rows["treatment"].sumOfSquares == pytest.approx(table.loc["C(treatment)", "sum_sq"], rel=1e-9)
  assert rows["error"].sumOfSquares == pytest.approx(table.loc["Residual", "sum_sq"], rel=1e-9)


def testCheckWithNothingToCompareStopsAndNamesThePlot():
  def zeroCheck(observations, layout):
    target = layout.checkFor(layout.plots[0].plotNumber).plotNumber
    return [Observation(plotNumber=o.plotNumber, assessmentCode=o.assessmentCode,
                        value=0.0 if (o.plotNumber, o.assessmentCode) == (target, "D7") else o.value)
            for o in observations]
  package, layout, observations = trial("paired", {"method": "abbott"}, zeroCheck)
  with pytest.raises(AnalysisError, match=f"plot {layout.plots[0].plotNumber} has no percent control by abbott"):
    plotEfficacies("D7", package, layout, observations)


def testMissingCheckValueIsNamed():
  def dropCheck(observations, layout):
    target = layout.checkPlots[0].plotNumber
    return [o for o in observations if (o.plotNumber, o.assessmentCode) != (target, "D7")]
  package, layout, observations = trial("paired", {"method": "abbott"}, dropCheck)
  with pytest.raises(AnalysisError, match=rf"Missing: \[{layout.checkPlots[0].plotNumber}\]"):
    plotEfficacies("D7", package, layout, observations)


# ---- the halves, and the pairs ------------------------------------------------

def testHalvesAreAnalysedInTwoStrata():
  pandas = pytest.importorskip("pandas")
  formula = pytest.importorskip("statsmodels.formula.api")
  anova = pytest.importorskip("statsmodels.stats.anova")
  package, layout, observations = trial("adjacent")
  result = analyzeHalves("D7", package, layout, observations)
  frame = pandas.DataFrame(
    [{"block": b + 1, "treatment": t, "half": "treated", "y": treatedAfter[t][b]} for t in treatedAfter for b in range(4)]
    + [{"block": b + 1, "treatment": t, "half": "untreated", "y": checkAfter[t][b]} for t in checkAfter for b in range(4)]
  )
  table = anova.anova_lm(formula.ols(
    "y ~ C(block) + C(treatment) + C(block):C(treatment) + C(half) + C(treatment):C(half)", data=frame).fit(), typ=1)
  rows = {row.source: row for row in result.table}
  for source, term in (("mainPlot", "C(treatment)"), ("mainPlotError", "C(block):C(treatment)"),
                       ("subPlot", "C(half)"), ("interaction", "C(treatment):C(half)"), ("subPlotError", "Residual")):
    assert rows[source].sumOfSquares == pytest.approx(table.loc[term, "sum_sq"], rel=1e-9), source


def testHalvesOnlyForAdjacentChecks():
  with pytest.raises(AnalysisError, match="only for adjacent checks"):
    analyzeHalves("D7", *trial("paired"))


def testEachTreatmentAgainstItsChecksIsAPairedTTest():
  scipyStats = pytest.importorskip("scipy.stats")
  comparisons = {c.treatmentCode: c for c in compareWithChecks("D7", *trial("paired"))}
  for code in ("A", "B", "UTC"):
    expected = scipyStats.ttest_rel(treatedAfter[code], checkAfter[code])
    assert comparisons[code].tStatistic == pytest.approx(expected.statistic, rel=1e-9)
    assert comparisons[code].pValue == pytest.approx(expected.pvalue, rel=1e-7)
    assert comparisons[code].degreesOfFreedom == 3


# ---- the record ---------------------------------------------------------------

def testGeneratedChecksSitBesideTheirPlots():
  package, layout, _ = trial("adjacent")
  assert sorted(check.plotNumber for check in layout.checkPlots) == sorted(10000 + p.plotNumber for p in layout.plots)
  assert all(check.pairedPlots == [check.plotNumber - 10000] for check in layout.checkPlots)


def documentWith(package, plots, checks):
  return {"package": package, "layout": plots, "observations": [], "checkPlots": checks}


def importedPlots():
  return [
    {"plotNumber": 1, "block": 1, "positionInBlock": 1, "treatmentCode": "A"},
    {"plotNumber": 2, "block": 1, "positionInBlock": 2, "treatmentCode": "B"},
    {"plotNumber": 3, "block": 1, "positionInBlock": 3, "treatmentCode": "UTC"},
    {"plotNumber": 4, "block": 2, "positionInBlock": 1, "treatmentCode": "B"},
    {"plotNumber": 5, "block": 2, "positionInBlock": 2, "treatmentCode": "UTC"},
    {"plotNumber": 6, "block": 2, "positionInBlock": 3, "treatmentCode": "A"},
  ]


def importedPackage(arrangement):
  data = packageDict(arrangement)
  data["design"] = {"designType": "rcbd", "replications": 2, "randomizationMethod": "imported",
                    "checkArrangement": arrangement}
  return data


def testOneStripMayServeSeveralPlots(tmp_path):
  """A strip between plots is shared; it comes through the store and the exchange unchanged."""
  checks = [{"plotNumber": 91, "block": 1, "pairedPlots": [1, 2, 3]},
            {"plotNumber": 92, "block": 2, "pairedPlots": [4, 5]},
            {"plotNumber": 93, "block": 2, "pairedPlots": [6]}]
  path = tmp_path / "doc.json"
  path.write_text(json.dumps(documentWith(importedPackage("imbricated"), importedPlots(), checks)), encoding="utf-8")
  first = Workspace.create(str(tmp_path / "a.db"))
  first.importDocument(str(path))
  assert [check.model_dump() for check in first.layoutFor("CHK-1").checkPlots] == checks
  exported = str(tmp_path / "out.json")
  first.exportDocument("CHK-1", exported)
  second = Workspace.create(str(tmp_path / "b.db"))
  second.importDocument(exported)
  assert second.contentHashFor("CHK-1") == first.contentHashFor("CHK-1")


@pytest.mark.parametrize("arrangement, checks, message", [
  ("paired", [{"plotNumber": 91, "block": 1, "pairedPlots": [1, 2]}], "a paired check belongs to exactly one plot"),
  ("imbricated", [{"plotNumber": 91, "block": 1, "pairedPlots": [1, 2, 3]}],
   r"without one \[4, 5, 6\], with several \[\]"),
  ("imbricated", [{"plotNumber": 91, "block": 2, "pairedPlots": [1, 2, 3]},
                  {"plotNumber": 92, "block": 2, "pairedPlots": [4, 5, 6]}],
   "check plot 91 is in block 2, its plot 1 is not"),
  ("imbricated", [{"plotNumber": 3, "block": 1, "pairedPlots": [1, 2, 3]},
                  {"plotNumber": 92, "block": 2, "pairedPlots": [4, 5, 6]}],
   r"used more than once or by treated plots: \[3\]"),
  ("none", [{"plotNumber": 91, "block": 1, "pairedPlots": [1]}], "the design has no checkArrangement"),
  ("adjacent", [], "needs its check plots"),
])
def testCheckPlotsThatDoNotFitAreRefused(tmp_path, arrangement, checks, message):
  path = tmp_path / "doc.json"
  path.write_text(json.dumps(documentWith(importedPackage(arrangement), importedPlots(), checks)), encoding="utf-8")
  with pytest.raises(ExchangeError, match=message):
    Workspace.create(str(tmp_path / "a.db")).importDocument(str(path))


def testPercentControlNeedsChecks():
  with pytest.raises(ValidationError, match="percent control needs untreated checks"):
    TrialPackage.model_validate(packageDict("none", {"method": "abbott"}))


def testHendersonTiltonNeedsItsBaseline():
  with pytest.raises(ValidationError, match="Henderson-Tilton needs the baselineAssessmentCode"):
    TrialPackage.model_validate(packageDict("paired", {"method": "hendersonTilton"}))
  with pytest.raises(ValidationError, match="baseline assessment 'POST' is not declared"):
    TrialPackage.model_validate(packageDict("paired", {"method": "hendersonTilton", "baselineAssessmentCode": "POST"}))


def testChecksAreInTheFieldBookFile(tmp_path):
  package, layout, _ = trial("paired")
  path = tmp_path / "field.csv"
  writeFieldImport(package, layout, path)
  with path.open(encoding="utf-8") as handle:
    rows = list(csv.reader(handle))[1:]
  plot = layout.plots[0]
  checkRow = next(row for row in rows if row[0] == str(10000 + plot.plotNumber))
  assert checkRow == [str(10000 + plot.plotNumber), str(plot.block), str(plot.positionInBlock),
                      f"untreated check of {plot.plotNumber}"]
  assert len(rows) == 2 * len(layout.plots)


# ---- the report ---------------------------------------------------------------

@pytest.mark.parametrize("arrangement, present, absent", [
  ("imbricated", "Untreated strips between the plots", "#### Treated and untreated halves"),
  ("adjacent", "#### Treated and untreated halves", "#### Each treatment against its checks"),
  ("paired", "#### Each treatment against its checks", "#### Treated and untreated halves"),
])
def testReportShowsWhatTheArrangementCallsFor(arrangement, present, absent):
  report = buildReport(*trial(arrangement, {"method": "abbott"}))
  assert "### Untreated checks" in report and present in report and absent not in report
  assert "#### Percent control (Abbott)" in report
  assert "| Treatment | Percent control | Group |" in report


def testReportOfATrialWithoutChecksSaysNothingOfThem(validPackageDict):
  package = TrialPackage.model_validate(validPackageDict)
  assert "Untreated checks" not in buildReport(package, generateLayout(package), [])
