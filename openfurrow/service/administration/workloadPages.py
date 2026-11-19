# SPDX-License-Identifier: Apache-2.0
"""Trusted workload rules (decision 0042), for holders of manageAccess: the rules, adding one, enabling, disabling and
removing it, and the roles given to it."""

from __future__ import annotations

import datetime

from flask import Blueprint, Response, request

from openfurrow.identity.workloads import claimsGiven, namedIssuers
from openfurrow.service.administration.pages import Pages, refusals
from openfurrow.workspace import IdentityError, Workspace


def registerWorkloadPages(blueprint: Blueprint, workspace: Workspace, pages: Pages) -> None:

  def ruleNamed(name: str, translator):
    if name not in [rule.name for rule in workspace.workloadRules()]:
      raise pages.unknown(translator, "workload", name)
    return workspace.workloadRule(name)

  def audience() -> str | None:
    return {setting.key: setting.value for setting in workspace.effectiveSettings("server")}["identity.workloadAudience"]

  @blueprint.route("/administration/workloads", methods=["GET", "POST"])
  def administrationWorkloads() -> Response:
    """The rules, and a form to add one: its name, its issuer, and the claims a token must carry, one to a line."""
    translator = pages.translator()
    typed = {"name": "", "issuer": "", "claims": "", "certificateAuthority": ""}
    problems: list[str] = []
    if request.method == "POST":
      typed = {field: request.form.get(field, "").strip() for field in typed}
      try:
        claims = claimsGiven([line.strip() for line in typed["claims"].splitlines() if line.strip()])
        rule = workspace.addWorkloadRule(typed["name"], typed["issuer"], claims, typed["certificateAuthority"] or None)
        return pages.back("web.administrationWorkload", translator, name=rule.name, done="added")
      except refusals as error:
        problems = pages.reasons(error)
    context = {"rules": workspace.workloadRules(), "typed": typed, "audience": audience(),
               "namedIssuers": ", ".join(namedIssuers)}
    return pages.render("administrationWorkloads.html", translator, problems, **context)

  @blueprint.route("/administration/workloads/<name>", methods=["GET", "POST"])
  def administrationWorkload(name: str) -> Response:
    """One rule: what it trusts, whether it is enabled, and its roles."""
    translator = pages.translator()
    ruleNamed(name, translator)
    typed = {"roleCode": "", "scope": ""}
    problems: list[str] = []
    if request.method == "POST":
      action = request.form.get("action")
      typed = {field: request.form.get(field, "").strip() for field in typed}
      try:
        if action in ("enable", "disable"):
          workspace.setWorkloadRuleEnabled(name, action == "enable")
          done = f"{action}d"
        elif action in ("give", "takeBack"):
          pages.changeAssignment(request.form, action == "give", "rule", name, translator)
          done = "given" if action == "give" else "takenBack"
        else:
          raise IdentityError(f"unknown action '{action}'")
        return pages.back("web.administrationWorkload", translator, name=name, done=done)
      except refusals as error:
        problems = pages.reasons(error)
    rule, given = workspace.workloadRule(name)
    context = {"rule": rule, "assignments": pages.assignmentRows(given, translator), "typed": typed,
               "added": pages.moment(rule.createdAt.replace(tzinfo=datetime.UTC), "UTC", translator),
               "roleChoices": pages.roleChoices(translator), "scopeChoices": pages.scopeChoices(translator)}
    return pages.render("administrationWorkload.html", translator, problems, **context)

  @blueprint.route("/administration/workloads/<name>/remove", methods=["GET", "POST"])
  def administrationWorkloadRemove(name: str) -> Response:
    """Removing a rule takes its roles with it, so it is asked twice: this page, then its button."""
    translator = pages.translator()
    rule, given = ruleNamed(name, translator)
    if request.method == "POST":
      workspace.removeWorkloadRule(name)
      return pages.back("web.administrationWorkloads", translator, done="removed")
    return pages.confirm(translator, [], "workload", "workloads", rule.name,
                         pages.addressOf("web.administrationWorkloadRemove", translator, name=name),
                         pages.addressOf("web.administrationWorkload", translator, name=name),
                         pages.assignmentRows(given, translator))
