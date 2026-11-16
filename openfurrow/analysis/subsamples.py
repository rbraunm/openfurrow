# SPDX-License-Identifier: Apache-2.0
"""Plot values from subsamples (decision 0033).

An assessment that takes subsamples keeps every value as entered; the analysis runs on
one value per plot, derived by the assessment's rule. The mean is taken over the
subsamples recorded, as ARM does ("Average ... Subsamples functions automatically
ignore missing data"), and the report names every plot with fewer than the full count.
A sum is a total over a fixed set of units, so a plot short of any subsample stops the
analysis instead. A plot with no subsample recorded has no value.
"""

from __future__ import annotations

from openfurrow.analysis.anova import AnalysisError
from openfurrow.schema.assessment import SubsampleRule
from openfurrow.schema.observation import Observation
from openfurrow.schema.trialPackage import TrialPackage


def plotValues(
  assessmentCode: str, package: TrialPackage, observations: list[Observation],
) -> dict[int, float | str | None]:
  """Each plot's value for one assessment: as recorded, or derived from its subsamples."""
  try:
    subsamples = package.assessmentFor(assessmentCode).subsamples
  except KeyError as error:
    raise AnalysisError(error.args[0]) from error
  given = [observation for observation in observations if observation.assessmentCode == assessmentCode]
  if subsamples is None:
    return {observation.plotNumber: observation.value for observation in given}
  recorded: dict[int, list[float]] = {}
  for observation in given:
    values = recorded.setdefault(observation.plotNumber, [])
    if observation.value is not None:
      values.append(float(observation.value))
  if subsamples.rule is SubsampleRule.sum:
    short = sorted(plot for plot, values in recorded.items() if 0 < len(values) < subsamples.count)
    if short:
      raise AnalysisError(
        f"assessment '{assessmentCode}' sums its {subsamples.count} subsamples, and plots {short} are short of "
        f"some; a total over fewer units is not comparable"
      )
    return {plot: (sum(values) if values else None) for plot, values in recorded.items()}
  return {plot: (sum(values) / len(values) if values else None) for plot, values in recorded.items()}


def missingSubsamples(assessmentCode: str, package: TrialPackage, observations: list[Observation]) -> dict[int, int]:
  """For a mean of subsamples: each plot with a value but fewer than the full count, and how many it lacks."""
  subsamples = package.assessmentFor(assessmentCode).subsamples
  if subsamples is None:
    return {}
  recorded: dict[int, int] = {}
  for observation in observations:
    if observation.assessmentCode == assessmentCode:
      recorded.setdefault(observation.plotNumber, 0)
      if observation.value is not None:
        recorded[observation.plotNumber] += 1
  return {plot: subsamples.count - count for plot, count in sorted(recorded.items()) if 0 < count < subsamples.count}
