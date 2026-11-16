# SPDX-License-Identifier: Apache-2.0
"""Where a trial stands and the size of its plots (EPPO PP 1/181, Appendix 1, 1.1 and 1.3).

Both are optional blocks (decision 0024). A block that is present holds at least one fact,
so an empty block and no block cannot be confused once stored.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from openfurrow.schema.quantity import Quantity, requirePositive


class Setting(str, Enum):
  """Where the trial is grown."""

  field = "field"
  glasshouse = "glasshouse"
  growthChamber = "growthChamber"
  other = "other"


def _requireSomething(model: BaseModel, what: str) -> None:
  if all(getattr(model, name) is None for name in type(model).model_fields):
    raise ValueError(f"{what} holds nothing; leave it out instead")


class SiteDetails(BaseModel):
  """The site's address, position and character."""

  model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)

  address: str | None = Field(default=None, min_length=1)
  latitude: float | None = Field(default=None, ge=-90.0, le=90.0, description="Decimal degrees, north positive.")
  longitude: float | None = Field(default=None, ge=-180.0, le=180.0, description="Decimal degrees, east positive.")
  elevation: Quantity | None = Field(default=None, description="E.g. 85 m above sea level.")
  setting: Setting | None = None
  exposure: str | None = Field(default=None, min_length=1, description="E.g. 'south-facing, sheltered'.")
  slope: str | None = Field(default=None, min_length=1, description="E.g. '2 %', 'level'.")

  @model_validator(mode="after")
  def isConsistent(self) -> SiteDetails:
    _requireSomething(self, "siteDetails")
    if (self.latitude is None) != (self.longitude is None):
      raise ValueError("a position needs both latitude and longitude")
    return self


class PlotDimensions(BaseModel):
  """The size of the plots and the space between them."""

  model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)

  grossLength: Quantity | None = None
  grossWidth: Quantity | None = None
  netLength: Quantity | None = Field(default=None, description="The part of the plot assessed.")
  netWidth: Quantity | None = None
  alleyWidth: Quantity | None = Field(default=None, description="The zone between plots or blocks.")
  notes: str | None = Field(default=None, min_length=1)

  @field_validator("grossLength", "grossWidth", "netLength", "netWidth", "alleyWidth")
  @classmethod
  def sizeIsPositive(cls, quantity: Quantity | None, info) -> Quantity | None:
    return requirePositive(quantity, info.field_name)

  @model_validator(mode="after")
  def isConsistent(self) -> PlotDimensions:
    _requireSomething(self, "plotDimensions")
    for side in ("Length", "Width"):
      gross, net = getattr(self, f"gross{side}"), getattr(self, f"net{side}")
      if gross and net and gross.unit == net.unit and net.value > gross.value:
        raise ValueError(f"net{side} {net.value} {net.unit} is larger than gross{side} {gross.value} {gross.unit}")
    return self
