# SPDX-License-Identifier: Apache-2.0
"""Randomized complete block design (RCBD) layout generation.

Each block receives every treatment exactly once, in an order shuffled independently
of the other blocks. The project owns the whole procedure (decision 0015): no
library's random number generator takes part, so the layout a seed produces is fixed
by this file alone and can be reproduced in any language.

Method `sha256FisherYates1`:

1. The random stream for a seed is the concatenation of
   SHA-256("sha256FisherYates1:<seed>:<counter>") for counter = 0, 1, 2, ..., the seed
   and the counter written in decimal and the text encoded as ASCII.
2. Random words are read from the stream eight bytes at a time, big-endian.
3. An integer below a bound n is drawn by rejection: a word at or above the largest
   multiple of n that fits in 64 bits is discarded, and the first word kept is reduced
   modulo n. Every result is equally likely.
4. A block's order starts as the treatments in package order and is shuffled by
   Fisher-Yates: for each position from the last down to the second, its entry is
   swapped with the entry at a position drawn below that position's number.
5. Blocks are shuffled in order, block 1 first, each continuing the stream where the
   previous one stopped.
6. When the design leaves the first block in treatment order, block 1 keeps package
   order and draws nothing from the stream; shuffling starts with block 2 at the start
   of the stream. A design without that option is laid out by steps 1 to 5 alone.

A split plot (decision 0020) uses the same stream. In each block the main-plot levels,
in factor order, are shuffled by step 4; then the subplot levels of each main plot, in
factor order, are shuffled the same way, main plot 1 first, each continuing the stream.
Main plot m holds positions (m - 1) * b + 1 to m * b of the block, b being the number of
subplot levels. Step 6 leaves block 1 entirely in factor order, drawing nothing.

A changed procedure gets a new method name. This one stays as it is, so a layout
recorded under it can always be regenerated and checked.
"""

from __future__ import annotations

from openfurrow.design.spatialBalance import generateSpatiallyBalancedLayout
from openfurrow.design.stream import Sha256Stream, shuffled
from openfurrow.schema.layout import PlotAssignment, TrialLayout
from openfurrow.schema.trialPackage import DesignType, RandomizationMethod, TrialPackage

_maxTreatmentsPerBlock = 99  # plotNumber = block * 100 + position; positions must stay 2-digit


def generateLayout(package: TrialPackage) -> TrialLayout:
  """Generate the plot map a package's design and seed call for."""
  if package.design.designType is DesignType.splitPlot:
    return generateSplitPlotLayout(package)
  if package.design.randomizationMethod is RandomizationMethod.sha256SpatialBalance1:
    return generateSpatiallyBalancedLayout(package)
  return generateRcbdLayout(package)


def generateSplitPlotLayout(package: TrialPackage) -> TrialLayout:
  """Generate the split-plot plot map for a trial package from its seed."""
  design = package.design
  if design.designType is not DesignType.splitPlot:
    raise ValueError(f"generateSplitPlotLayout requires a split-plot design, got {design.designType.value}")
  if design.randomizationMethod is not RandomizationMethod.sha256FisherYates1:
    raise ValueError(
      f"a layout with randomization method '{design.randomizationMethod.value}' "
      f"is supplied with the trial, not generated"
    )
  factors = {factor.factorCode: factor for factor in package.factors}
  mainLevels = [level.levelCode for level in factors[design.mainPlotFactor].levels]
  subLevels = [level.levelCode for level in factors[design.subPlotFactor].levels]
  if len(mainLevels) * len(subLevels) > _maxTreatmentsPerBlock:
    raise ValueError(
      f"{len(mainLevels) * len(subLevels)} plots per block exceeds the "
      f"{_maxTreatmentsPerBlock}-per-block plot-number scheme"
    )
  treatmentFor = {
    (treatment.factorLevels[design.mainPlotFactor], treatment.factorLevels[design.subPlotFactor]): treatment.treatmentCode
    for treatment in package.treatments
  }
  stream = Sha256Stream(design.randomizationSeed, RandomizationMethod.sha256FisherYates1.value)
  plots: list[PlotAssignment] = []
  for block in range(1, design.replications + 1):
    ordered = block == 1 and design.firstBlockInTreatmentOrder
    mainOrder = list(range(len(mainLevels))) if ordered else shuffled(len(mainLevels), stream)
    for mainPlot, mainIndex in enumerate(mainOrder, start=1):
      subOrder = list(range(len(subLevels))) if ordered else shuffled(len(subLevels), stream)
      for subPosition, subIndex in enumerate(subOrder, start=1):
        positionInBlock = (mainPlot - 1) * len(subLevels) + subPosition
        plots.append(PlotAssignment(
          plotNumber=block * 100 + positionInBlock,
          block=block,
          positionInBlock=positionInBlock,
          mainPlot=mainPlot,
          treatmentCode=treatmentFor[(mainLevels[mainIndex], subLevels[subIndex])],
        ))
  return TrialLayout.forPackage(package, plots)


def generateRcbdLayout(package: TrialPackage) -> TrialLayout:
  """Generate the RCBD plot map for a trial package from its seed.

  The package's design must be an RCBD whose layout is generated. Raises for a layout
  that is supplied with the trial instead, and if the treatment count would overflow
  the two-digit plot-position field rather than emitting colliding plot numbers.
  """
  design = package.design
  if design.designType is not DesignType.rcbd:
    raise ValueError(f"generateRcbdLayout requires an RCBD design, got {design.designType.value}")
  if design.randomizationMethod is not RandomizationMethod.sha256FisherYates1:
    raise ValueError(
      f"a layout with randomization method '{design.randomizationMethod.value}' "
      f"is supplied with the trial, not generated"
    )

  treatmentCodes = [treatment.treatmentCode for treatment in package.treatments]
  treatmentCount = len(treatmentCodes)
  if treatmentCount > _maxTreatmentsPerBlock:
    raise ValueError(
      f"{treatmentCount} treatments exceeds the {_maxTreatmentsPerBlock}-per-block plot-number scheme"
    )

  stream = Sha256Stream(design.randomizationSeed, RandomizationMethod.sha256FisherYates1.value)
  plots: list[PlotAssignment] = []
  for block in range(1, design.replications + 1):
    if block == 1 and design.firstBlockInTreatmentOrder:
      order = list(range(treatmentCount))
    else:
      order = shuffled(treatmentCount, stream)
    for positionInBlock, treatmentIndex in enumerate(order, start=1):
      plots.append(
        PlotAssignment(
          plotNumber=block * 100 + positionInBlock,
          block=block,
          positionInBlock=positionInBlock,
          treatmentCode=treatmentCodes[treatmentIndex],
        )
      )

  return TrialLayout.forPackage(package, plots)
