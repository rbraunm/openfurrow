# SPDX-License-Identifier: Apache-2.0
"""Treatments: what is compared in a trial, and what each one is made of.

Shaped on EPPO PP 1/181, Appendix 1, section 2 (decision 0016). A treatment may state its
role in the comparison and has zero or more lines. A line is one product at one rate,
applied at the applications it names: products that share an application are a mixture,
and products at successive applications are a program. A treatment that is a variety or
a cultural practice has no lines; neither has the untreated control.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from openfurrow.schema.quantity import Quantity, requirePositive


class TreatmentRole(str, Enum):
  """What a treatment is for in the comparison (EPPO PP 1/152 and PP 1/181).

  Declared, never inferred: a treatment whose role is not stated has none, and nothing
  reads one out of its name or its lines.
  """

  test = "test"                          # what the trial evaluates
  reference = "reference"                # a reference product or standard practice
  untreatedControl = "untreatedControl"  # receives none of the trial's treatments
  otherControl = "otherControl"          # another control, e.g. hand-weeded or uninoculated


class ProductKind(str, Enum):
  """What a product line is, so that an adjuvant is not read as an active treatment."""

  herbicide = "herbicide"
  fungicide = "fungicide"
  insecticide = "insecticide"
  growthRegulator = "growthRegulator"
  fertilizer = "fertilizer"
  biological = "biological"
  adjuvant = "adjuvant"
  other = "other"


class RateBasis(str, Enum):
  """What the rate is a rate of. A dose read on the wrong basis is a wrong dose."""

  formulatedProduct = "formulatedProduct"
  activeSubstance = "activeSubstance"


class ActiveSubstance(BaseModel):
  """One active substance of a product, with its concentration when known."""

  model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

  name: str = Field(min_length=1, description="Common name, e.g. 'azoxystrobin'.")
  concentration: Quantity | None = Field(default=None, description="E.g. 250 g/L.")

  @field_validator("concentration")
  @classmethod
  def concentrationIsPositive(cls, concentration: Quantity | None) -> Quantity | None:
    return requirePositive(concentration, "an active substance's concentration")


class TreatmentLine(BaseModel):
  """One product at one rate, applied at the applications it names."""

  model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

  product: str = Field(min_length=1, description="Exact name of the formulated product.")
  kind: ProductKind | None = None
  formulationType: str | None = Field(default=None, min_length=1, description="E.g. EC, SC, WG.")
  activeSubstances: list[ActiveSubstance] = Field(default_factory=list)
  rate: Quantity
  rateBasis: RateBasis = Field(description="Whether the rate is of the formulated product or of the active substance.")
  applicationCodes: list[str] = Field(min_length=1, description="The applications this line goes on at.")

  @field_validator("rate")
  @classmethod
  def rateIsPositive(cls, rate: Quantity) -> Quantity:
    return requirePositive(rate, "a rate")

  @model_validator(mode="after")
  def namesAreNotRepeated(self) -> TreatmentLine:
    substances = [substance.name for substance in self.activeSubstances]
    if len(set(substances)) != len(substances):
      raise ValueError(f"product '{self.product}': an active substance is listed more than once")
    if len(set(self.applicationCodes)) != len(self.applicationCodes):
      raise ValueError(f"product '{self.product}': an application is named more than once")
    return self


class Treatment(BaseModel):
  """One treatment under comparison: its role and the product lines it is made of."""

  model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

  treatmentCode: str = Field(min_length=1, description="Stable per-trial code, e.g. 'T1'.")
  name: str = Field(min_length=1)
  role: TreatmentRole | None = None
  factorLevels: dict[str, str] = Field(
    default_factory=dict, description="Factor code to level code, for a treatment that is a combination.",
  )
  lines: list[TreatmentLine] = Field(default_factory=list)

  @model_validator(mode="after")
  def untreatedControlHasNoLines(self) -> Treatment:
    if self.role is TreatmentRole.untreatedControl and self.lines:
      raise ValueError(f"treatment '{self.treatmentCode}': an untreated control has no product lines")
    return self
