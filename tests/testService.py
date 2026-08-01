# SPDX-License-Identifier: Apache-2.0
"""Tests for the HTTP service (B1).

The whole trial loop must work over HTTP, because that is what makes this the one
interface every non-CLI surface can sit on. Beyond that, two properties matter more
than any individual route:

- **Errors are mapped by type, not guessed from text.** An unknown trial is 404, a
  conflicting write is 409, bad input is 400. This is why the store grew
  TrialNotFoundError and TrialExistsError: an HTTP layer that sniffed the message
  string to choose a status would break the first time someone reworded an error.
- **The controllers stay thin.** They call the facade and serialize; they do not
  compute. The API's numbers must be the same objects the facade returns, so a test
  compares them to the facade's own output rather than to hand-written expectations.

TLS is configuration, not code: HTTPS is off by default and fails loud rather than
quietly degrading to HTTP.
"""

import csv
import json

import pytest

from openfurrow import TrialPackage, Workspace, defaultConfig
from openfurrow.config import OpenFurrowConfig, TLSSettings
from openfurrow.service import ServiceError, createApp, serviceUrl, tlsContext

_packageDict = {
  "schemaVersion": "0.1.0",
  "trial": {"trialCode": "API-1", "title": "Service trial", "crop": "Barley",
            "season": "2025", "site": "Field A", "objective": "Compare treatments"},
  "treatments": [{"treatmentCode": code, "name": code} for code in ["A", "B", "C", "D"]],
  "design": {"designType": "rcbd", "replications": 3, "randomizationSeed": 7},
  "assessments": [{"assessmentCode": "YIELD", "name": "Yield", "dataType": "numeric",
                   "unit": "kg/ha", "minValue": 0}],
}
_values = {
  ("A", 1): 106, ("A", 2): 99, ("A", 3): 95, ("B", 1): 103, ("B", 2): 100, ("B", 3): 94,
  ("C", 1): 86, ("C", 2): 79, ("C", 3): 75, ("D", 1): 83, ("D", 2): 80, ("D", 3): 74,
}


@pytest.fixture
def databasePath(tmp_path):
  path = str(tmp_path / "trials.db")
  Workspace.create(path)
  return path


@pytest.fixture
def client(databasePath):
  return createApp(databasePath).test_client()


@pytest.fixture
def workspace(databasePath):
  """A facade onto the same database, to compare the API's answers against."""
  return Workspace.open(databasePath)


def _observationCsv(workspace, tmp_path) -> bytes:
  layout = workspace.layoutFor("API-1")
  path = tmp_path / "obs.csv"
  with path.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.writer(handle)
    writer.writerow(["plotNumber", "assessmentCode", "value"])
    for plot in sorted(layout.plots, key=lambda plot: plot.plotNumber):
      writer.writerow([plot.plotNumber, "YIELD", _values[(plot.treatmentCode, plot.block)]])
  return path.read_bytes()


def _populate(client, workspace, tmp_path):
  client.post("/api/trials", data=json.dumps(_packageDict))
  client.post("/api/trials/API-1/observations", data=_observationCsv(workspace, tmp_path))


# ---- the loop over HTTP ---------------------------------------------------

def testHealth(client):
  response = client.get("/health")
  assert response.status_code == 200
  assert response.get_json()["status"] == "ok"


def testFullLoopOverHttp(client, workspace, tmp_path):
  # Add a trial.
  created = client.post("/api/trials", data=json.dumps(_packageDict))
  assert created.status_code == 201
  assert created.get_json()["trialCode"] == "API-1"

  assert client.get("/api/trials").get_json() == [{"trialCode": "API-1", "title": "Service trial"}]

  # Layout is derived, and matches the facade's.
  layout = client.get("/api/trials/API-1/layout").get_json()
  assert len(layout["plots"]) == len(workspace.layoutFor("API-1").plots)

  # Import observations as a CSV body.
  imported = client.post("/api/trials/API-1/observations", data=_observationCsv(workspace, tmp_path))
  assert imported.status_code == 201
  assert imported.get_json()["imported"] == 12
  assert len(client.get("/api/trials/API-1/observations").get_json()) == 12

  # Analysis, means, assumptions -- identical to what the facade returns.
  anova = client.get("/api/trials/API-1/analysis/YIELD").get_json()
  assert anova == workspace.analyze("API-1", "YIELD").model_dump(mode="json")

  means = client.get("/api/trials/API-1/means/YIELD").get_json()
  assert means == workspace.separateMeans("API-1", "YIELD").model_dump(mode="json")
  assert means["treatmentSignificant"] is True

  assumptions = client.get("/api/trials/API-1/assumptions/YIELD").get_json()
  assert assumptions == workspace.assessAssumptions("API-1", "YIELD").model_dump(mode="json")

  # Report is markdown, and the facade agrees byte for byte.
  report = client.get("/api/trials/API-1/report")
  assert report.status_code == 200
  assert report.mimetype == "text/markdown"
  assert report.get_data(as_text=True) == workspace.buildReport("API-1")

  # Fixity.
  assert client.get("/api/trials/API-1/hash").get_json()["contentHash"] == workspace.contentHashFor("API-1")
  verify = client.get("/api/trials/API-1/verify")
  assert verify.status_code == 200
  assert verify.get_json()["matches"] is True

  # Delete.
  assert client.delete("/api/trials/API-1").status_code == 200
  assert client.get("/api/trials").get_json() == []


