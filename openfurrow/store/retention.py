# SPDX-License-Identifier: Apache-2.0
"""Retention in the store: what each area holds, closing and holding trials, and pruning (decision 0044).

A pruning is worked out once, as a selection: the exact rows that leave and the lines
that say so. A preview shows the lines; pruning removes the rows and hands back the
same lines, so what was previewed is what goes.

Sizes are the bytes of what is held as content -- a trial's canonical document, a file's
bytes, the text of an event, a session or a run -- not the space a database engine uses
for them, which differs between engines and is not the store's to know.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from sqlalchemy import Integer, case, delete, func, select, tuple_
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import FunctionElement

from openfurrow.identity.model import Actor
from openfurrow.retention import (
  AreaStatus,
  Hold,
  PruneLine,
  RetentionError,
  RetentionPolicy,
  RetentionRule,
  RetentionStatus,
  RuleAt,
  StorageArea,
  isRetentionRecord,
  settingActions,
  settingKey,
)
from openfurrow.schema.document import TrialDocument, canonicalBytes, contentHash
from openfurrow.schema.layout import TrialLayout
from openfurrow.store.database import (
  AuditEventRow,
  AuthTokenRow,
  NotFoundError,
  PendingSignInRow,
  ProviderSessionRow,
  ReceivedFileRow,
  ReplayClaimRow,
  RetentionHoldRow,
  SettingValueRow,
  StoreError,
  TaskRunRow,
  TrialRow,
)
from openfurrow.store.hierarchy import pathOf, writtenScope
from openfurrow.store.repository import deleteTrial, loadCheckPlots, loadLayout, loadObservations, loadPackage
from openfurrow.store.settingValues import effectiveSettings
from openfurrow.store.tasks import aware, serverSetting, stored

deleteChunk = 500


class _TextBytes(FunctionElement):
  """The UTF-8 bytes of a text value, which each engine words its own way."""

  type = Integer()
  name = "textBytes"
  inherit_cache = True


@compiles(_TextBytes)
def _octetLength(element, compiler, **options) -> str:
  return f"octet_length({compiler.process(element.clauses, **options)})"


@compiles(_TextBytes, "sqlite")
def _lengthAsBlob(element, compiler, **options) -> str:
  return f"length(CAST({compiler.process(element.clauses, **options)} AS BLOB))"


def _textBytes(*columns):
  total = _TextBytes(func.coalesce(columns[0], ""))
  for column in columns[1:]:
    total = total + _TextBytes(func.coalesce(column, ""))
  return total


_eventBytes = _textBytes(AuditEventRow.actorKind, AuditEventRow.actorName, AuditEventRow.surface, AuditEventRow.action,
                         AuditEventRow.scope, AuditEventRow.detailJSON)
# A session's provider session leaves with its token, so it is weighed with it; none adds nothing.
_tokenBytes = _textBytes(AuthTokenRow.tokenHash, AuthTokenRow.kind, AuthTokenRow.name, ProviderSessionRow.providerName,
                         ProviderSessionRow.subject, ProviderSessionRow.sessionID, ProviderSessionRow.detailJSON)
_pendingBytes = _textBytes(PendingSignInRow.keyHash, PendingSignInRow.providerName, PendingSignInRow.stateJSON)
_claimBytes = _textBytes(ReplayClaimRow.scope, ReplayClaimRow.identifier)
_runBytes = _textBytes(TaskRunRow.taskName, TaskRunRow.requestedBy, TaskRunRow.summary, TaskRunRow.output)
_tokensWithSessions = select(AuthTokenRow.tokenHash, AuthTokenRow.kind, _tokenBytes.label("size")).outerjoin(
  ProviderSessionRow, ProviderSessionRow.tokenHash == AuthTokenRow.tokenHash)


def written(moment: datetime.datetime) -> str:
  """A stored moment as the audit log writes moments."""
  return moment.isoformat(timespec="seconds") + "Z"


def _total(session: Session, query) -> tuple[int, int]:
  count, size = session.execute(query).one()
  return count, int(size)


def storedDocument(session: Session, trialCode: str) -> TrialDocument:
  """A stored trial as its document, to weigh and to hash. Assembled without the document's own validation, which
  generates the layout again: this runs for every trial of a store, and the store validated each as it came in."""
  package = loadPackage(session, trialCode)
  layout = TrialLayout.forPackage(package, loadLayout(session, trialCode), loadCheckPlots(session, trialCode))
  return TrialDocument.model_construct(package=package, layout=layout.plots, checkPlots=layout.checkPlots,
                                       observations=loadObservations(session, trialCode))


# ---- what each area holds --------------------------------------------------------

def _measures(session: Session) -> dict[StorageArea, tuple[int, int]]:
  trialCodes = session.execute(select(TrialRow.trialCode)).scalars().all()
  tokens = _tokensWithSessions.subquery()
  held = [
    _total(session, select(func.count(), func.coalesce(func.sum(tokens.c.size), 0)).select_from(tokens)),
    _total(session, select(func.count(), func.coalesce(func.sum(_pendingBytes), 0)).select_from(PendingSignInRow)),
    _total(session, select(func.count(), func.coalesce(func.sum(_claimBytes), 0)).select_from(ReplayClaimRow)),
  ]
  return {
    StorageArea.trialRecords: (
      len(trialCodes), sum(len(canonicalBytes(storedDocument(session, trialCode))) for trialCode in trialCodes)),
    StorageArea.receivedFiles: _total(
      session, select(func.count(), func.coalesce(func.sum(ReceivedFileRow.sizeBytes), 0)).select_from(ReceivedFileRow)),
    StorageArea.auditLog: _total(
      session, select(func.count(), func.coalesce(func.sum(_eventBytes), 0)).select_from(AuditEventRow)),
    StorageArea.sessionsAndTokens: (sum(count for count, _ in held), sum(size for _, size in held)),
    StorageArea.taskRuns: _total(
      session, select(func.count(), func.coalesce(func.sum(_runBytes), 0)).select_from(TaskRunRow)),
  }


def _rules(session: Session, scope: str) -> dict[StorageArea, tuple[RetentionRule, str]]:
  """Each area's rule at a scope, and where it was set."""
  settings = {setting.key: setting for setting in effectiveSettings(session, scope)}
  return {area: (RetentionRule.read(settings[settingKey(area)].value), settings[settingKey(area)].source)
          for area in StorageArea}


