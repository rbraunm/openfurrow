# SPDX-License-Identifier: Apache-2.0
"""Typing values in the tool, in two strengths (decision 0023).

What cannot be a value is refused and nothing is saved; a number outside its limits is
held back until it is confirmed, and the confirmation is kept with the value, in the
store, the export and the content hash.
"""

import json
import re

import pytest
from pydantic import ValidationError

from openfurrow import Observation, TrialDocument, TrialPackage, Workspace, schemaVersion
from openfurrow.design import generateLayout
from openfurrow.importers.entry import EntryRefused, readEntry, writeEntry
from openfurrow.schema import Rating
from openfurrow.service import createApp

severity = Rating(ratingCode="SEV", name="Severity", dataType="numeric", unit="%", minValue=0, maxValue=100)
lodging = Rating(ratingCode="LODGE", name="Lodging", dataType="ordinal", allowedValues=["none", "slight", "severe"])


def packageDict():
  return {
    "schemaVersion": schemaVersion,
    "trial": {"trialCode": "ENT-1", "title": "Entry", "crop": "Wheat", "season": "2026",
              "site": "Field 4", "objective": "Typed values"},
    "treatments": [{"treatmentCode": code, "name": code} for code in ("A", "B")],
    "design": {"designType": "rcbd", "replications": 2, "randomizationMethod": "sha256FisherYates1",
               "randomizationSeed": 3, "checkArrangement": "paired"},
    "ratings": [severity.model_dump(mode="json"), lodging.model_dump(mode="json")],
    "assessments": [{"assessmentCode": "SEV", "ratingCode": "SEV"}, {"assessmentCode": "LODGE", "ratingCode": "LODGE"}],
  }


@pytest.fixture
def served(tmp_path):
  databasePath = str(tmp_path / "trials.db")
  workspace = Workspace.create(databasePath)
  workspace.addPackage(TrialPackage.model_validate(packageDict()))
  return workspace, createApp(databasePath).test_client()


def plotNumbers(workspace):
  layout = workspace.layoutFor("ENT-1")
  return sorted(p.plotNumber for p in layout.plots), sorted(c.plotNumber for c in layout.checkPlots)


# ---- reading what is typed ---------------------------------------------------

@pytest.mark.parametrize("typed, separator, read", [
  ("12.5", ".", 12.5), ("12,5", ",", 12.5), ("12.5", ",", 12.5), (" 7 ", ".", 7.0), ("-0.5", ".", -0.5),
  (".5", ".", 0.5), ("", ".", None), ("   ", ",", None),
])
def testNumbersAreReadInTheReadersDecimalMark(typed, separator, read):
  assert readEntry(typed, severity, separator) == read


@pytest.mark.parametrize("typed, separator, reason", [
  ("12,5", ".", "web.entry.refused.notNumber"), ("1,234.5", ",", "web.entry.refused.twoDecimalMarks"),
  ("12 %", ".", "web.entry.refused.notNumber"), ("nan", ".", "web.entry.refused.notNumber"),
  ("inf", ".", "web.entry.refused.notNumber"), ("1e3", ".", "web.entry.refused.notNumber"),
])
def testWhatIsNotANumberIsRefused(typed, separator, reason):
  with pytest.raises(EntryRefused) as refusal:
    readEntry(typed, severity, separator)
  assert refusal.value.reasonKey == reason


def testACategoryMustBeOneOfTheRatings():
  assert readEntry("slight", lodging, ".") == "slight"
  with pytest.raises(EntryRefused) as refusal:
    readEntry("Slight", lodging, ".")
  assert refusal.value.placeholders == {"values": "none / slight / severe"}


@pytest.mark.parametrize("value, separator, written", [(12.5, ",", "12,5"), (7.0, ".", "7"), (0.1, ".", "0.1"), (None, ".", "")])
def testStoredValuesAreWrittenBackAsEntered(value, separator, written):
  assert writeEntry(value, separator) == written


# ---- the record --------------------------------------------------------------

def documentWith(observations):
  package = TrialPackage.model_validate(packageDict())
  layout = generateLayout(package)
  return package, layout, observations


