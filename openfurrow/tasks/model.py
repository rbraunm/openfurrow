# SPDX-License-Identifier: Apache-2.0
"""Scheduled tasks as the store and its surfaces see them (decision 0041).

A task kind is code: the parameters it takes (a pydantic model, checked when a task is
saved), its default schedule and time limit, and the function a run calls. A task is
configuration: a name, a kind, its parameters, a schedule, a time limit and whether it
is enabled. A run of it is recorded from the moment it is requested to its outcome.
"""

from __future__ import annotations

import datetime
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
  from openfurrow.workspace import Workspace

taskNamePattern = re.compile(r"^[a-z][A-Za-z0-9-]{1,63}$")
minimumTimeLimitSeconds = 1
maximumTimeLimitSeconds = 24 * 60 * 60
outputLimitBytes = 64 * 1024


class TaskError(ValueError):
  """A task, schedule, time limit or run request that is refused."""


class RunState(str, Enum):
  requested = "requested"
  running = "running"
  succeeded = "succeeded"
  failed = "failed"
  stopped = "stopped"
  skipped = "skipped"


activeStates = (RunState.requested.value, RunState.running.value)


@dataclass(frozen=True)
class RunContext:
  """What a run is given: the store acting as the scheduler for its task, and a logger whose lines are its output."""

  runID: int
  taskName: str
  workspace: Workspace
  logger: logging.Logger


@dataclass(frozen=True)
class TaskKind:
  name: str
  parameters: type[BaseModel]
  defaultSchedule: str
  defaultTimeLimitSeconds: int
  run: Callable[[RunContext, Any], str]


def checkedTimeLimit(seconds: int) -> int:
  if not minimumTimeLimitSeconds <= seconds <= maximumTimeLimitSeconds:
    raise TaskError(f"a time limit is {minimumTimeLimitSeconds} second to {maximumTimeLimitSeconds // 3600} hours, "
                    f"not {seconds} seconds")
  return seconds


def checkedTaskName(name: str) -> str:
  if not taskNamePattern.match(name):
    raise TaskError(f"'{name}' is not a task name: a lower-case letter, then 1 to 63 letters, digits or '-'")
  return name


class TaskRun(BaseModel):
  model_config = ConfigDict(extra="forbid")

  runID: int
  taskName: str
  requestedBy: str
  requestedAt: datetime.datetime
  startedAt: datetime.datetime | None
  finishedAt: datetime.datetime | None
  state: RunState
  summary: str | None
  output: str


class Task(BaseModel):
  model_config = ConfigDict(extra="forbid")

  name: str
  kind: str
  parameters: dict[str, Any]
  schedule: str
  timeZone: str
  enabled: bool
  timeLimitSeconds: int
  nextRunAt: datetime.datetime | None
  ownerProvider: str | None
  lastRun: TaskRun | None


class SchedulerHeartbeat(BaseModel):
  model_config = ConfigDict(extra="forbid")

  host: str
  processID: int
  lastSeenAt: datetime.datetime
