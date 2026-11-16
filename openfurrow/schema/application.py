# SPDX-License-Identifier: Apache-2.0
"""Applications: when, how and under what conditions treatments were put on.

Shaped on EPPO PP 1/181, Appendix 1, sections 2.2, 3.1.1 and 3.1.2 (decision 0016). An
application has a code that treatment lines name, the timing that was planned, and --
once it has been made -- its date, how it was made, and the conditions at the time. One
code is one pass over the field: a timing carried out on two days, or differently for
some treatments, is two applications.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from openfurrow.schema.dateAndTime import CalendarDate, ClockTime
from openfurrow.schema.quantity import Quantity, requirePositive


class SoilMoisture(str, Enum):
  """Soil moisture at application, in the standard's qualitative terms."""

  dry = "dry"
  moist = "moist"
  wet = "wet"
  waterlogged = "waterlogged"


class Application(BaseModel):
  """One pass over the field: its plan, and what was done and found when it was made."""

  model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)

  applicationCode: str = Field(min_length=1, description="The code treatment lines name, e.g. 'A'.")
  timing: str | None = Field(default=None, min_length=1, description="The planned timing, e.g. 'BBCH 31'.")
  date: CalendarDate | None = Field(default=None, description="The day it was made.")
  time: ClockTime | None = Field(default=None, description="The time of day it was made, by the clock at the site.")
  method: str | None = Field(default=None, min_length=1, description="E.g. 'broadcast spray'.")
  placement: str | None = Field(default=None, min_length=1, description="E.g. 'foliar', 'soil', 'in-furrow'.")
  equipment: str | None = Field(default=None, min_length=1)
  nozzle: str | None = Field(default=None, min_length=1)
  pressure: Quantity | None = None
  sprayQuality: str | None = Field(default=None, min_length=1, description="Droplet size class, e.g. 'medium'.")
  travelSpeed: Quantity | None = None
  sprayVolume: Quantity | None = None
  cropStage: str | None = Field(default=None, min_length=1, description="Growth stage of the crop, BBCH where possible.")
  targetStage: str | None = Field(default=None, min_length=1, description="Stage or level of the target.")
  airTemperature: Quantity | None = None
  relativeHumidity: float | None = Field(default=None, ge=0.0, le=100.0, description="Percent.")
  windSpeed: Quantity | None = None
  cloudCover: float | None = Field(default=None, ge=0.0, le=100.0, description="Percent.")
  soilMoisture: SoilMoisture | None = None
  notes: str | None = Field(default=None, min_length=1)

  @field_validator("pressure", "travelSpeed", "sprayVolume")
  @classmethod
  def amountIsPositive(cls, quantity: Quantity | None, info) -> Quantity | None:
    return requirePositive(quantity, info.field_name)

  @field_validator("windSpeed")
  @classmethod
  def windSpeedIsNotNegative(cls, windSpeed: Quantity | None) -> Quantity | None:
    if windSpeed is not None and windSpeed.value < 0.0:
      raise ValueError(f"windSpeed must not be negative, got {windSpeed.value}")
    return windSpeed
