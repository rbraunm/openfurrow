# SPDX-License-Identifier: Apache-2.0
"""Ratings and assessments: what is rated, and each occasion it is rated on.

Shaped on EPPO PP 1/181, Appendix 1, section 3.2 and the trait, method and scale model of
MIAPPE and BrAPI (decision 0017). A rating says what is rated and the rules its values
obey: the data type, unit, limits or categories, what it measures and how it is
transformed for analysis. An assessment is one occasion a rating is taken: when, at which
crop and target stage, timed from which application, by whom. Observations belong to an
assessment, so each occasion is analysed on its own.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from openfurrow.schema.dateAndTime import CalendarDate
from openfurrow.schema.quantity import Quantity, requirePositive


class AssessmentDataType(str, Enum):
  """The kind of value a rating records."""

  numeric = "numeric"
  categorical = "categorical"
  ordinal = "ordinal"


class MeasurementKind(str, Enum):
  """What a numeric rating measures, guiding transform choice and recommendation.

  Declared, never inferred: unspecified is the default and is not second-guessed from
  the data. It drives transform recommendation and the transform/kind sanity check.
  """

  unspecified = "unspecified"
  count = "count"
  proportion = "proportion"
  continuous = "continuous"


class Transform(str, Enum):
  """A variance-stabilizing transform applied to a numeric rating (decision 0006).

  Declared per rating. When set, the analysis runs on the transformed scale and the
  transform enters the content hash. These are the plain forms with fail-loud domains;
  offsets for zero and boundary values are a separate future slice.
  """

  none = "none"
  sqrt = "sqrt"
  log = "log"
  arcsinSqrt = "arcsinSqrt"
  logit = "logit"


class Rating(BaseModel):
  """What is rated and the rules its values must obey.

  Value-domain rules are tied to the data type and validated here so that observation
  import checks against a single source of truth: a numeric rating may bound a range; a
  categorical or ordinal one must enumerate its allowed values.
  """

  model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)

  ratingCode: str = Field(min_length=1, description="Stable per-trial code, e.g. 'SEV'.")
  name: str = Field(min_length=1)
  ratingType: str | None = Field(default=None, min_length=1, description="E.g. 'disease severity', 'percent control'.")
  partRated: str | None = Field(default=None, min_length=1, description="E.g. 'flag leaf', 'whole plot'.")
  method: str | None = Field(default=None, min_length=1, description="How the value is obtained.")
  targetCode: str | None = Field(default=None, min_length=1, description="The target rated, when there is one.")
  dataType: AssessmentDataType
  unit: str | None = Field(default=None, min_length=1, description="Unit of a numeric rating, e.g. 'kg/ha'.")
  minValue: float | None = Field(default=None, description="Inclusive lower limit of a numeric value.")
  maxValue: float | None = Field(default=None, description="Inclusive upper limit of a numeric value.")
  allowedValues: list[str] | None = Field(default=None, description="Permitted values of a categorical or ordinal rating.")
  measurementKind: MeasurementKind = Field(
    default=MeasurementKind.unspecified,
    description="What a numeric rating measures; guides transform recommendation. Declared, not inferred.",
  )
  transform: Transform = Field(
    default=Transform.none,
    description="Variance-stabilizing transform for a numeric rating; enters the content hash (0006).",
  )

  @model_validator(mode="after")
  def domainMatchesDataType(self) -> Rating:
    code = self.ratingCode
    if self.dataType is AssessmentDataType.numeric:
      if self.allowedValues is not None:
        raise ValueError(f"rating '{code}': numeric type cannot define allowedValues")
      if self.minValue is not None and self.maxValue is not None and self.minValue > self.maxValue:
        raise ValueError(f"rating '{code}': minValue {self.minValue} exceeds maxValue {self.maxValue}")
    else:
      if self.transform is not Transform.none:
        raise ValueError(f"rating '{code}': {self.dataType.value} type cannot declare a transform")
      if self.measurementKind is not MeasurementKind.unspecified:
        raise ValueError(f"rating '{code}': {self.dataType.value} type cannot declare a measurementKind")
      if self.minValue is not None or self.maxValue is not None:
        raise ValueError(f"rating '{code}': {self.dataType.value} type cannot define a numeric range")
      if self.unit is not None:
        raise ValueError(f"rating '{code}': {self.dataType.value} type cannot declare a unit")
      if not self.allowedValues:
        raise ValueError(f"rating '{code}': {self.dataType.value} type must enumerate allowedValues")
      if len(set(self.allowedValues)) != len(self.allowedValues):
        raise ValueError(f"rating '{code}': allowedValues contains duplicates")
    return self


class Assessment(BaseModel):
  """One occasion a rating is taken: its plan, and when and how it was done."""

  model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)

  assessmentCode: str = Field(min_length=1, description="Stable per-trial code observations are keyed by.")
  ratingCode: str = Field(min_length=1, description="The rating taken on this occasion.")
  timing: str | None = Field(default=None, min_length=1, description="The planned timing, e.g. '14 DA-A'.")
  date: CalendarDate | None = Field(default=None, description="The day it was done.")
  cropStage: str | None = Field(default=None, min_length=1, description="Growth stage of the crop, BBCH where possible.")
  targetStage: str | None = Field(default=None, min_length=1, description="Stage of the target.")
  timedFromApplicationCode: str | None = Field(
    default=None, min_length=1, description="The application days are counted from.",
  )
  assessedBy: str | None = Field(default=None, min_length=1)
  sampleSize: Quantity | None = Field(default=None, description="E.g. 10 plants, 1 m2.")
  notes: str | None = Field(default=None, min_length=1)

  @field_validator("sampleSize")
  @classmethod
  def sampleSizeIsPositive(cls, sampleSize: Quantity | None) -> Quantity | None:
    return requirePositive(sampleSize, "sampleSize")
