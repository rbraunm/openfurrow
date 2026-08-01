# SPDX-License-Identifier: Apache-2.0
"""Tests for browsing, verifying, and deleting trials in the web UI (D4).

D4 rounds out the local tool: browse trials, run the reproducibility check in the
browser, and delete a trial safely. The safety property is the one that matters most --
only a POST deletes; the GET is a confirmation page, so a crawler, a prefetch, or an
accidental link-follow cannot destroy data. Verify is read-only and must not change the
trial. Both fail loud (404) on an unknown trial.
"""

import json

import pytest

from openfurrow import TrialPackage, Workspace
from openfurrow.service import createApp

_packageDict = {
  "schemaVersion": "0.1.0",
  "trial": {"trialCode": "D4-1", "title": "Barley trial", "crop": "Barley",
            "season": "2025", "site": "North Field", "objective": "Compare programs"},
  "treatments": [{"treatmentCode": code, "name": f"Treatment {code}"} for code in ["A", "B"]],
  "design": {"designType": "rcbd", "replications": 3, "randomizationSeed": 7},
  "assessments": [{"assessmentCode": "YIELD", "name": "Yield", "dataType": "numeric", "minValue": 0}],
}


@pytest.fixture
def databasePath(tmp_path):
  path = str(tmp_path / "trials.db")
  Workspace.create(path).addPackage(TrialPackage.model_validate(_packageDict))
  return path


@pytest.fixture
def client(databasePath):
  return createApp(databasePath).test_client()


@pytest.fixture
def workspace(databasePath):
  return Workspace.open(databasePath)


def _text(response):
  return response.get_data(as_text=True)


# ---- verify (read-only) ---------------------------------------------------

def testVerifyShowsPassAndDoesNotChangeHash(client, workspace):
  before = workspace.contentHashFor("D4-1")
  response = client.get("/trials/D4-1/verify")
  assert response.status_code == 200
  assert "Reproducibility check passed" in _text(response)
  assert workspace.contentHashFor("D4-1") == before


def testVerifyUnknownTrialIs404(client):
  assert client.get("/trials/NOPE/verify").status_code == 404


# ---- delete: confirmation is a GET, deletion is a POST --------------------

def testDeleteConfirmPageShowsWarning(client):
  response = client.get("/trials/D4-1/delete")
  assert response.status_code == 200
  body = _text(response)
  assert "Delete D4-1?" in body
  assert "cannot be undone" in body
  # The confirm page does not delete anything.
  assert client.get("/trials/D4-1").status_code == 200


def testGetDeleteDoesNotDelete(client, workspace):
  client.get("/trials/D4-1/delete")
  # A GET (crawler, prefetch, link-follow) must never remove the trial.
  assert workspace.listTrials() == [("D4-1", "Barley trial")]


def testPostDeleteRemovesTrialAndRedirects(client, workspace):
  response = client.post("/trials/D4-1/delete")
  assert response.status_code == 302
  assert response.headers["Location"].endswith("/")
  assert workspace.listTrials() == []


def testDeleteUnknownTrialIs404(client):
  assert client.get("/trials/NOPE/delete").status_code == 404
  assert client.post("/trials/NOPE/delete").status_code == 404


def testDeleteThenTrialGone(client):
  client.post("/trials/D4-1/delete")
  assert client.get("/trials/D4-1").status_code == 404
  assert "No trials yet" in _text(client.get("/"))


# ---- browse + manage affordances ------------------------------------------

def testTrialPageOffersVerifyAndDelete(client):
  body = _text(client.get("/trials/D4-1"))
  assert "Verify reproducibility" in body
  assert "Delete trial" in body


def testDeleteKeepsLocaleAcrossRedirect(client):
  response = client.post("/trials/D4-1/delete?locale=en-GB")
  assert response.status_code == 302
  assert "locale=en-GB" in response.headers["Location"]
