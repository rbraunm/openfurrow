# SPDX-License-Identifier: Apache-2.0
"""Subsamples within a plot (decision 0033).

Values are kept as entered and the analysis runs on plot values derived by the
assessment's rule. With every subsample present, the plot-mean ANOVA's treatment F equals
the treatment F of the subsample-level model tested against the experimental error
(Gomez and Gomez 1984, section 6.1), checked here with statsmodels.
"""

import base64
import csv

import numpy
import pytest
from pydantic import ValidationError

from openfurrow import TrialPackage, Workspace, schemaVersion
from openfurrow.analysis import AnalysisError, analyzeRcbd
from openfurrow.analysis.subsamples import missingSubsamples, plotValues
from openfurrow.design import generateLayout
from openfurrow.reports import buildReport
from openfurrow.schema import TrialDocument
from openfurrow.schema.observation import Observation
from storeHelpers import standardStudy


def packageDict(rule="mean", count=3):
  return {
    "schemaVersion": schemaVersion,
    "trial": {"trialCode": "SUB-1", "title": "Leaves", "crop": "Wheat", "season": "2026", "site": "Field 2",
              "objective": "Severity on ten leaves"},
    "treatments": [{"treatmentCode": code, "name": code} for code in ("A", "B", "C", "D")],
    "design": {"designType": "rcbd", "replications": 4, "randomizationMethod": "sha256FisherYates1", "randomizationSeed": 5},
    "ratings": [{"ratingCode": "SEV", "name": "Severity", "dataType": "numeric", "unit": "%", "minValue": 0, "maxValue": 100}],
    "assessments": [{"assessmentCode": "SEV", "ratingCode": "SEV", "subsamples": {"count": count, "rule": rule}}],
  }


def trial(rule="mean", drop=()):
  package = TrialPackage.model_validate(packageDict(rule))
  layout = generateLayout(package)
  generator = numpy.random.default_rng(11)
  effect = {"A": 30.0, "B": 24.0, "C": 18.0, "D": 12.0}
  observations = []
  for plot in layout.plots:
    plotEffect = generator.normal(0, 2)
    for subsample in (1, 2, 3):
      value = None if (plot.plotNumber, subsample) in drop else round(
        effect[plot.treatmentCode] + 2 * plot.block + plotEffect + generator.normal(0, 3), 1)
      observations.append(Observation(plotNumber=plot.plotNumber, assessmentCode="SEV", value=value, subsample=subsample))
  return package, layout, observations


def testPlotMeansGiveTheExperimentalErrorTest():
  pandas = pytest.importorskip("pandas")
  formula = pytest.importorskip("statsmodels.formula.api")
  anova = pytest.importorskip("statsmodels.stats.anova")
  package, layout, observations = trial()
  result = analyzeRcbd("SEV", package, layout, observations)
  where = {p.plotNumber: (p.block, p.treatmentCode) for p in layout.plots}
  frame = pandas.DataFrame([{"block": where[o.plotNumber][0], "t": where[o.plotNumber][1], "y": o.value}
                            for o in observations])
  table = anova.anova_lm(formula.ols("y ~ C(block) + C(t) + C(block):C(t)", data=frame).fit(), typ=1)
  experimentalError = table.loc["C(block):C(t)", "mean_sq"]
  treatment = next(row for row in result.table if row.source == "treatment")
  assert treatment.fStatistic == pytest.approx(table.loc["C(t)", "mean_sq"] / experimentalError, rel=1e-10)
  assert result.errorMeanSquare == pytest.approx(experimentalError / 3, rel=1e-10)


def testAMeanIsTakenOverTheSubsamplesRecordedAndTheReportSaysSo():
  package, layout, observations = trial()
  plot = layout.plots[0].plotNumber
  _, _, short = trial(drop={(plot, 2)})
  given = [o.value for o in short if o.plotNumber == plot and o.value is not None]
  assert plotValues("SEV", package, short)[plot] == pytest.approx(sum(given) / 2)
  assert missingSubsamples("SEV", package, short) == {plot: 1}
  report = buildReport(package, layout, short)
  assert "Each plot's value is the mean of its 3 subsamples, over those recorded." in report
  assert f"Plots short of subsamples, their mean taken over the rest: {plot} (1 missing)." in report


