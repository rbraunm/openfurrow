# SPDX-License-Identifier: Apache-2.0
"""The audit log: every change, who made it, from where, and what it changed (decision 0038).

An event is written in the same transaction as the change it records, so a change without
its event cannot be committed. The tool never updates or deletes an event; retention
(decision to come) is the only way one leaves.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from openfurrow.identity.model import Actor
from openfurrow.store.database import AuditEventRow
from openfurrow.store.identity import now


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


def record(session: Session, actor: Actor, action: str, scope: str, detail: dict) -> None:
  session.add(AuditEventRow(
    at=now(), actorKind=actor.kind.value, actorName=actor.name, surface=actor.surface, action=action,
    scope=scope, detailJSON=json.dumps(detail, sort_keys=True, default=str),
  ))
  session.flush()


def events(session: Session, scopePrefix: str | None = None, limit: int = 200) -> list[AuditEvent]:
  """The latest events, newest first; with a prefix, only those whose scope starts with it."""
  query = select(AuditEventRow).order_by(AuditEventRow.eventID.desc()).limit(limit)
  if scopePrefix is not None:
    query = query.where(AuditEventRow.scope.startswith(scopePrefix))
  return [
    AuditEvent(eventID=row.eventID, at=row.at.isoformat(timespec="seconds") + "Z", actorKind=row.actorKind,
               actorName=row.actorName, surface=row.surface, action=row.action, scope=row.scope,
               detail=json.loads(row.detailJSON))
    for row in session.execute(query).scalars().all()
  ]
