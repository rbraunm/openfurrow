# SPDX-License-Identifier: Apache-2.0
"""Adding and deleting scheduled tasks on the web (worklist GOV-6 and GOV-7; decision 0041): a task of a kind with
the form its parameters model makes, and deleting one after a confirmation page, unless a feature keeps it or a run
of it is under way."""

import pytest
from markupsafe import escape

import taskKindsForTests  # noqa: F401
from openIDConnectStandIn import loopbackCertificates
from openfurrow import Workspace
from openfurrow.i18n import translatorFor
from openfurrow.identity.providers import Provider
from openfurrow.tasks.kinds import registeredKinds
from openfurrow.tasks.model import TaskError

from administrationHelpers import audited, formWith, origin, seededStore, signedIn, text

english = translatorFor("en-US")
server = "https://openfurrow.example.org"


@pytest.fixture
def location(newStore, validPackageDict):
  return seededStore(newStore, validPackageDict)


def shown(written: str) -> str:
  return str(escape(written))


def testATaskOfAKindIsAddedWithTheFormItsParametersMake(location):
  operator = Workspace.open(location)
  admin = signedIn(location, "admin")
  assert 'href="/administration/tasks/add"' in text(admin.get("/tasks"))
  kinds = text(admin.get("/administration/tasks/add"))
  assert [kind.name for kind in operator.taskKinds()] == [kind.name for kind in registeredKinds()]
  for kind in registeredKinds():
    assert f'href="/administration/tasks/add/{kind.name}"' in kinds and kind.defaultSchedule in kinds
    form = formWith(text(admin.get(f"/administration/tasks/add/{kind.name}")), "name")
    assert list(form) == ["name", *kind.parameters.model_fields]

  address = "/administration/tasks/add/testEcho"
  empty = admin.post(address, data={"name": "greeting", "message": ""}, headers=origin)
  assert empty.status_code == 400 and shown(english.text("web.administration.form.needsValue", field="message")) in text(empty)
  assert formWith(text(empty), "name") == {"name": "greeting", "message": ""}
  badName = admin.post(address, data={"name": "Greeting Task", "message": "hello"}, headers=origin)
  assert badName.status_code == 400 and shown("'Greeting Task' is not a task name") in text(badName)
  assert formWith(text(badName), "name") == {"name": "Greeting Task", "message": "hello"}
  assert operator.tasks() == []

  added = admin.post(address, data={"name": "greeting", "message": "hello"}, headers=origin)
  assert added.status_code == 302 and added.headers["Location"] == "/tasks/greeting"
  task = operator.task("greeting")
  assert (task.kind, task.parameters, task.schedule, task.enabled, task.ownerProvider) == (
    "testEcho", {"message": "hello"}, "*/10 * * * *", True, None)
  assert audited(operator, "task.") == [("admin", "task.create", {"task": "greeting", "kind": "testEcho",
                                                                 "parameters": {"message": "hello"}})]
  again = admin.post(address, data={"name": "greeting", "message": "hello"}, headers=origin)
  assert again.status_code == 400 and shown("task 'greeting' already exists") in text(again)

  notANumber = admin.post("/administration/tasks/add/testSleep", data={"name": "nap", "seconds": "a while"}, headers=origin)
  assert notANumber.status_code == 400 and "a testSleep task does not take" in text(notANumber)
  assert formWith(text(notANumber), "name") == {"name": "nap", "seconds": "a while"}
  french = admin.post("/administration/tasks/add/testSleep?locale=fr", data={"name": "nap", "seconds": "1,5"}, headers=origin)
  assert french.status_code == 302 and operator.task("nap").parameters == {"seconds": 1.5}
  assert audited(operator, "task.create")[0] == ("admin", "task.create", {"task": "nap", "kind": "testSleep",
                                                                           "parameters": {"seconds": 1.5}})
  assert admin.post("/administration/tasks/add/testFail", data={"name": "failing"}, headers=origin).status_code == 302
  assert operator.task("failing").parameters == {}


def testATaskIsDeletedAfterAConfirmationPageUnlessAFeatureKeepsItOrARunIsUnderWay(location, tmp_path):
  operator = Workspace.open(location)
  operator.createTask("greeting", "testEcho", {"message": "hello"})
  admin = signedIn(location, "admin")
  assert 'href="/administration/tasks/delete/greeting"' in text(admin.get("/tasks/greeting"))
  confirm = admin.get("/administration/tasks/delete/greeting")
  assert confirm.status_code == 200 and shown(english.text("web.administration.confirm.task.warning")) in text(confirm)
  assert [task.name for task in operator.tasks()] == ["greeting"]

  operator.runTaskNow("greeting")
  running = admin.post("/administration/tasks/delete/greeting", headers=origin)
  assert running.status_code == 400 and shown("task 'greeting' has a run requested or running") in text(running)
  assert [task.name for task in operator.tasks()] == ["greeting"]

  operator.createTask("other", "testEcho", {"message": "again"})
  deleted = admin.post("/administration/tasks/delete/other", headers=origin)
  assert deleted.status_code == 302 and deleted.headers["Location"] == "/tasks"
  assert [task.name for task in operator.tasks()] == ["greeting"]
  assert audited(operator, "task.delete") == [("admin", "task.delete", {"task": "other", "kind": "testEcho",
                                                                         "parameters": {"message": "again"}})]
  assert admin.get("/administration/tasks/delete/other").status_code == 404

  certificate = loopbackCertificates(tmp_path)[0].read_text(encoding="ascii")
  operator.addProvider(Provider.of("fed", "samlFederation", {
    "mdqURL": "https://mdq.federation.example.org", "signingCertificate": certificate,
    "discoveryAggregate": {"url": "https://federation.example.org/aggregate.xml", "signingCertificate": certificate},
    "entityID": f"{server}/saml", "returnURL": f"{server}/signin/with/fed/return", "subjectAttribute": "subjectID",
    "organizationName": "Example Station", "informationURL": f"{server}/about",
    "privacyStatementURL": f"{server}/privacy", "technicalContact": "it@example.org"}))
  kept = english.text("web.administration.confirm.task.kept", provider="fed")
  taskPage = text(admin.get("/tasks/federationRefresh-fed"))
  assert kept in taskPage and "/administration/tasks/delete/federationRefresh-fed" not in taskPage
  confirmKept = text(admin.get("/administration/tasks/delete/federationRefresh-fed"))
  assert kept in confirmKept and 'class="button button-danger"' not in confirmKept
  refused = admin.post("/administration/tasks/delete/federationRefresh-fed", headers=origin)
  assert refused.status_code == 400 and shown("task 'federationRefresh-fed' is kept for the identity provider 'fed'") in text(refused)
  assert [task.name for task in operator.tasks()] == ["federationRefresh-fed", "greeting"]
  with pytest.raises(TaskError, match="is kept for the identity provider 'fed'"):
    operator.deleteTask("federationRefresh-fed")
