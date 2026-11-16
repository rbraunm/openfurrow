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
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from openfurrow import schemaVersion
from openfurrow.cli.main import main
from openfurrow.design import generateRcbdLayout
from openfurrow.schema import TrialPackage

repositoryRoot = Path(__file__).parent.parent

demoPackage = {
  "schemaVersion": schemaVersion,
  "trial": {"trialCode": "DEMO", "title": "Demo trial", "crop": "Wheat", "season": "2025",
            "site": "Field A", "objective": "Compare treatments"},
  "treatments": [{"treatmentCode": code, "name": code} for code in ["A", "B", "C", "D"]],
  "design": {"designType": "rcbd", "replications": 3, "randomizationMethod": "sha256FisherYates1", "randomizationSeed": 1},
  "ratings": [
    {"ratingCode": "YIELD", "name": "Yield", "dataType": "numeric", "unit": "kg/ha", "minValue": 0}
  ],
  "assessments": [
    {"assessmentCode": "YIELD", "ratingCode": "YIELD"}
  ],
}
demoValues = {
  ("A", 1): 106, ("A", 2): 99, ("A", 3): 95, ("B", 1): 103, ("B", 2): 100, ("B", 3): 94,
  ("C", 1): 86, ("C", 2): 79, ("C", 3): 75, ("D", 1): 83, ("D", 2): 80, ("D", 3): 74,
}


@pytest.fixture
def project(tmp_path, newStore):
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
    "db": newStore("trials"),
    "db2": newStore("trials2"),
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
  assert "Layout for 'DEMO' (sha256FisherYates1, seed 1):" in first
  assert "101\t1\t1\tC" in first  # the recorded seed-1 layout


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
  assert b"\r" not in outputPath.read_bytes()


