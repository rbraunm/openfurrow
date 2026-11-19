# SPDX-License-Identifier: Apache-2.0
"""The audit log: every change, who made it, from where, and what it changed (decision 0038).

An event is written in the same transaction as the change it records, so a change without
its event cannot be committed. The tool never updates an event, and one leaves only when
the audit log's retention rule lets it go (decision 0044).
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from openfurrow.identity.model import Actor
from openfurrow.store.database import AuditEventRow
from openfurrow.store.tasks import stored


class AuditEvent(BaseModel):
  model_config = ConfigDict(extra="forbid")

  eventID: int
  at: str
  actorKind: str
  actorName: str | None
  surface: str
  action: str
  scope: str
  detail: dict


def record(session: Session, actor: Actor, action: str, scope: str, detail: dict, at: datetime.datetime) -> None:
  """Write an event. A workload's event also carries the run its token came from (decision 0042), added here so no
  caller can leave it out."""
  if actor.run is not None:
    detail = detail | {"workloadRun": actor.run}
  session.add(AuditEventRow(
    at=stored(at), actorKind=actor.kind.value, actorName=actor.name, surface=actor.surface, action=action,
    scope=scope, detailJSON=json.dumps(detail, sort_keys=True, default=str),
  ))
  session.flush()


@dataclass(frozen=True)
class EventFilter:
  """Which events to read: those of an actor (an account's user name, a task, a workload rule, or 'operator' and
  'everyone' for the actors that have no name), those whose action is `action` or starts with it, those from `since`
  on and before `until` (UTC), and those older than the event `before`. Nothing set reads every event."""

  actor: str | None = None
  action: str | None = None
  since: datetime.datetime | None = None
  until: datetime.datetime | None = None
  before: int | None = None


def events(session: Session, place: str | None = None, trialCodes: list[str] | None = None, limit: int = 200,
           chosen: EventFilter = EventFilter()) -> list[AuditEvent]:
  """The latest events, newest first: every one, or those at a place, at the places inside it and at the trials
  named (the ones the caller found in it), or with no place those at the trials named alone."""
  query = select(AuditEventRow).order_by(AuditEventRow.eventID.desc()).limit(limit)
  if place is not None or trialCodes is not None:
    scopes = [AuditEventRow.scope.in_([f"trial:{code}" for code in trialCodes or []])]
    if place is not None:
      scopes += [AuditEventRow.scope == f"place:{place}", AuditEventRow.scope.startswith(f"place:{place}/", autoescape=True)]
    query = query.where(or_(*scopes))
  if chosen.actor is not None:
    query = query.where(or_(AuditEventRow.actorName == chosen.actor,
                            and_(AuditEventRow.actorName.is_(None), AuditEventRow.actorKind == chosen.actor)))
  if chosen.action is not None:
    query = query.where(AuditEventRow.action.startswith(chosen.action, autoescape=True))
  if chosen.since is not None:
    query = query.where(AuditEventRow.at >= stored(chosen.since))
  if chosen.until is not None:
    query = query.where(AuditEventRow.at < stored(chosen.until))
  if chosen.before is not None:
    query = query.where(AuditEventRow.eventID < chosen.before)
  return [
    AuditEvent(eventID=row.eventID, at=row.at.isoformat(timespec="seconds") + "Z", actorKind=row.actorKind,
               actorName=row.actorName, surface=row.surface, action=row.action, scope=row.scope,
               detail=json.loads(row.detailJSON))
    for row in session.execute(query).scalars().all()
  ]