def status(session: Session) -> RetentionStatus:
  """Every area's count and size, the server's rule for it, and the scopes below the server that set their own."""
  measures = _measures(session)
  below: dict[str, list[RuleAt]] = {}
  for row in session.execute(select(SettingValueRow).where(SettingValueRow.key.startswith("retention."),
                                                           SettingValueRow.scope != "server")).scalars().all():
    below.setdefault(row.key, []).append(RuleAt(scope=writtenScope(session, row.scope), rule=json.loads(row.valueJSON)))
  areas = []
  for area, (rule, source) in _rules(session, "server").items():
    count, size = measures[area]
    areas.append(AreaStatus(area=area, count=count, sizeBytes=size, rule=rule.text, source=source,
                            setBelow=sorted(below.get(settingKey(area), []), key=lambda entry: entry.scope)))
  return RetentionStatus(areas=areas, holds=holds(session))


# ---- closing and holding a trial -------------------------------------------------------

def _trial(session: Session, trialCode: str) -> TrialRow:
  row = session.get(TrialRow, trialCode)
  if row is None:
    raise NotFoundError(f"trial '{trialCode}' not found")
  return row


def closedOn(session: Session, trialCode: str) -> datetime.date | None:
  return _trial(session, trialCode).closedOn


def today(session: Session, at: datetime.datetime) -> datetime.date:
  """The day it is at the server, in the time zone its schedules are read in."""
  return at.astimezone(ZoneInfo(serverSetting(session, "tasks.timeZone"))).date()


def setClosedOn(session: Session, trialCode: str, day: datetime.date | None, at: datetime.datetime) -> None:
  """Record the day a trial was closed, or with None that it is open again."""
  if day is not None and day > today(session, at):
    raise RetentionError(f"trial '{trialCode}' cannot be closed on {day.isoformat()}, a day that has not come; "
                         f"it is {today(session, at).isoformat()} at the server")
  _trial(session, trialCode).closedOn = day
  session.flush()


