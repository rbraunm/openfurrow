# SPDX-License-Identifier: Apache-2.0
"""The administration area of the web interface (worklist GOV-6): who is offered which section, and the pages for
accounts, groups, roles and their assignments, settings by scope and the sign-in mode. Each change is made through
the page, read back from the facade and found in the audit log."""

import re

import pytest
from markupsafe import escape
from sqlalchemy.orm import Session

from openfurrow import Workspace
from openfurrow.i18n import translatorFor
from openfurrow.identity import IdentityError, Permission, RoleAssignment, RoleDefinition, SignInMode, builtInRoles
from openfurrow.identity.providers import Provider
from openfurrow.service import createApp
from openfurrow.settings import SettingScope, allowedValues, definitions, jsonValue
from openfurrow.store.database import createDatabase
from openfurrow.store.providers import mirroredGroup

from administrationHelpers import audited, held, origin, password, seededStore, signedIn, text, trialCode
from storeHelpers import standardPath

english = translatorFor("en-US")
sectionAddresses = ["/administration/accounts", "/administration/groups", "/administration/roles", "/administration/assignments", "/administration/settings",
                    "/administration/sign-in-mode", "/administration/providers", "/administration/workloads", "/tasks",
                    "/administration/retention", "/administration/audit"]
placeScope = f"place:{standardPath}"
trialScope = f"trial:{trialCode}"
scimSettings = {"baseURL": "https://openfurrow.example.org/scim/campus/v2", "groups": "mirror"}


@pytest.fixture
def location(newStore, validPackageDict):
  return seededStore(newStore, validPackageDict)


def shown(written: str) -> str:
  """A text as a page carries it."""
  return str(escape(written))


def accountNamed(operator: Workspace, userName: str):
  return next(account for account in operator.accounts() if account.userName == userName)


def groupNamed(operator: Workspace, name: str):
  return next(group for group in operator.groups() if group.name == name)


def settingsAt(operator: Workspace, scope: str) -> dict:
  return {setting.key: (jsonValue(setting.key, setting.value), setting.source) for setting in operator.effectiveSettings(scope)}


def card(page: str, key: str) -> str:
  """The part of the settings page that is one setting's."""
  start = page.index(f'dir="ltr">{key}</h2>')
  return page[start:page.index("</article>", start)]


# ---- who is offered the area ------------------------------------------------------

def testTheAreaIsLinkedFromTheMastheadForThoseWhoMayUseSomeOfIt(location):
  admin = signedIn(location, "admin")
  assert 'href="/administration"' in text(admin.get("/"))
  index = text(admin.get("/administration"))
  assert [address for address in sectionAddresses if f'href="{address}"' in index] == sectionAddresses
  viewer = signedIn(location, "viewer")
  assert 'href="/administration"' not in text(viewer.get("/"))
  nothing = viewer.get("/administration")
  assert nothing.status_code == 404 and english.text("web.administration.index.nothing") in text(nothing)


def testAPersonHoldingAPermissionAtAPlaceOnlyIsOfferedItsPagesAndRefusedAtTheServer(location):
  operator = Workspace.open(location)
  operator.createAccount("lead", "Lead", None, password)
  operator.defineRole(RoleDefinition(roleCode="auditor", name="Auditor", permissions=[Permission.viewAudit]))
  for roleCode in ("trialManager", "auditor"):
    operator.assignRole(RoleAssignment(roleCode=roleCode, scope=placeScope, userName="lead"))
  lead = signedIn(location, "lead")
  assert 'href="/administration"' in text(lead.get("/"))
  index = text(lead.get("/administration"))
  assert [address for address in sectionAddresses if f'href="{address}"' in index] == ["/administration/settings", "/administration/audit"]

  change = {"action": "set", "key": "analysis.meanComparison", "value": "tukeyHSD"}
  assert lead.post(f"/administration/settings?scope={trialScope}", data=change, headers=origin).status_code == 302
  assert settingsAt(operator, trialScope)["analysis.meanComparison"] == ("tukeyHSD", trialScope)
  atServer = lead.post("/administration/settings?scope=server", data=change, headers=origin)
  assert atServer.status_code == 403 and english.text("web.refused.heading") in text(atServer)
  assert settingsAt(operator, "server")["analysis.meanComparison"] == ("protectedLSD", "default")
  readOnly = text(lead.get("/administration/settings?scope=server"))
  assert english.text("web.administration.settings.readOnly") in readOnly and 'name="action" value="set"' not in readOnly

  audit = lead.get("/administration/audit")
  page = text(audit)
  assert audit.status_code == 200 and f'<option value="{placeScope}" selected>' in page
  assert "setting.set" in page and "trial.add" in page and "account.create" not in page
  assert lead.get("/administration/audit?scope=server").status_code == 403
  assert lead.get("/administration/accounts").status_code == 403


