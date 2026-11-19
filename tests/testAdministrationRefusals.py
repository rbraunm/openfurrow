# SPDX-License-Identifier: Apache-2.0
"""What the administration pages refuse, and how (worklist GOV-6): a person without a page's permission gets the 403
page in their language and nothing is done; a thing that is not there is the 404 page; the API keeps its JSON; a
visitor is sent to sign in and comes back; a change from another site is refused; and every page renders in every
language, Arabic right to left."""

import json

import pytest
from markupsafe import escape

import taskKindsForTests  # noqa: F401
from openfurrow import Workspace
from openfurrow.i18n import availableLocales, translatorFor
from openfurrow.identity import Permission, RoleDefinition
from openfurrow.identity.providers import Provider
from openfurrow.service import createApp

from administrationHelpers import origin, password, seededStore, signedIn, text, trialCode

english = translatorFor("en-US")
guardedPages = {
  "/administration/accounts": Permission.manageAccess,
  "/administration/accounts/viewer": Permission.manageAccess,
  "/administration/groups": Permission.manageAccess,
  "/administration/groups/show?name=team": Permission.manageAccess,
  "/administration/groups/delete?name=team": Permission.manageAccess,
  "/administration/roles": Permission.manageAccess,
  "/administration/roles/fieldLead": Permission.manageAccess,
  "/administration/assignments": Permission.manageAccess,
  "/administration/sign-in-mode": Permission.changeSettings,
  "/administration/providers": Permission.manageAccess,
  "/administration/providers/add/scim": Permission.manageAccess,
  "/administration/providers/campus": Permission.manageAccess,
  "/administration/workloads": Permission.manageAccess,
  "/administration/workloads/nightly": Permission.manageAccess,
  "/administration/workloads/nightly/remove": Permission.manageAccess,
  "/administration/tasks/add": Permission.manageTasks,
  "/administration/tasks/add/testEcho": Permission.manageTasks,
  "/administration/tasks/delete/echo": Permission.manageTasks,
  "/tasks": Permission.manageTasks,
  "/tasks/echo": Permission.manageTasks,
  "/administration/retention": Permission.manageRetention,
  "/administration/retention/prune": Permission.manageRetention,
  "/administration/audit": Permission.viewAudit,
}
openPages = ["/administration", "/administration/settings", f"/administration/settings?scope=trial:{trialCode}"]
# Each is a change when an administrator makes it from the site's own pages, in this order; the mode goes last
# because after it nobody is signed in.
changes = [
  ("/administration/accounts", {"userName": "new", "displayName": "New", "password": password}),
  ("/administration/accounts/viewer", {"action": "password", "newPassword": "another long password"}),
  ("/administration/accounts/viewer", {"action": "deactivate", "confirm": "yes"}),
  ("/administration/accounts/viewer", {"action": "activate"}),
  ("/administration/accounts/viewer", {"action": "link", "provider": "campus", "subject": "campus-user-1"}),
  ("/administration/accounts/viewer", {"action": "join", "group": "team"}),
  ("/administration/accounts/viewer", {"action": "give", "roleCode": "analyst", "scope": "server"}),
  ("/administration/groups", {"name": "another"}),
  ("/administration/groups/show?name=team", {"action": "leave", "userName": "viewer"}),
  ("/administration/groups/show?name=team", {"action": "give", "roleCode": "analyst", "scope": "server"}),
  ("/administration/groups/delete?name=team", {}),
  ("/administration/roles", {"roleCode": "other", "name": "Other", "permissions": ["view"]}),
  ("/administration/roles/fieldLead", {"action": "save", "name": "Renamed", "permissions": ["view", "enterValues"]}),
  ("/administration/roles/fieldLead", {"action": "delete", "confirm": "yes"}),
  ("/administration/assignments", {"action": "give", "holder": "user:viewer", "roleCode": "trialManager", "scope": "server"}),
  ("/administration/assignments", {"action": "takeBack", "holder": "user:viewer", "roleCode": "trialManager", "scope": "server"}),
  ("/administration/settings?scope=server", {"action": "set", "key": "identity.sessionHours", "value": "1"}),
  ("/administration/settings?scope=server", {"action": "clear", "key": "identity.sessionHours"}),
  ("/administration/providers/add/scim", {"name": "other", "baseURL": "https://openfurrow.example.org/scim/other/v2", "groups": "ignore"}),
  ("/administration/providers/campus", {"action": "disable"}),
  ("/administration/providers/campus", {"action": "token"}),
  ("/administration/workloads", {"name": "other", "issuer": "githubActions", "claims": "repository_id=2"}),
  ("/administration/workloads/nightly", {"action": "disable"}),
  ("/administration/workloads/nightly", {"action": "give", "roleCode": "analyst", "scope": "server"}),
  ("/administration/workloads/nightly/remove", {}),
  ("/administration/tasks/add/testEcho", {"name": "other", "message": "again"}),
  ("/administration/tasks/delete/echo", {}),
  ("/tasks/other", {"action": "disable"}),
  ("/administration/retention/prune", {}),
  ("/administration/sign-in-mode", {"mode": "open", "confirm": "yes"}),
]


