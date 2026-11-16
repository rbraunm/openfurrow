# SPDX-License-Identifier: Apache-2.0
"""The trial document: the portable unit of a trial.

A trial document is a trial package together with its layout and its observations --
the whole trial in one object. It is the unit that is exported to and imported from
JSON, and the unit the content hash is computed over. The layout is part of it
(decision 0015): which treatment stands on which plot is a fact about the field, so it
is recorded and hashed, not recomputed.

A document is consistent or it does not exist. Its layout must be complete blocks of
the package's treatments; if the package says the layout was generated, it must be
exactly what that method produces from the seed; and every observation must belong to
a plot of the layout.

The canonical form sorts plots and observations and sorts object keys so the
serialization is deterministic: the same trial always produces the same bytes, and
therefore the same hash, regardless of order or how it was assembled.
"""

from __future__ import annotations

import math

import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field, model_validator

from openfurrow.schema.assessment import AssessmentDataType, Rating
from openfurrow.schema.layout import CheckPlot, PlotAssignment, TrialLayout
from openfurrow.schema.observation import Observation
from openfurrow.schema.trialPackage import RandomizationMethod, TrialPackage


class TrialDocument(BaseModel):
  """A trial package, its layout and its observations: the exportable, hashable trial."""

  model_config = ConfigDict(extra="forbid")

  package: TrialPackage
  layout: list[PlotAssignment]
  checkPlots: list[CheckPlot] = Field(default_factory=list, description="Untreated checks beside the plots.")
  observations: list[Observation] = Field(default_factory=list)

  @model_validator(mode="after")
  def layoutBelongsToThePackage(self) -> TrialDocument:
    design = self.package.design
    TrialLayout.forPackage(self.package, self.layout, self.checkPlots)

    if design.randomizationMethod is not RandomizationMethod.imported:
      # Imported here, not at the top: the design package builds on this schema
      # package, so a top-level import would make the two depend on import order.
      from openfurrow.design.randomization import generateLayout

      generated = generateLayout(self.package)
      if (_byPlotNumber(self.layout) != _byPlotNumber(generated.plots)
          or _byPlotNumber(self.checkPlots) != _byPlotNumber(generated.checkPlots)):
        raise ValueError(
          f"the layout is not the one method '{design.randomizationMethod.value}' produces "
          f"from seed {design.randomizationSeed}; a layout made or changed elsewhere is "
          f"declared with randomizationMethod '{RandomizationMethod.imported.value}'"
        )

    checkObservationValues(self.package, self.observations)
    plotNumbers = {plot.plotNumber for plot in self.layout} | {check.plotNumber for check in self.checkPlots}
    stray = sorted({observation.plotNumber for observation in self.observations} - plotNumbers)
    if stray:
      raise ValueError(f"observations reference plots that are not in the layout: {stray}")
    return self

  def canonicalDict(self) -> dict:
    """A deterministic dict of the document: plots and observations sorted, JSON-mode values."""
    return {
      "package": self.package.model_dump(mode="json"),
      "layout": sorted(
        (plot.model_dump(mode="json") for plot in self.layout),
        key=lambda row: row["plotNumber"],
      ),
      "checkPlots": sorted(
        (check.model_dump(mode="json") for check in self.checkPlots),
        key=lambda row: row["plotNumber"],
      ),
      "observations": sorted(
        (observation.model_dump(mode="json") for observation in self.observations),
        key=lambda row: (row["plotNumber"], row["assessmentCode"]),
      ),
    }


def isOutOfRange(rating: Rating, value: float) -> bool:
  """True when a numeric value lies outside the rating's limits."""
  return (rating.minValue is not None and value < rating.minValue) or (
    rating.maxValue is not None and value > rating.maxValue
  )


def checkObservationValues(package: TrialPackage, observations: list[Observation]) -> None:
  """Raise unless every value fits its assessment's rating (decision 0023).

  A numeric value is a finite number and a category is one of the rating's values. A
  number outside the rating's limits is kept only when a person confirmed it, and a
  confirmation on anything else is refused, so the flag always means what it says.
  """
  for observation in observations:
    where = f"plot {observation.plotNumber}, assessment '{observation.assessmentCode}'"
    try:
      rating = package.ratingFor(observation.assessmentCode)
    except KeyError as error:
      raise ValueError(f"{where}: {error.args[0]}") from error
    value = observation.value
    outside = False
    if value is None:
      pass
    elif rating.dataType is AssessmentDataType.numeric:
      if isinstance(value, str) or not math.isfinite(value):
        raise ValueError(f"{where}: {value!r} is not a finite number")
      outside = isOutOfRange(rating, value)
    elif not isinstance(value, str) or value not in rating.allowedValues:
      raise ValueError(f"{where}: {value!r} is not one of {rating.allowedValues}")
    if outside and not observation.outOfRangeConfirmed:
      raise ValueError(f"{where}: {value} is outside the rating's limits and was not confirmed")
    if observation.outOfRangeConfirmed and not outside:
      raise ValueError(f"{where}: a confirmation is recorded for a value that is not outside the limits")


def _byPlotNumber(plots: list[PlotAssignment] | list[CheckPlot]) -> dict[int, PlotAssignment | CheckPlot]:
  return {plot.plotNumber: plot for plot in plots}


def canonicalBytes(document: TrialDocument) -> bytes:
  """The canonical UTF-8 JSON bytes of a document (sorted keys, compact)."""
  return json.dumps(document.canonicalDict(), sort_keys=True, separators=(",", ":")).encode("utf-8")


def contentHash(document: TrialDocument) -> str:
  """A stable SHA-256 over the document's canonical bytes."""
  return hashlib.sha256(canonicalBytes(document)).hexdigest()