def testRedirectedReportIsUTF8InEveryLocale(project):
  """Printed to a pipe, a report is UTF-8 whatever the platform's code page.

  Runs the command as a process of its own, without the variables that would force an
  encoding, because the encoding of a redirected stream is decided at process start.
  """
  setUpTrialWithData(project)
  environment = {
    name: value for name, value in os.environ.items()
    if name not in ("PYTHONIOENCODING", "PYTHONUTF8")
  }
  for locale in ("ar", "fr"):
    outputPath = Path(project["dir"]) / f"report-{locale}.md"
    assert main(["report", project["db"], "DEMO", "--locale", locale, "--output", str(outputPath)]) == 0
    completed = subprocess.run(
      [sys.executable, "-m", "openfurrow.cli.main", "report", project["db"], "DEMO", "--locale", locale],
      capture_output=True, env=environment, cwd=repositoryRoot,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    printed = completed.stdout.decode("utf-8").replace("\r\n", "\n")
    assert printed.rstrip("\n") == outputPath.read_text(encoding="utf-8").rstrip("\n")


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
  assert "create it first" in capsys.readouterr().err


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


def testInfoSurfacesTransformAndMeasurementKind(tmp_path, newStore, capsys):
  """info shows each numeric assessment's transform and measurement kind (the gap the
  unit closes: previously visible only by reading the trial JSON), and the allowed
  values of a categorical/ordinal assessment."""
  packageDict = {
    "schemaVersion": schemaVersion,
    "trial": {"trialCode": "INFO-1", "title": "Info trial", "crop": "Barley", "season": "2025",
              "site": "Field A", "objective": "Compare"},
    "treatments": [{"treatmentCode": code, "name": code} for code in ["A", "B"]],
    "design": {"designType": "rcbd", "replications": 2, "randomizationMethod": "sha256FisherYates1", "randomizationSeed": 1},
    "ratings": [
      {"ratingCode": "CT", "name": "Insect count", "dataType": "numeric", "unit": "per m2", "minValue": 0, "transform": "sqrt", "measurementKind": "count"},
      {"ratingCode": "SEV", "name": "Severity", "dataType": "ordinal", "allowedValues": ["none", "low", "high"]}
    ],
    "assessments": [
      {"assessmentCode": "CT", "ratingCode": "CT"},
      {"assessmentCode": "SEV", "ratingCode": "SEV"}
    ],
  }
  packagePath = tmp_path / "info.json"
  packagePath.write_text(json.dumps(packageDict), encoding="utf-8")
  db = newStore("info")
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
  assert "Layout: sha256FisherYates1, seed 1" in out


def testInfoListsTreatmentsAndApplications(tmp_path, newStore, capsys, validPackageDict):
  packagePath = tmp_path / "package.json"
  packagePath.write_text(json.dumps(validPackageDict), encoding="utf-8")
  database = newStore("trials")
  assert main(["init", database]) == 0
  assert main(["add", database, str(packagePath)]) == 0
  capsys.readouterr()
  assert main(["info", database, "ESV-2025-01"]) == 0
  out = capsys.readouterr().out
  assert (
    "Treatments:\n"
    "  T1  role=untreatedControl\n"
    "  T2  role=test  Fungicide A 2.5 L/ha (formulatedProduct) at GS31\n"
    "  T3  role=reference  Fungicide B 1.0 L/ha (formulatedProduct) at GS39\n"
    "Applications:\n"
    "  GS31  timing=BBCH 31\n"
    "  GS39  timing=BBCH 39\n"
    "Ratings:\n"
  ) in out


def testInfoOfATrialWithoutApplicationsListsNone(project, capsys):
  assert main(["init", project["db"]]) == 0
  assert main(["add", project["db"], project["package"]]) == 0
  capsys.readouterr()
  assert main(["info", project["db"], "DEMO"]) == 0
  out = capsys.readouterr().out
  assert "Treatments:\n  A\n  B\n  C\n  D\nRatings:\n" in out
  assert "Assessments:\n  YIELD  rating=YIELD\n" in out


def importedTrialDocument():
  """A trial laid out elsewhere, as a trial document: its own plot numbers and no seed."""
  package = json.loads(json.dumps(demoPackage))
  package["trial"]["trialCode"] = "FIELD-7"
  package["treatments"] = [{"treatmentCode": code, "name": code} for code in ["A", "B"]]
  package["design"] = {"designType": "rcbd", "replications": 2, "randomizationMethod": "imported"}
  layout = [
    {"plotNumber": 1, "block": 1, "positionInBlock": 1, "treatmentCode": "A"},
    {"plotNumber": 2, "block": 1, "positionInBlock": 2, "treatmentCode": "B"},
    {"plotNumber": 3, "block": 2, "positionInBlock": 1, "treatmentCode": "A"},
    {"plotNumber": 4, "block": 2, "positionInBlock": 2, "treatmentCode": "B"},
  ]
  return {"package": package, "layout": layout, "observations": []}


def testTrialLaidOutElsewhereComesInAsADocument(project, capsys):
  """An unrandomized layout with its own plot numbers is kept and shown as given."""
  documentPath = Path(project["dir"]) / "field7.json"
  documentPath.write_text(json.dumps(importedTrialDocument()), encoding="utf-8")
  assert main(["import-json", project["db"], str(documentPath)]) == 0
  capsys.readouterr()
  assert main(["randomize", project["db"], "FIELD-7"]) == 0
  out = capsys.readouterr().out
  assert "Layout for 'FIELD-7' (imported):" in out
  assert [line for line in out.splitlines()[2:]] == ["1\t1\t1\tA", "2\t1\t2\tB", "3\t2\t1\tA", "4\t2\t2\tB"]
  assert main(["info", project["db"], "FIELD-7"]) == 0
  assert "Layout: imported" in capsys.readouterr().out
  assert main(["verify", project["db"], "FIELD-7"]) == 0


def testAddRefusesAPackageWithAnImportedLayout(project, capsys):
  packagePath = Path(project["dir"]) / "imported.json"
  packagePath.write_text(json.dumps(importedTrialDocument()["package"]), encoding="utf-8")
  assert main(["init", project["db"]]) == 0
  capsys.readouterr()
  assert main(["add", project["db"], str(packagePath)]) == 1
  assert "declares an imported layout" in capsys.readouterr().err


def testImportJsonRefusesALayoutChangedAfterGeneration(project, capsys):
  setUpTrialWithData(project)
  documentPath = Path(project["dir"]) / "demo-doc.json"
  assert main(["export", project["db"], "DEMO", "--json", str(documentPath)]) == 0
  document = json.loads(documentPath.read_text(encoding="utf-8"))
  first, second = document["layout"][0], document["layout"][1]
  first["treatmentCode"], second["treatmentCode"] = second["treatmentCode"], first["treatmentCode"]
  documentPath.write_text(json.dumps(document), encoding="utf-8")
  capsys.readouterr()
  assert main(["import-json", project["db2"], str(documentPath)]) == 1
  assert "is not the one method 'sha256FisherYates1' produces from seed 1" in capsys.readouterr().err
