# SPDX-License-Identifier: Apache-2.0
"""Tests for the analyst web UI import and report views (D2).

D2 completes the workflow with a face: import observations, run the analysis, and read
the report in the browser. The checks mirror what a researcher does -- upload a CSV and
see the count, upload a Field Book export the same way, get a clear error on bad data
without losing the page, then open the report and see the AOV Means Table rendered as an
actual HTML table in their language. The report is display: opening it in any locale
must not change the trial's content hash.
"""

from io import BytesIO

import csv
import io

import pytest

from openfurrow import TrialPackage, Workspace
from openfurrow.service import createApp

_packageDict = {
  "schemaVersion": "0.1.0",
  "trial": {"trialCode": "D2-1", "title": "Barley trial", "crop": "Barley",
            "season": "2025", "site": "North Field", "objective": "Compare programs"},
  "treatments": [{"treatmentCode": code, "name": f"Treatment {code}"} for code in ["A", "B", "C", "D"]],
  "design": {"designType": "rcbd", "replications": 3, "randomizationSeed": 7},
  "assessments": [{"assessmentCode": "YIELD", "name": "Grain yield", "dataType": "numeric",
                   "unit": "kg/ha", "minValue": 0}],
}
_values = {
  ("A", 1): 106, ("A", 2): 99, ("A", 3): 95, ("B", 1): 103, ("B", 2): 100, ("B", 3): 94,
  ("C", 1): 86, ("C", 2): 79, ("C", 3): 75, ("D", 1): 83, ("D", 2): 80, ("D", 3): 74,
}


@pytest.fixture
def databasePath(tmp_path):
  path = str(tmp_path / "trials.db")
  workspace = Workspace.create(path)
  workspace.addPackage(TrialPackage.model_validate(_packageDict))
  return path


@pytest.fixture
def client(databasePath):
  return createApp(databasePath).test_client()


@pytest.fixture
def workspace(databasePath):
  return Workspace.open(databasePath)


def _openFurrowCsv(workspace) -> bytes:
  layout = workspace.layoutFor("D2-1")
  buffer = io.StringIO()
  writer = csv.writer(buffer)
  writer.writerow(["plotNumber", "assessmentCode", "value"])
  for plot in sorted(layout.plots, key=lambda plot: plot.plotNumber):
    writer.writerow([plot.plotNumber, "YIELD", _values[(plot.treatmentCode, plot.block)]])
  return buffer.getvalue().encode()


def _fieldBookCsv(workspace) -> bytes:
  layout = workspace.layoutFor("D2-1")
  buffer = io.StringIO()
  writer = csv.writer(buffer)
  writer.writerow(["plotNumber", "trait", "value", "timestamp", "person", "device_name"])
  for plot in sorted(layout.plots, key=lambda plot: plot.plotNumber):
    writer.writerow([plot.plotNumber, "YIELD", _values[(plot.treatmentCode, plot.block)],
                     "2025-06-01 10:00:00-05:00", "Field Tech", "Pixel-7"])
  return buffer.getvalue().encode()


def _upload(data: bytes, fieldFormat: str = "openfurrow"):
  return {"file": (BytesIO(data), "obs.csv"), "format": fieldFormat}


# ---- import ---------------------------------------------------------------

def testImportOpenFurrowCsvShowsCount(client, workspace):
  response = client.post(
    "/trials/D2-1/observations", data=_upload(_openFurrowCsv(workspace)),
    content_type="multipart/form-data",
  )
  assert response.status_code == 200
  assert "Imported 12 observations" in response.get_data(as_text=True)
  assert len(workspace.loadObservations("D2-1")) == 12


def testImportFieldBookExportShowsCount(client, workspace):
  response = client.post(
    "/trials/D2-1/observations", data=_upload(_fieldBookCsv(workspace), "fieldbook"),
    content_type="multipart/form-data",
  )
  assert response.status_code == 200
  assert "Imported 12 observations" in response.get_data(as_text=True)
  assert len(workspace.loadObservations("D2-1")) == 12


def testImportWithNoFileFailsLoud(client):
  response = client.post("/trials/D2-1/observations", data={"format": "openfurrow"},
                         content_type="multipart/form-data")
  assert response.status_code == 400
  assert "Import failed" in response.get_data(as_text=True)


def testImportBadValueFailsLoudAndSavesNothing(client, workspace):
  bad = b"plotNumber,assessmentCode,value\n101,YIELD,notanumber\n"
  response = client.post("/trials/D2-1/observations", data=_upload(bad),
                         content_type="multipart/form-data")
  assert response.status_code == 400
  assert "Import failed" in response.get_data(as_text=True)
  assert workspace.loadObservations("D2-1") == []


def testReportLinkAppearsOnlyAfterObservations(client, workspace):
  # Before import: no report link.
  assert "View report" not in client.get("/trials/D2-1").get_data(as_text=True)
  client.post("/trials/D2-1/observations", data=_upload(_openFurrowCsv(workspace)),
              content_type="multipart/form-data")
  assert "View report" in client.get("/trials/D2-1").get_data(as_text=True)


# ---- report view ----------------------------------------------------------

@pytest.fixture
def populated(client, workspace):
  client.post("/trials/D2-1/observations", data=_upload(_openFurrowCsv(workspace)),
              content_type="multipart/form-data")
  return workspace


def testReportRendersAsHtmlTable(client, populated):
  response = client.get("/trials/D2-1/report")
  assert response.status_code == 200
  body = response.get_data(as_text=True)
  # The AOV Means Table becomes a real HTML table, not a Markdown pipe blob.
  assert "<table>" in body
  assert "<th" in body
  assert "Analysis of variance" in body
  assert "Grand mean" in body


def testReportIsLocalizedAndDisplayOnly(client, populated):
  before = populated.contentHashFor("D2-1")
  american = client.get("/trials/D2-1/report?locale=en-US").get_data(as_text=True)
  british = client.get("/trials/D2-1/report?locale=en-GB").get_data(as_text=True)
  assert "Randomization seed" in american
  assert "Randomisation seed" in british
  # Reading the report in any locale must not touch the trial.
  assert populated.contentHashFor("D2-1") == before


def testReportOffersMarkdownDownload(client, populated):
  body = client.get("/trials/D2-1/report").get_data(as_text=True)
  assert 'href="/api/trials/D2-1/report' in body


def testReportContainsCanonicalInputHash(client, populated):
  body = client.get("/trials/D2-1/report").get_data(as_text=True)
  assert populated.contentHashFor("D2-1") in body


def testReportWithoutObservationsStillRenders(client):
  # A report before any data still renders -- each assessment simply says "not analyzed".
  body = client.get("/trials/D2-1/report").get_data(as_text=True)
  assert "Not analyzed" in body