def testValueOutsideItsLimitsNeedsAConfirmation():
  package, layout, _ = documentWith([])
  plot = layout.plots[0].plotNumber
  with pytest.raises(ValidationError, match="120.0 is outside the rating's limits and was not confirmed"):
    TrialDocument(package=package, layout=layout.plots, checkPlots=layout.checkPlots,
                  observations=[Observation(plotNumber=plot, assessmentCode="SEV", value=120.0)])
  confirmed = Observation(plotNumber=plot, assessmentCode="SEV", value=120.0, outOfRangeConfirmed=True)
  document = TrialDocument(package=package, layout=layout.plots, checkPlots=layout.checkPlots, observations=[confirmed])
  assert document.observations[0].outOfRangeConfirmed is True


@pytest.mark.parametrize("value", [55.0, "slight", None])
def testConfirmationOnAnythingElseIsRefused(value):
  package, layout, _ = documentWith([])
  code = "LODGE" if value == "slight" else "SEV"
  with pytest.raises(ValidationError, match="a confirmation is recorded for a value that is not outside the limits"):
    TrialDocument(package=package, layout=layout.plots, checkPlots=layout.checkPlots, observations=[
      Observation(plotNumber=layout.plots[0].plotNumber, assessmentCode=code, value=value, outOfRangeConfirmed=True),
    ])


def testDocumentWithAWrongTypeOrCategoryIsRefused():
  package, layout, _ = documentWith([])
  plot = layout.plots[0].plotNumber
  with pytest.raises(ValidationError, match="'heavy' is not one of"):
    TrialDocument(package=package, layout=layout.plots, checkPlots=layout.checkPlots,
                  observations=[Observation(plotNumber=plot, assessmentCode="LODGE", value="heavy")])
  with pytest.raises(ValidationError, match="'12' is not a finite number"):
    TrialDocument(package=package, layout=layout.plots, checkPlots=layout.checkPlots,
                  observations=[Observation(plotNumber=plot, assessmentCode="SEV", value="12")])


def testConfirmationTravelsThroughStoreExportAndHash(tmp_path, served):
  workspace, _ = served
  plots, checks = plotNumbers(workspace)
  workspace.recordValues("ENT-1", "SEV", [
    Observation(plotNumber=plots[0], assessmentCode="SEV", value=120.0, outOfRangeConfirmed=True),
    Observation(plotNumber=checks[0], assessmentCode="SEV", value=40.0),
  ])
  stored = {o.plotNumber: o for o in workspace.loadObservations("ENT-1")}
  assert stored[plots[0]].outOfRangeConfirmed is True and stored[checks[0]].outOfRangeConfirmed is False
  exported = tmp_path / "doc.json"
  workspace.exportDocument("ENT-1", str(exported))
  assert {"plotNumber": plots[0], "assessmentCode": "SEV", "value": 120.0, "outOfRangeConfirmed": True} in json.loads(
    exported.read_text(encoding="utf-8"))["observations"]
  other = Workspace.create(str(tmp_path / "other.db"))
  other.importDocument(str(exported))
  assert other.contentHashFor("ENT-1") == workspace.contentHashFor("ENT-1")


def testRecordingReplacesTheAssessmentsValuesOnly(served):
  workspace, _ = served
  plots, _ = plotNumbers(workspace)
  workspace.recordValues("ENT-1", "LODGE", [Observation(plotNumber=plots[0], assessmentCode="LODGE", value="none")])
  workspace.recordValues("ENT-1", "SEV", [Observation(plotNumber=plots[0], assessmentCode="SEV", value=10.0)])
  workspace.recordValues("ENT-1", "SEV", [Observation(plotNumber=plots[1], assessmentCode="SEV", value=20.0)])
  assert sorted((o.plotNumber, o.assessmentCode, o.value) for o in workspace.loadObservations("ENT-1")) == sorted([
    (plots[0], "LODGE", "none"), (plots[1], "SEV", 20.0),
  ])


# ---- the page ----------------------------------------------------------------

