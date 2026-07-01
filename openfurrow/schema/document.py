# SPDX-License-Identifier: Apache-2.0
"""The trial document: the portable unit of a trial.

A trial document is a trial package together with its observations -- the whole
reproducible trial in one object. It is the unit that is exported to and imported
from JSON, and the unit the content hash is computed over. The layout is not part
of it: the layout is regenerable from the package's seed, so hashing or exporting
package plus observations captures the trial completely.

The canonical form sorts observations and sorts object keys so the serialization
is deterministic: the same trial always produces the same bytes, and therefore the
same hash, regardless of observation order or how it was assembled.
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field

from openfurrow.schema.observation import Observation
from openfurrow.schema.trialPackage import TrialPackage


class TrialDocument(BaseModel):
  """A trial package and its observations: the exportable, hashable trial."""

  model_config = ConfigDict(extra="forbid")

  package: TrialPackage
  observations: list[Observation] = Field(default_factory=list)

  def canonicalDict(self) -> dict:
    """A deterministic dict of the document: observations sorted, JSON-mode values."""
    return {
      "package": self.package.model_dump(mode="json"),
      "observations": sorted(
        (observation.model_dump(mode="json") for observation in self.observations),
        key=lambda row: (row["plotNumber"], row["assessmentCode"]),
      ),
    }


def canonicalBytes(document: TrialDocument) -> bytes:
  """The canonical UTF-8 JSON bytes of a document (sorted keys, compact)."""
  return json.dumps(document.canonicalDict(), sort_keys=True, separators=(",", ":")).encode("utf-8")


def contentHash(document: TrialDocument) -> str:
  """A stable SHA-256 over the document's canonical bytes."""
  return hashlib.sha256(canonicalBytes(document)).hexdigest()
