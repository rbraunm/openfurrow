# SPDX-License-Identifier: Apache-2.0
"""Mean separation for an ANOVA: Fisher's LSD, protected or not, and Tukey's HSD.

Each method compares every pair of treatment means against a critical difference and
shows the result as a compact letter display: means that share a letter are not
significantly different at the chosen level.

- **Fisher's protected LSD** (the default, as in ARM): t(alpha/2, error df) * the standard
  error of the difference, applied only when the treatment F is significant.
- **Fisher's LSD**: the same difference, applied regardless of F.
- **Tukey's HSD**: q(1 - alpha; t, error df) / sqrt(2) * the standard error of the
  difference, q being the studentized range of the t means; it holds the chance of any
  false difference among all pairs at alpha, and is applied regardless of F.

With equal replication every pair has the standard error sqrt(2 MS error / n), so there is
one critical difference: the LSD, or the HSD q * sqrt(MS error / n). With unequal
replication, which a missing plot brings about (decision 0043), each pair has its own
standard error from the analysis' covariance of the means, and so its own critical
difference; Tukey's test in that form is the Tukey-Kramer test. The t and q quantiles are
self-authored (decision 0002).

A letter stands for a largest set of means no two of which differ. With one critical
difference those sets are runs of consecutive sorted means; with a difference for each
pair they need not be, so they are found as the maximal cliques of the pairs that do not
differ.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from enum import Enum

from pydantic import BaseModel, ConfigDict

from openfurrow.analysis.anova import AnalysisError, AnovaResult, differenceStandardError, meanStandardError
from openfurrow.analysis.distributions import tCriticalValue
from openfurrow.analysis.studentizedRange import studentizedRangeQuantile


class MeanComparison(str, Enum):
  """The test that separates means after an analysis of variance."""

  protectedLSD = "protectedLSD"  # Fisher's LSD, only when the treatment F is significant
  lsd = "lsd"  # Fisher's LSD, applied regardless
  tukeyHSD = "tukeyHSD"  # Tukey's honestly significant difference, applied regardless
  dunnett = "dunnett"  # Dunnett's test of every treatment against the untreated check


def criticalValue(
  meanComparison: MeanComparison, significanceLevel: float, meanCount: int, errorDegreesOfFreedom: int,
) -> float:
  """What the standard error of a difference between two of `meanCount` means is multiplied by to test it."""
  if meanComparison is MeanComparison.dunnett:
    raise AnalysisError("Dunnett's critical difference compares with the check; see analysis.dunnett")
  if meanComparison is MeanComparison.tukeyHSD:
    return studentizedRangeQuantile(1.0 - significanceLevel, meanCount, errorDegreesOfFreedom) / math.sqrt(2.0)
  return tCriticalValue(significanceLevel / 2.0, errorDegreesOfFreedom)


def criticalDifference(
  meanComparison: MeanComparison, significanceLevel: float, meanCount: int,
  errorMeanSquare: float, errorDegreesOfFreedom: int, perMean: int,
) -> float:
  """The difference two of `meanCount` means of `perMean` observations each must exceed to be called different."""
  return (
    criticalValue(meanComparison, significanceLevel, meanCount, errorDegreesOfFreedom)
    * math.sqrt(2.0 * errorMeanSquare / perMean)
  )


def commonValue(values: list[float]) -> float | None:
  """The one value `values` share, or None when they differ by more than rounding."""
  low, high = min(values), max(values)
  return high if high - low <= 1.0e-9 * abs(high) else None


class TreatmentGroup(BaseModel):
  """A treatment's mean, its standard error and its letter grouping."""

  model_config = ConfigDict(extra="forbid")

  treatmentCode: str
  mean: float
  standardError: float
  group: str


class PairComparison(BaseModel):
  """Two treatment means: their difference, its standard error, and the difference it must exceed."""

  model_config = ConfigDict(extra="forbid")

  firstTreatmentCode: str
  secondTreatmentCode: str
  difference: float
  standardError: float
  criticalDifference: float
  significant: bool


def methodKeyFor(meanComparison: MeanComparison, unequalReplication: bool = False) -> str:
  """The catalog key naming the separation method.

  The analysis layer names the method with a key, never with a sentence (decision
  0007): a display string built here would be English in every locale, and this is
  the one place that knows which method ran. The reproducibility section resolves the
  same key from the same function, so the two cannot describe different methods.
  Tukey's test on pairs with standard errors of their own is the Tukey-Kramer test.
  """
  if meanComparison is MeanComparison.tukeyHSD and unequalReplication:
    return "report.method.tukeyKramer"
  return {
    MeanComparison.protectedLSD: "report.method.fisherProtectedLSD",
    MeanComparison.lsd: "report.method.fisherLSD",
    MeanComparison.tukeyHSD: "report.method.tukeyHSD",
    MeanComparison.dunnett: "report.method.dunnett",
  }[meanComparison]