def form(values, confirmed=()):
  data = {f"value-{plot}": text for plot, text in values.items()}
  data.update({f"confirm-{plot}": "yes" for plot in confirmed})
  return data


def testPageListsEveryPlotAndCheck(served):
  workspace, client = served
  plots, checks = plotNumbers(workspace)
  body = client.get("/trials/ENT-1/entry?assessment=SEV").get_data(as_text=True)
  assert sorted(int(n) for n in re.findall(r'name="value-(\d+)"', body)) == sorted(plots + checks)
  assert "0 of 8 plots have a value." in body
  assert "Expected values: 0 to 100." in body
  assert f"untreated check of {plots[0]}" in body


def testRefusedValueSavesNothingAndNamesTheReason(served):
  workspace, client = served
  plots, _ = plotNumbers(workspace)
  response = client.post("/trials/ENT-1/entry?assessment=SEV", data=form({plots[0]: "12", plots[1]: "lots"}))
  body = response.get_data(as_text=True)
  assert response.status_code == 400
  assert "Nothing was saved: the marked values cannot be accepted." in body and "Not a number." in body
  assert 'value="lots"' in body
  assert workspace.loadObservations("ENT-1") == []


def testOutOfRangeIsHeldUntilConfirmed(served):
  workspace, client = served
  plots, _ = plotNumbers(workspace)
  first = client.post("/trials/ENT-1/entry?assessment=SEV", data=form({plots[0]: "12", plots[1]: "120"}))
  body = first.get_data(as_text=True)
  assert first.status_code == 200 and "Nothing was saved yet" in body
  assert f'name="confirm-{plots[1]}"' in body and f'name="confirm-{plots[0]}"' not in body
  assert workspace.loadObservations("ENT-1") == []
  second = client.post("/trials/ENT-1/entry?assessment=SEV",
                       data=form({plots[0]: "12", plots[1]: "120"}, confirmed=[plots[1]]))
  assert second.status_code == 302
  stored = {o.plotNumber: o for o in workspace.loadObservations("ENT-1")}
  assert (stored[plots[0]].value, stored[plots[0]].outOfRangeConfirmed) == (12.0, False)
  assert (stored[plots[1]].value, stored[plots[1]].outOfRangeConfirmed) == (120.0, True)
  after = client.get(second.headers["Location"]).get_data(as_text=True)
  assert "Saved. 2 of 8 plots have a value." in after
  assert re.search(rf'name="confirm-{plots[1]}" value="yes"\s+checked', after)


def testEmptyingABoxRemovesTheValue(served):
  workspace, client = served
  plots, _ = plotNumbers(workspace)
  client.post("/trials/ENT-1/entry?assessment=SEV", data=form({plots[0]: "12", plots[1]: "30"}))
  client.post("/trials/ENT-1/entry?assessment=SEV", data=form({plots[0]: "12", plots[1]: ""}))
  assert [(o.plotNumber, o.value) for o in workspace.loadObservations("ENT-1")] == [(plots[0], 12.0)]


def testSpanishEntryTakesADecimalComma(served):
  workspace, client = served
  plots, _ = plotNumbers(workspace)
  response = client.post("/trials/ENT-1/entry?assessment=SEV&locale=es", data=form({plots[0]: "12,5"}))
  assert response.status_code == 302
  assert workspace.loadObservations("ENT-1")[0].value == 12.5
  assert 'value="12,5"' in client.get("/trials/ENT-1/entry?assessment=SEV&locale=es").get_data(as_text=True)


def testUnknownAssessmentIsNotFound(served):
  _, client = served
  assert client.get("/trials/ENT-1/entry?assessment=NOPE").status_code == 404


def testTrialPageLinksToEntry(served):
  _, client = served
  assert "/trials/ENT-1/entry" in client.get("/trials/ENT-1").get_data(as_text=True)


def testBackArrowFollowsThePageDirection(served):
  _, client = served
  assert "&larr; Back to trial" in client.get("/trials/ENT-1/entry").get_data(as_text=True)
  assert "&rarr; " in client.get("/trials/ENT-1/entry?locale=ar").get_data(as_text=True)