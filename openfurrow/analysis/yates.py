# SPDX-License-Identifier: Apache-2.0
"""Yates' missing-plot estimates for a randomized complete block design (decision 0043).

A missing value is given the estimate that makes the error sum of squares of the completed
table smallest. With one missing value that is the closed form of Yates (1933), as Gomez
and Gomez (1984), section 7.1.2.1, give it:

    X = (r B + t T - G) / ((r - 1)(t - 1))

for r blocks and t treatments, B and T the totals of the values present in the missing
plot's block and treatment, and G the total of all values present. With several, each is
estimated in turn by the same formula with the others at their current estimates, and
the cycle is repeated until no estimate moves by more than `tolerance` of the largest
value present (Gomez and Gomez, section 7.1.2.6). The start (the mean of the plot's
treatment mean and block mean over the values present), the order (block by block, in
treatment order) and the stopping rule are fixed, so the estimates are reproducible.

The completed table's treatment sum of squares is too large, because the estimates carry
no error of their own. What treatments account for, adjusted for blocks, is the sum of
squares of the values present about their block means less the error sum of squares; for
one missing value the difference from the completed table's figure is the classical
correction B = (B - (t - 1) X)^2 / (t (t - 1)) of the same section.
"""

from __future__ import annotations

import numpy

from openfurrow.analysis.anova import AnalysisError

tolerance = 1.0e-12
maximumCycles = 10000


def estimateMissingValues(values: numpy.ndarray) -> tuple[numpy.ndarray, int]:
  """The table completed with Yates' estimates where `values` holds nan, and the cycles it took.

  `values` is indexed [block, treatment]; every block and every treatment must have a value.
  """
  blockCount, treatmentCount = values.shape
  present = ~numpy.isnan(values)
  cells = [(int(block), int(treatment)) for block, treatment in zip(*numpy.nonzero(~present))]
  treatmentMeans = numpy.nanmean(values, axis=0)
  blockMeans = numpy.nanmean(values, axis=1)
  completed = values.copy()
  for block, treatment in cells:
    completed[block, treatment] = (treatmentMeans[treatment] + blockMeans[block]) / 2.0
  scale = float(numpy.abs(values[present]).max())
  for cycle in range(1, maximumCycles + 1):
    largestMove = 0.0
    for block, treatment in cells:
      current = completed[block, treatment]
      blockTotal = completed[block].sum() - current
      treatmentTotal = completed[:, treatment].sum() - current
      grandTotal = completed.sum() - current
      estimate = float(
        (blockCount * blockTotal + treatmentCount * treatmentTotal - grandTotal)
        / ((blockCount - 1) * (treatmentCount - 1))
      )
      largestMove = max(largestMove, abs(estimate - current))
      completed[block, treatment] = estimate
    # One missing value needs no second cycle: its formula involves no other estimate.
    if len(cells) == 1 or largestMove <= tolerance * scale:
      return completed, cycle
  raise AnalysisError(
    f"the missing-plot estimates did not settle within {maximumCycles} cycles "
    f"(the last cycle still moved one by {largestMove:g})"
  )


def sumOfSquaresWithinBlocks(values: numpy.ndarray) -> float:
  """The sum of squares of the values present about the mean of those present in their block."""
  return float(numpy.nansum((values - numpy.nanmean(values, axis=1)[:, None]) ** 2))
