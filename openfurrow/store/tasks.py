# SPDX-License-Identifier: Apache-2.0
"""Scheduled tasks and their runs in the store (decision 0041).

Times are kept as naive UTC like every other time in the store and handed out with their
zone. A task's next run time is worked out from its schedule in the server's time zone
whenever the schedule, the zone or its enabled flag changes, and by the scheduler each
time the task comes due; a disabled task has none.
"""

from __future__ import annotations

import datetime
import json

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from openfurrow.retention import retentionTaskName
from openfurrow.store.database import NotFoundError, ScheduledTaskRow, SchedulerHeartbeatRow, TaskRunRow
from openfurrow.store.settingValues import effectiveSettings
from openfurrow.tasks.kinds import kindNamed
from openfurrow.tasks.retentionPrune import retentionPrune
from openfurrow.tasks.model import (RunState, SchedulerHeartbeat, Task, TaskError, TaskRun, activeStates,
                                    checkedTaskName, checkedTimeLimit)
from openfurrow.tasks.schedule import Schedule, ScheduleError


def stored(moment: datetime.datetime) -> datetime.datetime:
  if moment.tzinfo is None:
    raise ValueError("a moment carries its time zone")
  return moment.astimezone(datetime.UTC).replace(tzinfo=None)


def aware(moment: datetime.datetime | None) -> datetime.datetime | None:
  return None if moment is None else moment.replace(tzinfo=datetime.UTC)


def serverSetting(session: Session, key: str):
  return {setting.key: setting.value for setting in effectiveSettings(session, "server")}[key]


def readSchedule(expression: str, zone: str) -> Schedule:
  try:
    return Schedule.read(expression, zone)
  except ScheduleError as error:
    raise TaskError(str(error)) from None


def nextRun(row: ScheduledTaskRow, zone: str, at: datetime.datetime) -> datetime.datetime | None:
  if not row.enabled:
    return None
  return stored(readSchedule(row.schedule, zone).nextAfter(at))


def checkedParameters(kind: str, parameters: dict) -> BaseModel:
  try:
    return kindNamed(kind).parameters.model_validate(parameters)
  except ValidationError as error:
    raise TaskError(f"a {kind} task does not take {parameters}: {error.errors()[0]['msg']}") from None


def taskRow(session: Session, name: str) -> ScheduledTaskRow:
  row = session.get(ScheduledTaskRow, name)
  if row is None:
    raise NotFoundError(f"task '{name}' not found")
  return row


def createTask(session: Session, name: str, kind: str, parameters: dict, at: datetime.datetime,
               ownerProvider: str | None = None, ownerFeature: str | None = None) -> None:
  checkedTaskName(name)
  definition = kindNamed(kind)
  checked = checkedParameters(kind, parameters)
  if session.get(ScheduledTaskRow, name) is not None:
    raise TaskError(f"task '{name}' already exists")
  row = ScheduledTaskRow(name=name, kind=kind, parametersJSON=checked.model_dump_json(),
                         schedule=definition.defaultSchedule, enabled=True,
                         timeLimitSeconds=definition.defaultTimeLimitSeconds, createdAt=stored(at),
                         ownerProvider=ownerProvider, ownerFeature=ownerFeature)
  row.nextRunAt = nextRun(row, serverSetting(session, "tasks.timeZone"), at)
  session.add(row)
  session.flush()


def deleteTask(session: Session, name: str) -> None:
  """Delete a task and its runs. A task kept for a feature goes with that feature, and one with a run requested or
  running waits for it."""
  row = taskRow(session, name)
  if row.ownerProvider is not None:
    raise TaskError(f"task '{name}' is kept for the identity provider '{row.ownerProvider}' and is not deleted "
                    "while that provider uses it")
  if row.ownerFeature is not None:
    raise TaskError(f"task '{name}' is kept for the store's own {row.ownerFeature} and is not deleted; disable it "
                    "to stop its runs")
  if hasActiveRun(session, name):
    raise TaskError(f"task '{name}' has a run requested or running; delete it once that run has ended")
  session.delete(row)
  session.flush()
