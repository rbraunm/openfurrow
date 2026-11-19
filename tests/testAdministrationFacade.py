# SPDX-License-Identifier: Apache-2.0
"""What the facade gained for the administration pages (worklist GOV-6), each with its permission: where a permission
is held, a check a page can ask for, deleting a group and a task, an account's linked identities, the task kinds, and
the audit log read at a place."""

import datetime

import pytest

import taskKindsForTests  # noqa: F401
from openfurrow import Workspace
from openfurrow.identity import IdentityError, Permission, RoleAssignment, RoleDefinition
from openfurrow.identity.providers import Provider
from openfurrow.retention import retentionTaskName
from openfurrow.workspace import EventFilter, NotFoundError, NotPermitted

from administrationHelpers import audited, held, password, seededStore, trialCode
from storeHelpers import standardPath

placeScope = f"place:{standardPath}"
trialScope = f"trial:{trialCode}"


@pytest.fixture
def location(newStore, validPackageDict):
  return seededStore(newStore, validPackageDict)


def acting(operator: Workspace, userName: str) -> Workspace:
  _, token = operator.signIn(userName, password, "web")
  return operator.actingAs(operator.actorForSession(token, "web"))


def testWhereAPermissionIsHeldIsToldServerFirstAndACheckNamesWhatIsMissing(location):
  operator = Workspace.open(location)
  operator.createGroup("team")
  operator.setMembership("team", "viewer", True)
  operator.defineRole(RoleDefinition(roleCode="auditor", name="Auditor", permissions=[Permission.viewAudit]))
  operator.assignRole(RoleAssignment(roleCode="trialManager", scope=trialScope, userName="viewer"))
  operator.assignRole(RoleAssignment(roleCode="trialManager", scope=placeScope, groupName="team"))
  operator.assignRole(RoleAssignment(roleCode="auditor", scope="place:station", userName="viewer"))
  viewer = acting(operator, "viewer")
  assert operator.scopesGranting(Permission.changeSettings) == ["server"]
  assert acting(operator, "admin").scopesGranting(Permission.changeSettings) == ["server"]
  assert viewer.scopesGranting(Permission.changeSettings) == [placeScope, trialScope]
  assert viewer.scopesGranting(Permission.view) == ["server", placeScope, trialScope]
  assert viewer.scopesGranting(Permission.viewAudit) == ["place:station"]
  assert viewer.scopesGranting(Permission.manageAccess) == []

  viewer.require(Permission.changeSettings, trialScope)
  viewer.require(Permission.viewAudit, placeScope)
  with pytest.raises(NotPermitted, match="^viewer may not changeSettings at server$") as refused:
    viewer.require(Permission.changeSettings, "server")
  assert (refused.value.permission, refused.value.scope) == (Permission.changeSettings, "server")
  with pytest.raises(NotPermitted, match="^viewer may not viewAudit at server$"):
    viewer.auditEvents()
  assert [event.action for event in viewer.auditEvents(trialScope)] == ["role.assign", "trial.add"]

  operator.setAccountActive("viewer", False)
  assert viewer.scopesGranting(Permission.view) == []


def testTheAuditLogAtAPlaceIsItsOwnItsPlacesAndItsTrialsAndNoNeighbours(location):
  operator = Workspace.open(location)
  operator.addPlace(None, "station2", "A second station")
  operator.setSetting(trialScope, "analysis.meanComparison", "lsd")
  operator.setSetting("place:station2", "analysis.meanComparison", "lsd")
  everything = operator.auditEvents(limit=1000)

  def scopes(found) -> list[str]:
    return [event.scope for event in found]

  inStation = operator.auditEvents("place:station")
  assert scopes(inStation) == [trialScope, trialScope, placeScope, "place:station/trials", "place:station"]
  assert [event.action for event in inStation][:2] == ["setting.set", "trial.add"]
  assert scopes(operator.auditEvents("place:station2")) == ["place:station2", "place:station2"]
  assert scopes(operator.auditEvents(trialScope)) == [trialScope, trialScope]
  assert operator.auditEvents("server", limit=1000) == everything
  assert scopes(operator.auditEvents("place:station", chosen=EventFilter(action="place."))) == [
    placeScope, "place:station/trials", "place:station"]
  moment = datetime.datetime.now(datetime.UTC)
  assert operator.auditEvents(chosen=EventFilter(since=moment + datetime.timedelta(hours=1))) == []
  assert operator.auditEvents(limit=1000, chosen=EventFilter(until=moment + datetime.timedelta(hours=1))) == everything
  with pytest.raises(ValueError, match="a moment carries its time zone"):
    operator.auditEvents(chosen=EventFilter(since=datetime.datetime(2026, 1, 1)))
  with pytest.raises(NotFoundError, match="no place 'nowhere'"):
    operator.auditEvents("place:nowhere")


def testAGroupATaskAndTheirReadsBelongToThoseWhoManageThem(location):
  operator = Workspace.open(location)
  operator.createGroup("team")
  operator.setMembership("team", "viewer", True)
  operator.assignRole(RoleAssignment(roleCode="analyst", scope=placeScope, groupName="team"))
  operator.addProvider(Provider.of("campus", "scim", {"baseURL": "https://openfurrow.example.org/scim/campus/v2"}))
  operator.linkIdentity("campus", "campus-user-1", "viewer")
  operator.createTask("echo", "testEcho", {"message": "hello"})
  viewer = acting(operator, "viewer")
  for attempt, permission in ((lambda: viewer.deleteGroup("team"), "manageAccess"),
                              (lambda: viewer.linkedIdentities("viewer"), "manageAccess"),
                              (lambda: viewer.deleteTask("echo"), "manageTasks"),
                              (viewer.taskKinds, "manageTasks")):
    with pytest.raises(NotPermitted, match=f"^viewer may not {permission} at server$"):
      attempt()
  assert [group.name for group in operator.groups()] == ["team"]
  assert [task.name for task in operator.tasks()] == ["echo", retentionTaskName]

  assert [(linked.providerName, linked.subject) for linked in operator.linkedIdentities("viewer")] == [("campus", "campus-user-1")]
  assert operator.linkedIdentities("admin") == []
  with pytest.raises(IdentityError, match="no account 'nobody'"):
    operator.linkedIdentities("nobody")
  assert "testEcho" in [kind.name for kind in operator.taskKinds()]

  with pytest.raises(IdentityError, match="no group 'nobody'"):
    operator.deleteGroup("nobody")
  admin = acting(operator, "admin")
  admin.deleteGroup("team")
  assert operator.groups() == [] and [given for given in held(operator) if given[3] is not None] == []
  assert audited(operator, "group.delete") == [("admin", "group.delete", {
    "group": "team", "roles": [{"roleCode": "analyst", "scope": placeScope}]})]
  assert viewer.permissionsAt(trialScope) == frozenset({Permission.view})

  with pytest.raises(NotFoundError, match="task 'nothing' not found"):
    operator.deleteTask("nothing")
  admin.deleteTask("echo")
  assert [task.name for task in operator.tasks()] == [retentionTaskName] and audited(operator, "task.delete")[0][0] == "admin"
  with pytest.raises(IdentityError, match="role 'empty' needs a permission"):
    operator.defineRole(RoleDefinition(roleCode="empty", name="Empty", permissions=[]))
