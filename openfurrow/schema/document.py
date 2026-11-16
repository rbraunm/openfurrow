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

import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field, model_validator

from openfurrow.schema.layout import PlotAssignment, checkCompleteBlocks
from openfurrow.schema.observation import Observation
from openfurrow.schema.trialPackage import RandomizationMethod, TrialPackage


class TrialDocument(BaseModel):
  """A trial package, its layout and its observations: the exportable, hashable trial."""

  model_config = ConfigDict(extra="forbid")

  package: TrialPackage
  layout: list[PlotAssignment]
  observations: list[Observation] = Field(default_factory=list)

  @model_validator(mode="after")
  def layoutBelongsToThePackage(self) -> TrialDocument:
    design = self.package.design
    treatmentCodes = [treatment.treatmentCode for treatment in self.package.treatments]
    checkCompleteBlocks(treatmentCodes, design.replications, self.layout)

    if design.randomizationMethod is not RandomizationMethod.imported:
      # Imported here, not at the top: the design package builds on this schema
      # package, so a top-level import would make the two depend on import order.
      from openfurrow.design.randomization import generateRcbdLayout

      generated = generateRcbdLayout(self.package).plots
      if _byPlotNumber(self.layout) != _byPlotNumber(generated):
        raise ValueError(
          f"the layout is not the one method '{design.randomizationMethod.value}' produces "
          f"from seed {design.randomizationSeed}; a layout made or changed elsewhere is "
          f"declared with randomizationMethod '{RandomizationMethod.imported.value}'"
        )

    plotNumbers = {plot.plotNumber for plot in self.layout}
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
      "observations": sorted(
        (observation.model_dump(mode="json") for observation in self.observations),
        key=lambda row: (row["plotNumber"], row["assessmentCode"]),
      ),
    }


def _byPlotNumber(plots: list[PlotAssignment]) -> dict[int, PlotAssignment]:
  return {plot.plotNumber: plot for plot in plots}


def canonicalBytes(document: TrialDocument) -> bytes:
  """The canonical UTF-8 JSON bytes of a document (sorted keys, compact)."""
  return json.dumps(document.canonicalDict(), sort_keys=True, separators=(",", ":")).encode("utf-8")


def contentHash(document: TrialDocument) -> str:
  """A stable SHA-256 over the document's canonical bytes."""
  return hashlib.sha256(canonicalBytes(document)).hexdigest()
