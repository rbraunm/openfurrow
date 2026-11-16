# SPDX-License-Identifier: Apache-2.0
"""Trial layout schema: the plot map of a trial.

The plot map -- which treatment is on which plot, in which block -- is recorded data
(decision 0015). A trial document carries it as a list of plot assignments; a
`TrialLayout` is the same plots together with what the package says about the design,
the form the analysis, the importer and the surfaces work with.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from openfurrow.schema.trialPackage import CheckArrangement, DesignType, TrialPackage


class PlotAssignment(BaseModel):
  """One plot: a treatment placed at a position within a block."""

  model_config = ConfigDict(extra="forbid")

  plotNumber: int = Field(gt=0, description="Field plot label, e.g. 101 for block 1 position 1.")
  block: int = Field(ge=1, description="Block (replication) number, 1-based.")
  positionInBlock: int = Field(ge=1, description="Plot position within the block, 1-based.")
  mainPlot: int | None = Field(default=None, ge=1, description="Split plot: the main plot within the block, 1-based.")
  treatmentCode: str = Field(min_length=1, description="Treatment placed in this plot.")


class CheckPlot(BaseModel):
  """An untreated check plot and the treated plot or plots it is compared with."""

  model_config = ConfigDict(extra="forbid")

  plotNumber: int = Field(gt=0, description="Field label; a generated check of plot 101 is 10101.")
  block: int = Field(ge=1)
  pairedPlots: list[int] = Field(min_length=1, description="The treated plots this check is compared with.")


def checkCheckPlots(arrangement: CheckArrangement, plots: list[PlotAssignment], checkPlots: list[CheckPlot]) -> None:
  """Raise unless the check plots fit the arrangement and the treated plots.

  Every treated plot has exactly one check, in its own block. A strip between plots
  (imbricated) may serve several plots; a half plot or a partner serves exactly one.
  """
  if arrangement is CheckArrangement.none:
    if checkPlots:
      raise ValueError("check plots are given, but the design has no checkArrangement")
    return
  if not checkPlots:
    raise ValueError(f"a design with checkArrangement '{arrangement.value}' needs its check plots")
  blockOf = {plot.plotNumber: plot.block for plot in plots}
  numbers = [check.plotNumber for check in checkPlots]
  clashing = sorted(set(numbers) & set(blockOf) | {n for n in numbers if numbers.count(n) > 1})
  if clashing:
    raise ValueError(f"check plot numbers used more than once or by treated plots: {clashing}")
  served: list[int] = []
  for check in checkPlots:
    if arrangement is not CheckArrangement.imbricated and len(check.pairedPlots) != 1:
      raise ValueError(f"check plot {check.plotNumber}: a {arrangement.value} check belongs to exactly one plot")
    for plotNumber in check.pairedPlots:
      if plotNumber not in blockOf:
        raise ValueError(f"check plot {check.plotNumber} names plot {plotNumber}, which is not a treated plot")
      if blockOf[plotNumber] != check.block:
        raise ValueError(f"check plot {check.plotNumber} is in block {check.block}, its plot {plotNumber} is not")
    served += check.pairedPlots
  without = sorted(set(blockOf) - set(served))
  twice = sorted({number for number in served if served.count(number) > 1})
  if without or twice:
    raise ValueError(f"every treated plot has exactly one check; without one {without}, with several {twice}")


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


def checkMainPlots(mainPlotLevels: dict[str, str], plots: list[PlotAssignment]) -> None:
  """Raise unless each block's main plots each hold one main-plot level, every subplot of it.

  Within a block every plot names its main plot; a main plot holds the treatments of one
  main-plot level and all of them, and the block's main plots hold different levels.
  """
  subplotCount = len(mainPlotLevels) // len(set(mainPlotLevels.values()))
  byMainPlot: dict[tuple[int, int], list[PlotAssignment]] = {}
  for plot in plots:
    if plot.mainPlot is None:
      raise ValueError(f"plot {plot.plotNumber} of a split plot names no main plot")
    byMainPlot.setdefault((plot.block, plot.mainPlot), []).append(plot)
  levelsByBlock: dict[int, list[str]] = {}
  for (block, mainPlot), mainPlotPlots in sorted(byMainPlot.items()):
    levels = {mainPlotLevels[plot.treatmentCode] for plot in mainPlotPlots}
    if len(levels) != 1 or len(mainPlotPlots) != subplotCount:
      raise ValueError(
        f"block {block}, main plot {mainPlot} must hold the {subplotCount} subplots of one main-plot level"
      )
    levelsByBlock.setdefault(block, []).append(levels.pop())
  for block, levels in levelsByBlock.items():
    if len(set(levels)) != len(levels):
      raise ValueError(f"block {block} holds a main-plot level in more than one main plot")


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

  mainPlotLevels: dict[str, str] | None = Field(
    default=None, description="Split plot: each treatment's main-plot level.",
  )
  checkArrangement: CheckArrangement
  checkPlots: list[CheckPlot]

  @model_validator(mode="after")
  def plotsFormCompleteBlocks(self) -> TrialLayout:
    checkCompleteBlocks(self.treatmentCodes, self.replications, self.plots)
    if self.designType is DesignType.splitPlot:
      if self.mainPlotLevels is None:
        raise ValueError("a split-plot layout needs each treatment's main-plot level")
      checkMainPlots(self.mainPlotLevels, self.plots)
    elif any(plot.mainPlot is not None for plot in self.plots) or self.mainPlotLevels is not None:
      raise ValueError(f"a {self.designType.value} layout has no main plots")
    checkCheckPlots(self.checkArrangement, self.plots, self.checkPlots)
    return self

  def checkFor(self, plotNumber: int) -> CheckPlot:
    """The check a treated plot is compared with."""
    return next(check for check in self.checkPlots if plotNumber in check.pairedPlots)

  @classmethod
  def forPackage(
    cls, package: TrialPackage, plots: list[PlotAssignment], checkPlots: list[CheckPlot],
  ) -> TrialLayout:
    """The layout view of `plots` and `checkPlots` for the trial `package` describes."""
    return cls(
      trialCode=package.trial.trialCode,
      designType=package.design.designType,
      replications=package.design.replications,
      treatmentCodes=[treatment.treatmentCode for treatment in package.treatments],
      plots=plots,
      checkArrangement=package.design.checkArrangement,
      checkPlots=checkPlots,
      mainPlotLevels=(
        {treatment.treatmentCode: package.mainPlotLevelOf(treatment.treatmentCode) for treatment in package.treatments}
        if package.design.designType is DesignType.splitPlot else None
      ),
    )