def testDocumentRoundTripOverHttp(client, workspace, tmp_path):
  _populate(client, workspace, tmp_path)
  exported = client.get("/api/trials/API-1/document")
  assert exported.status_code == 200
  sourceHash = workspace.contentHashFor("API-1")

  # Into a second, empty store: the same document must reproduce the same hash.
  freshPath = str(tmp_path / "fresh.db")
  Workspace.create(freshPath)
  freshClient = createApp(freshPath).test_client()
  imported = freshClient.post("/api/documents", data=exported.get_data())
  assert imported.status_code == 201
  assert imported.get_json()["contentHash"] == sourceHash


def testReportLocaleIsDisplayOnly(client, workspace, tmp_path):
  _populate(client, workspace, tmp_path)
  before = workspace.contentHashFor("API-1")
  british = client.get("/api/trials/API-1/report?locale=en-GB").get_data(as_text=True)
  assert "Randomisation seed" in british
  assert workspace.contentHashFor("API-1") == before


# ---- error mapping, by type ------------------------------------------------

def testUnknownTrialIs404(client):
  assert client.get("/api/trials/NOPE").status_code == 404
  assert client.get("/api/trials/NOPE/layout").status_code == 404
  assert client.delete("/api/trials/NOPE").status_code == 404


def testDuplicateTrialIs409(client):
  assert client.post("/api/trials", data=json.dumps(_packageDict)).status_code == 201
  conflict = client.post("/api/trials", data=json.dumps(_packageDict))
  assert conflict.status_code == 409
  assert "already exists" in conflict.get_json()["error"]


def testInvalidPackageIs400(client):
  broken = dict(_packageDict, treatments=[])
  response = client.post("/api/trials", data=json.dumps(broken))
  assert response.status_code == 400


def testMalformedJsonIs400(client):
  assert client.post("/api/trials", data=b"{not json").status_code == 400


def testEmptyBodyIs400(client):
  assert client.post("/api/trials", data=b"").status_code == 400


def testAnalyzeWithoutObservationsIs400(client):
  client.post("/api/trials", data=json.dumps(_packageDict))
  assert client.get("/api/trials/API-1/analysis/YIELD").status_code == 400


def testUnknownLocaleIs400(client, workspace, tmp_path):
  _populate(client, workspace, tmp_path)
  assert client.get("/api/trials/API-1/report?locale=xx-XX").status_code == 400


def testEmptyCsvIs400(client):
  client.post("/api/trials", data=json.dumps(_packageDict))
  assert client.post("/api/trials/API-1/observations", data=b"").status_code == 400


# ---- Field Book interop over HTTP -----------------------------------------

def testFieldBookImportOverHttp(client, workspace, tmp_path):
  client.post("/api/trials", data=json.dumps(_packageDict))
  layout = workspace.layoutFor("API-1")
  path = tmp_path / "fb.csv"
  with path.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.writer(handle)
    writer.writerow(["plotNumber", "trait", "value", "timestamp", "person", "device_name"])
    for plot in sorted(layout.plots, key=lambda plot: plot.plotNumber):
      writer.writerow([plot.plotNumber, "YIELD", _values[(plot.treatmentCode, plot.block)],
                       "2025-06-01 10:00:00-05:00", "Field Tech", "Pixel-7"])
  response = client.post("/api/trials/API-1/observations/fieldbook", data=path.read_bytes())
  assert response.status_code == 201
  assert response.get_json()["imported"] == 12


# ---- TLS is configuration, and fails loud ---------------------------------

def testTlsOffByDefault():
  config = defaultConfig()
  assert config.service.tls.enabled is False
  assert tlsContext(config) is None
  assert serviceUrl(config) == "http://127.0.0.1:8420"


def testTlsEnabledWithoutCertificateIsRejectedAtConstruction():
  with pytest.raises(ValueError):
    TLSSettings(enabled=True)


def testTlsEnabledWithMissingFileFailsLoud(tmp_path):
  config = OpenFurrowConfig.model_validate({
    "service": {"tls": {"enabled": True,
                        "certificateFile": str(tmp_path / "absent.pem"),
                        "privateKeyFile": str(tmp_path / "absent.key")}},
  })
  # It must not quietly serve plain HTTP because a certificate is missing.
  with pytest.raises(ServiceError):
    tlsContext(config)


def testTlsContextIsUsedWhenFilesExist(tmp_path):
  certificate = tmp_path / "cert.pem"
  key = tmp_path / "key.pem"
  certificate.write_text("certificate", encoding="utf-8")
  key.write_text("key", encoding="utf-8")
  config = OpenFurrowConfig.model_validate({
    "service": {"host": "0.0.0.0", "port": 8443,
                "tls": {"enabled": True,
                        "certificateFile": str(certificate),
                        "privateKeyFile": str(key)}},
  })
  assert tlsContext(config) == (str(certificate), str(key))
  assert serviceUrl(config) == "https://0.0.0.0:8443"


# ---- operations: request bodies are bounded -------------------------------

def testOversizeRequestIsRejectedWith413(databasePath):
  from openfurrow.config import OpenFurrowConfig
  config = OpenFurrowConfig.model_validate({"service": {"maxUploadBytes": 1024}})
  client = createApp(databasePath, config).test_client()
  response = client.post("/api/trials", data=b"x" * 2048)
  assert response.status_code == 413
  assert response.get_json()["error"]


def testDefaultUploadCapIsSet(databasePath):
  app = createApp(databasePath)
  assert app.config["MAX_CONTENT_LENGTH"] == 16 * 1024 * 1024
