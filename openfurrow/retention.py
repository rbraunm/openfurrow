# SPDX-License-Identifier: Apache-2.0
"""Retention: how long each kind of stored data is kept (decision 0044).

What a store holds beside its settings and accounts lies in storage areas: the trial
records, the files as received, the audit log, sessions and tokens, and the runs of
scheduled tasks. Each area has a retention rule, a setting of the registry (decision
0035) named `retention.<area>`:

- `keep`: nothing leaves. The default for everything an owner would miss: trial records,
  files as received and the audit log.
- `keepFor:<period>`: a record leaves once it is older than the period. Expired sessions
  and tokens are kept for 30 days and finished task runs for 90 unless an owner says
  otherwise, so a store nobody tends does not grow without bound.
- `keepUntilClosed:<period>`: a trial's records stay while the trial is open and for the
  period after its closed date.

A period is a count of days, months or years written as in ISO 8601: `P90D`, `P18M`,
`P5Y`. A record is older than a period when its time is at or before now less the
period, the day of the month kept and held to the month's last day.

Pruning removes what the rules let go and nothing else: never part of a trial's record,
so a trial in the store hashes the same before and after, and nothing of a trial under
a hold.
"""

from __future__ import annotations

import calendar
import datetime
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict


retentionTaskName = "retentionPrune"


class RetentionError(ValueError):
  """A retention rule, hold or closing that is refused."""


class StorageArea(str, Enum):
  trialRecords = "trialRecords"
  receivedFiles = "receivedFiles"
  auditLog = "auditLog"
  sessionsAndTokens = "sessionsAndTokens"
  taskRuns = "taskRuns"


class RetentionPolicy(str, Enum):
  keep = "keep"
  keepFor = "keepFor"
  keepUntilClosed = "keepUntilClosed"


class PeriodUnit(str, Enum):
  days = "D"
  months = "M"
  years = "Y"


_periodPattern = re.compile(r"^P([1-9][0-9]{0,4})([DMY])$")
_longestPeriod = {PeriodUnit.days: 36500, PeriodUnit.months: 1200, PeriodUnit.years: 100}


@dataclass(frozen=True)
class Period:
  count: int
  unit: PeriodUnit

  @classmethod
  def read(cls, text: str) -> Period:
    match = _periodPattern.match(text)
    if match is None:
      raise RetentionError(f"'{text}' is not a period: P, a whole number from 1, then D, M or Y, such as P90D, P18M or P5Y")
    period = cls(int(match.group(1)), PeriodUnit(match.group(2)))
    if period.count > _longestPeriod[period.unit]:
      raise RetentionError(f"'{text}' is longer than a hundred years (P36500D, P1200M, P100Y)")
    return period

  @property
  def text(self) -> str:
    return f"P{self.count}{self.unit.value}"

  def before(self, moment: datetime.date) -> datetime.date:
    """The day, or the moment, this period earlier."""
    if self.unit is PeriodUnit.days:
      return moment - datetime.timedelta(days=self.count)
    months = self.count * (12 if self.unit is PeriodUnit.years else 1)
    year, month = divmod(moment.year * 12 + moment.month - 1 - months, 12)
    return moment.replace(year=year, month=month + 1, day=min(moment.day, calendar.monthrange(year, month + 1)[1]))


@dataclass(frozen=True)
class RetentionRule:
  policy: RetentionPolicy
  period: Period | None = None

  @classmethod
  def read(cls, text: str) -> RetentionRule:
    name, separator, period = text.partition(":")
    try:
      policy = RetentionPolicy(name)
    except ValueError:
      raise RetentionError(f"'{text}' is not a retention rule: keep, keepFor:<period> or keepUntilClosed:<period>") from None
    if policy is RetentionPolicy.keep:
      if separator:
        raise RetentionError(f"'{text}' is not a retention rule: keep takes no period")
      return cls(policy)
    if not period:
      raise RetentionError(f"'{text}' is not a retention rule: {policy.value} needs its period, such as {policy.value}:P5Y")
    return cls(policy, Period.read(period))

  @property
  def text(self) -> str:
    return self.policy.value if self.period is None else f"{self.policy.value}:{self.period.text}"

  def letsGo(self, moment: datetime.date, now: datetime.date) -> bool:
    """Whether a record of `moment` (its own time, or its trial's closed date) is older than the period at `now`."""
    return self.period is not None and moment <= self.period.before(now)


_everyPolicy = frozenset(RetentionPolicy)
_byAge = frozenset({RetentionPolicy.keep, RetentionPolicy.keepFor})

