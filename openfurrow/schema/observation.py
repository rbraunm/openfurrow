# SPDX-License-Identifier: Apache-2.0
"""Observation schema: the long-format observation atom.

One observation is one value for one assessment on one plot -- the same atom
BrAPI and Field Book's database export use. The value is stored already typed:
numeric assessments hold a float, categorical and ordinal assessments hold the
string code, and an explicitly missing value holds None. The model is strict so
a categorical code that happens to look numeric (e.g. "3") is not silently
coerced to a number; the importer is responsible for parsing each value to the
correct type against its assessment definition before constructing the model.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Observation(BaseModel):
  """A single recorded value, keyed by plot and assessment."""

  model_config = ConfigDict(extra="forbid", strict=True)

  plotNumber: int = Field(gt=0, description="Plot this value was collected on.")
  assessmentCode: str = Field(min_length=1, description="Assessment this value belongs to.")
  value: float | str | None = Field(description="Typed value; None means explicitly missing.")