def _hold(row: RetentionHoldRow) -> Hold:
  return Hold(trialCode=row.trialCode, reason=row.reason, heldByKind=row.heldByKind, heldByName=row.heldByName,
              heldAt=aware(row.heldAt))


def holdOn(session: Session, trialCode: str) -> Hold | None:
  _trial(session, trialCode)
  row = session.get(RetentionHoldRow, trialCode)
  return None if row is None else _hold(row)


def holds(session: Session) -> list[Hold]:
  rows = session.execute(select(RetentionHoldRow).order_by(RetentionHoldRow.trialCode)).scalars().all()
  return [_hold(row) for row in rows]


def setHold(session: Session, trialCode: str, reason: str, actor: Actor, at: datetime.datetime) -> Hold:
  existing = holdOn(session, trialCode)
  if existing is not None:
    raise RetentionError(f"trial '{trialCode}' is under a hold already: {existing.reason}")
  if not reason.strip():
    raise RetentionError("a hold needs its reason")
  row = RetentionHoldRow(trialCode=trialCode, reason=reason.strip(), heldByKind=actor.kind.value, heldByName=actor.name,
                         heldAt=stored(at))
  session.add(row)
  session.flush()
  return _hold(row)


def releaseHold(session: Session, trialCode: str) -> Hold:
  """Take a trial's hold away; the hold that stood is handed back for the record of its release."""
  _trial(session, trialCode)
  row = session.get(RetentionHoldRow, trialCode)
  if row is None:
    raise RetentionError(f"trial '{trialCode}' is under no hold")
  released = _hold(row)
  session.delete(row)
  session.flush()
  return released


# ---- pruning -----------------------------------------------------------------------

@dataclass
class Selection:
  """What a pruning removes: the lines that say it, and the rows that are it."""

  lines: list[PruneLine] = field(default_factory=list)
  trialCodes: list[str] = field(default_factory=list)
  fileIDs: list[int] = field(default_factory=list)
  eventIDs: list[int] = field(default_factory=list)
  tokenHashes: list[str] = field(default_factory=list)
  pendingKeys: list[str] = field(default_factory=list)
  claims: list[tuple[str, str]] = field(default_factory=list)
  runIDs: list[int] = field(default_factory=list)


def _line(area: StorageArea, scope: str, count: int, size: int, ruled: tuple[RetentionRule, str], detail: dict) -> PruneLine:
  return PruneLine(area=area, scope=scope, count=count, sizeBytes=int(size), rule=ruled[0].text, source=ruled[1],
                   detail=detail)


def _selectTrialsAndFiles(session: Session, chosen: Selection, now: datetime.datetime, day: datetime.date,
                          held: set[str]) -> None:
  files: dict[str, list] = {}
  for row in session.execute(
    select(ReceivedFileRow.fileID, ReceivedFileRow.trialCode, ReceivedFileRow.kind, ReceivedFileRow.fileName,
           ReceivedFileRow.sha256, ReceivedFileRow.sizeBytes, ReceivedFileRow.importedAt)
    .order_by(ReceivedFileRow.fileID)
  ).all():
    files.setdefault(row.trialCode, []).append(row)
  fileLines = []
  for trial in session.execute(select(TrialRow).order_by(TrialRow.trialCode)).scalars().all():
    if trial.trialCode in held:
      continue
    scope = f"trial:{trial.trialCode}"
    ruled = _rules(session, scope)
    ofRecord, ofFiles = ruled[StorageArea.trialRecords], ruled[StorageArea.receivedFiles]
    recordGoes = trial.closedOn is not None and ofRecord[0].letsGo(trial.closedOn, day)
    received = files.get(trial.trialCode, [])
    if recordGoes:
      document = storedDocument(session, trial.trialCode)
      chosen.trialCodes.append(trial.trialCode)
      chosen.lines.append(_line(StorageArea.trialRecords, scope, 1, len(canonicalBytes(document)), ofRecord, {
        "title": trial.title, "contentHash": contentHash(document), "closedOn": trial.closedOn.isoformat(),
        "place": None if trial.placeID is None else pathOf(session, trial.placeID),
      }))
      leaving, under, detail = received, ofRecord, {"withTheTrialRecord": True}
    elif ofFiles[0].policy is RetentionPolicy.keepUntilClosed:
      leaving = received if trial.closedOn is not None and ofFiles[0].letsGo(trial.closedOn, day) else []
      under, detail = ofFiles, {}
    else:
      leaving, under, detail = [row for row in received if ofFiles[0].letsGo(row.importedAt, now)], ofFiles, {}
    if leaving:
      chosen.fileIDs += [row.fileID for row in leaving]
      size = sum(row.sizeBytes for row in leaving)
      fileLines.append(_line(StorageArea.receivedFiles, scope, len(leaving), size, under, detail | {
        "files": [{"fileID": row.fileID, "kind": row.kind, "fileName": row.fileName, "sha256": row.sha256,
                   "sizeBytes": row.sizeBytes, "importedAt": written(row.importedAt)} for row in leaving],
      }))
  chosen.lines += fileLines


