# SPDX-License-Identifier: Apache-2.0
"""The places trials live in (decision 0034).

A store has an ordered list of hierarchy levels -- organization, project and study by
default -- and places at each level, every place below the first inside one place of the
level above. A trial is always the last level and belongs to one place of the last level
the store has. Levels are configured, not fixed: an administrator adds levels (a program,
a season) or removes them to make the groups that roles and settings attach to finer or
simpler. A place is named by its path, the codes from the top down joined by '/'.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

defaultLevelCodes = ("organization", "project", "study")
placeCodePattern = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def checkPlaceCode(code: str) -> str:
  if not placeCodePattern.match(code):
    raise ValueError(f"'{code}' is not a code: letters, digits, '.', '_' and '-', starting with a letter or digit")
  return code


def splitPath(path: str) -> list[str]:
  """The codes of a place path, each checked."""
  codes = path.split("/")
  for code in codes:
    checkPlaceCode(code)
  return codes


class HierarchyLevel(BaseModel):
  """One level of the hierarchy. A built-in level is named by the message catalog; any other names itself."""

  model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

  levelCode: str
  name: str | None = Field(default=None, min_length=1)

  @field_validator("levelCode")
  @classmethod
  def codeIsACode(cls, levelCode: str) -> str:
    return checkPlaceCode(levelCode)

  @model_validator(mode="after")
  def customLevelIsNamed(self) -> HierarchyLevel:
    if self.name is None and self.levelCode not in defaultLevelCodes:
      raise ValueError(f"level '{self.levelCode}' is not built in, so it needs a name")
    return self


class Place(BaseModel):
  """A place in the hierarchy: its path, its level and its name."""

  model_config = ConfigDict(extra="forbid")

  path: str
  levelCode: str
  name: str