class MeanSeparation(BaseModel):
  """The result of mean separation: the lettered treatment means and every pair compared.

  `criticalDifference` is the one difference every pair is held to and `standardError`
  the one standard error of every mean; each is None when replication is unequal, and
  then each pair's own are in `comparisons` and each mean's own in `groups`.
  """

  model_config = ConfigDict(extra="forbid")

  methodKey: str
  significanceLevel: float
  criticalValue: float
  criticalDifference: float | None
  standardError: float | None
  treatmentSignificant: bool
  groups: list[TreatmentGroup]
  comparisons: list[PairComparison]


def separateMeans(
  anovaResult: AnovaResult,
  significanceLevel: float = 0.05,
  meanComparison: MeanComparison = MeanComparison.protectedLSD,
) -> MeanSeparation:
  """Separate treatment means by the chosen test into letter groups."""
  if meanComparison is MeanComparison.dunnett:
    raise AnalysisError("Dunnett's test compares each treatment with the check rather than grouping them; use compareWithControl")
  if not 0.0 < significanceLevel < 1.0:
    raise AnalysisError(f"significance level must be in (0, 1), got {significanceLevel}")
  critical = criticalValue(
    meanComparison, significanceLevel, anovaResult.treatmentCount, anovaResult.errorDegreesOfFreedom,
  )
  treatmentRow = next(row for row in anovaResult.table if row.source == "treatment")
  treatmentSignificant = treatmentRow.pValue is not None and treatmentRow.pValue <= significanceLevel
  separated = meanComparison is not MeanComparison.protectedLSD or treatmentSignificant
  means = anovaResult.treatmentMeans
  order = sorted(range(len(means)), key=lambda index: means[index].mean, reverse=True)
  comparisons = []
  differing = set()
  for higher in range(len(order)):
    for lower in range(higher + 1, len(order)):
      first, second = order[higher], order[lower]
      difference = means[first].mean - means[second].mean
      standardError = differenceStandardError(anovaResult, first, second)
      significant = separated and difference > critical * standardError
      if significant:
        differing.add((higher, lower))
      comparisons.append(PairComparison(
        firstTreatmentCode=means[first].treatmentCode, secondTreatmentCode=means[second].treatmentCode,
        difference=difference, standardError=standardError, criticalDifference=critical * standardError,
        significant=significant,
      ))
  letters = lettersFor(len(order), lambda higher, lower: (higher, lower) in differing)
  common = commonValue([comparison.criticalDifference for comparison in comparisons])
  standardErrors = [meanStandardError(anovaResult, index) for index in order]
  return MeanSeparation(
    methodKey=methodKeyFor(meanComparison, unequalReplication=common is None),
    significanceLevel=significanceLevel,
    criticalValue=critical,
    criticalDifference=common,
    standardError=commonValue(standardErrors),
    treatmentSignificant=treatmentSignificant,
    groups=[
      TreatmentGroup(
        treatmentCode=means[index].treatmentCode, mean=means[index].mean, standardError=standardErrors[position],
        group=letters[position],
      )
      for position, index in enumerate(order)
    ],
    comparisons=comparisons,
  )


def letterGroups(sortedMeans: list[float], leastSignificantDifference: float) -> list[str]:
  """Compact letter display for means sorted in descending order, all held to one critical difference."""
  return lettersFor(
    len(sortedMeans),
    lambda higher, lower: (sortedMeans[higher] - sortedMeans[lower]) > leastSignificantDifference,
  )


def lettersFor(count: int, differ: Callable[[int, int], bool]) -> list[str]:
  """Compact letter display for `count` means in descending order; `differ(i, j)` for i < j says a pair differs.

  Each letter is a largest set of means no two of which differ (a maximal clique of the
  pairs that do not, found by the Bron-Kerbosch method), lettered in order of its highest
  means. Two means share a letter exactly when they do not differ.
  """
  alike = [
    {other for other in range(count) if other != index and not differ(min(index, other), max(index, other))}
    for index in range(count)
  ]
  sets: list[list[int]] = []

  def grow(chosen: list[int], candidates: set[int], excluded: set[int]) -> None:
    if not candidates and not excluded:
      sets.append(sorted(chosen))
      return
    pivot = max(sorted(candidates | excluded), key=lambda index: len(candidates & alike[index]))
    for index in sorted(candidates - alike[pivot]):
      grow(chosen + [index], candidates & alike[index], excluded & alike[index])
      candidates = candidates - {index}
      excluded = excluded | {index}

  grow([], set(range(count)), set())
  membership: list[list[int]] = [[] for _ in range(count)]
  for letterIndex, members in enumerate(sorted(sets)):
    for position in members:
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