@pytest.fixture
def location(newStore, validPackageDict):
  location = seededStore(newStore, validPackageDict)
  operator = Workspace.open(location)
  operator.createGroup("team")
  operator.defineRole(RoleDefinition(roleCode="fieldLead", name="Field lead", permissions=[Permission.view]))
  operator.addProvider(Provider.of("campus", "scim", {"baseURL": "https://openfurrow.example.org/scim/campus/v2"}))
  operator.setSetting("server", "identity.workloadAudience", "https://openfurrow.example.org")
  operator.addWorkloadRule("nightly", "githubActions", {"repository_id": "1"})
  operator.createTask("echo", "testEcho", {"message": "hello"})
  return location


def everythingIn(operator: Workspace) -> tuple:
  """What the pages can change, and how many audit events there are."""
  return (operator.accounts(), operator.groups(), operator.roles(), operator.assignments(), operator.effectiveSettings("server"),
          operator.providers(), operator.workloadRules(), operator.tasks(), len(operator.auditEvents(limit=10000)))


def testAPersonWithoutAPagesPermissionGetsTheRefusalPageAndNothingIsDone(location):
  operator = Workspace.open(location)
  viewer = signedIn(location, "viewer")
  before = everythingIn(operator)
  heading = english.text("web.refused.heading")
  for address, permission in guardedPages.items():
    answer = viewer.get(address)
    page = text(answer)
    assert answer.status_code == 403 and answer.mimetype == "text/html" and heading in page, address
    assert str(escape(english.text(f"web.administration.permission.{permission.value}"))) in page, address
    assert f'<span class="code">{permission.value}</span>' in page and english.text("web.administration.scope.named.server") in page
  for address, data in changes:
    answer = viewer.post(address, data=data, headers=origin)
    assert answer.status_code == 403 and heading in text(answer), (address, data)
  assert everythingIn(operator) == before


def testTheRefusalPageIsInThePersonsLanguageAndSaysWhere(location):
  viewer = signedIn(location, "viewer")
  arabic = translatorFor("ar")
  page = text(viewer.get("/administration/accounts?locale=ar"))
  assert '<html lang="ar" dir="rtl">' in page and arabic.text("web.refused.heading") in page
  assert arabic.text("web.administration.permission.manageAccess") in page and arabic.text("web.administration.scope.named.server") in page
  assert english.text("web.refused.heading") not in page

  Workspace.open(location).setPreferredLocale("viewer", "fr")
  french = translatorFor("fr")
  change = {"action": "set", "key": "analysis.meanComparison", "value": "lsd"}
  refused = viewer.post(f"/administration/settings?scope=trial:{trialCode}", data=change, headers=origin)
  page = text(refused)
  assert refused.status_code == 403 and '<html lang="fr" dir="ltr">' in page
  assert str(escape(french.text("web.refused.heading"))) in page
  assert str(escape(french.text("web.administration.permission.changeSettings"))) in page
  assert french.text("web.administration.scope.named.trial", name=trialCode) in page
  assert ">viewer</dd>" in page


