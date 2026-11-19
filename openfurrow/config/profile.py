# SPDX-License-Identifier: Apache-2.0
"""Configuration schema for an OpenFurrow project.

All project configuration lives in a single YAML file (conventionally
config/openfurrow.yaml) under namespaced sections: the import profile, the
analysis settings, and the service settings. The import profile declares how an
observation CSV is shaped so the importer can map arbitrary column layouts onto
the canonical long-format observation atom; it sets defaults, and individual
fields can be overridden per import for a one-off file.

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
  subsample: str | None = Field(
    default=None, min_length=1, description="The column numbering subsamples, for assessments that take them.",
  )

  @model_validator(mode="after")
  def distinctColumns(self) -> LongColumns:
    names = [self.plotNumber, self.assessmentCode, self.value] + ([self.subsample] if self.subsample else [])
    if len(set(names)) != len(names):
      raise ValueError("long-format plotNumber, assessmentCode, value and subsample must map to distinct columns")
    return self


class WideColumns(BaseModel):
  """Column roles in a wide-format file.

  The plot identifier is one named column. Assessment columns may be mapped
  explicitly, each column name to the assessment code it holds; if omitted, every
  column that is neither the plot column nor an ignored column is taken as the
  assessment of the same code and validated against the trial at import time. Several
  columns may hold one assessment only when it takes subsamples: they are its subsamples
  in the order of the file (decision 0033), which the importer checks against the trial.
  """

  model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

  plotNumber: str = Field(default="plotNumber", min_length=1)
  assessmentColumns: dict[str, str] | None = Field(
    default=None,
    description="Column name to the assessment code it holds; None means every other column, named by its code.",
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


class TLSSettings(BaseModel):
  """HTTPS for the service (optional; off by default).

  HTTPS is opt-in because the first target is a local, single-user analyst tool bound
  to loopback, where TLS buys nothing and a mandatory certificate would be pure
  friction. It becomes necessary the moment the service is reachable from another
  machine -- the self-hostable server of decision 0011 -- so the configuration exists
  now and the switch is one setting, not a rebuild.

  Certificates are supplied by the operator. Automatic certificate issuance
  (Let's Encrypt / ACME) is deliberately NOT implemented: it needs a public DNS name,
  inbound reachability, and a renewal daemon -- none of which a local or LAN
  deployment has. It belongs with the internet-facing server, and this shape does not
  block it: an ACME-obtained certificate is just a certificate/key pair pointed at
  here.
  """

  model_config = ConfigDict(extra="forbid")

  enabled: bool = False
  certificateFile: str | None = Field(
    default=None, description="Path to the PEM certificate (chain) file."
  )
  privateKeyFile: str | None = Field(
    default=None, description="Path to the PEM private key file."
  )

  @model_validator(mode="after")
  def certificateRequiredWhenEnabled(self) -> "TLSSettings":
    # Fail at construction, not at the first request: a service that believes it is
    # serving HTTPS but silently fell back to HTTP is a security bug, not a warning.
    if not self.enabled:
      return self
    missing = [
      name for name, value in
      (("certificateFile", self.certificateFile), ("privateKeyFile", self.privateKeyFile))
      if not value
    ]
    if missing:
      raise ValueError(f"tls.enabled is true but {', '.join(missing)} is not set")
    return self


defaultMaxUploadBytes = 16 * 1024 * 1024


class ServiceSettings(BaseModel):
  """How the HTTP service binds (decision 0009).

  The default binds to loopback: a local analyst tool must not become a network
  service by accident. Serving beyond this machine is a deliberate change of `host`.
  """

  model_config = ConfigDict(extra="forbid")

  host: str = Field(default="127.0.0.1", min_length=1)
  port: int = Field(default=8420, gt=0, lt=65536)
  maxUploadBytes: int = Field(
    default=defaultMaxUploadBytes, gt=0,
    description="Largest accepted request body. Bounds memory use; oversize requests "
                "are rejected with 413 before being read. Trial packages and observation "
                "CSVs are small, so the default (16 MiB) is generous. It is also the largest "
                "file an import keeps as received (decision 0044), on every surface.",
  )
  tls: TLSSettings = Field(default_factory=TLSSettings)


class OpenFurrowConfig(BaseModel):
  """Root of the project configuration file.

  The import profile is keyed 'import' in YAML (a Python keyword, so the model
  field is importProfile with that alias). Unknown top-level sections are
  rejected so a misspelled section name fails loud instead of being ignored.
  """

  model_config = ConfigDict(extra="forbid", populate_by_name=True)

  importProfile: ImportProfile = Field(default_factory=ImportProfile, alias="import")
  service: ServiceSettings = Field(default_factory=ServiceSettings)
