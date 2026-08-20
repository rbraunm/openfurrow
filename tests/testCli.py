# SPDX-License-Identifier: Apache-2.0
"""Tests for the command-line interface.

Exercises the whole loop through main(): init, add, randomize, import, report,
export, import-json, verify. The reproducibility guarantee is checked end to end
(a trial re-imported into a fresh database has the same content hash), and the
fail-loud paths (missing trial, missing database, duplicate add, no export target)
return non-zero.
"""

import csv
import json
import re
from pathlib import Path

import pytest

from openfurrow.cli.main import main
from openfurrow.design import generateRcbdLayout
from openfurrow.schema import TrialPackage

demoPackage = {
  "schemaVersion": "0.1.0",
  "trial": {"trialCode": "DEMO", "title": "Demo trial", "crop": "Wheat", "season": "2025",
            "site": "Field A", "objective": "Compare treatments"},
  "treatments": [{"treatmentCode": code, "name": code} for code in ["A", "B", "C", "D"]],
  "design": {"designType": "rcbd", "replications": 3, "randomizationSeed": 1},
  "assessments": [{"assessmentCode": "YIELD", "name": "Yield", "dataType": "numeric", "unit": "kg/ha", "minValue": 0}],
}
demoValues = {
  ("A", 1): 106, ("A", 2): 99, ("A", 3): 95, ("B", 1): 103, ("B", 2): 100, ("B", 3): 94,
  ("C", 1): 86, ("C", 2): 79, ("C", 3): 75, ("D", 1): 83, ("D", 2): 80, ("D", 3): 74,
}


@pytest.fixture
def project(tmp_path):
  packagePath = tmp_path / "demo.json"
  packagePath.write_text(json.dumps(demoPackage), encoding="utf-8")
  package = TrialPackage.model_validate(demoPackage)
  layout = generateRcbdLayout(package)
  observationsPath = tmp_path / "obs.csv"
  with observationsPath.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.writer(handle)
    writer.writerow(["plotNumber", "assessmentCode", "value"])
    for plot in sorted(layout.plots, key=lambda plot: plot.plotNumber):
      writer.writerow([plot.plotNumber, "YIELD", demoValues[(plot.treatmentCode, plot.block)]])
  return {
    "db": str(tmp_path / "trials.db"),
    "db2": str(tmp_path / "trials2.db"),
    "package": str(packagePath),
    "obs": str(observationsPath),
    "dir": tmp_path,
  }


def setUpTrialWithData(project):
  assert main(["init", project["db"]]) == 0
  assert main(["add", project["db"], project["package"]]) == 0
  assert main(["import", project["db"], "DEMO", project["obs"]]) == 0


def hashFromInfo(text):
  match = re.search(r"Content hash: ([0-9a-f]{64})", text)
  assert match, f"no content hash in:\n{text}"
  return match.group(1)


# ---- basic commands -------------------------------------------------------

def testInitAddList(project, capsys):
  assert main(["init", project["db"]]) == 0
  assert main(["add", project["db"], project["package"]]) == 0
  capsys.readouterr()
  assert main(["list", project["db"]]) == 0
  out = capsys.readouterr().out
  assert "DEMO" in out and "Demo trial" in out


def testImportReportsCount(project, capsys):
  setUpTrialWithData(project)
  out = capsys.readouterr().out
  assert "Imported 12 observations for 'DEMO'" in out


def testRandomizeIsDeterministic(project, capsys):
  assert main(["init", project["db"]]) == 0
  assert main(["add", project["db"], project["package"]]) == 0
  capsys.readouterr()
  assert main(["randomize", project["db"], "DEMO"]) == 0
  first = capsys.readouterr().out
  assert main(["randomize", project["db"], "DEMO"]) == 0
  second = capsys.readouterr().out
  assert first == second
  assert "101\t1\t1\tA" in first  # seed-1 layout is stable


# ---- report ---------------------------------------------------------------

def testReportShowsAovMeansTable(project, capsys):
  setUpTrialWithData(project)
  capsys.readouterr()
  assert main(["report", project["db"], "DEMO"]) == 0
  report = capsys.readouterr().out
  assert "### Analysis of variance" in report
  assert "| Treatment | 3 | 1203.0000 | 401.0000 | 300.75 | < 0.0001 |" in report
  assert "Treatment effect significant" in report
  assert "| A | 100.000 | a |" in report
  assert "| C | 80.000 | b |" in report


def testReportWritesToFile(project, capsys):
  setUpTrialWithData(project)
  outputPath = Path(project["dir"]) / "report.md"
  assert main(["report", project["db"], "DEMO", "--output", str(outputPath)]) == 0
  assert outputPath.exists()
  assert "### Analysis of variance" in outputPath.read_text(encoding="utf-8")


def testReportUsesConfigSignificance(project, capsys):
  setUpTrialWithData(project)
  configPath = Path(project["dir"]) / "openfurrow.yaml"
  configPath.write_text("analysis:\n  significanceLevel: 0.01\n", encoding="utf-8")
  capsys.readouterr()
  assert main(["report", project["db"], "DEMO", "--config", str(configPath)]) == 0
  report = capsys.readouterr().out
  assert "alpha = 0.01" in report


