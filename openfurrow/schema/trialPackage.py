# SPDX-License-Identifier: Apache-2.0
"""Trial package schema: the import/export boundary for an OpenFurrow trial design.

A trial package is the design document for a single trial -- its metadata, the
treatments under comparison, the experimental design used to lay them out, and
the assessments that will be collected. Observations are imported separately and
are not part of the design package.

Every model fails loud: invalid state is rejected at construction, not deferred
to analysis time. There are no silent coercions or fallback defaults that paper
over a malformed package.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DesignType(str, Enum):
  """Experimental design used to lay out treatments into plots."""

  rcbd = "rcbd"  # randomized complete block design


class AssessmentDataType(str, Enum):
  """The kind of value an assessment records."""

  numeric = "numeric"
  categorical = "categorical"
  ordinal = "ordinal"


class MeasurementKind(str, Enum):
  """What a numeric assessment measures, guiding transform choice and recommendation.

  Declared, never inferred: unspecified is the default and is not second-guessed from
  the data. It drives transform recommendation and the transform/kind sanity check.
  """

  unspecified = "unspecified"
  count = "count"
  proportion = "proportion"
  continuous = "continuous"


class Transform(str, Enum):
  """A variance-stabilizing transform applied to a numeric assessment (decision 0006).

  Declared per assessment. When set, the analysis runs on the transformed scale and
  the transform enters the content hash. These are the plain forms with fail-loud
  domains; offsets for zero and boundary values are a separate future slice.
  """

  none = "none"
  sqrt = "sqrt"
  log = "log"
  arcsinSqrt = "arcsinSqrt"
  logit = "logit"


class TrialMetadata(BaseModel):
  """Descriptive metadata for a single trial.

  Investigator and organization use generic labels rather than modeling a full
  actor/organization graph -- that belongs to the canonical store, not to the
  design package.
  """

  model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

  trialCode: str = Field(min_length=1, description="Short stable identifier, e.g. 'ESV-2025-01'.")
  title: str = Field(min_length=1)
  crop: str = Field(min_length=1)
  season: str = Field(min_length=1, description="Free-form season label, e.g. '2025 Spring'.")
  site: str = Field(min_length=1)
  objective: str = Field(min_length=1)
  investigator: str | None = None
  organization: str | None = None


class Treatment(BaseModel):
  """One treatment under comparison.

  A treatment with no product is an untreated control. A rate and its unit are
  inseparable: a number without a unit is meaningless, and a unit without a
  number is incomplete, so the package is rejected if exactly one is present.
  """

  model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

  treatmentCode: str = Field(min_length=1, description="Stable per-trial code, e.g. 'T1'.")
  name: str = Field(min_length=1)
  product: str | None = Field(default=None, description="Material applied; omit for an untreated control.")
  rate: float | None = Field(default=None, gt=0.0)
  rateUnit: str | None = Field(default=None, min_length=1, description="Unit for rate, e.g. 'L/ha'.")
  timing: str | None = Field(default=None, description="Application timing or growth stage.")

  @model_validator(mode="after")
  def rateAndUnitTogether(self) -> Treatment:
    if (self.rate is None) != (self.rateUnit is None):
      raise ValueError(
        f"treatment '{self.treatmentCode}': rate and rateUnit must be provided together "
        f"(got rate={self.rate!r}, rateUnit={self.rateUnit!r})"
      )
    return self


class DesignSpecification(BaseModel):
  """How treatments are laid out into plots.

  For the v0.1 MVP only RCBD is supported. The randomization seed is mandatory:
  reproducibility is not optional, so a layout that cannot be regenerated from a
  recorded seed is not a valid OpenFurrow design.
  """

  model_config = ConfigDict(extra="forbid")

  designType: DesignType = DesignType.rcbd
  replications: int = Field(ge=2, description="Number of complete blocks; RCBD requires at least 2.")
  randomizationSeed: int = Field(ge=0, description="Explicit seed; the layout must be regenerable from it.")


class AssessmentDefinition(BaseModel):
  """A trait or measurement to be collected, and the rules its values must obey.

  Value-domain rules are tied to the data type and validated here so that
  observation import can reject out-of-domain values against a single source of
  truth: numeric assessments may bound a range; categorical and ordinal
  assessments must enumerate their allowed values.
  """

  model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

  assessmentCode: str = Field(min_length=1, description="Stable per-trial code, e.g. 'YIELD'.")
  name: str = Field(min_length=1)
  dataType: AssessmentDataType
  unit: str | None = Field(default=None, description="Unit for numeric assessments, e.g. 'kg/ha'.")
  timing: str | None = Field(default=None, description="Assessment date or growth stage.")
  minValue: float | None = Field(default=None, description="Inclusive lower bound for numeric values.")
  maxValue: float | None = Field(default=None, description="Inclusive upper bound for numeric values.")
  allowedValues: list[str] | None = Field(default=None, description="Permitted values for categorical/ordinal.")
  measurementKind: MeasurementKind = Field(
    default=MeasurementKind.unspecified,
    description="What a numeric assessment measures; guides transform recommendation. Declared, not inferred.",
  )
  transform: Transform = Field(
    default=Transform.none,
    description="Variance-stabilizing transform for a numeric assessment; enters the content hash (0006).",
  )

  @model_validator(mode="after")
  def domainMatchesDataType(self) -> AssessmentDefinition:
    code = self.assessmentCode
    if self.dataType is AssessmentDataType.numeric:
      if self.allowedValues is not None:
        raise ValueError(f"assessment '{code}': numeric type cannot define allowedValues")
      if self.minValue is not None and self.maxValue is not None and self.minValue > self.maxValue:
        raise ValueError(
          f"assessment '{code}': minValue {self.minValue} exceeds maxValue {self.maxValue}"
        )
    else:
      if self.transform is not Transform.none:
        raise ValueError(
          f"assessment '{code}': {self.dataType.value} type cannot declare a transform"
        )
      if self.measurementKind is not MeasurementKind.unspecified:
        raise ValueError(
          f"assessment '{code}': {self.dataType.value} type cannot declare a measurementKind"
        )
      if self.minValue is not None or self.maxValue is not None:
        raise ValueError(
          f"assessment '{code}': {self.dataType.value} type cannot define a numeric range"
        )
      if not self.allowedValues:
        raise ValueError(
          f"assessment '{code}': {self.dataType.value} type must enumerate allowedValues"
        )
      if len(set(self.allowedValues)) != len(self.allowedValues):
        raise ValueError(f"assessment '{code}': allowedValues contains duplicates")
    return self


class TrialPackage(BaseModel):
  """The complete design document for one trial.

  Treatment and assessment codes must each be unique within the package; they
  are the join keys observation import and analysis rely on, so a collision is
  rejected here rather than producing silently merged rows downstream.
  """

  model_config = ConfigDict(extra="forbid")

  schemaVersion: str = Field(min_length=1, description="Package schema version for migration/reproducibility.")
  trial: TrialMetadata
  treatments: list[Treatment] = Field(min_length=2, description="At least two treatments to compare.")
  design: DesignSpecification
  assessments: list[AssessmentDefinition] = Field(min_length=1)

  @field_validator("treatments")
  @classmethod
  def uniqueTreatmentCodes(cls, treatments: list[Treatment]) -> list[Treatment]:
    codes = [t.treatmentCode for t in treatments]
    if len(set(codes)) != len(codes):
      raise ValueError(f"duplicate treatmentCode values: {sorted(_duplicates(codes))}")
    return treatments

  @field_validator("assessments")
  @classmethod
  def uniqueAssessmentCodes(cls, assessments: list[AssessmentDefinition]) -> list[AssessmentDefinition]:
    codes = [a.assessmentCode for a in assessments]
    if len(set(codes)) != len(codes):
      raise ValueError(f"duplicate assessmentCode values: {sorted(_duplicates(codes))}")
    return assessments

  @property
  def plotCount(self) -> int:
    """Total plots the design produces; derived, never stored."""
    return len(self.treatments) * self.design.replications


def _duplicates(values: list[str]) -> set[str]:
  seen: set[str] = set()
  repeated: set[str] = set()
  for value in values:
    if value in seen:
      repeated.add(value)
    seen.add(value)
  return repeated