def _selectEvents(session: Session, chosen: Selection, now: datetime.datetime, day: datetime.date, held: set[str]) -> None:
  closed = dict(session.execute(select(TrialRow.trialCode, TrialRow.closedOn)).all())
  ofServer = _rules(session, "server")[StorageArea.auditLog]
  events = select(
    AuditEventRow.eventID, AuditEventRow.at, AuditEventRow.action, _eventBytes.label("size"),
    case((AuditEventRow.action.in_(settingActions), AuditEventRow.detailJSON)).label("settingDetail"),
  ).order_by(AuditEventRow.eventID)
  for scope in sorted(session.execute(select(AuditEventRow.scope).distinct()).scalars().all()):
    trialCode = scope.partition(":")[2] if scope.startswith("trial:") else None
    if trialCode in held:
      continue
    try:
      ruled = _rules(session, scope)[StorageArea.auditLog]
    except NotFoundError:
      # The place or the trial is gone, and its own settings with it; what still stands above its events is the server.
      ruled = ofServer
    rule = ruled[0]
    if rule.policy is RetentionPolicy.keep:
      continue
    ofScope = events.where(AuditEventRow.scope == scope)
    if rule.policy is RetentionPolicy.keepUntilClosed and trialCode in closed:
      if closed[trialCode] is None or not rule.letsGo(closed[trialCode], day):
        continue
      rows = [row for row in session.execute(ofScope).all() if rule.letsGo(row.at, now) or not isRetentionRecord(
        row.action, json.loads(row.settingDetail) if row.settingDetail is not None else {})]
    else:
      rows = session.execute(ofScope.where(AuditEventRow.at <= rule.period.before(now))).all()
    if rows:
      chosen.eventIDs += [row.eventID for row in rows]
      chosen.lines.append(_line(StorageArea.auditLog, scope, len(rows), sum(row.size for row in rows), ruled, {
        "oldest": written(min(row.at for row in rows)), "newest": written(max(row.at for row in rows)),
        "firstEventID": rows[0].eventID, "lastEventID": rows[-1].eventID,
      }))


def _selectSessionsAndTokens(session: Session, chosen: Selection, now: datetime.datetime) -> None:
  ruled = _rules(session, "server")[StorageArea.sessionsAndTokens]
  if ruled[0].policy is RetentionPolicy.keep:
    return
  cutoff = ruled[0].period.before(now)
  tokens = session.execute(_tokensWithSessions.where(AuthTokenRow.expiresAt <= cutoff)).all()
  pending = session.execute(select(PendingSignInRow.keyHash, _pendingBytes.label("size"))
                            .where(PendingSignInRow.expiresAt <= cutoff)).all()
  claims = session.execute(select(ReplayClaimRow.scope, ReplayClaimRow.identifier, _claimBytes.label("size"))
                           .where(ReplayClaimRow.expiresAt <= cutoff)).all()
  count = len(tokens) + len(pending) + len(claims)
  if not count:
    return
  chosen.tokenHashes += [row.tokenHash for row in tokens]
  chosen.pendingKeys += [row.keyHash for row in pending]
  chosen.claims += [(row.scope, row.identifier) for row in claims]
  chosen.lines.append(_line(
    StorageArea.sessionsAndTokens, "server", count, sum(row.size for row in (*tokens, *pending, *claims)), ruled, {
      "expiredSessions": sum(row.kind == "session" for row in tokens),
      "expiredTokens": sum(row.kind == "api" for row in tokens),
      "pendingSignIns": len(pending), "messageClaims": len(claims),
    }))


