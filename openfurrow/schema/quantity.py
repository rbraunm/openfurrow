# SPDX-License-Identifier: Apache-2.0
"""A number with its unit.

A rate, a pressure or a temperature means nothing without its unit, and a unit means
nothing without its number, so the two travel as one value and neither can be given
alone. Units are text as the user wrote them; nothing here converts between them.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Quantity(BaseModel):
  """A value and the unit it is expressed in."""

  model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)

  value: float
  unit: str = Field(min_length=1, description="The unit as written, e.g. 'L/ha', 'kPa', 'C'.")


def requirePositive(quantity: Quantity | None, what: str) -> Quantity | None:
  """Return the quantity, raising unless it is absent or greater than zero."""
  if quantity is not None and quantity.value <= 0.0:
    raise ValueError(f"{what} must be greater than zero, got {quantity.value}")
  return quantity