def createFeatureTasks(session: Session, at: datetime.datetime) -> None:
  """The tasks a store's own features need, made with the store: retention's daily pruning (decision 0044)."""
  createTask(session, retentionTaskName, retentionPrune.name, {}, at, ownerFeature="retention")


def _run(row: TaskRunRow) -> TaskRun:
  return TaskRun(runID=row.runID, taskName=row.taskName, requestedBy=row.requestedBy,
                 requestedAt=aware(row.requestedAt), startedAt=aware(row.startedAt), finishedAt=aware(row.finishedAt),
                 state=RunState(row.state), summary=row.summary, output=row.output)


def _latestRun(session: Session, name: str) -> TaskRunRow | None:
  return session.execute(select(TaskRunRow).where(TaskRunRow.taskName == name)
                         .order_by(TaskRunRow.runID.desc()).limit(1)).scalar_one_or_none()


def _task(session: Session, row: ScheduledTaskRow, zone: str) -> Task:
  latest = _latestRun(session, row.name)
  return Task(name=row.name, kind=row.kind, parameters=json.loads(row.parametersJSON), schedule=row.schedule,
              timeZone=zone, enabled=row.enabled, timeLimitSeconds=row.timeLimitSeconds,
              nextRunAt=aware(row.nextRunAt), ownerProvider=row.ownerProvider, ownerFeature=row.ownerFeature,
              lastRun=None if latest is None else _run(latest))


def listTasks(session: Session) -> list[Task]:
  zone = serverSetting(session, "tasks.timeZone")
  rows = session.execute(select(ScheduledTaskRow).order_by(ScheduledTaskRow.name)).scalars().all()
  return [_task(session, row, zone) for row in rows]


def task(session: Session, name: str) -> Task:
  return _task(session, taskRow(session, name), serverSetting(session, "tasks.timeZone"))


def setSchedule(session: Session, name: str, expression: str, at: datetime.datetime) -> None:
  row = taskRow(session, name)
  zone = serverSetting(session, "tasks.timeZone")
  row.schedule = readSchedule(expression, zone).expression
  row.nextRunAt = nextRun(row, zone, at)
  session.flush()


def setTimeLimit(session: Session, name: str, seconds: int) -> None:
  taskRow(session, name).timeLimitSeconds = checkedTimeLimit(seconds)
  session.flush()


def setEnabled(session: Session, name: str, enabled: bool, at: datetime.datetime) -> None:
  row = taskRow(session, name)
  row.enabled = enabled
  row.nextRunAt = nextRun(row, serverSetting(session, "tasks.timeZone"), at)
  session.flush()


def rescheduleAll(session: Session, at: datetime.datetime) -> None:
  """Every task's next run worked out again, after the server's time zone changed."""
  zone = serverSetting(session, "tasks.timeZone")
  for row in session.execute(select(ScheduledTaskRow)).scalars().all():
    row.nextRunAt = nextRun(row, zone, at)
  session.flush()


def hasActiveRun(session: Session, name: str) -> bool:
  return session.execute(select(TaskRunRow.runID).where(TaskRunRow.taskName == name,
                                                        TaskRunRow.state.in_(activeStates)).limit(1)).first() is not None


def requestRun(session: Session, name: str, requestedBy: str, at: datetime.datetime) -> int:
  taskRow(session, name)
  if hasActiveRun(session, name):
    raise TaskError(f"task '{name}' has a run requested or running already")
  row = TaskRunRow(taskName=name, requestedBy=requestedBy, requestedAt=stored(at), state=RunState.requested.value,
                   output="")
  session.add(row)
  session.flush()
  return row.runID


def runs(session: Session, name: str, limit: int) -> list[TaskRun]:
  taskRow(session, name)
  rows = session.execute(select(TaskRunRow).where(TaskRunRow.taskName == name)
                         .order_by(TaskRunRow.runID.desc()).limit(limit)).scalars().all()
  return [_run(row) for row in rows]


def heartbeat(session: Session) -> SchedulerHeartbeat | None:
  row = session.get(SchedulerHeartbeatRow, 1)
  if row is None:
    return None
  return SchedulerHeartbeat(host=row.host, processID=row.processID, lastSeenAt=aware(row.lastSeenAt))

