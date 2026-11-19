# SPDX-License-Identifier: Apache-2.0
"""What the administration pages share: who may use which section, rendering, the way back after a change, the
hierarchy as the choices of a scope, and the words for a scope, a role and a refusal."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from flask import Response, g, redirect, render_template, request, url_for
from pydantic import ValidationError

from openfurrow.identity.model import Permission, RoleAssignment, SignInMode
from openfurrow.retention import RetentionError
from openfurrow.settings import SettingError, definitions
from openfurrow.store.hierarchy import ScopeError
from openfurrow.workspace import IdentityError, NotFoundError, StoreError, TaskError, Workspace

sectionEndpoints = {
  "accounts": "web.administrationAccounts",
  "groups": "web.administrationGroups",
  "roles": "web.administrationRoles",
  "assignments": "web.administrationAssignments",
  "settings": "web.administrationSettings",
  "signInMode": "web.administrationSignInMode",
  "providers": "web.administrationProviders",
  "workloads": "web.administrationWorkloads",
  "tasks": "web.tasks",
  "retention": "web.administrationRetention",
  "audit": "web.administrationAudit",
}
doneCodes = frozenset({
  "created", "passwordSet", "deactivated", "reactivated", "linked", "joined", "left", "deleted", "defined", "saved",
  "given", "takenBack", "set", "cleared", "added", "enabled", "disabled", "removed", "pruned", "nothingPruned",
})
refusals = (IdentityError, StoreError, TaskError, SettingError, ScopeError, ValidationError, RetentionError)
# A setting names the permission that changes it (decision 0044): the settings page is for whoever holds one of them.
settingPermissions = frozenset(definition.permission for definition in definitions.values())
holderFields = {"user": "userName", "group": "groupName", "rule": "ruleName"}


@dataclass(frozen=True)
class ScopeChoice:
  scope: str
  label: str
  depth: int


class Pages:
  def __init__(self, workspace: Workspace, translatorOf: Callable, contextOf: Callable, localized: Callable,
               momentOf: Callable, levelNameOf: Callable) -> None:
    self.workspace = workspace
    self.translator = translatorOf
    self._contextOf = contextOf
    self._localized = localized
    self.moment = momentOf
    self._levelNameOf = levelNameOf

  def sections(self) -> list[tuple[str, str]]:
    """The sections the person may use, each with its endpoint; none for a visitor who has not signed in."""
    if g.signedIn is None and g.signInMode is not SignInMode.open:
      return []
    held = self.workspace.permissionsAt("server")
    may = {
      "accounts": Permission.manageAccess in held,
      "groups": Permission.manageAccess in held,
      "roles": Permission.manageAccess in held,
      "assignments": Permission.manageAccess in held,
      "settings": any(self.workspace.scopesGranting(permission) for permission in settingPermissions),
      "signInMode": Permission.changeSettings in held,
      "providers": Permission.manageAccess in held,
      "workloads": Permission.manageAccess in held,
      "tasks": Permission.manageTasks in held,
      "retention": Permission.manageRetention in held,
      "audit": bool(self.workspace.scopesGranting(Permission.viewAudit)),
    }
    return [(section, endpoint) for section, endpoint in sectionEndpoints.items() if may[section]]

  def render(self, template: str, translator, problems: list[str] | None = None, **context) -> Response:
    done = request.args.get("done")
    notice = translator.text(f"web.administration.done.{done}") if done in doneCodes and request.method == "GET" else None
    body = render_template(template, problems=problems or [], notice=notice, **context, **self._contextOf(translator))
    return Response(body, status=400 if problems else 200)

  def addressOf(self, endpoint: str, translator, **values) -> str:
    return self._localized(url_for(endpoint, **values), translator)

  def back(self, endpoint: str, translator, **values) -> Response:
    return redirect(self.addressOf(endpoint, translator, **values))

  def confirm(self, translator, problems: list[str], what: str, section: str, subject: str, formAction: str,
              cancelAddress: str, assignments: list[dict] | None = None, blocked: str | None = None) -> Response:
    """The page that asks again before a group, a workload rule or a task is removed, with the roles that go with it;
    `blocked` says why the thing cannot be removed at all."""
    return self.render(
      "administrationConfirm.html", translator, problems, section=section, subject=subject, formAction=formAction,
      cancelAddress=cancelAddress, assignments=assignments, blocked=blocked,
      heading=translator.text(f"web.administration.confirm.{what}.heading"),
      warning=translator.text(f"web.administration.confirm.{what}.warning"),
      confirmLabel=translator.text(f"web.administration.confirm.{what}.button"),
    )

  def reasons(self, error: Exception) -> list[str]:
    """Why the core refused, one line for each thing wrong."""
    if isinstance(error, ValidationError):
      return [": ".join(filter(None, (".".join(str(part) for part in found["loc"]), found["msg"])))
              for found in error.errors()]
    return [str(error)]

  def scopeChoices(self, translator) -> list[ScopeChoice]:
    """The server, then every place the person may see with the trials in it, in the hierarchy's order."""
    workspace = self.workspace
    levels = workspace.hierarchyLevels()
    names = {level.levelCode: self._levelNameOf(level, translator) for level in levels}

    def trials(found: list[tuple[str, str]], depth: int) -> list[ScopeChoice]:
      return [ScopeChoice(f"trial:{code}", translator.text("web.administration.scope.trial", code=code, title=title), depth)
              for code, title in found]

    choices = [ScopeChoice("server", translator.text("web.administration.scope.server"), 0)]
    if not levels:
      return choices + trials(workspace.listTrials(), 1)
    for place in workspace.places():
      depth = place.path.count("/") + 1
      label = translator.text("web.administration.scope.place", level=names[place.levelCode], name=place.name, path=place.path)
      choices.append(ScopeChoice(f"place:{place.path}", label, depth))
      if place.levelCode == levels[-1].levelCode:
        choices += trials(workspace.trialsIn(place.path), depth + 1)
    return choices

  def unknown(self, translator, what: str, name: str) -> NotFoundError:
    """The refusal for a page about an account, group, role, provider, rule, kind or scope that is not there."""
    return NotFoundError(translator.text(f"web.administration.unknown.{what}", name=name))

  def chosenScope(self, scope: str, choices: list[ScopeChoice], translator) -> str:
    if scope not in {choice.scope for choice in choices}:
      raise self.unknown(translator, "scope", scope)
    return scope

  def scopeName(self, scope: str, translator) -> str:
    kind, _, name = scope.partition(":")
    if scope == "server":
      return translator.text("web.administration.scope.named.server")
    if kind in ("place", "trial") and name:
      return translator.text(f"web.administration.scope.named.{kind}", name=name)
    raise ScopeError(f"'{scope}' is not a scope: 'server', 'place:<path>' or 'trial:<code>'")

  def roleName(self, role, translator) -> str:
    return translator.text(f"web.administration.role.{role.roleCode}") if role.builtIn else role.name

  def changeAssignment(self, form, given: bool, holderKind: str, holderName: str, translator) -> None:
    """Give or take back the role and scope a form names, for one account, group or workload rule."""
    if holderKind not in holderFields or not holderName:
      raise IdentityError(translator.text("web.administration.assignments.chooseHolder"))
    assignment = RoleAssignment(roleCode=form.get("roleCode", ""), scope=form.get("scope", ""),
                                **{holderFields[holderKind]: holderName})
    (self.workspace.assignRole if given else self.workspace.unassignRole)(assignment)

  def assignmentRows(self, assignments: list[RoleAssignment], translator) -> list[dict]:
    roles = self.workspace.roles()
    rows = []
    for assignment in assignments:
      kind, name = next((kind, getattr(assignment, field)) for kind, field in holderFields.items()
                        if getattr(assignment, field) is not None)
      rows.append({"roleCode": assignment.roleCode, "roleName": self.roleName(roles[assignment.roleCode], translator),
                   "scope": assignment.scope, "scopeName": self.scopeName(assignment.scope, translator),
                   "holderKind": kind, "holderName": name})
    return rows

  def roleChoices(self, translator) -> list[tuple[str, str]]:
    return [(code, self.roleName(role, translator)) for code, role in sorted(self.workspace.roles().items())]
