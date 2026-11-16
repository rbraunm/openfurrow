# SPDX-License-Identifier: Apache-2.0
"""The completely randomized design (decision 0027).

Pinned against Gomez and Gomez (1984), Tables 2.1 and 2.2: rice yield under seven
insecticide treatments in four replications (fixture `gomezInsecticide.csv`), and checked
against statsmodels.
"""

import csv
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from openfurrow import ExchangeError, TrialPackage, Workspace, schemaVersion
from openfurrow.analysis import AnalysisError, analyzeCrd, analyzeRcbd, separateMeans
from openfurrow.design import generateLayout
from openfurrow.reports import buildReport
from openfurrow.schema.observation import Observation
from openfurrow.service import createApp

fixtures = Path(__file__).parent / "fixtures"
treatments = ["DolMix1", "DolMix2", "DDT", "Azodrin", "DimecronBoom", "DimecronKnap", "Control"]


def packageDict(**design):
  return {
    "schemaVersion": schemaVersion,
    "trial": {"trialCode": "GOMEZ-2.1", "title": "Insecticides on rice", "crop": "Rice", "season": "1984",
              "site": "IRRI", "objective": "Gomez and Gomez Table 2.1"},
    "treatments": [{"treatmentCode": code, "name": code} for code in treatments],
    "design": {"designType": "crd", "replications": 4, "randomizationMethod": "sha256FisherYates1",
               "randomizationSeed": 21} | design,
    "ratings": [{"ratingCode": "Y", "name": "Grain yield", "dataType": "numeric", "unit": "kg/ha"}],
    "assessments": [{"assessmentCode": "Y", "ratingCode": "Y"}],
  }


def gomezInputs():
  package = TrialPackage.model_validate(packageDict())
  layout = generateLayout(package)
  with (fixtures / "gomezInsecticide.csv").open(encoding="utf-8") as handle:
    byTreatment: dict[str, list[float]] = {}
    for row in csv.DictReader(handle):
      byTreatment.setdefault(row["treatment"], []).append(float(row["yield"]))
  observations = []
  for plot in sorted(layout.plots, key=lambda plot: plot.plotNumber):
    observations.append(Observation(plotNumber=plot.plotNumber, assessmentCode="Y",
                                    value=byTreatment[plot.treatmentCode].pop(0)))
  return package, layout, observations


def testMatchesGomezTable22():
  package, layout, observations = gomezInputs()
  result = analyzeCrd("Y", package, layout, observations)
  rows = {row.source: row for row in result.table}
  # The book subtracts its correction factor rounded to 116,484,004 (exactly 116,484,003.57)
  # and takes the error as total less treatment, both as it printed them.
  shortfall = 116484004 - sum(o.value for o in observations) ** 2 / 28
  treatment = round(rows["treatment"].sumOfSquares - shortfall)
  total = round(rows["total"].sumOfSquares - shortfall)
  assert (treatment, total, total - treatment) == (5587174, 7577412, 1990238)
  assert {source: row.degreesOfFreedom for source, row in rows.items()} == {"treatment": 6, "error": 21, "total": 27}
  assert round(rows["treatment"].fStatistic, 2) == 9.83
  assert round(result.coefficientOfVariation, 1) == 15.1
  assert round(result.grandMean) == 2040


def testAgreesWithStatsmodels():
  pandas = pytest.importorskip("pandas")
  formula = pytest.importorskip("statsmodels.formula.api")
  anova = pytest.importorskip("statsmodels.stats.anova")
  package, layout, observations = gomezInputs()
  treatmentOf = {plot.plotNumber: plot.treatmentCode for plot in layout.plots}
  frame = pandas.DataFrame([{"t": treatmentOf[o.plotNumber], "y": o.value} for o in observations])
  table = anova.anova_lm(formula.ols("y ~ C(t)", data=frame).fit(), typ=1)
  rows = {row.source: row for row in analyzeCrd("Y", package, layout, observations).table}
  assert rows["treatment"].sumOfSquares == pytest.approx(table.loc["C(t)", "sum_sq"], rel=1e-12)
  assert rows["treatment"].pValue == pytest.approx(table.loc["C(t)", "PR(>F)"], rel=1e-6)