# ---- accounts ------------------------------------------------------------------------

def testAnAccountIsAddedAndTheFormKeepsWhatWasTypedButNeverThePassword(location):
  operator = Workspace.open(location)
  admin = signedIn(location, "admin")
  typed = {"userName": "Ana.Lopez", "displayName": "Ana Lopez", "email": "ana@example.org", "password": "tiny-Zq7"}
  refused = admin.post("/administration/accounts", data=typed, headers=origin)
  page = text(refused)
  assert refused.status_code == 400 and "a password is 12 to 256 characters, got 8" in page
  assert 'value="Ana.Lopez"' in page and 'value="Ana Lopez"' in page and 'value="ana@example.org"' in page
  assert "tiny-Zq7" not in page
  assert [account.userName for account in operator.accounts()] == ["admin", "viewer"]

  added = admin.post("/administration/accounts", data=typed | {"password": "a long enough password"}, headers=origin)
  assert added.status_code == 302 and added.headers["Location"] == "/administration/accounts/ana.lopez?done=created"
  after = text(admin.get(added.headers["Location"]))
  assert english.text("web.administration.done.created") in after and "a long enough password" not in after
  account = accountNamed(operator, "ana.lopez")
  assert (account.displayName, account.email, account.active) == ("Ana Lopez", "ana@example.org", True)
  assert audited(operator, "account.")[0] == ("admin", "account.create", {"userName": "ana.lopez"})
  assert operator.signIn("ana.lopez", "a long enough password", "test")[0].userName == "ana.lopez"

  provided = {"userName": "sso", "displayName": "Through a provider", "email": "", "password": ""}
  assert admin.post("/administration/accounts", data=provided, headers=origin).status_code == 302
  assert accountNamed(operator, "sso").email is None
  with pytest.raises(IdentityError, match="the user name or the password is wrong"):
    operator.signIn("sso", "", "test")
  listed = text(admin.get("/administration/accounts"))
  assert 'href="/administration/accounts/ana.lopez"' in listed and "Through a provider" in listed
  assert admin.get("/administration/accounts/nobody").status_code == 404


def testAnAccountsPasswordActivityIdentitiesGroupsAndRolesAreChangedOnItsPage(location):
  operator = Workspace.open(location)
  operator.addProvider(Provider.of("campus", "scim", scimSettings))
  operator.createGroup("team")
  admin = signedIn(location, "admin")

  def post(**data):
    return admin.post("/administration/accounts/viewer", data=data, headers=origin)

  assert post(action="password", newPassword="a brand new password").status_code == 302
  short = post(action="password", newPassword="tiny-Zq7")
  assert short.status_code == 400 and "a password is 12 to 256 characters" in text(short) and "tiny-Zq7" not in text(short)

  unconfirmed = post(action="deactivate")
  assert unconfirmed.status_code == 400 and english.text("web.administration.confirmNeeded") in text(unconfirmed)
  assert accountNamed(operator, "viewer").active is True
  assert post(action="deactivate", confirm="yes").status_code == 302
  assert accountNamed(operator, "viewer").active is False
  assert post(action="activate").status_code == 302
  assert accountNamed(operator, "viewer").active is True

  assert post(action="link", provider="campus", subject="campus-user-17").status_code == 302
  assert [(linked.providerName, linked.subject) for linked in operator.linkedIdentities("viewer")] == [("campus", "campus-user-17")]
  again = post(action="link", provider="campus", subject="campus-user-17")
  assert again.status_code == 400 and "that campus identity is already linked" in text(again)
  assert 'value="campus-user-17"' in text(again)

  assert post(action="join", group="team").status_code == 302
  assert groupNamed(operator, "team").members == ["viewer"]
  assert post(action="leave", group="team").status_code == 302
  assert groupNamed(operator, "team").members == []

  assert post(action="give", roleCode="analyst", scope=placeScope).status_code == 302
  assert ("analyst", placeScope, "viewer", None, None) in held(operator)
  nowhere = post(action="give", roleCode="analyst", scope="")
  assert nowhere.status_code == 400 and '<option value="analyst" selected>' in text(nowhere)
  page = text(admin.get("/administration/accounts/viewer"))
  assert "campus-user-17" in page and english.text("web.administration.role.analyst") in page
  assert english.text("web.administration.scope.named.place", name=standardPath) in page
  assert post(action="takeBack", roleCode="analyst", scope=placeScope).status_code == 302
  assert ("analyst", placeScope, "viewer", None, None) not in held(operator)

  byAdmin = [(action, detail) for who, action, detail in reversed(audited(operator, "")) if who == "admin" and action != "signIn"]
  assert byAdmin == [
    ("account.password", {"userName": "viewer"}),
    ("account.active", {"userName": "viewer", "active": False}),
    ("account.active", {"userName": "viewer", "active": True}),
    ("provider.link", {"provider": "campus", "subject": "campus-user-17", "userName": "viewer"}),
    ("group.member", {"group": "team", "userName": "viewer", "member": True}),
    ("group.member", {"group": "team", "userName": "viewer", "member": False}),
    ("role.assign", {"roleCode": "analyst", "scope": placeScope, "userName": "viewer"}),
    ("role.unassign", {"roleCode": "analyst", "scope": placeScope, "userName": "viewer"}),
  ]
  assert operator.signIn("viewer", "a brand new password", "test")[0].userName == "viewer"


