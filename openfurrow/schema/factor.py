# SPDX-License-Identifier: Apache-2.0
"""Factors: the dimensions a factorial trial's treatments are combinations of.

A factor has a code, a name and its levels (decision 0020). In a two-factor trial every
treatment states its level of each factor, so a treatment is one combination; the
treatment keeps its own code and may still carry product lines.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FactorLevel(BaseModel):
  """One level of a factor, e.g. '60 kg N/ha' or a variety."""

  model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

  levelCode: str = Field(min_length=1)
  name: str = Field(min_length=1)


class Factor(BaseModel):
  """One factor and its levels, in the order they are listed and laid out."""

  model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

  factorCode: str = Field(min_length=1, description="E.g. 'N' for nitrogen.")
  name: str = Field(min_length=1)
  levels: list[FactorLevel] = Field(min_length=2)

  @field_validator("levels")
  @classmethod
  def levelCodesAreUnique(cls, levels: list[FactorLevel]) -> list[FactorLevel]:
    codes = [level.levelCode for level in levels]
    repeated = sorted({code for code in codes if codes.count(code) > 1})
    if repeated:
      raise ValueError(f"level codes used more than once: {repeated}")
    return levels