# A trial's record has no time of its own that a period could run from while the trial is open, and the server's own
# areas belong to no trial that could be closed.
policiesOf: dict[StorageArea, frozenset[RetentionPolicy]] = {
  StorageArea.trialRecords: frozenset({RetentionPolicy.keep, RetentionPolicy.keepUntilClosed}),
  StorageArea.receivedFiles: _everyPolicy,
  StorageArea.auditLog: _everyPolicy,
  StorageArea.sessionsAndTokens: _byAge,
  StorageArea.taskRuns: _byAge,
}
trialBoundAreas = (StorageArea.trialRecords, StorageArea.receivedFiles, StorageArea.auditLog)
# What an area is kept by until its setting says otherwise.
defaultRuleOf: dict[StorageArea, str] = {
  StorageArea.trialRecords: "keep",
  StorageArea.receivedFiles: "keep",
  StorageArea.auditLog: "keep",
  StorageArea.sessionsAndTokens: "keepFor:P30D",
  StorageArea.taskRuns: "keepFor:P90D",
}


def settingKey(area: StorageArea) -> str:
  return f"retention.{area.value}"


def checkedRule(area: StorageArea, text: str) -> str:
  """A retention rule as the area's setting keeps it, refused when it is not a rule or not one the area takes."""
  rule = RetentionRule.read(text.strip())
  if rule.policy not in policiesOf[area]:
    taken = ", ".join(policy.value for policy in RetentionPolicy if policy in policiesOf[area])
    raise RetentionError(f"{area.value} is not kept by {rule.policy.value}; it takes {taken}")
  return rule.text


_retentionActions = frozenset({"retention.prune", "retention.hold", "retention.release", "trial.close", "trial.reopen"})
settingActions = ("setting.set", "setting.clear")


def isRetentionRecord(action: str, detail: dict[str, Any]) -> bool:
  """Whether an audit event records a pruning, a hold, a closing or a change of a retention setting: the events the
  audit log keeps for the whole period from their own time, whatever else lets its neighbours go."""
  if action in settingActions:
    return str(detail["key"]).startswith("retention.")
  return action in _retentionActions


class Hold(BaseModel):
  model_config = ConfigDict(extra="forbid")

  trialCode: str
  reason: str
  heldByKind: str
  heldByName: str | None
  heldAt: datetime.datetime


class RuleAt(BaseModel):
  model_config = ConfigDict(extra="forbid")

  scope: str
  rule: str


class AreaStatus(BaseModel):
  """One area: how much it holds, the rule the server gives it and where that was set, and the places and trials
  that set their own."""

  model_config = ConfigDict(extra="forbid")

  area: StorageArea
  count: int
  sizeBytes: int
  rule: str
  source: str
  setBelow: list[RuleAt]


class RetentionStatus(BaseModel):
  model_config = ConfigDict(extra="forbid")

  areas: list[AreaStatus]
  holds: list[Hold]


class PruneLine(BaseModel):
  """What leaves one area at one scope -- a trial where the area is a trial's, otherwise a place or the server --
  under which rule, set where; `detail` names it as the area can."""

  model_config = ConfigDict(extra="forbid")

  area: StorageArea
  scope: str
  count: int
  sizeBytes: int
  rule: str
  source: str
  detail: dict[str, Any]


class PruneReport(BaseModel):
  """What a pruning at `at` would remove, or did."""

  model_config = ConfigDict(extra="forbid")

  at: datetime.datetime
  lines: list[PruneLine]

  def totals(self) -> dict[StorageArea, tuple[int, int]]:
    """Count and bytes by area, for the areas something leaves."""
    totals: dict[StorageArea, tuple[int, int]] = {}
    for line in self.lines:
      count, size = totals.get(line.area, (0, 0))
      totals[line.area] = (count + line.count, size + line.sizeBytes)
    return totals


_areaNouns = {
  StorageArea.trialRecords: ("trial record", "trial records"),
  StorageArea.receivedFiles: ("received file", "received files"),
  StorageArea.auditLog: ("audit event", "audit events"),
  StorageArea.sessionsAndTokens: ("session or token", "sessions and tokens"),
  StorageArea.taskRuns: ("task run", "task runs"),
}


def summaryOf(report: PruneReport) -> str:
  """One line for a run's record: what was pruned, by area."""
  totals = report.totals()
  if not totals:
    return "nothing pruned: no retention rule lets anything go"
  parts = [f"{count} {_areaNouns[area][count != 1]} ({size} bytes)"
           for area, (count, size) in ((area, totals[area]) for area in StorageArea if area in totals)]
  return "pruned " + ", ".join(parts)