def testASumNeedsEverySubsample():
  package = TrialPackage.model_validate(packageDict("sum"))
  _, layout, observations = trial()
  plot = layout.plots[0].plotNumber
  total = sum(o.value for o in observations if o.plotNumber == plot)
  assert plotValues("SEV", package, observations)[plot] == pytest.approx(total)
  short = [o for o in observations if not (o.plotNumber == plot and o.subsample == 3)]
  with pytest.raises(AnalysisError, match=rf"sums its 3 subsamples, and plots \[{plot}\] are short of some"):
    analyzeRcbd("SEV", package, layout, short)


def testAPlotWithNoSubsampleHasNoValue():
  package, layout, _ = trial()
  plot = layout.plots[0].plotNumber
  _, _, empty = trial(drop={(plot, 1), (plot, 2), (plot, 3)})
  with pytest.raises(AnalysisError, match=rf"Missing: plot {plot} "):
    analyzeRcbd("SEV", package, layout, empty)


@pytest.mark.parametrize("observation, message", [
  (Observation(plotNumber=101, assessmentCode="SEV", value=1.0), "the value has no subsample number"),
  (Observation(plotNumber=101, assessmentCode="SEV", value=1.0, subsample=4), "subsample 4 is beyond the 3"),
])
def testEveryValueOfASubsampledAssessmentIsNumbered(observation, message):
  package, layout, _ = trial()
  with pytest.raises(ValidationError, match=message):
    TrialDocument(package=package, layout=layout.plots, observations=[observation])


def testNoSubsampleTwiceAndNoneWithoutSubsamples():
  package, layout, observations = trial()
  with pytest.raises(ValidationError, match="subsample 2: given twice"):
    TrialDocument(package=package, layout=layout.plots, observations=observations + [observations[1]])
  data = packageDict()
  del data["assessments"][0]["subsamples"]
  plain = TrialPackage.model_validate(data)
  with pytest.raises(ValidationError, match="subsample 1 given, but the assessment takes no subsamples"):
    TrialDocument(package=plain, layout=layout.plots, observations=[observations[0]])


def testSubsamplesNeedANumericRatingAndTwoOrMore():
  data = packageDict()
  data["ratings"][0] = {"ratingCode": "SEV", "name": "Severity", "dataType": "ordinal", "allowedValues": ["low", "high"]}
  with pytest.raises(ValidationError, match="subsamples give a plot value by a mean or a sum, so they need a numeric rating"):
    TrialPackage.model_validate(data)
  with pytest.raises(ValidationError, match="greater than or equal to 2"):
    TrialPackage.model_validate(packageDict(count=1))


def testSubsamplesSurviveStoreExportAndCsv(tmp_path, newStore):
  package, layout, observations = trial()
  workspace = Workspace.create(newStore("t"))
  workspace.addPackage(package, standardStudy(workspace))
  workspace.recordValues("SUB-1", "SEV", observations)
  stored = workspace.loadObservations("SUB-1")
  assert sorted(stored, key=lambda o: (o.plotNumber, o.subsample)) == sorted(observations, key=lambda o: (o.plotNumber, o.subsample))
  assert workspace.loadPackage("SUB-1").assessments[0].subsamples.count == 3
  assert workspace.verifyRoundTrip("SUB-1").matches
  workspace.exportObservationsCsv("SUB-1", str(tmp_path / "o.csv"))
  with open(tmp_path / "o.csv", encoding="utf-8") as handle:
    rows = list(csv.DictReader(handle))
  assert len(rows) == 48 and [row["subsample"] for row in rows[:3]] == ["1", "2", "3"]


def testWideFileGivesOneColumnPerSubsample(tmp_path, newStore):
  package, layout, observations = trial()
  workspace = Workspace.create(newStore("t"))
  workspace.addPackage(package, standardStudy(workspace))
  values = {(o.plotNumber, o.subsample): o.value for o in observations}
  lines = ["Plot,Leaf 1,Leaf 2,Leaf 3"] + [
    f"{plot.plotNumber},{values[(plot.plotNumber, 1)]},{values[(plot.plotNumber, 2)]},{values[(plot.plotNumber, 3)]}"
    for plot in layout.plots
  ]
  data = ("\n".join(lines) + "\n").encode()
  from openfurrow.service import createApp
  client = createApp(newStore("t")).test_client()
  response = client.post("/trials/SUB-1/import", data={
    "fileName": "leaves.csv", "fileData": base64.b64encode(data).decode(), "previewedSheet": "", "shape": "wide",
    "plot": "0", "column-1": "SEV", "column-2": "SEV", "column-3": "SEV", "decimal": ".", "action": "import"})
  assert response.status_code == 200, response.get_data(as_text=True)
  stored = {(o.plotNumber, o.subsample): o.value for o in workspace.loadObservations("SUB-1")}
  assert stored == values


