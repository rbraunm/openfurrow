# SPDX-License-Identifier: Apache-2.0
"""Fisher's LSD mean separation for an RCBD ANOVA.

Computes the least significant difference and a compact letter display over the
treatment means: means that share a letter are not significantly different at the
chosen level. By default the test is *protected* (Fisher's Protected LSD): the
separation is only performed when the treatment F is significant, matching ARM's
default and the standard recommendation; an unprotected LSD separates regardless.

The least significant difference is

    LSD = t(alpha/2, error df) * sqrt(2 * MS_error / n)

with n the number of observations per treatment mean (the block count in a
balanced RCBD). The t critical value is self-authored (decision 0002).

The letter grouping uses the fact that the LSD is a single constant threshold and
the means are sorted: a run of consecutive means is mutually non-significant
exactly when its spread is within the LSD, so the maximal non-significant groups
are contiguous intervals. Each maximal interval is one letter.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict

from openfurrow.analysis.anova import AnalysisError, AnovaResult
from openfurrow.analysis.distributions import tCriticalValue


class TreatmentGroup(BaseModel):
  """A treatment's mean and its letter grouping."""

  model_config = ConfigDict(extra="forbid")

  treatmentCode: str
  mean: float
  group: str


def methodKeyFor(protected: bool) -> str:
  """The catalog key naming the separation method.

  The analysis layer names the method with a key, never with a sentence (decision
  0007): a display string built here would be English in every locale, and this is
  the one place that knows which method ran. The reproducibility section resolves the
  same key from the same function, so the two cannot describe different methods.
  """
  return "report.method.fisherProtectedLSD" if protected else "report.method.fisherLSD"


class MeanSeparation(BaseModel):
  """The result of mean separation: the LSD and the lettered treatment means."""

  model_config = ConfigDict(extra="forbid")

  methodKey: str
  significanceLevel: float
  leastSignificantDifference: float
  treatmentSignificant: bool
  groups: list[TreatmentGroup]


def separateMeans(
  anovaResult: AnovaResult,
  significanceLevel: float = 0.05,
  protected: bool = True,
) -> MeanSeparation:
  """Separate treatment means by Fisher's (Protected) LSD."""
  if not 0.0 < significanceLevel < 1.0:
    raise AnalysisError(f"significance level must be in (0, 1), got {significanceLevel}")

  perTreatment = anovaResult.blockCount
  criticalT = tCriticalValue(significanceLevel / 2.0, anovaResult.errorDegreesOfFreedom)
  leastSignificantDifference = criticalT * math.sqrt(2.0 * anovaResult.errorMeanSquare / perTreatment)

  treatmentRow = next(row for row in anovaResult.table if row.source == "treatment")
  treatmentSignificant = treatmentRow.pValue is not None and treatmentRow.pValue <= significanceLevel
  ordered = sorted(anovaResult.treatmentMeans, key=lambda mean: mean.mean, reverse=True)
  means = [mean.mean for mean in ordered]
  if protected and not treatmentSignificant:
    # Protected: no separation when the treatment effect is not significant.
    letters = ["a"] * len(ordered)
  else:
    letters = _letterGroups(means, leastSignificantDifference)

  groups = [
    TreatmentGroup(treatmentCode=mean.treatmentCode, mean=mean.mean, group=letters[index])
    for index, mean in enumerate(ordered)
  ]
  return MeanSeparation(
    methodKey=methodKeyFor(protected),
    significanceLevel=significanceLevel,
    leastSignificantDifference=leastSignificantDifference,
    treatmentSignificant=treatmentSignificant,
    groups=groups,
  )


def _letterGroups(sortedMeans: list[float], leastSignificantDifference: float) -> list[str]:
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
