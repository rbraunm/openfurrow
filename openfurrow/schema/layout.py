# SPDX-License-Identifier: Apache-2.0
"""Trial layout schema: the generated plot map for a randomized design.

A layout is produced from a trial package's design specification. It is a
serializable artifact (the plot map that gets exported and re-imported), so it
lives alongside the package schema rather than in the design logic. It records
the seed it was generated from so the layout can be regenerated and verified.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from openfurrow.schema.trialPackage import DesignType


class PlotAssignment(BaseModel):
  """One plot: a treatment placed at a position within a block."""

  model_config = ConfigDict(extra="forbid")

  plotNumber: int = Field(gt=0, description="Field plot label, e.g. 101 for block 1 position 1.")
  block: int = Field(ge=1, description="Block (replication) number, 1-based.")
  positionInBlock: int = Field(ge=1, description="Plot position within the block, 1-based.")
  treatmentCode: str = Field(min_length=1, description="Treatment placed in this plot.")


class TrialLayout(BaseModel):
  """The complete randomized plot map for a trial.

  Every block holds each treatment exactly once (a complete block), so the plot
  count is exactly treatments x replications. These invariants are checked here
  so a hand-edited or corrupted layout is rejected on load, not trusted blindly.
  """

  model_config = ConfigDict(extra="forbid")

  trialCode: str = Field(min_length=1)
  designType: DesignType
  randomizationSeed: int = Field(ge=0)
  replications: int = Field(ge=2)
  treatmentCodes: list[str] = Field(min_length=2)
  plots: list[PlotAssignment] = Field(min_length=1)

  @model_validator(mode="after")
  def plotsFormCompleteBlocks(self) -> TrialLayout:
    expectedTreatments = set(self.treatmentCodes)
    if len(expectedTreatments) != len(self.treatmentCodes):
      raise ValueError("treatmentCodes contains duplicates")
    if len(self.plots) != len(self.treatmentCodes) * self.replications:
      raise ValueError(
        f"plot count {len(self.plots)} does not equal treatments "
        f"{len(self.treatmentCodes)} x replications {self.replications}"
      )
    byBlock: dict[int, list[str]] = {}
    for plot in self.plots:
      byBlock.setdefault(plot.block, []).append(plot.treatmentCode)
    if set(byBlock) != set(range(1, self.replications + 1)):
      raise ValueError(f"blocks {sorted(byBlock)} are not 1..{self.replications}")
    for block, codes in byBlock.items():
      if sorted(codes) != sorted(self.treatmentCodes):
        raise ValueError(f"block {block} is not a complete set of every treatment exactly once")
    return self
