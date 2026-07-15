# SPDX-License-Identifier: Apache-2.0
"""Tests for the analyst web UI (B2 entry point + D1 pages).

The UI is server-rendered and thin over the facade, so these check what a researcher
actually experiences: the pages render, the randomized field layout shows every plot
with its treatment, adding a trial from JSON works and bad input fails loud without
losing what was typed, and the localization discipline holds -- strings and the
document direction come from the locale, and choosing a locale never changes the
trial's content hash. The plot map is a redundant-cue design (colour plus code), so it
is asserted by the codes it must contain, not by colour.
"""

import glob
import json
import re
import zipfile

import pytest

from openfurrow import TrialPackage, Workspace
from openfurrow.service import createApp

_packageDict = {
  "schemaVersion": "0.1.0",
  "trial": {"trialCode": "WEB-1", "title": "Barley trial", "crop": "Barley",
            "season": "2025", "site": "North Field", "objective": "Compare programs"},
  "treatments": [{"treatmentCode": code, "name": f"Treatment {code}"} for code in ["A", "B", "C", "D"]],
  "design": {"designType": "rcbd", "replications": 3, "randomizationSeed": 7},
  "assessments": [{"assessmentCode": "YIELD", "name": "Yield", "dataType": "numeric",
                   "unit": "kg/ha", "minValue": 0}],
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
def populated(databasePath):
  workspace = Workspace.open(databasePath)
  workspace.addPackage(TrialPackage.model_validate(_packageDict))
  return workspace


def _text(response):
  return response.get_data(as_text=True)


# ---- pages render ---------------------------------------------------------

def testIndexEmptyState(client):
  response = client.get("/")
  assert response.status_code == 200
  assert "No trials yet" in _text(response)


def testIndexListsTrials(client, populated):
  body = _text(client.get("/"))
  assert "WEB-1" in body
  assert "Barley trial" in body


def testAddFormShowsExample(client):
  body = _text(client.get("/trials/new"))
  # The form is seeded with an editable example package.
  assert "ESV-2025-01" in body
  assert "<textarea" in body


def testHtmlDeclaresLangAndDir(client):
  body = _text(client.get("/"))
  assert '<html lang="en-US" dir="ltr">' in body


# ---- add a trial ----------------------------------------------------------

def testAddTrialFromJsonRedirectsToDetail(client):
  response = client.post("/trials/new", data={"package": json.dumps(_packageDict)})
  assert response.status_code == 302
  assert response.headers["Location"].endswith("/trials/WEB-1")
  # It really landed in the store.
  assert _text(client.get("/")).count("WEB-1") >= 1


def testAddTrialFromFileUpload(client):
  from io import BytesIO
  data = {"file": (BytesIO(json.dumps(_packageDict).encode()), "trial.json")}
  response = client.post("/trials/new", data=data, content_type="multipart/form-data")
  assert response.status_code == 302
  assert response.headers["Location"].endswith("/trials/WEB-1")


def testAddInvalidJsonRerendersWithErrorAndKeepsInput(client):
  response = client.post("/trials/new", data={"package": "{not valid"})
  assert response.status_code == 400
  body = _text(response)
  assert "Could not create the trial" in body
  # What the user typed is preserved in the textarea, not discarded.
  assert "{not valid" in body


def testAddInvalidPackageRerendersWithError(client):
  broken = dict(_packageDict, treatments=[])
  response = client.post("/trials/new", data={"package": json.dumps(broken)})
  assert response.status_code == 400
  assert "Could not create the trial" in _text(response)


# ---- the field-layout map (the signature) ---------------------------------

def testTrialPageShowsEveryPlotWithTreatment(client, populated):
  body = _text(client.get("/trials/WEB-1"))
  layout = populated.layoutFor("WEB-1")
  # Every plot number appears in the map.
  for plot in layout.plots:
    assert f">{plot.plotNumber}<" in body
  # A cell for each plot, coloured by treatment via a CSS custom property.
  assert body.count("--treatment:") == len(layout.plots)
  # The seed -- the provenance anchor -- is shown.
  assert "7" in body


def testTrialPageShowsContentHash(client, populated):
  body = _text(client.get("/trials/WEB-1"))
  assert populated.contentHashFor("WEB-1") in body


def testUnknownTrialIs404(client):
  assert client.get("/trials/NOPE").status_code == 404


# ---- localization ---------------------------------------------------------

def testLocaleSwitchesStringsAndKeepsHash(client, populated):
  before = populated.contentHashFor("WEB-1")
  american = _text(client.get("/trials/WEB-1?locale=en-US"))
  british = _text(client.get("/trials/WEB-1?locale=en-GB"))
  assert "Randomization seed" in american
  assert "Randomisation seed" in british
  # Display-only guardrail: choosing a locale never changes the trial.
  assert populated.contentHashFor("WEB-1") == before


def testBritishLocaleSetsHtmlLang(client, populated):
  body = _text(client.get("/trials/WEB-1?locale=en-GB"))
  assert '<html lang="en-GB" dir="ltr">' in body


def testUnknownLocaleFailsLoud(client):
  assert client.get("/?locale=xx-XX").status_code == 400


def testLocalePersistsAcrossNavigation(client, populated):
  # The detail link on the index carries the chosen locale forward.
  body = _text(client.get("/?locale=en-GB"))
  assert "locale=en-GB" in body


# ---- offline / packaging --------------------------------------------------

def testNoExternalAssetReferences(client, populated):
  """Offline posture: no CDN or off-site asset references anywhere in the markup."""
  for path in ("/", "/trials/new", "/trials/WEB-1"):
    body = _text(client.get(path))
    assert "http://" not in body
    assert "https://" not in body
    assert "cdn" not in body.lower()


def testTemplatesAndStaticArePackaged(tmp_path):
  """A source checkout renders; an installed wheel must carry the templates and CSS too."""
  import subprocess, sys
  subprocess.run(
    [sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp_path)],
    check=True, capture_output=True,
  )
  wheel = glob.glob(str(tmp_path / "*.whl"))[0]
  names = zipfile.ZipFile(wheel).namelist()
  assert any(n.endswith("service/templates/base.html") for n in names)
  assert any(n.endswith("service/templates/trial.html") for n in names)
  assert any(n.endswith("service/static/openfurrow.css") for n in names)
