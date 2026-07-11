# SPDX-License-Identifier: Apache-2.0
"""Tests for Field Book ingest (E1b): a database (long) export into observations.

Ingest reuses the standard importer with the Field Book column mapping, so these
tests prove the mapping: the shipped conformant fixture parses to the exact expected
observations (unique-id -> plot, `trait` -> assessmentCode, `value` -> value; the
provenance columns ignored), and a full round-trip -- observations out to a Field Book
export and back into a fresh store -- reproduces the same content hash, which is the
reproducibility guarantee the whole platform rests on.
"""

import csv
from pathlib import Path

import pytest

from openfurrow.schema import TrialPackage
from openfurrow.workspace import Workspace

_fixtureDir = Path(__file__).parent / "fixtures"

_packageDict = {
  "schemaVersion": "0.1.0",
  "trial": {"trialCode": "FB-IN", "title": "Field Book ingest", "crop": "Barley", "season": "2025",
            "site": "North Field", "objective": "Compare treatments"},
  "treatments": [{"treatmentCode": code, "name": code} for code in ["A", "B", "C", "D"]],
  "design": {"designType": "rcbd", "replications": 3, "randomizationSeed": 7},
  "assessments": [
    {"assessmentCode": "YIELD", "name": "Grain yield", "dataType": "numeric",
     "unit": "kg/ha", "minValue": 0, "maxValue": 400},
    {"assessmentCode": "SEV", "name": "Disease severity", "dataType": "ordinal",
     "allowedValues": ["none", "low", "moderate", "high"]},
  ],
}


@pytest.fixture
def workspace(tmp_path):
  ws = Workspace.create(str(tmp_path / "trials.db"))
  ws.addPackage(TrialPackage.model_validate(_packageDict))
  return ws


def _byKey(observations):
  return {(observation.plotNumber, observation.assessmentCode): observation.value
          for observation in observations}


# ---- ingest a conformant export -------------------------------------------

def testIngestFixtureProducesExactObservations(workspace):
  result = workspace.importFieldBook("FB-IN", str(_fixtureDir / "fieldbook_database_export.csv"))
  assert len(result.observations) == 15

  stored = _byKey(workspace.loadObservations("FB-IN"))
  plots = [101, 102, 103, 104, 201, 202, 203, 204, 301, 302, 303, 304]
  expected = {(plot, "YIELD"): float(plot) for plot in plots}
  expected[(101, "SEV")] = "low"
  expected[(102, "SEV")] = "moderate"
  expected[(103, "SEV")] = "high"
  assert stored == expected


def testIngestRejectsPlotOutsideLayout(workspace, tmp_path):
  # A row referencing a plot the trial does not have must fail loud.
  path = tmp_path / "bad.csv"
  with path.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.writer(handle)
    writer.writerow(["plotNumber", "block", "treatment", "trait", "value", "device_name"])
    writer.writerow([999, 1, "A", "YIELD", 100, "Pixel-7"])
  with pytest.raises(Exception):
    workspace.importFieldBook("FB-IN", str(path))


# ---- full round-trip preserves the content hash --------------------------

def _writeFieldBookExport(observations, path):
  """Write observations as a Field Book database (long) export (test producer)."""
  header = ["plotNumber", "block", "treatment", "trait", "value", "timestamp",
            "person", "location", "number", "attached_photo", "attached_video",
            "attached_audio", "device_name"]
  with open(path, "w", newline="", encoding="utf-8") as handle:
    writer = csv.writer(handle)
    writer.writerow(header)
    for observation in observations:
      value = "" if observation.value is None else observation.value
      writer.writerow([observation.plotNumber, "", "", observation.assessmentCode, value,
                       "2025-06-01 10:00:00-05:00", "Field Tech", "North Field", 1,
                       "", "", "", "Pixel-7"])


def testRoundTripThroughFieldBookPreservesHash(workspace, tmp_path):
  # Populate the source trial with a complete set of YIELD observations.
  plotNumbers = sorted(plot.plotNumber for plot in workspace.layoutFor("FB-IN").plots)
  sourceCsv = tmp_path / "obs.csv"
  with sourceCsv.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.writer(handle)
    writer.writerow(["plotNumber", "assessmentCode", "value"])
    for plot in plotNumbers:
      writer.writerow([plot, "YIELD", plot])
  from openfurrow.config import defaultConfig
  workspace.importObservations("FB-IN", str(sourceCsv), defaultConfig().importProfile)
  sourceHash = workspace.contentHashFor("FB-IN")

  # Out to a Field Book export, then back into a fresh store with the same package.
  exportCsv = tmp_path / "fb_database.csv"
  _writeFieldBookExport(workspace.loadObservations("FB-IN"), exportCsv)

  fresh = Workspace.create(str(tmp_path / "fresh.db"))
  fresh.addPackage(TrialPackage.model_validate(_packageDict))
  fresh.importFieldBook("FB-IN", str(exportCsv))
  assert fresh.contentHashFor("FB-IN") == sourceHash