def _selectRuns(session: Session, chosen: Selection, now: datetime.datetime) -> None:
  ruled = _rules(session, "server")[StorageArea.taskRuns]
  if ruled[0].policy is RetentionPolicy.keep:
    return
  rows = session.execute(select(TaskRunRow.runID, TaskRunRow.taskName, TaskRunRow.finishedAt, _runBytes.label("size"))
                         .where(TaskRunRow.finishedAt <= ruled[0].period.before(now)).order_by(TaskRunRow.runID)).all()
  if not rows:
    return
  byTask: dict[str, int] = {}
  for row in rows:
    byTask[row.taskName] = byTask.get(row.taskName, 0) + 1
  chosen.runIDs += [row.runID for row in rows]
  chosen.lines.append(_line(StorageArea.taskRuns, "server", len(rows), sum(row.size for row in rows), ruled, {
    "oldest": written(min(row.finishedAt for row in rows)), "newest": written(max(row.finishedAt for row in rows)),
    "byTask": byTask,
  }))


def selection(session: Session, at: datetime.datetime) -> Selection:
  """What the retention rules let go at `at`: nothing of a trial under a hold, and never part of a trial's record.

  A trial's record leaves whole, once its trial has been closed for the rule's period, and its received files with
  it. A received file leaves by its own age or its trial's closing. An audit event leaves by the rule that holds at
  its scope: by its age, or with its trial's closing, when the records of prunings, holds, closings and changed
  retention settings still stay until they are themselves older than the period. Expired sessions and tokens,
  expired pending sign-ins, expired message claims and finished runs leave by age.
  """
  chosen = Selection()
  now, day = stored(at), today(session, at)
  held = set(session.execute(select(RetentionHoldRow.trialCode)).scalars().all())
  _selectTrialsAndFiles(session, chosen, now, day, held)
  _selectEvents(session, chosen, now, day, held)
  _selectSessionsAndTokens(session, chosen, now)
  _selectRuns(session, chosen, now)
  return chosen


def _remove(session: Session, table, column, keys: list) -> None:
  removed = 0
  for start in range(0, len(keys), deleteChunk):
    removed += session.execute(delete(table).where(column.in_(keys[start:start + deleteChunk]))).rowcount
  if removed != len(keys):
    # What was selected is what the caller records as gone; rows that left in between would make that record false.
    raise StoreError(f"{len(keys) - removed} of the {len(keys)} rows of '{table.__tablename__}' selected for pruning "
                     f"were gone before they were removed; something else removed them meanwhile, so nothing is pruned")


def prune(session: Session, at: datetime.datetime) -> list[PruneLine]:
  """Remove what `selection` selects at `at`, and say what went."""
  chosen = selection(session, at)
  _remove(session, ReceivedFileRow, ReceivedFileRow.fileID, chosen.fileIDs)
  for trialCode in chosen.trialCodes:
    deleteTrial(session, trialCode)
  _remove(session, AuditEventRow, AuditEventRow.eventID, chosen.eventIDs)
  _remove(session, AuthTokenRow, AuthTokenRow.tokenHash, chosen.tokenHashes)
  _remove(session, PendingSignInRow, PendingSignInRow.keyHash, chosen.pendingKeys)
  _remove(session, ReplayClaimRow, tuple_(ReplayClaimRow.scope, ReplayClaimRow.identifier), chosen.claims)
  _remove(session, TaskRunRow, TaskRunRow.runID, chosen.runIDs)
  session.flush()
  return chosen.lines

