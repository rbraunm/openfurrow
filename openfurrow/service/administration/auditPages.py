# SPDX-License-Identifier: Apache-2.0
"""The audit log (decision 0038), for holders of viewAudit: the newest events first, a page at a time, narrowed by who
acted, the action, where, and when."""

from __future__ import annotations

import datetime

from flask import Blueprint, Response, request

from openfurrow.identity.model import Permission
from openfurrow.service.administration.pages import Pages
from openfurrow.workspace import EventFilter, Workspace

pageSize = 50


def registerAuditPages(blueprint: Blueprint, workspace: Workspace, pages: Pages) -> None:

  def day(text: str, field: str, translator, problems: list[str]) -> datetime.datetime | None:
    if not text:
      return None
    try:
      chosen = datetime.date.fromisoformat(text)
    except ValueError:
      problems.append(translator.text("web.administration.audit.notADate", field=translator.text(f"web.administration.audit.{field}"), typed=text))
      return None
    return datetime.datetime.combine(chosen, datetime.time(), datetime.UTC)

  @blueprint.get("/administration/audit")
  def administrationAudit() -> Response:
    """The events at a scope chosen from the hierarchy: the server when the person may read it there, otherwise the
    first place or trial where they may."""
    translator = pages.translator()
    choices = pages.scopeChoices(translator)
    granted = workspace.scopesGranting(Permission.viewAudit)
    scope = pages.chosenScope(request.args.get("scope") or (granted[0] if granted else "server"), choices, translator)
    typed = {field: request.args.get(field, "").strip() for field in ("actor", "action", "since", "until")}
    before = request.args.get("before", type=int)
    problems: list[str] = []
    since = day(typed["since"], "since", translator, problems)
    until = day(typed["until"], "until", translator, problems)
    chosen = EventFilter(actor=typed["actor"] or None, action=typed["action"] or None, since=since,
                         until=None if until is None else until + datetime.timedelta(days=1), before=before)
    found = workspace.auditEvents(scope, pageSize + 1, chosen)
    events = [{
      "event": event, "actorKind": translator.text(f"web.administration.audit.actor.{event.actorKind}"),
      "when": pages.moment(datetime.datetime.fromisoformat(event.at), "UTC", translator),
      "where": pages.scopeName(event.scope, translator),
    } for event in found[:pageSize]]
    kept = {"scope": scope} | {field: text for field, text in typed.items() if text}
    context = {
      "events": events, "typed": typed, "scope": scope, "scopeChoices": choices, "isFirstPage": before is None,
      "filtered": any(typed.values()),
      "olderAddress": (pages.addressOf("web.administrationAudit", translator, before=found[pageSize - 1].eventID, **kept)
                       if len(found) > pageSize else None),
      "newestAddress": pages.addressOf("web.administrationAudit", translator, **kept),
      "allAddress": pages.addressOf("web.administrationAudit", translator, scope=scope),
    }
    return pages.render("administrationAudit.html", translator, problems, **context)
