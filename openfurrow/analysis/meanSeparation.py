# SPDX-License-Identifier: Apache-2.0
"""Mean separation for an ANOVA: Fisher's LSD, protected or not, and Tukey's HSD.

Each method compares every pair of treatment means against one critical difference and
shows the result as a compact letter display: means that share a letter are not
significantly different at the chosen level.

- **Fisher's protected LSD** (the default, as in ARM): t(alpha/2, error df) *
  sqrt(2 MS error / n), applied only when the treatment F is significant.
- **Fisher's LSD**: the same difference, applied regardless of F.
- **Tukey's HSD**: q(1 - alpha; t, error df) * sqrt(MS error / n), q being the
  studentized range of the t means; it holds the chance of any false difference among
  all pairs at alpha, and is applied regardless of F.

n is the number of observations per mean. The t and q quantiles are self-authored
(decision 0002). Because the critical difference is one constant and the means are
sorted, a run of consecutive means is mutually non-significant exactly when its spread
is within it, so the maximal non-significant groups are contiguous intervals, each one
letter.
"""

from __future__ import annotations

import math

from enum import Enum

from pydantic import BaseModel, ConfigDict

from openfurrow.analysis.anova import AnalysisError, AnovaResult
from openfurrow.analysis.distributions import tCriticalValue
from openfurrow.analysis.studentizedRange import studentizedRangeQuantile


class MeanComparison(str, Enum):
  """The test that separates means after an analysis of variance."""

  protectedLSD = "protectedLSD"  # Fisher's LSD, only when the treatment F is significant
  lsd = "lsd"  # Fisher's LSD, applied regardless
  tukeyHSD = "tukeyHSD"  # Tukey's honestly significant difference, applied regardless


def criticalDifference(
  meanComparison: MeanComparison, significanceLevel: float, meanCount: int,
  errorMeanSquare: float, errorDegreesOfFreedom: int, perMean: int,
) -> float:
  """The difference two of `meanCount` means must exceed to be called different."""
  if meanComparison is MeanComparison.tukeyHSD:
    q = studentizedRangeQuantile(1.0 - significanceLevel, meanCount, errorDegreesOfFreedom)
    return q * math.sqrt(errorMeanSquare / perMean)
  return tCriticalValue(significanceLevel / 2.0, errorDegreesOfFreedom) * math.sqrt(2.0 * errorMeanSquare / perMean)


class TreatmentGroup(BaseModel):
  """A treatment's mean and its letter grouping."""

  model_config = ConfigDict(extra="forbid")

  treatmentCode: str
  mean: float
  group: str


def methodKeyFor(meanComparison: MeanComparison) -> str:
  """The catalog key naming the separation method.

  The analysis layer names the method with a key, never with a sentence (decision
  0007): a display string built here would be English in every locale, and this is
  the one place that knows which method ran. The reproducibility section resolves the
  same key from the same function, so the two cannot describe different methods.
  """
  return {
    MeanComparison.protectedLSD: "report.method.fisherProtectedLSD",
    MeanComparison.lsd: "report.method.fisherLSD",
    MeanComparison.tukeyHSD: "report.method.tukeyHSD",
  }[meanComparison]


class MeanSeparation(BaseModel):
  """The result of mean separation: the critical difference and the lettered treatment means."""

  model_config = ConfigDict(extra="forbid")

  methodKey: str
  significanceLevel: float
  criticalDifference: float
  treatmentSignificant: bool
  groups: list[TreatmentGroup]


def separateMeans(
  anovaResult: AnovaResult,
  significanceLevel: float = 0.05,
  meanComparison: MeanComparison = MeanComparison.protectedLSD,
) -> MeanSeparation:
  """Separate treatment means by the chosen test."""
  if not 0.0 < significanceLevel < 1.0:
    raise AnalysisError(f"significance level must be in (0, 1), got {significanceLevel}")
  difference = criticalDifference(
    meanComparison, significanceLevel, anovaResult.treatmentCount,
    anovaResult.errorMeanSquare, anovaResult.errorDegreesOfFreedom, anovaResult.blockCount,
  )
  treatmentRow = next(row for row in anovaResult.table if row.source == "treatment")
  treatmentSignificant = treatmentRow.pValue is not None and treatmentRow.pValue <= significanceLevel
  ordered = sorted(anovaResult.treatmentMeans, key=lambda mean: mean.mean, reverse=True)
  means = [mean.mean for mean in ordered]
  if meanComparison is MeanComparison.protectedLSD and not treatmentSignificant:
    letters = ["a"] * len(ordered)
  else:
    letters = letterGroups(means, difference)
  return MeanSeparation(
    methodKey=methodKeyFor(meanComparison),
    significanceLevel=significanceLevel,
    criticalDifference=difference,
    treatmentSignificant=treatmentSignificant,
    groups=[
      TreatmentGroup(treatmentCode=mean.treatmentCode, mean=mean.mean, group=letters[index])
      for index, mean in enumerate(ordered)
    ],
  )


def letterGroups(sortedMeans: list[float], leastSignificantDifference: float) -> list[str]:
  """Compact letter display for means sorted in descending order.

  Returns, for each mean, the concatenation of the letters of every maximal
  non-significant interval that contains it.
  """
  count = len(sortedMeans)
  # reach[i] = the furthest j such that means i..j are all within the LSD; because
  # the means are sorted, that is governed by the i..j spread alone.
  reach = []
  for start in range(count):
    farthest = start
    while farthest + 1 < count and (sortedMeans[start] - sortedMeans[farthest + 1]) <= leastSignificantDifference:
      farthest += 1
    reach.append(farthest)

  # A maximal interval starts a new letter; an interval whose reach does not extend
  # past the previous one is contained in it and adds no letter.
  intervals = [
    (start, reach[start])
    for start in range(count)
    if start == 0 or reach[start] > reach[start - 1]
  ]

  membership: list[list[int]] = [[] for _ in range(count)]
  for letterIndex, (start, end) in enumerate(intervals):
    for position in range(start, end + 1):
      membership[position].append(letterIndex)

  return ["".join(_letterFor(letterIndex) for letterIndex in letters) for letters in membership]


def _letterFor(index: int) -> str:
  """0 -> 'a', 25 -> 'z', 26 -> 'aa', 27 -> 'ab', ... ."""
  letters = ""
  index += 1
  while index > 0:
    index, remainder = divmod(index - 1, 26)
    letters = chr(ord("a") + remainder) + letters
  return letters
