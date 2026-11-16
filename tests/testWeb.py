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

import html
import json
import re

import pytest

from openfurrow import TrialPackage, Workspace, schemaVersion
from openfurrow.service import createApp
from storeHelpers import standardStudy, standardStudyAt
from storeHelpers import standardPath, standardStudy

_packageDict = {
  "schemaVersion": schemaVersion,
  "trial": {"trialCode": "WEB-1", "title": "Barley trial", "crop": "Barley",
            "season": "2025", "site": "North Field", "objective": "Compare programs"},
  "treatments": [{"treatmentCode": code, "name": f"Treatment {code}"} for code in ["A", "B", "C", "D"]],
  "design": {"designType": "rcbd", "replications": 3, "randomizationMethod": "sha256FisherYates1", "randomizationSeed": 7},
  "ratings": [
    {"ratingCode": "YIELD", "name": "Yield", "dataType": "numeric", "unit": "kg/ha", "minValue": 0}
  ],
  "assessments": [
    {"assessmentCode": "YIELD", "ratingCode": "YIELD"}
  ],
}


@pytest.fixture
def databasePath(tmp_path, newStore):
  path = newStore("trials")
  standardStudy(Workspace.create(path))
  return path


@pytest.fixture
def client(databasePath):
  return createApp(databasePath).test_client()


@pytest.fixture
def populated(databasePath):
  workspace = Workspace.open(databasePath)
  workspace.addPackage(TrialPackage.model_validate(_packageDict), standardStudy(workspace))
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


def testTheFormsOwnExampleCreatesATrial(client):
  """The example a new user starts from has to be a valid trial itself, treatment lines included."""
  body = _text(client.get("/trials/new"))
  example = html.unescape(re.search(r"<textarea[^>]*>(.*?)</textarea>", body, re.DOTALL).group(1))
  assert client.post("/trials/new", data={"package": example, "place": standardPath}).status_code == 302
  report = _text(client.get("/trials/ESV-2025-01/report"))
  for cell in ("<td>Reference</td>", "<td>Fungicide B</td>", "<td>0.75 L/ha of product</td>",
               "<th>Application</th>", "<td>Broadcast spray</td>"):
    assert cell in report, cell


def testHtmlDeclaresLangAndDir(client):
  body = _text(client.get("/"))
  assert '<html lang="en-US" dir="ltr">' in body


def testTrialLaidOutElsewhereShowsItsOwnPlotsAndNoSeed(client, databasePath, tmp_path):
  """A layout supplied with the trial is shown as recorded, in every shipped locale."""
  package = json.loads(json.dumps(_packageDict))
  package["trial"]["trialCode"] = "FIELD-7"
  package["treatments"] = package["treatments"][:2]
  package["design"] = {"designType": "rcbd", "replications": 2, "randomizationMethod": "imported"}
  layout = [
    {"plotNumber": 71, "block": 1, "positionInBlock": 1, "treatmentCode": "A"},
    {"plotNumber": 72, "block": 1, "positionInBlock": 2, "treatmentCode": "B"},
    {"plotNumber": 73, "block": 2, "positionInBlock": 1, "treatmentCode": "A"},
    {"plotNumber": 74, "block": 2, "positionInBlock": 2, "treatmentCode": "B"},
  ]
  observations = [
    {"plotNumber": plot["plotNumber"], "assessmentCode": "YIELD", "value": value}
    for plot, value in zip(layout, [10.0, 14.0, 11.0, 16.0])
  ]
  documentPath = tmp_path / "field7.json"
  documentPath.write_text(
    json.dumps({"package": package, "layout": layout, "observations": observations}), encoding="utf-8",
  )
  Workspace.open(databasePath).importDocument(str(documentPath), standardStudyAt(databasePath))

  body = _text(client.get("/trials/FIELD-7"))
  assert re.findall(r'<span class="plot-number code">(\d+)</span>', body) == ["71", "72", "73", "74"]
  assert "This layout was supplied with the trial." in body
  assert "supplied with the trial, not randomized here" in body
  assert "Randomization seed" not in body

  report = _text(client.get("/trials/FIELD-7/report"))
  assert "Layout: supplied with the trial, not randomized here" in report
  assert "Randomization method: imported" in report
  assert "Randomization seed" not in report

  for locale in ("en-GB", "es", "fr", "ar"):
    assert client.get(f"/trials/FIELD-7?locale={locale}").status_code == 200
    assert client.get(f"/trials/FIELD-7/report?locale={locale}").status_code == 200


# ---- add a trial ----------------------------------------------------------

def testAddTrialFromJsonRedirectsToDetail(client):
  response = client.post("/trials/new", data={"package": json.dumps(_packageDict), "place": standardPath})
  assert response.status_code == 302
  assert response.headers["Location"].endswith("/trials/WEB-1")
  # It really landed in the store.
  assert _text(client.get("/")).count("WEB-1") >= 1


def testAddTrialFromFileUpload(client):
  from io import BytesIO
  data = {"file": (BytesIO(json.dumps(_packageDict).encode()), "trial.json"), "place": standardPath}
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


# ---- offline --------------------------------------------------------------
# That an installed wheel carries the templates and the stylesheet is proved by
# scripts/productSmoke.py, which serves the pages from one.

def testNoExternalAssetReferences(client, populated):
  """Offline posture: no CDN or off-site asset references anywhere in the markup."""
  for path in ("/", "/trials/new", "/trials/WEB-1"):
    body = _text(client.get(path))
    assert "http://" not in body
    assert "https://" not in body
    assert "cdn" not in body.lower()


def testLocaleSwitchHasNoScriptFallback(client, populated):
  """The locale switch uses onchange for JS users, but must still work without JS."""
  body = _text(client.get("/"))
  assert "<noscript>" in body
  assert "this.form.submit()" in body  # JS path still present


def testTrialsTableHeadersHaveScope(client, populated):
  body = _text(client.get("/"))
  assert 'scope="col"' in body


# ---- draft locales in the UI (decision 0007) -------------------------------

def testDraftBannerShowsForDraftLocaleOnly(client, populated):
  spanish = _text(client.get("/?locale=es"))
  english = _text(client.get("/"))
  assert "borrador automático" in spanish
  assert "draft-banner" in spanish
  assert "draft-banner" not in english


def testArabicLocaleMirrorsTheDocument(client, populated):
  """ar is the first shipped RTL locale: the document direction must flip, the draft
  banner must render in Arabic, and choosing it must not touch the trial."""
  body = _text(client.get("/trials/WEB-1?locale=ar"))
  assert '<html lang="ar" dir="rtl">' in body
  assert "مسودة آلية" in body            # the Arabic draft banner
  assert "المعاملات" in body             # treatments heading, in Arabic
