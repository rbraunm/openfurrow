# SPDX-License-Identifier: Apache-2.0
"""How the crop was grown, the soil it grew in, and the weather it had.

Shaped on EPPO PP 1/181, Appendix 1, sections 1.2, 3.1.2 and 3.1.1 (decision 0019).
Planting and soil are one block each and may be absent; a block that is present holds at
least one fact, so an empty block and no block cannot be confused. The weather is a log
with one record per day. The conditions at an application stay with the application.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from openfurrow.schema.dateAndTime import CalendarDate
from openfurrow.schema.quantity import Quantity, requirePositive


def _requireSomething(model: BaseModel, what: str) -> None:
  if all(getattr(model, name) is None for name in type(model).model_fields):
    raise ValueError(f"{what} holds nothing; leave it out instead")


def _requireNotNegative(quantity: Quantity | None, what: str) -> Quantity | None:
  if quantity is not None and quantity.value < 0.0:
    raise ValueError(f"{what} must not be negative, got {quantity.value}")
  return quantity


class Planting(BaseModel):
  """How and when the crop was established."""

  model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)

  cultivar: str | None = Field(default=None, min_length=1)
  cropEPPOCode: str | None = Field(default=None, pattern=r"^[0-9A-Z]{5,6}$", description="E.g. 'TRZAW'.")
  sowingDate: CalendarDate | None = None
  seedingRate: Quantity | None = Field(default=None, description="E.g. 350 seeds/m2, 160 kg/ha.")
  plantDensity: Quantity | None = Field(default=None, description="E.g. 280 plants/m2.")
  rowSpacing: Quantity | None = None
  inRowSpacing: Quantity | None = None
  sowingDepth: Quantity | None = None
  emergenceDate: CalendarDate | None = None
  precedingCrop: str | None = Field(default=None, min_length=1)
  tillage: str | None = Field(default=None, min_length=1)
  notes: str | None = Field(default=None, min_length=1)

  @field_validator("seedingRate", "plantDensity", "rowSpacing", "inRowSpacing", "sowingDepth")
  @classmethod
  def amountIsPositive(cls, quantity: Quantity | None, info) -> Quantity | None:
    return requirePositive(quantity, info.field_name)

  @model_validator(mode="after")
  def isConsistent(self) -> Planting:
    _requireSomething(self, "planting")
    if self.sowingDate and self.emergenceDate and self.emergenceDate < self.sowingDate:
      raise ValueError(f"emergenceDate {self.emergenceDate} is before sowingDate {self.sowingDate}")
    return self


class Soil(BaseModel):
  """The soil of the trial site and how it was fed."""

  model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)

  soilType: str | None = Field(default=None, min_length=1, description="E.g. 'Luvisol', 'alluvial'.")
  texture: str | None = Field(default=None, min_length=1, description="E.g. 'silty clay loam'.")
  pH: float | None = Field(default=None, ge=0.0, le=14.0)
  pHMethod: str | None = Field(default=None, min_length=1, description="E.g. 'water 1:2.5', 'CaCl2'.")
  organicMatter: float | None = Field(default=None, ge=0.0, le=100.0, description="Percent.")
  seedbedQuality: str | None = Field(default=None, min_length=1)
  fertilizerRegime: str | None = Field(default=None, min_length=1)
  notes: str | None = Field(default=None, min_length=1)

  @model_validator(mode="after")
  def isConsistent(self) -> Soil:
    _requireSomething(self, "soil")
    if self.pHMethod is not None and self.pH is None:
      raise ValueError("pHMethod is given without a pH")
    return self


class WeatherRecord(BaseModel):
  """One day of the trial's weather log."""

  model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)

  date: CalendarDate
  rainfall: Quantity | None = None
  irrigation: Quantity | None = None
  minimumTemperature: Quantity | None = None
  maximumTemperature: Quantity | None = None
  notes: str | None = Field(default=None, min_length=1)

  @field_validator("rainfall", "irrigation")
  @classmethod
  def amountIsNotNegative(cls, quantity: Quantity | None, info) -> Quantity | None:
    return _requireNotNegative(quantity, info.field_name)

  @model_validator(mode="after")
  def isConsistent(self) -> WeatherRecord:
    if all(getattr(self, name) is None for name in type(self).model_fields if name != "date"):
      raise ValueError(f"weather record for {self.date} holds nothing")
    low, high = self.minimumTemperature, self.maximumTemperature
    if low is not None and high is not None:
      if low.unit != high.unit:
        raise ValueError(
          f"weather record for {self.date}: temperatures in '{low.unit}' and '{high.unit}' cannot be compared"
        )
      if low.value > high.value:
        raise ValueError(
          f"weather record for {self.date}: minimum {low.value} is above maximum {high.value}"
        )
    return self
