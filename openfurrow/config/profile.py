# SPDX-License-Identifier: Apache-2.0
"""Configuration schema for an OpenFurrow project.

All project configuration lives in a single YAML file (conventionally
config/openfurrow.yaml) under namespaced sections. The only section today is
the import profile, which declares how an observation CSV is shaped so the
importer can map arbitrary column layouts onto the canonical long-format
observation atom. The profile sets defaults; individual fields can be
overridden per import (by the CLI) for a one-off file.

Every setting is validated loud at construction: contradictory or ambiguous
configuration is rejected here rather than misparsing a data file later.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ImportFormat(str, Enum):
  """Shape of an observation CSV."""

  long = "long"  # one row per observation: plot, assessment, value
  wide = "wide"  # one row per plot, one column per assessment


class LongColumns(BaseModel):
  """Column names carrying each role in a long-format file."""

  model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

  plotNumber: str = Field(default="plotNumber", min_length=1)
  assessmentCode: str = Field(default="assessmentCode", min_length=1)
  value: str = Field(default="value", min_length=1)

  @model_validator(mode="after")
  def distinctColumns(self) -> LongColumns:
    names = [self.plotNumber, self.assessmentCode, self.value]
    if len(set(names)) != len(names):
      raise ValueError("long-format plotNumber, assessmentCode, and value must map to distinct columns")
    return self


class WideColumns(BaseModel):
  """Column roles in a wide-format file.

  The plot identifier is one named column. Assessment columns may be listed
  explicitly; if omitted, every column that is neither the plot column nor an
  ignored column is treated as an assessment and validated against the trial's
  defined assessments at import time.
  """

  model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

  plotNumber: str = Field(default="plotNumber", min_length=1)
  assessmentColumns: list[str] | None = Field(
    default=None, description="Explicit assessment columns; None means infer from the file."
  )
  ignoreColumns: list[str] = Field(
    default_factory=list, description="Columns to skip (extra metadata such as entry, row, range)."
  )

  @model_validator(mode="after")
  def coherentColumns(self) -> WideColumns:
    if len(set(self.ignoreColumns)) != len(self.ignoreColumns):
      raise ValueError("wide-format ignoreColumns contains duplicates")
    if self.plotNumber in self.ignoreColumns:
      raise ValueError(f"wide-format plot column '{self.plotNumber}' is also listed in ignoreColumns")
    if self.assessmentColumns is not None:
      if not self.assessmentColumns:
        raise ValueError("wide-format assessmentColumns, if given, must be non-empty")
      if len(set(self.assessmentColumns)) != len(self.assessmentColumns):
        raise ValueError("wide-format assessmentColumns contains duplicates")
      if self.plotNumber in self.assessmentColumns:
        raise ValueError(f"wide-format plot column '{self.plotNumber}' is also an assessment column")
      overlap = set(self.assessmentColumns) & set(self.ignoreColumns)
      if overlap:
        raise ValueError(f"wide-format columns both assessed and ignored: {sorted(overlap)}")
    return self


class ValueParsing(BaseModel):
  """How raw cell text becomes a typed value."""

  model_config = ConfigDict(extra="forbid")

  decimalSeparator: str = Field(default=".", description="Decimal mark in numeric values; '.' or ','.")
  naTokens: list[str] = Field(
    default_factory=lambda: ["", "NA", "na", "N/A"],
    description="Raw cell values treated as explicitly missing.",
  )

  @field_validator("decimalSeparator")
  @classmethod
  def separatorIsDotOrComma(cls, separator: str) -> str:
    if separator not in {".", ","}:
      raise ValueError("decimalSeparator must be '.' or ','")
    return separator

  @model_validator(mode="after")
  def separatorIsNotNaToken(self) -> ValueParsing:
    if self.decimalSeparator in self.naTokens:
      raise ValueError(f"decimalSeparator '{self.decimalSeparator}' cannot also be an NA token")
    return self


class ImportProfile(BaseModel):
  """How an observation CSV is shaped and parsed."""

  model_config = ConfigDict(extra="forbid")

  format: ImportFormat = ImportFormat.long
  long: LongColumns = Field(default_factory=LongColumns)
  wide: WideColumns = Field(default_factory=WideColumns)
  parsing: ValueParsing = Field(default_factory=ValueParsing)

  def withOverrides(
    self,
    *,
    format: ImportFormat | str | None = None,
    long: dict | None = None,
    wide: dict | None = None,
    parsing: dict | None = None,
  ) -> ImportProfile:
    """Return a copy with the given fields overridden.

    Only the sections and keys actually supplied are changed; the result is
    re-validated, so an override that produces a contradictory profile (for
    example mapping the value column onto the plot column) fails loud here.
    """
    data = self.model_dump(mode="json")
    if format is not None:
      data["format"] = format.value if isinstance(format, ImportFormat) else format
    if long:
      data["long"].update(long)
    if wide:
      data["wide"].update(wide)
    if parsing:
      data["parsing"].update(parsing)
    return ImportProfile.model_validate(data)


class OpenFurrowConfig(BaseModel):
  """Root of the project configuration file.

  The import profile is keyed 'import' in YAML (a Python keyword, so the model
  field is importProfile with that alias). Unknown top-level sections are
  rejected so a misspelled section name fails loud instead of being ignored.
  """

  model_config = ConfigDict(extra="forbid", populate_by_name=True)

  importProfile: ImportProfile = Field(default_factory=ImportProfile, alias="import")