# ---- groups --------------------------------------------------------------------------

def testAGroupIsMadeFilledGivenARoleAndDeletedAfterAConfirmationPage(location):
  operator = Workspace.open(location)
  admin = signedIn(location, "admin")
  made = admin.post("/administration/groups", data={"name": "field team"}, headers=origin)
  assert made.status_code == 302 and english.text("web.administration.done.created") in text(admin.get(made.headers["Location"]))
  twice = admin.post("/administration/groups", data={"name": "field team"}, headers=origin)
  assert twice.status_code == 400 and shown("group 'field team' already exists") in text(twice)
  assert 'value="field team"' in text(twice)
  assert [group.name for group in operator.groups()] == ["field team"]

  address = "/administration/groups/show?name=field+team"
  assert admin.post(address, data={"action": "join", "userName": "viewer"}, headers=origin).status_code == 302
  assert groupNamed(operator, "field team").members == ["viewer"]
  given = {"action": "give", "roleCode": "dataCollector", "scope": trialScope}
  assert admin.post(address, data=given, headers=origin).status_code == 302
  assert ("dataCollector", trialScope, None, "field team", None) in held(operator)

  confirm = admin.get("/administration/groups/delete?name=field+team")
  page = text(confirm)
  assert confirm.status_code == 200 and shown(english.text("web.administration.confirm.group.warning")) in page
  assert english.text("web.administration.role.dataCollector") in page and english.text("web.administration.scope.named.trial", name=trialCode) in page
  assert [group.name for group in operator.groups()] == ["field team"]
  assert admin.post("/administration/groups/delete?name=field+team", headers=origin).status_code == 302
  assert operator.groups() == [] and [given for given in held(operator) if given[3] is not None] == []
  assert audited(operator, "group.")[0] == ("admin", "group.delete", {
    "group": "field team", "roles": [{"roleCode": "dataCollector", "scope": trialScope}]})
  assert admin.get(address).status_code == 404


