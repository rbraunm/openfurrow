# SPDX-License-Identifier: Apache-2.0
"""What an analysis does with a plot that has no value, and the record of what it did (decisions 0003, 0043).

The policy is a setting (`analysis.missingPlots`, decision 0035). Whichever applies, the
result names every missing plot and how it was handled, so a result never depends on a
setting changed since:

- `refuse`: the analysis stops and names the missing plots.
- `leastSquares`: the model is fitted by least squares to the plots present, and the
  treatment means are the adjusted (least-squares) means.
- `estimate`: Yates' missing-plot estimates complete the table for the classical
  arithmetic. An estimate is never an observation and is never stored.

Covered so far: the single-factor RCBD and the completely randomized design, without
untreated checks beside the plots and without subsamples. Every other analysis refuses a
missing plot under every policy.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict

coveredDesigns = (
  "missing plots are handled (setting analysis.missingPlots) only for a single-factor RCBD and a completely "
  "randomized design, without untreated checks beside the plots and without subsamples"
)


class MissingPlotPolicy(str, Enum):
  """What an analysis does with a plot that has no value."""

  refuse = "refuse"
  estimate = "estimate"
  leastSquares = "leastSquares"


class MissingHandling(str, Enum):
  """How one missing plot was handled."""

  leftOut = "leftOut"  # least squares: the model is fitted to the plots present
  estimated = "estimated"  # Yates: an estimate stands in for the arithmetic only


class MissingCell(BaseModel):
  """One plot without a value on the analysed scale, and what the analysis did about it."""

  model_config = ConfigDict(extra="forbid")

  plotNumber: int
  treatmentCode: str
  block: int
  handling: MissingHandling
  estimate: float | None = None


class SumsOfSquares(str, Enum):
  """Which sums of squares an ANOVA table holds."""

  balanced = "balanced"  # complete table: sequential and adjusted sums of squares are the same
  typeIII = "typeIII"  # least squares: each term adjusted for every other term
  completedTable = "completedTable"  # Yates: the completed table's, the treatment line corrected for bias


class MissingPlotEstimation(BaseModel):
  """How Yates' estimates were reached, and the bias taken off the treatment sum of squares."""

  model_config = ConfigDict(extra="forbid")

  cycles: int
  tolerance: float
  treatmentBias: float