# ---- export / import-json / verify (round trip) ---------------------------

def testExportImportJsonVerifyRoundTrip(project, capsys):
  setUpTrialWithData(project)
  documentPath = Path(project["dir"]) / "demo-doc.json"
  csvPath = Path(project["dir"]) / "demo-obs.csv"
  capsys.readouterr()

  assert main(["export", project["db"], "DEMO", "--json", str(documentPath), "--csv", str(csvPath)]) == 0
  assert documentPath.exists() and csvPath.exists()

  assert main(["import-json", project["db2"], str(documentPath)]) == 0

  assert main(["verify", project["db"], "DEMO"]) == 0
  assert "PASS" in capsys.readouterr().out

  # the two databases describe the same trial: identical content hash
  assert main(["info", project["db"], "DEMO"]) == 0
  hashOne = hashFromInfo(capsys.readouterr().out)
  assert main(["info", project["db2"], "DEMO"]) == 0
  hashTwo = hashFromInfo(capsys.readouterr().out)
  assert hashOne == hashTwo


def testDeleteRemovesTrial(project, capsys):
  setUpTrialWithData(project)
  assert main(["delete", project["db"], "DEMO"]) == 0
  assert main(["info", project["db"], "DEMO"]) == 1  # now not found


# ---- fail loud ------------------------------------------------------------

def testMissingDatabaseErrors(project, capsys):
  assert main(["list", project["db"]]) == 1
  assert "does not exist" in capsys.readouterr().err


def testMissingTrialErrors(project, capsys):
  assert main(["init", project["db"]]) == 0
  capsys.readouterr()
  assert main(["report", project["db"], "GHOST"]) == 1
  assert "not found" in capsys.readouterr().err


def testAddDuplicateErrors(project, capsys):
  assert main(["init", project["db"]]) == 0
  assert main(["add", project["db"], project["package"]]) == 0
  capsys.readouterr()
  assert main(["add", project["db"], project["package"]]) == 1
  assert "already exists" in capsys.readouterr().err


def testExportRequiresTarget(project, capsys):
  setUpTrialWithData(project)
  capsys.readouterr()
  assert main(["export", project["db"], "DEMO"]) == 2
  assert "specify --json" in capsys.readouterr().err


def testInvalidPackageRejected(project, capsys):
  broken = dict(demoPackage)
  broken["treatments"] = demoPackage["treatments"][:1]  # min is 2
  brokenPath = Path(project["dir"]) / "broken.json"
  brokenPath.write_text(json.dumps(broken), encoding="utf-8")
  assert main(["init", project["db"]]) == 0
  capsys.readouterr()
  assert main(["add", project["db"], str(brokenPath)]) == 1
  assert "error:" in capsys.readouterr().err


def testInfoSurfacesTransformAndMeasurementKind(tmp_path, capsys):
  """info shows each numeric assessment's transform and measurement kind (the gap the
  unit closes: previously visible only by reading the trial JSON), and the allowed
  values of a categorical/ordinal assessment."""
  packageDict = {
    "schemaVersion": "0.1.0",
    "trial": {"trialCode": "INFO-1", "title": "Info trial", "crop": "Barley", "season": "2025",
              "site": "Field A", "objective": "Compare"},
    "treatments": [{"treatmentCode": code, "name": code} for code in ["A", "B"]],
    "design": {"designType": "rcbd", "replications": 2, "randomizationSeed": 1},
    "assessments": [
      {"assessmentCode": "CT", "name": "Insect count", "dataType": "numeric", "unit": "per m2",
       "minValue": 0, "transform": "sqrt", "measurementKind": "count"},
      {"assessmentCode": "SEV", "name": "Severity", "dataType": "ordinal",
       "allowedValues": ["none", "low", "high"]},
    ],
  }
  packagePath = tmp_path / "info.json"
  packagePath.write_text(json.dumps(packageDict), encoding="utf-8")
  db = str(tmp_path / "info.db")
  assert main(["init", db]) == 0
  assert main(["add", db, str(packagePath)]) == 0
  capsys.readouterr()
  assert main(["info", db, "INFO-1"]) == 0
  out = capsys.readouterr().out
  assert "transform=sqrt" in out
  assert "kind=count" in out
  assert "values=none/low/high" in out
  # A default numeric assessment still shows its (default) transform and kind.
  assert "unit=per m2" in out


def testInfoShowsDefaultTransformForPlainNumeric(project, capsys):
  """Even at defaults, transform and kind are shown, so the current setting is visible."""
  assert main(["init", project["db"]]) == 0
  assert main(["add", project["db"], project["package"]]) == 0
  capsys.readouterr()
  assert main(["info", project["db"], "DEMO"]) == 0
  out = capsys.readouterr().out
  assert "transform=none" in out
  assert "kind=unspecified" in out