def testAMirroredGroupIsItsProvidersAndShownReadOnly(location):
  operator = Workspace.open(location)
  operator.addProvider(Provider.of("campus", "scim", scimSettings))
  with Session(createDatabase(location, create=False)) as session:
    mirroredGroup(session, "campus", "staff")
    session.commit()
  admin = signedIn(location, "admin")
  address = "/administration/groups/show?name=campus/staff"
  page = text(admin.get(address))
  assert shown(english.text("web.administration.group.mirrored", provider="campus")) in page
  assert 'name="action" value="join"' not in page and "/administration/groups/delete" not in page
  assert 'name="action" value="give"' in page
  assert english.text("web.administration.groups.mirroredFrom", provider="campus") in text(admin.get("/administration/groups"))

  member = admin.post(address, data={"action": "join", "userName": "viewer"}, headers=origin)
  assert member.status_code == 400
  assert shown("group 'campus/staff' is mirrored from campus, which alone sets its members") in text(member)
  deleted = admin.post("/administration/groups/delete?name=campus/staff", headers=origin)
  assert deleted.status_code == 400
  assert shown("group 'campus/staff' is mirrored from campus, which alone removes it") in text(deleted)
  mirrored = groupNamed(operator, "campus/staff")
  assert (mirrored.members, mirrored.providerName) == ([], "campus")

  given = {"action": "give", "roleCode": "viewer", "scope": "server"}
  assert admin.post(address, data=given, headers=origin).status_code == 302
  assert ("viewer", "server", None, "campus/staff", None) in held(operator)


# ---- roles ---------------------------------------------------------------------------

def testTheRolesPageShowsEveryRoleAndPermissionAndDefinesChangesAndDeletesCustomOnes(location):
  operator = Workspace.open(location)
  admin = signedIn(location, "admin")
  page = text(admin.get("/administration/roles"))
  for code in builtInRoles:
    assert english.text(f"web.administration.role.{code}") in page and f'<span class="code">{code}</span>' in page
  for permission in Permission:
    assert page.count(shown(english.text(f"web.administration.permission.{permission.value}"))) >= 2
    assert f'name="permissions" value="{permission.value}"' in page

  def define(**data):
    return admin.post("/administration/roles", data=data, headers=origin)

  bad = define(roleCode="Field Lead", name="Field lead", permissions=["view", "enterValues"])
  badPage = text(bad)
  assert bad.status_code == 400 and shown("'Field Lead' is not a role code") in badPage
  assert 'value="Field Lead"' in badPage and 'value="Field lead"' in badPage
  assert 'name="permissions" value="view" checked' in badPage and 'name="permissions" value="enterValues" checked' in badPage
  assert 'name="permissions" value="viewAudit" checked' not in badPage
  none = define(roleCode="empty", name="Empty")
  assert none.status_code == 400 and shown("role 'empty' needs a permission") in text(none)
  assert set(operator.roles()) == set(builtInRoles)

  assert define(roleCode="fieldLead", name="Field lead", permissions=["view", "enterValues"]).status_code == 302
  role = operator.roles()["fieldLead"]
  assert (role.name, role.permissions) == ("Field lead", frozenset({Permission.view, Permission.enterValues}))
  assert audited(operator, "role.")[0] == ("admin", "role.define", {"role": "fieldLead", "permissions": ["enterValues", "view"]})
  again = define(roleCode="fieldLead", name="Another", permissions=["view"])
  assert again.status_code == 400 and shown(english.text("web.administration.roles.exists", code="fieldLead")) in text(again)
  assert operator.roles()["fieldLead"].name == "Field lead"

  def change(**data):
    return admin.post("/administration/roles/fieldLead", data=data, headers=origin)

  assert change(action="save", name="Field leader", permissions=["view", "enterValues", "importValues"]).status_code == 302
  role = operator.roles()["fieldLead"]
  assert (role.name, role.permissions) == ("Field leader", frozenset({Permission.view, Permission.enterValues,
                                                                      Permission.importValues}))
  operator.assignRole(RoleAssignment(roleCode="fieldLead", scope="server", userName="viewer"))
  unconfirmed = change(action="delete")
  assert unconfirmed.status_code == 400 and english.text("web.administration.confirmNeeded") in text(unconfirmed)
  stillGiven = change(action="delete", confirm="yes")
  assert stillGiven.status_code == 400 and shown("role 'fieldLead' is still given to someone") in text(stillGiven)
  assert "fieldLead" in operator.roles()
  operator.unassignRole(RoleAssignment(roleCode="fieldLead", scope="server", userName="viewer"))
  assert change(action="delete", confirm="yes").status_code == 302
  assert "fieldLead" not in operator.roles()
  assert audited(operator, "role.delete") == [("admin", "role.delete", {"role": "fieldLead"})]
  assert admin.get("/administration/roles/fieldLead").status_code == 404
  assert admin.get("/administration/roles/administrator").status_code == 404


# ---- role assignments ----------------------------------------------------------------

