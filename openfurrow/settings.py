# SPDX-License-Identifier: Apache-2.0
"""Settings: the choices a deployment makes, by scope (decision 0035).

Every setting is defined here once: its key, the values it takes, its default, and the
scopes it may be set at, and the permission that changes it. A value is set at the server,
at a place of the hierarchy, or on a trial, and the nearest one applies: the trial, then
its places from the innermost out, then the server, then the default. Each effective value
carries where it came from, so a page or a report can say so. Unknown keys, values outside
a setting's type, and values at a scope the setting does not allow are refused.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import partial
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from openfurrow.analysis.meanSeparation import MeanComparison
from openfurrow.analysis.missingPlots import MissingPlotPolicy
from openfurrow.identity.model import Permission, SignInMode
from openfurrow.retention import RetentionPolicy, StorageArea, checkedRule, policiesOf, settingKey


class SettingError(ValueError):
  """A setting that does not exist, a value it does not take, or a scope it may not be set at."""


class SettingScope(str, Enum):
  """Where a setting's value may be set."""

  server = "server"
  place = "place"
  trial = "trial"


@dataclass(frozen=True)
class SettingDefinition:
  key: str
  adapter: TypeAdapter
  default: Any
  scopes: frozenset[SettingScope]
  permission: Permission = Permission.changeSettings


everyScope = frozenset(SettingScope)
serverOnly = frozenset({SettingScope.server})


def _timeZone(name: str) -> str:
  """An IANA time zone name, as the scheduler reads schedules in (decision 0041)."""
  try:
    ZoneInfo(name)
  except (ValueError, KeyError) as error:
    raise ValueError(f"'{name}' is not an IANA time zone name such as UTC or Africa/Nairobi ({error})") from None
  return name


def _audience(name: str) -> str:
  """The audience every workload token must name (decision 0042): the server's own name for itself, usually its address."""
  if not 1 <= len(name) <= 255 or not name.isascii() or not name.isprintable() or " " in name:
    raise ValueError("an audience is 1 to 255 printable ASCII characters without spaces, such as the server's address")
  return name


def _retention(area: StorageArea) -> SettingDefinition:
  """An area's retention rule (decision 0044), set down to the trial where a trial's closing can end it."""
  scopes = everyScope if RetentionPolicy.keepUntilClosed in policiesOf[area] else serverOnly
  return SettingDefinition(
    settingKey(area), TypeAdapter(Annotated[str, AfterValidator(partial(checkedRule, area))]),
    RetentionPolicy.keep.value, scopes, Permission.manageRetention,
  )


definitions: dict[str, SettingDefinition] = {
  definition.key: definition for definition in (
    SettingDefinition(
      "analysis.significanceLevel", TypeAdapter(Annotated[float, Field(gt=0.0, lt=1.0)]), 0.05, everyScope,
    ),
    SettingDefinition("analysis.meanComparison", TypeAdapter(MeanComparison), MeanComparison.protectedLSD, everyScope),
    SettingDefinition("analysis.missingPlots", TypeAdapter(MissingPlotPolicy), MissingPlotPolicy.refuse, everyScope),
    SettingDefinition("identity.signInMode", TypeAdapter(SignInMode), SignInMode.open, frozenset({SettingScope.server})),
    SettingDefinition(
      "identity.sessionHours", TypeAdapter(Annotated[int, Field(ge=1, le=720)]), 12, frozenset({SettingScope.server}),
    ),
    SettingDefinition(
      "identity.workloadAudience", TypeAdapter(Annotated[str, AfterValidator(_audience)] | None), None, serverOnly,
    ),
    SettingDefinition("tasks.timeZone", TypeAdapter(Annotated[str, AfterValidator(_timeZone)]), "UTC", serverOnly),
    SettingDefinition(
      "tasks.maximumConcurrentRuns", TypeAdapter(Annotated[int, Field(ge=1, le=64)]), 2, serverOnly,
    ),
    *(_retention(area) for area in StorageArea),
  )
}


def definitionFor(key: str) -> SettingDefinition:
  try:
    return definitions[key]
  except KeyError:
    raise SettingError(f"no setting '{key}'; the settings are {sorted(definitions)}") from None


def checkedValue(key: str, value: Any, scope: SettingScope) -> Any:
  """The value as the setting's type, refused when it is not one or the scope is not allowed."""
  definition = definitionFor(key)
  if scope not in definition.scopes:
    raise SettingError(f"setting '{key}' is not set at the {scope.value} level")
  if value is None:
    raise SettingError(f"setting '{key}' is not set to nothing; clear it instead")
  try:
    return definition.adapter.validate_python(value)
  except ValidationError as error:
    raise SettingError(f"setting '{key}' does not take {value!r}: {error.errors()[0]['msg']}") from None


def allowedValues(key: str) -> list[str] | None:
  """The values a setting takes when it takes one of a fixed list; None for a setting that takes a number or text."""
  return definitionFor(key).adapter.json_schema().get("enum")


def takesNumber(key: str) -> bool:
  return definitionFor(key).adapter.json_schema().get("type") in ("number", "integer")


def jsonValue(key: str, value: Any) -> Any:
  return definitionFor(key).adapter.dump_python(value, mode="json")


class EffectiveSetting(BaseModel):
  """A setting's value where it is read, and where that value was set."""

  model_config = ConfigDict(extra="forbid")

  key: str
  value: Any
  source: str = Field(description="'default', 'server', 'place:<path>' or 'trial:<code>'.")
