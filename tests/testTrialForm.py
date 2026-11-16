# SPDX-License-Identifier: Apache-2.0
"""Setting up a trial without writing JSON (worklist USR-1), including a layout uploaded as
planted (USR-7)."""

import io
import re

import pytest

from openfurrow import RandomizationMethod, TreatmentRole, Workspace
from openfurrow.importers.layoutCsv import LayoutFileError, readLayoutCsv
from openfurrow.service import createApp
from storeHelpers import standardPath, standardStudy


@pytest.fixture
def setup(tmp_path, newStore):
  databasePath = newStore("trials")
  standardStudy(Workspace.create(databasePath))
  return Workspace.open(databasePath), createApp(databasePath).test_client()


def filled(**overrides):
  data = {
    "trialCode": "FORM-1", "title": "Barley fungicides", "crop": "Barley", "season": "2026",
    "site": "North Field", "objective": "Compare programs", "investigator": "", "organization": "",
    "treatmentsRows": "6", "assessmentsRows": "3", "replications": "3",
    "layoutSource": "generate", "seed": "12", "create": "yes", "place": standardPath,
    "treatments-0-code": "UTC", "treatments-0-name": "Untreated", "treatments-0-role": "untreatedControl",
    "treatments-1-code": "A", "treatments-1-name": "Program A", "treatments-1-role": "test",
    "treatments-2-code": "B", "treatments-2-name": "Program B", "treatments-2-role": "",
    "assessments-0-code": "SEV", "assessments-0-name": "Severity", "assessments-0-dataType": "numeric",
    "assessments-0-unit": "%", "assessments-0-minValue": "0", "assessments-0-maxValue": "100",
    "assessments-1-code": "LODGE", "assessments-1-name": "Lodging", "assessments-1-dataType": "ordinal",
    "assessments-1-categories": "none, slight, severe",
  }
  data.update(overrides)
  return data


def testFormCreatesTheTrialItDescribes(setup):
  workspace, client = setup
  response = client.post("/trials/form", data=filled())
  assert response.status_code == 302 and response.headers["Location"].endswith("/trials/FORM-1")
  package = workspace.loadPackage("FORM-1")
  assert [(t.treatmentCode, t.role) for t in package.treatments] == [
    ("UTC", TreatmentRole.untreatedControl), ("A", TreatmentRole.test), ("B", None),
  ]
  assert (package.design.replications, package.design.randomizationSeed) == (3, 12)
  severity, lodging = package.ratings
  assert (severity.unit, severity.minValue, severity.maxValue) == ("%", 0.0, 100.0)
  assert lodging.allowedValues == ["none", "slight", "severe"]
  assert [(a.assessmentCode, a.ratingCode) for a in package.assessments] == [("SEV", "SEV"), ("LODGE", "LODGE")]
  assert package.trial.investigator is None
  assert len(workspace.layoutFor("FORM-1").plots) == 9


def testEmptySeedIsDrawnAndRecorded(setup):
  workspace, client = setup
  client.post("/trials/form", data=filled(seed=""))
  assert isinstance(workspace.loadPackage("FORM-1").design.randomizationSeed, int)


def testSpanishLimitsTakeADecimalComma(setup):
  workspace, client = setup
  client.post("/trials/form?locale=es", data=filled(**{"assessments-0-maxValue": "99,5"}))
  assert workspace.loadPackage("FORM-1").ratings[0].maxValue == 99.5


def testProblemKeepsWhatWasTyped(setup):
  workspace, client = setup
  response = client.post("/trials/form", data=filled(**{"treatments-2-code": "A"}))
  body = response.get_data(as_text=True)
  assert response.status_code == 400
  assert "duplicate treatmentCode values: [&#39;A&#39;]" in body
  assert 'value="Program B"' in body and 'value="Barley fungicides"' in body
  assert workspace.listTrials() == []


@pytest.mark.parametrize("field, value, message", [
  ("assessments-0-maxValue", "lots", "Assessment row 1: maxValue is not a number."),
  ("replications", "three", "The number of blocks is a whole number."),
  ("seed", "-5", "The seed is a whole number."),
])
def testTypedNumbersAreChecked(setup, field, value, message):
  _, client = setup
  response = client.post("/trials/form", data=filled(**{field: value}))
  assert response.status_code == 400 and message in response.get_data(as_text=True)


def testMoreRowsAddsRowsAndKeepsTheRest(setup):
  workspace, client = setup
  data = filled(more="treatments")
  del data["create"]
  body = client.post("/trials/form", data=data).get_data(as_text=True)
  assert len(re.findall(r'name="treatments-\d+-code"', body)) == 10
  assert 'value="Program A"' in body
  assert workspace.listTrials() == []


def testLayoutUploadedAsPlantedIsKeptExactly(setup):
  workspace, client = setup
  csvText = "plotNumber,block,positionInBlock,treatmentCode,row\n" + "".join(
    f"{number},{block},{position},{code},{block}\n"
    for block, codes in ((1, ("A", "UTC", "B")), (2, ("B", "A", "UTC")), (3, ("UTC", "B", "A")))
    for position, (number, code) in enumerate(zip(range(block * 10 + 1, block * 10 + 4), codes), start=1)
  )
  data = filled(layoutSource="upload", seed="")
  data["layoutFile"] = (io.BytesIO(csvText.encode("utf-8")), "layout.csv")
  response = client.post("/trials/form", data=data, content_type="multipart/form-data")
  assert response.status_code == 302
  assert workspace.loadPackage("FORM-1").design.randomizationMethod is RandomizationMethod.imported
  plots = sorted(workspace.layoutFor("FORM-1").plots, key=lambda plot: plot.plotNumber)
  assert [(p.plotNumber, p.block, p.treatmentCode) for p in plots][:3] == [(11, 1, "A"), (12, 1, "UTC"), (13, 1, "B")]


def testUploadedLayoutThatIsNotCompleteBlocksIsRefused(setup):
  workspace, client = setup
  csvText = "plotNumber,block,positionInBlock,treatmentCode\n11,1,1,A\n12,1,2,A\n13,1,3,B\n"
  data = filled(layoutSource="upload", replications="1")
  data["layoutFile"] = (io.BytesIO(csvText.encode("utf-8")), "layout.csv")
  response = client.post("/trials/form", data=data, content_type="multipart/form-data")
  assert response.status_code == 400
  assert workspace.listTrials() == []


def testUploadWithoutAFileIsRefused(setup):
  _, client = setup
  response = client.post("/trials/form", data=filled(layoutSource="upload"))
  assert response.status_code == 400 and "Choose the layout file to upload." in response.get_data(as_text=True)


@pytest.mark.parametrize("text, message", [
  ("plotNumber,block,treatmentCode\n1,1,A\n", r"lacks the column\(s\) \['positionInBlock'\]"),
  ("plotNumber,block,positionInBlock,treatmentCode\n1,one,1,A\n", "row 2: plotNumber, block and positionInBlock"),
  ("plotNumber,block,positionInBlock,treatmentCode\n1,1,1,\n", "row 2: treatmentCode is empty"),
  ("plotNumber,block,positionInBlock,treatmentCode\n", "lists no plots"),
])
def testLayoutFileProblemsAreNamed(tmp_path, text, message):
  path = tmp_path / "layout.csv"
  path.write_text(text, encoding="utf-8")
  with pytest.raises(LayoutFileError, match=message):
    readLayoutCsv(path)


def testAddTrialLeadsToTheForm(setup):
  _, client = setup
  assert 'href="/trials/form"' in client.get("/").get_data(as_text=True)
  assert "Use a trial file instead." in client.get("/trials/form").get_data(as_text=True)