def testLongFileNamesTheSubsample(tmp_path, newStore):
  package, layout, observations = trial()
  workspace = Workspace.create(newStore("t"))
  workspace.addPackage(package, standardStudy(workspace))
  path = tmp_path / "long.csv"
  path.write_text("plot,code,leaf,value\n" + "".join(
    f"{o.plotNumber},SEV,{o.subsample},{o.value}\n" for o in observations), encoding="utf-8")
  from openfurrow import ImportProfile
  profile = ImportProfile().withOverrides(long={"plotNumber": "plot", "assessmentCode": "code", "value": "value", "subsample": "leaf"})
  assert len(workspace.importObservations("SUB-1", str(path), profile).observations) == 48
  path.write_text("plot,code,leaf,value\n101,SEV,,4\n", encoding="utf-8")
  with pytest.raises(Exception, match="takes 3 subsamples; the row gives no subsample number"):
    workspace.importObservations("SUB-1", str(path), profile)


def testWideColumnsForAnAssessmentWithoutSubsamplesAreRefused(tmp_path, newStore):
  data = packageDict()
  del data["assessments"][0]["subsamples"]
  package = TrialPackage.model_validate(data)
  workspace = Workspace.create(newStore("t"))
  workspace.addPackage(package, standardStudy(workspace))
  path = tmp_path / "w.csv"
  path.write_text("Plot,S1,S2\n101,1,2\n", encoding="utf-8")
  from openfurrow import ImportProfile
  profile = ImportProfile().withOverrides(format="wide", wide={"plotNumber": "Plot", "assessmentColumns": {"S1": "SEV", "S2": "SEV"}})
  with pytest.raises(Exception, match=r"columns \['S1', 'S2'\] all hold assessment 'SEV', which takes no subsamples"):
    workspace.importObservations("SUB-1", str(path), profile)


def testEntryPageTakesARowOfSubsamplesPerPlot(tmp_path, newStore):
  package, layout, _ = trial()
  workspace = Workspace.create(newStore("t"))
  workspace.addPackage(package, standardStudy(workspace))
  from openfurrow.service import createApp
  client = createApp(newStore("t")).test_client()
  plot = layout.plots[0].plotNumber
  page = client.get("/trials/SUB-1/entry?assessment=SEV").get_data(as_text=True)
  assert f'name="value-{plot}-3"' in page and "Each plot takes 3 subsamples; the plot&#39;s value is their mean." in page
  response = client.post("/trials/SUB-1/entry?assessment=SEV", data={f"value-{plot}-1": "10", f"value-{plot}-3": "14"})
  assert response.status_code == 302
  stored = {(o.plotNumber, o.subsample): o.value for o in workspace.loadObservations("SUB-1")}
  assert stored == {(plot, 1): 10.0, (plot, 3): 14.0}


def testCheckPlotsExportToCsv(tmp_path):
  from testChecks import trial as checkTrial
  package, layout, observations = checkTrial("adjacent")
  document = TrialDocument(package=package, layout=layout.plots, checkPlots=layout.checkPlots, observations=observations)
  from openfurrow.exchange import exportObservationsCsv
  exportObservationsCsv(document, str(tmp_path / "c.csv"))
  with open(tmp_path / "c.csv", encoding="utf-8") as handle:
    rows = {int(row["plotNumber"]): row for row in csv.DictReader(handle)}
  check = layout.checkPlots[0]
  assert (rows[check.plotNumber]["treatment"], rows[check.plotNumber]["checkFor"]) == ("", " ".join(map(str, check.pairedPlots)))
  treated = layout.plots[0]
  assert (rows[treated.plotNumber]["treatment"], rows[treated.plotNumber]["checkFor"]) == (treated.treatmentCode, "")
