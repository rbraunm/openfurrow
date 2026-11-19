# SPDX-License-Identifier: Apache-2.0
"""The task kinds a run may be of: OpenFurrow's own, and any a deployment registers before its runs start."""

from __future__ import annotations

from openfurrow.tasks.federationRefresh import federationRefresh
from openfurrow.tasks.model import TaskError, TaskKind, checkedTimeLimit
from openfurrow.tasks.retentionPrune import retentionPrune
from openfurrow.tasks.schedule import Schedule

_kinds: dict[str, TaskKind] = {}


def register(kind: TaskKind) -> None:
  if kind.name in _kinds:
    raise TaskError(f"a task kind '{kind.name}' is registered already")
  Schedule.read(kind.defaultSchedule, "UTC")
  checkedTimeLimit(kind.defaultTimeLimitSeconds)
  _kinds[kind.name] = kind


def kindNamed(name: str) -> TaskKind:
  try:
    return _kinds[name]
  except KeyError:
    raise TaskError(f"no task kind '{name}'; the kinds are {sorted(_kinds)}") from None


def registeredKinds() -> list[TaskKind]:
  return [_kinds[name] for name in sorted(_kinds)]


register(federationRefresh)
register(retentionPrune)