def testARoleIsGivenAndTakenBackWithItsScopeChosenFromTheHierarchy(location):
  operator = Workspace.open(location)
  operator.createGroup("team")
  operator.setSetting("server", "identity.workloadAudience", "https://openfurrow.example.org")
  operator.addWorkloadRule("nightly", "githubActions", {"repository_id": "1"})
  admin = signedIn(location, "admin")
  page = text(admin.get("/administration/assignments"))
  assert '<select id="giveScope" name="scope">' in page
  assert re.findall(r'<option value="((?:server|place:|trial:)[^"]*)"', page) == [
    "server", "place:station", "place:station/trials", placeScope, trialScope]
  for holder in ("user:admin", "user:viewer", "group:team", "rule:nightly"):
    assert f'<option value="{holder}"' in page

  def post(action, holder, scope):
    return admin.post("/administration/assignments", data={"action": action, "holder": holder, "roleCode": "analyst", "scope": scope},
                      headers=origin)

  for holder, scope, expected in (("user:viewer", placeScope, ("analyst", placeScope, "viewer", None, None)),
                                  ("group:team", "server", ("analyst", "server", None, "team", None)),
                                  ("rule:nightly", trialScope, ("analyst", trialScope, None, None, "nightly"))):
    assert post("give", holder, scope).status_code == 302
    assert expected in held(operator)
  assert audited(operator, "role.assign")[0] == ("admin", "role.assign", {
    "roleCode": "analyst", "scope": trialScope, "ruleName": "nightly"})

  unchosen = post("give", "", "server")
  unchosenPage = text(unchosen)
  assert unchosen.status_code == 400 and shown(english.text("web.administration.assignments.chooseHolder")) in unchosenPage
  assert '<option value="analyst" selected>' in unchosenPage and '<option value="server" selected>' in unchosenPage

  assert post("takeBack", "group:team", "server").status_code == 302
  assert ("analyst", "server", None, "team", None) not in held(operator)
  assert audited(operator, "role.unassign") == [("admin", "role.unassign", {
    "roleCode": "analyst", "scope": "server", "groupName": "team"})]
  notGiven = post("takeBack", "group:team", "server")
  assert notGiven.status_code == 400 and shown("role 'analyst' is not given there") in text(notGiven)


# ---- settings ------------------------------------------------------------------------

def testEverySettingIsShownWithItsValueItsSourceAndTheRegistrysChoices(location):
  operator = Workspace.open(location)
  operator.setSetting(placeScope, "analysis.significanceLevel", 0.01)
  admin = signedIn(location, "admin")
  page = text(admin.get(f"/administration/settings?scope={trialScope}"))
  assert re.findall(r'dir="ltr">([A-Za-z.]+)</h2>', page) == sorted(definitions)
  for key, definition in definitions.items():
    shownCard = card(page, key)
    assert shown(english.text(f"web.administration.setting.{key}")) in shownCard
    if key == "identity.signInMode":
      assert 'href="/administration/sign-in-mode"' in shownCard and 'name="action" value="set"' not in shownCard
    elif SettingScope.trial not in definition.scopes:
      assert english.text("web.administration.settings.notAtThisScope") in shownCard and 'name="action" value="set"' not in shownCard
    elif allowedValues(key) is not None:
      assert re.findall(r'<option value="([^"]*)"', shownCard) == allowedValues(key)
    else:
      assert '<input type="text"' in shownCard
  level = card(page, "analysis.significanceLevel")
  assert '<span class="code" dir="ltr">0.01</span>' in level
  assert english.text("web.administration.scope.named.place", name=standardPath) in level
  comparison = card(page, "analysis.meanComparison")
  assert '<span class="code" dir="ltr">protectedLSD</span>' in comparison
  assert english.text("web.administration.settings.source.default") in comparison and '<option value="protectedLSD" selected>' in comparison
  serverPage = text(admin.get("/administration/settings"))
  assert 'name="action" value="set"' in card(serverPage, "tasks.timeZone")