def testAThingThatIsNotThereIsThePageForItAndTheAPIKeepsItsJSON(location):
  operator = Workspace.open(location)
  admin = signedIn(location, "admin")
  heading = english.text("web.notFound.heading")
  for address, said in (("/administration/accounts/nobody", english.text("web.administration.unknown.account", name="nobody")),
                        ("/administration/groups/show?name=nobody", english.text("web.administration.unknown.group", name="nobody")),
                        ("/administration/providers/nobody", english.text("web.administration.unknown.provider", name="nobody")),
                        ("/administration/providers/add/telepathy", english.text("web.administration.unknown.providerKind", name="telepathy")),
                        ("/administration/workloads/nobody", english.text("web.administration.unknown.workload", name="nobody")),
                        ("/administration/tasks/add/nothing", english.text("web.administration.unknown.taskKind", name="nothing")),
                        ("/administration/tasks/delete/nothing", "task 'nothing' not found"),
                        ("/tasks/nothing", "task 'nothing' not found"),
                        ("/trials/NOPE", "trial 'NOPE' not found"),
                        ("/nowhere/at/all", english.text("web.notFound.intro"))):
    answer = admin.get(address)
    page = text(answer)
    assert answer.status_code == 404 and answer.mimetype == "text/html", address
    assert heading in page and str(escape(said)) in page and '<header class="masthead">' in page, address
  french = text(admin.get("/administration/accounts/nobody?locale=fr"))
  assert str(escape(translatorFor("fr").text("web.administration.unknown.account", name="nobody"))) in french

  _, session = operator.signIn("viewer", password, "test")
  token = operator.actingAs(operator.actorForSession(session, "test")).issueAPIToken("script", 1)
  bearer = {"Authorization": f"Bearer {token}"}
  api = createApp(location).test_client()
  refused = api.delete(f"/api/trials/{trialCode}", headers=bearer)
  assert refused.status_code == 403 and refused.mimetype == "application/json"
  assert json.loads(refused.get_data()) == {"error": f"viewer may not manageTrials at trial:{trialCode}"}
  missing = api.get("/api/trials/NOPE", headers=bearer)
  assert missing.status_code == 404 and json.loads(missing.get_data()) == {"error": "trial 'NOPE' not found"}
  unknown = api.get("/api/nowhere", headers=bearer)
  assert unknown.status_code == 404 and '<header class="masthead">' not in text(unknown)


def testAVisitorIsSentToSignInAndComesBackToWhereTheyWereGoing(location):
  visitor = createApp(location).test_client()
  for address in ("/administration/assignments", "/administration/providers/campus"):
    asked = visitor.get(address)
    assert asked.status_code == 302 and asked.headers["Location"] == f"/signin?next={address}"
  posted = visitor.post("/administration/groups", data={"name": "uninvited"}, headers=origin)
  assert posted.status_code == 302 and posted.headers["Location"] == "/signin?next=/administration/groups"
  assert [group.name for group in Workspace.open(location).groups()] == ["team"]
  back = visitor.post("/signin?next=/administration/providers/campus", data={"userName": "admin", "password": password}, headers=origin)
  assert back.status_code == 302 and back.headers["Location"] == "/administration/providers/campus"
  assert visitor.get("/administration/providers/campus").status_code == 200


def testAChangeFromAnotherSiteIsRefusedOnEveryFormAndMadeFromThisOne(location):
  operator = Workspace.open(location)
  admin = signedIn(location, "admin")
  before = everythingIn(operator)
  for address, data in changes:
    for headers in ({}, {"Origin": "http://evil.example"}, {"Referer": "http://evil.example/administration"}):
      answer = admin.post(address, data=data, headers=headers)
      assert answer.status_code == 403, (address, headers)
      assert text(answer) == "refused: a change must come from this site's own pages"
  assert everythingIn(operator) == before
  for address, data in changes:
    answer = admin.post(address, data=data, headers=origin)
    assert answer.status_code == (200 if data.get("action") == "token" else 302), (address, data, text(answer))
  after = everythingIn(operator)
  assert [now != then for now, then in zip(after, before)] == [True] * len(before)


def testEveryPageRendersInEveryLanguageAndArabicRightToLeft(location):
  admin = signedIn(location, "admin")
  arabic = translatorFor("ar")
  for address in [*guardedPages, *openPages, "/administration/providers/add/samlFederation"]:
    for locale in availableLocales():
      answer = admin.get(address + ("&" if "?" in address else "?") + f"locale={locale}")
      page = text(answer)
      assert answer.status_code == 200, (address, locale)
      assert f'<html lang="{locale}" dir="{"rtl" if locale == "ar" else "ltr"}">' in page, (address, locale)
      if locale == "ar":
        assert arabic.text("web.administration.heading") in page and arabic.text("web.locale.draftNotice") in page, address
        assert f'aria-label="{arabic.text("web.administration.heading")}"' in page, address
