# SPDX-License-Identifier: Apache-2.0
"""Targets: the pests, weeds and diseases a trial is about (EPPO PP 1/181, Appendix 1, 1.1).

A target is named once, with its scientific name and EPPO code where known, and ratings
name the target they rate by its code (decision 0018).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class TargetKind(str, Enum):
  """What kind of organism a target is."""

  weed = "weed"
  disease = "disease"
  insect = "insect"
  mite = "mite"
  nematode = "nematode"
  mollusc = "mollusc"
  other = "other"


class Target(BaseModel):
  """One organism the trial's treatments are meant to act on."""

  model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

  targetCode: str = Field(min_length=1, description="Stable per-trial code ratings name, e.g. 'SEPT'.")
  name: str = Field(min_length=1, description="Common name, e.g. 'Septoria leaf blotch'.")
  kind: TargetKind
  scientificName: str | None = Field(default=None, min_length=1, description="E.g. 'Zymoseptoria tritici'.")
  eppoCode: str | None = Field(
    default=None, pattern=r"^[0-9A-Z]{5,6}$", description="The EPPO code, e.g. 'SEPTTR'.",
  )
