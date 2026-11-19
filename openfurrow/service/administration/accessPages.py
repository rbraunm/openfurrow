# SPDX-License-Identifier: Apache-2.0
"""Accounts, groups, roles and who holds which role where (decisions 0036, 0037), for holders of manageAccess."""

from __future__ import annotations

from flask import Blueprint, Response, request

from openfurrow.identity.model import Permission, RoleDefinition
from openfurrow.service.administration.pages import Pages, refusals
from openfurrow.workspace import IdentityError, Workspace


def registerAccessPages(blueprint: Blueprint, workspace: Workspace, pages: Pages) -> None:

  def accountNamed(userName: str, translator):
    found = [account for account in workspace.accounts() if account.userName == userName]
    if not found:
      raise pages.unknown(translator, "account", userName)
    return found[0]

  def groupNamed(name: str, translator):
    found = [group for group in workspace.groups() if group.name == name]
    if not found:
      raise pages.unknown(translator, "group", name)
    return found[0]

  def confirmed(translator) -> None:
    if request.form.get("confirm") != "yes":
      raise IdentityError(translator.text("web.administration.confirmNeeded"))

  @blueprint.route("/administration/accounts", methods=["GET", "POST"])
  def administrationAccounts() -> Response:
    """The accounts, and a form to add one; a password is typed here or left out for a provider's account."""
    translator = pages.translator()
    typed = {"userName": "", "displayName": "", "email": ""}
    problems: list[str] = []
    if request.method == "POST":
      typed = {field: request.form.get(field, "").strip() for field in typed}
      try:
        account = workspace.createAccount(typed["userName"], typed["displayName"], typed["email"] or None,
                                          request.form.get("password") or None)
        return pages.back("web.administrationAccount", translator, userName=account.userName, done="created")
      except refusals as error:
        problems = pages.reasons(error)
    return pages.render("administrationAccounts.html", translator, problems, accounts=workspace.accounts(), typed=typed)

  @blueprint.route("/administration/accounts/<userName>", methods=["GET", "POST"])
  def administrationAccount(userName: str) -> Response:
    """One account: its password, whether it is active, its providers' identities, its groups and its roles."""
    translator = pages.translator()
    account = accountNamed(userName, translator)
    typed = {"provider": "", "subject": "", "roleCode": "", "scope": ""}
    problems: list[str] = []
    if request.method == "POST":
      action = request.form.get("action")
      typed = {field: request.form.get(field, "").strip() for field in typed}
      try:
        if action == "password":
          workspace.setPassword(account.userName, request.form.get("newPassword", ""))
          done = "passwordSet"
        elif action == "deactivate":
          confirmed(translator)
          workspace.setAccountActive(account.userName, False)
          done = "deactivated"
        elif action == "activate":
          workspace.setAccountActive(account.userName, True)
          done = "reactivated"
        elif action == "link":
          workspace.linkIdentity(typed["provider"], typed["subject"], account.userName)
          done = "linked"
        elif action in ("join", "leave"):
          workspace.setMembership(request.form.get("group", ""), account.userName, action == "join")
          done = "joined" if action == "join" else "left"
        elif action in ("give", "takeBack"):
          pages.changeAssignment(request.form, action == "give", "user", account.userName, translator)
          done = "given" if action == "give" else "takenBack"
        else:
          raise IdentityError(f"unknown action '{action}'")
        return pages.back("web.administrationAccount", translator, userName=account.userName, done=done)
      except refusals as error:
        problems = pages.reasons(error)
    groups = workspace.groups()
    memberOf = [group for group in groups if account.userName in group.members]
    held = [assignment for assignment in workspace.assignments()
            if assignment.userName == account.userName or assignment.groupName in {group.name for group in memberOf}]
    context = {
      "account": accountNamed(userName, translator), "identities": workspace.linkedIdentities(account.userName),
      "providers": workspace.providers(), "memberOf": memberOf,
      "joinable": [group for group in groups if group.providerName is None and account.userName not in group.members],
      "assignments": pages.assignmentRows(held, translator), "roleChoices": pages.roleChoices(translator),
      "scopeChoices": pages.scopeChoices(translator), "typed": typed,
    }
    return pages.render("administrationAccount.html", translator, problems, **context)

  @blueprint.route("/administration/groups", methods=["GET", "POST"])
  def administrationGroups() -> Response:
    translator = pages.translator()
    typed = {"name": ""}
    problems: list[str] = []
    if request.method == "POST":
      typed = {"name": request.form.get("name", "").strip()}
      try:
        group = workspace.createGroup(typed["name"])
        return pages.back("web.administrationGroup", translator, name=group.name, done="created")
      except refusals as error:
        problems = pages.reasons(error)
    return pages.render("administrationGroups.html", translator, problems, groups=workspace.groups(), typed=typed)

  @blueprint.route("/administration/groups/show", methods=["GET", "POST"])
  def administrationGroup() -> Response:
    """One group: its members and its roles. A mirrored group's members are its provider's to set."""
    translator = pages.translator()
    group = groupNamed(request.args.get("name", ""), translator)
    typed = {"roleCode": "", "scope": ""}
    problems: list[str] = []
    if request.method == "POST":
      action = request.form.get("action")
      typed = {field: request.form.get(field, "").strip() for field in typed}
      try:
        if action in ("join", "leave"):
          workspace.setMembership(group.name, request.form.get("userName", ""), action == "join")
          done = "joined" if action == "join" else "left"
        elif action in ("give", "takeBack"):
          pages.changeAssignment(request.form, action == "give", "group", group.name, translator)
          done = "given" if action == "give" else "takenBack"
        else:
          raise IdentityError(f"unknown action '{action}'")
        return pages.back("web.administrationGroup", translator, name=group.name, done=done)
      except refusals as error:
        problems = pages.reasons(error)
    group = groupNamed(group.name, translator)
    held = [assignment for assignment in workspace.assignments() if assignment.groupName == group.name]
    context = {
      "group": group, "addable": [account for account in workspace.accounts() if account.userName not in group.members],
      "assignments": pages.assignmentRows(held, translator), "roleChoices": pages.roleChoices(translator),
      "scopeChoices": pages.scopeChoices(translator), "typed": typed,
    }
    return pages.render("administrationGroup.html", translator, problems, **context)

  @blueprint.route("/administration/groups/delete", methods=["GET", "POST"])
  def administrationGroupDelete() -> Response:
    """Deleting a group takes its roles with it, so it is asked twice: this page, then its button."""
    translator = pages.translator()
    group = groupNamed(request.args.get("name", ""), translator)
    problems: list[str] = []
    if request.method == "POST":
      try:
        workspace.deleteGroup(group.name)
        return pages.back("web.administrationGroups", translator, done="deleted")
      except refusals as error:
        problems = pages.reasons(error)
    held = [assignment for assignment in workspace.assignments() if assignment.groupName == group.name]
    return pages.confirm(translator, problems, "group", "groups", group.name,
                         pages.addressOf("web.administrationGroupDelete", translator, name=group.name),
                         pages.addressOf("web.administrationGroup", translator, name=group.name),
                         pages.assignmentRows(held, translator))

  def typedRole(form) -> dict:
    return {"roleCode": form.get("roleCode", "").strip(), "name": form.get("name", "").strip(),
            "permissions": form.getlist("permissions")}

  def define(typed: dict) -> None:
    workspace.defineRole(RoleDefinition(roleCode=typed["roleCode"], name=typed["name"] or None,
                                        permissions=typed["permissions"]))

  @blueprint.route("/administration/roles", methods=["GET", "POST"])
  def administrationRoles() -> Response:
    """The roles with their permissions, and a form to define a custom one."""
    translator = pages.translator()
    workspace.require(Permission.manageAccess, "server")
    typed = {"roleCode": "", "name": "", "permissions": []}
    problems: list[str] = []
    if request.method == "POST":
      typed = typedRole(request.form)
      try:
        if typed["roleCode"] in workspace.roles():
          raise IdentityError(translator.text("web.administration.roles.exists", code=typed["roleCode"]))
        define(typed)
        return pages.back("web.administrationRoles", translator, done="defined")
      except refusals as error:
        problems = pages.reasons(error)
    roles = [{"role": role, "name": pages.roleName(role, translator)} for _, role in sorted(workspace.roles().items())]
    return pages.render("administrationRoles.html", translator, problems, roles=roles, permissions=list(Permission), typed=typed)

  @blueprint.route("/administration/roles/<roleCode>", methods=["GET", "POST"])
  def administrationRole(roleCode: str) -> Response:
    """One custom role: change its name and permissions, or delete it once nobody holds it."""
    translator = pages.translator()
    workspace.require(Permission.manageAccess, "server")
    role = workspace.roles().get(roleCode)
    if role is None or role.builtIn:
      raise pages.unknown(translator, "role", roleCode)
    typed = {"roleCode": roleCode, "name": role.name, "permissions": sorted(permission.value for permission in role.permissions)}
    problems: list[str] = []
    if request.method == "POST":
      action = request.form.get("action")
      try:
        if action == "save":
          typed = typedRole(request.form) | {"roleCode": roleCode}
          define(typed)
          return pages.back("web.administrationRole", translator, roleCode=roleCode, done="saved")
        if action == "delete":
          confirmed(translator)
          workspace.deleteRole(roleCode)
          return pages.back("web.administrationRoles", translator, done="deleted")
        raise IdentityError(f"unknown action '{action}'")
      except refusals as error:
        problems = pages.reasons(error)
    held = [assignment for assignment in workspace.assignments() if assignment.roleCode == roleCode]
    return pages.render("administrationRole.html", translator, problems, role=role, permissions=list(Permission), typed=typed,
                        assignments=pages.assignmentRows(held, translator))

  @blueprint.route("/administration/assignments", methods=["GET", "POST"])
  def administrationAssignments() -> Response:
    """Every role given, to whom and where; give one to an account, a group or a workload rule, or take one back."""
    translator = pages.translator()
    typed = {"roleCode": "", "scope": "", "holder": ""}
    problems: list[str] = []
    if request.method == "POST":
      action = request.form.get("action")
      typed = {field: request.form.get(field, "").strip() for field in typed}
      holderKind, _, holderName = typed["holder"].partition(":")
      try:
        if action not in ("give", "takeBack"):
          raise IdentityError(f"unknown action '{action}'")
        pages.changeAssignment(request.form, action == "give", holderKind, holderName, translator)
        return pages.back("web.administrationAssignments", translator, done="given" if action == "give" else "takenBack")
      except refusals as error:
        problems = pages.reasons(error)
    context = {
      "assignments": pages.assignmentRows(workspace.assignments(), translator),
      "holders": {"user": [account.userName for account in workspace.accounts()],
                  "group": [group.name for group in workspace.groups()],
                  "rule": [rule.name for rule in workspace.workloadRules()]},
      "roleChoices": pages.roleChoices(translator),
      "scopeChoices": pages.scopeChoices(translator), "typed": typed,
    }
    return pages.render("administrationAssignments.html", translator, problems, **context)
