# SPDX-License-Identifier: Apache-2.0
"""Signing in to the service, and each request acting as its account (decision 0036)."""

import json

import pytest

from openfurrow import TrialPackage, Workspace
from openfurrow.identity import RoleAssignment
from openfurrow.service import createApp

from storeHelpers import standardPath, standardStudy

password = "correct horse battery"
origin = {"Origin": "http://localhost"}


@pytest.fixture
def location(newStore, validPackageDict):
  location = newStore("s")
  operator = Workspace.create(location)
  standardStudy(operator)
  operator.addPackage(TrialPackage.model_validate(validPackageDict), standardPath)
  operator.createAccount("admin", "Administrator", None, password)
  operator.createAccount("viewer", "Viewer", None, password)
  operator.assignRole(RoleAssignment(roleCode="administrator", scope="server", userName="admin"))
  operator.assignRole(RoleAssignment(roleCode="viewer", scope="server", userName="viewer"))
  operator.setSetting("server", "identity.signInMode", "accounts")
  return location


def signedIn(location, userName):
  client = createApp(location).test_client()
  response = client.post("/signin", data={"userName": userName, "password": password}, headers=origin)
  assert response.status_code == 302
  return client


def testThePagesAskForSignIn(location):
  client = createApp(location).test_client()
  response = client.get("/trials/ESV-2025-01")
  assert response.status_code == 302 and response.headers["Location"] == "/signin?next=/trials/ESV-2025-01"
  refused = client.post("/signin", data={"userName": "admin", "password": "not the password"}, headers=origin)
  assert refused.status_code == 401
  assert "the user name or the password is wrong" in refused.get_data(as_text=True)
  accepted = client.post("/signin?next=/trials/ESV-2025-01", data={"userName": "admin", "password": password}, headers=origin)
  assert accepted.status_code == 302 and accepted.headers["Location"] == "/trials/ESV-2025-01"
  cookie = accepted.headers["Set-Cookie"]
  assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
  page = client.get("/trials/ESV-2025-01").get_data(as_text=True)
  assert "Fungicide efficacy on winter wheat" in page and ">admin</a>" in page


def testAChangeFromAnotherSiteIsRefused(location):
  client = signedIn(location, "admin")
  data = {"parent": "", "code": "elsewhere", "name": "Elsewhere"}
  assert client.post("/places", data=data).status_code == 403
  assert client.post("/places", data=data, headers={"Origin": "http://evil.example"}).status_code == 403
  assert client.post("/places", data=data, headers=origin).status_code == 302
  assert "elsewhere" in [place.path for place in Workspace.open(location).places()]


def testAViewerCannotChangeWhatTheyCanSee(location):
  client = signedIn(location, "viewer")
  assert client.get("/trials/ESV-2025-01").status_code == 200
  response = client.post("/places", data={"parent": "", "code": "x", "name": "X"}, headers=origin)
  page = response.get_data(as_text=True)
  assert response.status_code == 403 and response.mimetype == "text/html"
  assert "Not permitted" in page and "Manage places and hierarchy levels" in page
  assert '<span class="code">manageStructure</span>' in page and "The whole server" in page and ">viewer</dd>" in page
  assert "x" not in [place.path for place in Workspace.open(location).places()]


def testSigningOutEndsTheSession(location):
  client = signedIn(location, "admin")
  assert client.post("/signout", headers=origin).status_code == 302
  assert client.get("/").status_code == 302


def testAPreferredLanguageIsUsed(location):
  client = signedIn(location, "viewer")
  assert client.post("/account", data={"action": "locale", "preferredLocale": "fr"}, headers=origin).status_code == 302
  assert '<html lang="fr" dir="ltr">' in client.get("/").get_data(as_text=True)
  assert '<html lang="ar" dir="rtl">' in client.get("/?locale=ar").get_data(as_text=True)


def testTheAPIWantsAToken(location):
  client = createApp(location).test_client()
  assert client.get("/api/trials").status_code == 401
  assert client.get("/api/trials", headers={"Authorization": "Bearer nonsense"}).status_code == 401
  viewer = Workspace.open(location)
  _, session = viewer.signIn("viewer", password, "test")
  token = viewer.actingAs(viewer.actorForSession(session, "test")).issueAPIToken("script", 1)
  listed = client.get("/api/trials", headers={"Authorization": f"Bearer {token}"})
  assert listed.status_code == 200 and [t["trialCode"] for t in json.loads(listed.get_data())] == ["ESV-2025-01"]
  refused = client.delete("/api/trials/ESV-2025-01", headers={"Authorization": f"Bearer {token}"})
  assert refused.status_code == 403
  assert client.get("/health").status_code == 200
