# SPDX-License-Identifier: Apache-2.0
"""Trial layout schema: the plot map of a trial.

The plot map -- which treatment is on which plot, in which block -- is recorded data
(decision 0015). A trial document carries it as a list of plot assignments; a
`TrialLayout` is the same plots together with what the package says about the design,
the form the analysis, the importer and the surfaces work with.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from openfurrow.schema.trialPackage import DesignType, TrialPackage


class PlotAssignment(BaseModel):
  """One plot: a treatment placed at a position within a block."""

  model_config = ConfigDict(extra="forbid")

  plotNumber: int = Field(gt=0, description="Field plot label, e.g. 101 for block 1 position 1.")
  block: int = Field(ge=1, description="Block (replication) number, 1-based.")
  positionInBlock: int = Field(ge=1, description="Plot position within the block, 1-based.")
  treatmentCode: str = Field(min_length=1, description="Treatment placed in this plot.")


def checkCompleteBlocks(treatmentCodes: list[str], replications: int, plots: list[PlotAssignment]) -> None:
  """Raise unless the plots are complete blocks of the treatments, each plot distinct.

  Every block 1..replications holds each treatment exactly once, no plot number is
  used twice, and no two plots share a position in their block. A layout made by hand
  or by another tool is held to the same rules as a generated one.
  """
  if len(set(treatmentCodes)) != len(treatmentCodes):
    raise ValueError("treatmentCodes contains duplicates")
  if len(plots) != len(treatmentCodes) * replications:
    raise ValueError(
      f"plot count {len(plots)} does not equal treatments "
      f"{len(treatmentCodes)} x replications {replications}"
    )
  plotNumbers = [plot.plotNumber for plot in plots]
  if len(set(plotNumbers)) != len(plotNumbers):
    repeated = sorted({number for number in plotNumbers if plotNumbers.count(number) > 1})
    raise ValueError(f"plot numbers used more than once: {repeated}")
  byBlock: dict[int, list[PlotAssignment]] = {}
  for plot in plots:
    byBlock.setdefault(plot.block, []).append(plot)
  if set(byBlock) != set(range(1, replications + 1)):
    raise ValueError(f"blocks {sorted(byBlock)} are not 1..{replications}")
  for block, blockPlots in byBlock.items():
    if sorted(plot.treatmentCode for plot in blockPlots) != sorted(treatmentCodes):
      raise ValueError(f"block {block} is not a complete set of every treatment exactly once")
    positions = [plot.positionInBlock for plot in blockPlots]
    if len(set(positions)) != len(positions):
      raise ValueError(f"block {block} has two plots at the same position")


class TrialLayout(BaseModel):
  """The complete plot map for a trial, with the design it belongs to.

  Every block holds each treatment exactly once (a complete block), so the plot count
  is exactly treatments x replications. These invariants are checked here so a
  hand-edited or corrupted layout is rejected on load, not trusted blindly.
  """

  model_config = ConfigDict(extra="forbid")

  trialCode: str = Field(min_length=1)
  designType: DesignType
  replications: int = Field(ge=2)
  treatmentCodes: list[str] = Field(min_length=2)
  plots: list[PlotAssignment] = Field(min_length=1)

  @model_validator(mode="after")
  def plotsFormCompleteBlocks(self) -> TrialLayout:
    checkCompleteBlocks(self.treatmentCodes, self.replications, self.plots)
    return self

  @classmethod
  def forPackage(cls, package: TrialPackage, plots: list[PlotAssignment]) -> TrialLayout:
    """The layout view of `plots` for the trial `package` describes."""
    return cls(
      trialCode=package.trial.trialCode,
      designType=package.design.designType,
      replications=package.design.replications,
      treatmentCodes=[treatment.treatmentCode for treatment in package.treatments],
      plots=plots,
    )
