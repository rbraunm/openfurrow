# SPDX-License-Identifier: Apache-2.0
"""Accounts, roles, permissions and the audit log in the facade (decisions 0036 to 0038)."""

import hashlib

import pytest

from openfurrow import TrialPackage, Workspace
from openfurrow.identity import Actor, ActorKind, IdentityError, Permission, RoleAssignment, RoleDefinition
from openfurrow.identity.passwords import hashPassword, passwordMatches
from openfurrow.schema.observation import Observation
from openfurrow.store import NotFoundError
from openfurrow.workspace import NotPermitted

from storeHelpers import standardPath, standardStudy

password = "correct horse battery"


@pytest.fixture
def store(newStore, validPackageDict):
  operator = Workspace.create(newStore("i"))
  standardStudy(operator)
  operator.addPlace("station/trials", "other", "Other")
  operator.addPackage(TrialPackage.model_validate(validPackageDict), standardPath)
  for userName in ("ana", "ben", "chen"):
    operator.createAccount(userName, userName.title(), None, password)
  return operator


def acting(store, userName):
  account, token = store.signIn(userName, password, "web")
  return store.actingAs(store.actorForSession(token, "web"))


def testPasswordsAreScryptAndChecked():
  stored = hashPassword(password)
  assert stored.startswith("scrypt$32768$8$1$")
  assert passwordMatches(password, stored) and not passwordMatches(password + "!", stored)
  assert hashPassword(password) != stored
  with pytest.raises(IdentityError, match="a password is 12 to 256 characters, got 5"):
    hashPassword("short")


def testSignInRefusesWithOneMessageAndRecordsIt(store):
  for userName, attempt in (("ana", "wrong password!!"), ("nobody", password)):
    with pytest.raises(IdentityError, match="^the user name or the password is wrong$"):
      store.signIn(userName, attempt, "web")
  store.setAccountActive("ben", False)
  with pytest.raises(IdentityError, match="^the user name or the password is wrong$"):
    store.signIn("ben", password, "web")
  refused = [e for e in store.auditEvents() if e.action == "signIn.refused"]
  assert [e.detail["userName"] for e in refused] == ["ben", "nobody", "ana"]
  assert all(password not in str(e.detail) for e in store.auditEvents())


def testARoleHoldsBelowWhereItIsGiven(store):
  store.assignRole(RoleAssignment(roleCode="dataCollector", scope="place:station/trials/study", userName="ana"))
  ana = acting(store, "ana")
  assert ana.permissionsAt("trial:ESV-2025-01") == frozenset({Permission.view, Permission.enterValues})
  assert ana.permissionsAt("place:station/trials/other") == frozenset()
  assert [code for code, _ in ana.listTrials()] == ["ESV-2025-01"]
  assert [place.path for place in ana.places()] == ["station", "station/trials", "station/trials/study"]
  plot = ana.layoutFor("ESV-2025-01").plots[0].plotNumber
  ana.recordValues("ESV-2025-01", "YIELD", [Observation(plotNumber=plot, assessmentCode="YIELD", value=5000.0)])
  with pytest.raises(NotPermitted, match="ana may not changeSettings at trial:ESV-2025-01"):
    ana.setSetting("trial:ESV-2025-01", "analysis.significanceLevel", 0.01)
  with pytest.raises(NotPermitted, match="ana may not manageTrials at trial:ESV-2025-01"):
    ana.deleteTrial("ESV-2025-01")


def testWithoutViewATrialIsNotFoundLikeOneThatDoesNotExist(store):
  ben = acting(store, "ben")
  assert ben.listTrials() == [] and ben.places() == []
  for code in ("ESV-2025-01", "NO-SUCH-TRIAL"):
    with pytest.raises(NotFoundError, match=f"trial '{code}' not found"):
      ben.loadPackage(code)


def testGroupsAndCustomRolesGivePermissions(store):
  store.createGroup("Field team")
  store.setMembership("Field team", "chen", True)
  store.defineRole(RoleDefinition(roleCode="importer", name="Importer",
                                  permissions=frozenset({Permission.view, Permission.importValues})))
  store.assignRole(RoleAssignment(roleCode="importer", scope="server", groupName="Field team"))
  chen = acting(store, "chen")
  assert chen.permissionsAt("trial:ESV-2025-01") == frozenset({Permission.view, Permission.importValues})
  store.setMembership("Field team", "chen", False)
  assert chen.permissionsAt("trial:ESV-2025-01") == frozenset()
  with pytest.raises(IdentityError, match="role 'importer' is still given to someone"):
    store.deleteRole("importer")


def testDeactivatingEndsSessionsAndTokens(store):
  store.assignRole(RoleAssignment(roleCode="viewer", scope="server", userName="ana"))
  _, session = store.signIn("ana", password, "web")
  ana = store.actingAs(store.actorForSession(session, "web"))
  token = ana.issueAPIToken("script", 30)
  assert store.actorForAPIToken(token, "api").userName == "ana"
  store.setAccountActive("ana", False)
  for check in (lambda: store.actorForSession(session, "web"), lambda: store.actorForAPIToken(token, "api")):
    with pytest.raises(IdentityError, match="the token is not valid"):
      check()


def testOnlyHashesOfTokensAreStored(store):
  _, token = store.signIn("ana", password, "web")
  from sqlalchemy import select
  from openfurrow.store.database import AuthTokenRow
  with store._engine.connect() as connection:
    stored = connection.execute(select(AuthTokenRow.tokenHash)).scalars().all()
  assert stored == [hashlib.sha256(token.encode()).hexdigest()]


def testSignInByAccountsNeedsAnAdministratorFirst(store):
  with pytest.raises(IdentityError, match="needs an active account that is administrator at the server first"):
    store.setSetting("server", "identity.signInMode", "accounts")
  assert store.signInMode().value == "open"
  store.assignRole(RoleAssignment(roleCode="administrator", scope="server", userName="ana"))
  store.setSetting("server", "identity.signInMode", "accounts")
  assert store.signInMode().value == "accounts"


def testEveryChangeIsAuditedWithWhoAndWhatChanged(store):
  store.assignRole(RoleAssignment(roleCode="trialManager", scope="place:station", userName="ana"))
  ana = acting(store, "ana")
  plot = ana.layoutFor("ESV-2025-01").plots[0].plotNumber
  ana.recordValues("ESV-2025-01", "YIELD", [Observation(plotNumber=plot, assessmentCode="YIELD", value=5000.0)])
  ana.recordValues("ESV-2025-01", "YIELD", [Observation(plotNumber=plot, assessmentCode="YIELD", value=5100.0)])
  ana.setSetting("trial:ESV-2025-01", "analysis.significanceLevel", 0.01)
  latest = store.auditEvents("trial:ESV-2025-01")
  assert [(e.action, e.actorName, e.surface) for e in latest[:3]] == [
    ("setting.set", "ana", "web"), ("values.record", "ana", "web"), ("values.record", "ana", "web"),
  ]
  assert latest[1].detail == {"assessment": "YIELD", "changes": [{"plot": plot, "subsample": None, "before": 5000.0, "after": 5100.0}]}
  assert latest[0].detail["before"] == {"value": 0.05, "source": "default"}
  first = store.auditEvents()[-1]
  assert (first.action, first.actorKind, first.surface) == ("place.add", ActorKind.operator.value, "library")
  with pytest.raises(NotPermitted, match="ana may not viewAudit at server"):
    ana.auditEvents()
