# SPDX-License-Identifier: Apache-2.0
"""What the administration pages' tests share: a store with sign-in by accounts, an administrator and a viewer, a
signed-in browser, and readers of what the facade and the audit log then hold."""

from html.parser import HTMLParser

from openfurrow import TrialPackage, Workspace
from openfurrow.identity import RoleAssignment
from openfurrow.service import createApp

from storeHelpers import standardPath, standardStudy

password = "correct horse battery"
origin = {"Origin": "http://localhost"}
trialCode = "ESV-2025-01"


def seededStore(newStore, validPackageDict) -> str:
  location = newStore("administration")
  operator = Workspace.create(location)
  standardStudy(operator)
  operator.addPackage(TrialPackage.model_validate(validPackageDict), standardPath)
  operator.createAccount("admin", "Administrator", None, password)
  operator.createAccount("viewer", "Viewer", None, password)
  operator.assignRole(RoleAssignment(roleCode="administrator", scope="server", userName="admin"))
  operator.assignRole(RoleAssignment(roleCode="viewer", scope="server", userName="viewer"))
  operator.setSetting("server", "identity.signInMode", "accounts")
  return location


def signedIn(location: str, userName: str):
  client = createApp(location).test_client()
  answer = client.post("/signin", data={"userName": userName, "password": password}, headers=origin)
  assert answer.status_code == 302
  return client


def text(response) -> str:
  return response.get_data(as_text=True)


def audited(operator: Workspace, prefix: str) -> list[tuple]:
  """The audit events whose action starts with a prefix, newest first, as (who, action, detail)."""
  return [(event.actorName, event.action, event.detail) for event in operator.auditEvents()
          if event.action.startswith(prefix)]


def held(operator: Workspace) -> list[tuple]:
  """Every role given, as (role, scope, account, group, workload rule)."""
  return [(given.roleCode, given.scope, given.userName, given.groupName, given.ruleName) for given in operator.assignments()]


class _PostedForms(HTMLParser):
  """The forms of a page that post, each as the fields a browser would send before anything is typed: what the
  text fields and text areas hold, the options chosen, and the boxes ticked."""

  def __init__(self) -> None:
    super().__init__()
    self.forms: list[dict[str, str]] = []
    self._form: dict[str, str] | None = None
    self._select: str | None = None
    self._textarea: str | None = None

  def handle_starttag(self, tag, attributes):
    given = dict(attributes)
    if tag == "form":
      self._form = {} if given.get("method") == "post" else None
      if self._form is not None:
        self.forms.append(self._form)
    elif self._form is None:
      return
    elif tag == "input" and "name" in given:
      if given.get("type") not in ("checkbox", "radio") or "checked" in given:
        self._form[given["name"]] = given.get("value", "")
    elif tag == "select":
      self._select = given["name"]
    elif tag == "option" and self._select is not None:
      if "selected" in given or self._select not in self._form:
        self._form[self._select] = given.get("value", "")
    elif tag == "textarea":
      self._textarea = given["name"]
      self._form[self._textarea] = ""

  def handle_endtag(self, tag):
    if tag == "form":
      self._form = None
    elif tag == "select":
      self._select = None
    elif tag == "textarea":
      self._textarea = None

  def handle_data(self, data):
    if self._textarea is not None and self._form is not None:
      self._form[self._textarea] += data


def formWith(page: str, field: str) -> dict[str, str]:
  """The fields of the page's posting form that has a field of this name, as a browser would send them untouched."""
  parser = _PostedForms()
  parser.feed(page)
  found = [form for form in parser.forms if field in form]
  assert len(found) == 1, f"{len(found)} posting forms have a field '{field}'"
  return found[0]
