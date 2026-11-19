# SPDX-License-Identifier: Apache-2.0
"""Retention (decision 0044), for holders of manageRetention at the server: what each storage area holds, the rule it
is kept by and where that was set, the holds, a preview of exactly what pruning now would remove, and pruning itself
behind a page that asks again. What a pruning removed is in the audit log. The rules are settings, changed on the
settings page; a trial's closed date and its hold are on the trial's own page."""

from __future__ import annotations

from flask import Blueprint, Response, request

from openfurrow.retention import retentionTaskName
from openfurrow.service.administration.pages import Pages
from openfurrow.service.retentionWords import ruleText
from openfurrow.workspace import Workspace


def registerRetentionPages(blueprint: Blueprint, workspace: Workspace, pages: Pages) -> None:

  def words(translator) -> dict:
    """What the two pages say rules, scopes, sources and moments with."""
    zone = {setting.key: setting.value for setting in workspace.effectiveSettings("server")}["tasks.timeZone"]

    def sourceName(source: str) -> str:
      if source == "default":
        return translator.text("web.administration.settings.source.default")
      return pages.scopeName(source, translator)

    return {
      "ruleText": lambda rule: ruleText(rule, translator),
      "scopeName": lambda scope: pages.scopeName(scope, translator),
      "sourceName": sourceName,
      "moment": lambda moment: pages.moment(moment, zone, translator),
      "zone": zone,
      "retentionTask": retentionTaskName,
    }

  @blueprint.get("/administration/retention")
  def administrationRetention() -> Response:
    """The storage areas and the holds; with `preview=yes`, also what pruning now would remove. Nothing changes."""
    translator = pages.translator()
    status = workspace.retentionStatus()
    preview = workspace.previewPruning() if request.args.get("preview") == "yes" else None
    return pages.render("administrationRetention.html", translator, status=status, preview=preview, **words(translator))

  @blueprint.route("/administration/retention/prune", methods=["GET", "POST"])
  def administrationRetentionPrune() -> Response:
    """Pruning: the GET shows exactly what would go and asks; only the POST removes it."""
    translator = pages.translator()
    if request.method == "GET":
      return pages.render("administrationRetentionPrune.html", translator, preview=workspace.previewPruning(),
                          **words(translator))
    outcome = workspace.prune()
    return pages.back("web.administrationRetention", translator, done="pruned" if outcome.lines else "nothingPruned")