def testMeansAreSeparatedOnTheError():
  scipyStats = pytest.importorskip("scipy.stats")
  result = analyzeCrd("Y", *gomezInputs())
  separation = separateMeans(result)
  assert separation.leastSignificantDifference == pytest.approx(
    scipyStats.t.ppf(0.975, 21) * (2 * result.errorMeanSquare / 4) ** 0.5, rel=1e-9)
  assert separation.groups[0].treatmentCode == "DolMix2" and separation.groups[-1].treatmentCode == "Control"


def testLayoutShufflesEveryPlotInOneField():
  package = TrialPackage.model_validate(packageDict())
  plots = generateLayout(package).plots
  assert sorted(plot.plotNumber for plot in plots) == list(range(101, 129))
  assert {plot.block for plot in plots} == {1}
  assert sorted(plot.treatmentCode for plot in plots) == sorted(treatments * 4)
  # Shuffled, not laid out in treatment order.
  assert [plot.treatmentCode for plot in sorted(plots, key=lambda p: p.plotNumber)][:4] != ["DolMix1"] * 4


def testLayoutWithATreatmentOnTooFewPlotsIsRefused(tmp_path):
  package = TrialPackage.model_validate(packageDict(randomizationMethod="imported", randomizationSeed=None))
  plots = [{"plotNumber": 100 + index, "block": 1, "positionInBlock": index, "treatmentCode": code}
           for index, code in enumerate(treatments * 3 + ["Control"] * 7, start=1)]
  path = tmp_path / "doc.json"
  path.write_text(json.dumps({"package": package.model_dump(mode="json"), "layout": plots, "observations": []}),
                  encoding="utf-8")
  with pytest.raises(ExchangeError, match="are not on exactly 4 plots"):
    Workspace.create(str(tmp_path / "t.db")).importDocument(str(path))


@pytest.mark.parametrize("design, message", [
  ({"firstBlockInTreatmentOrder": True}, "no first block to keep in order"),
  ({"checkArrangement": "paired"}, "not to a completely randomized design yet"),
  ({"randomizationMethod": "sha256SpatialBalance1"}, "a completely randomized design has none"),
])
def testBlockOptionsAreRefused(design, message):
  with pytest.raises(ValidationError, match=message):
    TrialPackage.model_validate(packageDict(**design))


def testRcbdAnalysisRefusesACrd():
  with pytest.raises(AnalysisError, match="analyzeRcbd requires an RCBD layout, got crd"):
    analyzeRcbd("Y", *gomezInputs())


def testReportAndPages(tmp_path):
  report = buildReport(*gomezInputs())
  assert "- Design: Completely randomized design" in report
  assert "| Treatment | 6 | 5587174.9286 | 931195.8214 | 9.83 | < 0.0001 |" in report
  assert "| Error | 21 | 1990237.5000 | 94773.2143 | - | - |" in report
  assert "Assumption checks are not computed for completely randomized designs yet." in report
  assert "One-way ANOVA (completely randomized)" in report
  databasePath = str(tmp_path / "trials.db")
  workspace = Workspace.create(databasePath)
  package, _, observations = gomezInputs()
  workspace.addPackage(package)
  body = createApp(databasePath).test_client().get("/trials/GOMEZ-2.1").get_data(as_text=True)
  assert "All plots" in body and "Block 1" not in body


def testFormSetsUpACrd(tmp_path):
  databasePath = str(tmp_path / "trials.db")
  Workspace.create(databasePath)
  client = createApp(databasePath).test_client()
  response = client.post("/trials/form", data={
    "trialCode": "CRD-1", "title": "Pots", "crop": "Wheat", "season": "2026", "site": "Glasshouse 2",
    "objective": "Compare", "treatmentsRows": "2", "assessmentsRows": "1", "replications": "5",
    "designType": "crd", "layoutSource": "generate", "seed": "4", "create": "yes",
    "treatments-0-code": "A", "treatments-0-name": "A", "treatments-1-code": "B", "treatments-1-name": "B",
    "assessments-0-code": "H", "assessments-0-name": "Height", "assessments-0-dataType": "numeric",
  })
  assert response.status_code == 302
  assert Workspace.open(databasePath).loadPackage("CRD-1").design.designType.value == "crd"