def testASettingIsSetAndClearedAtTheChosenScopeAndARefusedValueStaysInItsField(location):
  operator = Workspace.open(location)
  admin = signedIn(location, "admin")
  address = f"/administration/settings?scope={trialScope}"

  def post(action, key, value=""):
    return admin.post(address, data={"action": action, "key": key, "value": value}, headers=origin)

  assert post("set", "analysis.meanComparison", "tukeyHSD").status_code == 302
  assert settingsAt(operator, trialScope)["analysis.meanComparison"] == ("tukeyHSD", trialScope)
  assert settingsAt(operator, "server")["analysis.meanComparison"] == ("protectedLSD", "default")
  assert audited(operator, "setting.")[0] == ("admin", "setting.set", {
    "key": "analysis.meanComparison", "before": {"value": "protectedLSD", "source": "default"},
    "after": {"value": "tukeyHSD", "source": trialScope}})

  bad = post("set", "analysis.significanceLevel", "2")
  assert bad.status_code == 400 and shown("setting 'analysis.significanceLevel' does not take '2'") in text(bad)
  assert 'name="value" dir="ltr" autocomplete="off" value="2"' in card(text(bad), "analysis.significanceLevel")
  assert settingsAt(operator, trialScope)["analysis.significanceLevel"] == (0.05, "default")

  french = admin.post(address + "&locale=fr", data={"action": "set", "key": "analysis.significanceLevel", "value": "0,01"},
                      headers=origin)
  assert french.status_code == 302 and french.headers["Location"].endswith("locale=fr")
  assert settingsAt(operator, trialScope)["analysis.significanceLevel"] == (0.01, trialScope)
  assert '<span class="code" dir="ltr">0,01</span>' in text(admin.get(address + "&locale=fr"))
  assert post("clear", "analysis.significanceLevel").status_code == 302
  assert settingsAt(operator, trialScope)["analysis.significanceLevel"] == (0.05, "default")
  assert audited(operator, "setting.clear")[0][2]["key"] == "analysis.significanceLevel"

  serverOnly = post("set", "tasks.timeZone", "Africa/Nairobi")
  assert serverOnly.status_code == 400 and shown("setting 'tasks.timeZone' is not set at the trial level") in text(serverOnly)
  elsewhere = admin.post("/administration/settings?scope=server", data={"action": "set", "key": "identity.signInMode", "value": "open"},
                         headers=origin)
  assert elsewhere.status_code == 400 and english.text("web.administration.settings.onItsOwnPage") in text(elsewhere)
  assert operator.signInMode() is SignInMode.accounts
  assert admin.get("/administration/settings?scope=trial:NOPE").status_code == 404
  assert admin.get("/administration/settings?scope=nonsense").status_code == 404


# ---- the sign-in mode ----------------------------------------------------------------

def testTheSignInModeIsSwitchedOnItsPageAndOpeningTheServerIsConfirmed(newStore):
  location = newStore("mode")
  operator = Workspace.create(location)
  everyone = createApp(location).test_client()
  opened = english.text("web.administration.signInMode.current", mode=english.text("web.administration.signInMode.name.open"))
  assert shown(opened) in text(everyone.get("/administration/sign-in-mode"))
  early = everyone.post("/administration/sign-in-mode", data={"mode": "accounts"}, headers=origin)
  assert early.status_code == 400
  assert "needs an active account that is administrator at the server first" in text(early)
  assert 'name="mode" value="accounts" checked' in text(early)
  assert operator.signInMode() is SignInMode.open

  operator.createAccount("admin", "Administrator", None, password)
  operator.assignRole(RoleAssignment(roleCode="administrator", scope="server", userName="admin"))
  assert everyone.post("/administration/sign-in-mode", data={"mode": "accounts"}, headers=origin).status_code == 302
  assert operator.signInMode() is SignInMode.accounts
  asked = everyone.get("/administration/sign-in-mode")
  assert asked.status_code == 302 and asked.headers["Location"] == "/signin?next=/administration/sign-in-mode"

  admin = signedIn(location, "admin")
  unconfirmed = admin.post("/administration/sign-in-mode", data={"mode": "open"}, headers=origin)
  assert unconfirmed.status_code == 400 and english.text("web.administration.confirmNeeded") in text(unconfirmed)
  assert operator.signInMode() is SignInMode.accounts
  assert admin.post("/administration/sign-in-mode", data={"mode": "open", "confirm": "yes"}, headers=origin).status_code == 302
  assert operator.signInMode() is SignInMode.open
  assert [(who, detail["after"]["value"]) for who, _, detail in audited(operator, "setting.set")] == [
    ("admin", "open"), (None, "accounts")]
