# SPDX-License-Identifier: Apache-2.0
"""Settings: the choices a deployment makes, by scope (decision 0035).

Every setting is defined here once: its key, the values it takes, its default, and the
scopes it may be set at. A value is set at the server, at a place of the hierarchy, or on
a trial, and the nearest one applies: the trial, then its places from the innermost out,
then the server, then the default. Each effective value carries where it came from, so a
page or a report can say so. Unknown keys, values outside a setting's type, and values at
a scope the setting does not allow are refused.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from openfurrow.analysis.meanSeparation import MeanComparison


class SettingError(ValueError):
  """A setting that does not exist, a value it does not take, or a scope it may not be set at."""


class SettingScope(str, Enum):
  """Where a setting's value may be set."""

  server = "server"
  place = "place"
  trial = "trial"


class MissingPlotPolicy(str, Enum):
  """What an analysis does with a plot that has no value (decision 0003)."""

  refuse = "refuse"  # the analysis stops and names the missing plots


@dataclass(frozen=True)
class SettingDefinition:
  key: str
  adapter: TypeAdapter
  default: Any
  scopes: frozenset[SettingScope]


everyScope = frozenset(SettingScope)

definitions: dict[str, SettingDefinition] = {
  definition.key: definition for definition in (
    SettingDefinition(
      "analysis.significanceLevel", TypeAdapter(Annotated[float, Field(gt=0.0, lt=1.0)]), 0.05, everyScope,
    ),
    SettingDefinition("analysis.meanComparison", TypeAdapter(MeanComparison), MeanComparison.protectedLSD, everyScope),
    SettingDefinition("analysis.missingPlots", TypeAdapter(MissingPlotPolicy), MissingPlotPolicy.refuse, everyScope),
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
  try:
    return definition.adapter.validate_python(value)
  except ValidationError as error:
    raise SettingError(f"setting '{key}' does not take {value!r}: {error.errors()[0]['msg']}") from None


def jsonValue(key: str, value: Any) -> Any:
  return definitionFor(key).adapter.dump_python(value, mode="json")


class EffectiveSetting(BaseModel):
  """A setting's value where it is read, and where that value was set."""

  model_config = ConfigDict(extra="forbid")

  key: str
  value: Any
  source: str = Field(description="'default', 'server', 'place:<path>' or 'trial:<code>'.")
