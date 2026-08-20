# SPDX-License-Identifier: Apache-2.0
"""Tests for the Markdown trial report.

Checks that the AOV Means Table renders with the expected figures on the Yates
oats RCBD, that a significant trial shows separated letter groups, that the input
hash is stable and sensitive, and that an assessment which cannot be analyzed is
reported with an explicit note rather than dropped.
"""

import csv
from pathlib import Path

import pytest

from openfurrow.analysis import AnalysisError
from openfurrow.design import generateRcbdLayout
from openfurrow.reports import buildReport, inputHash
from openfurrow.schema import TrialPackage
from openfurrow.schema.observation import Observation

fixturesDirectory = Path(__file__).parent / "fixtures"


def loadYatesCells():
  cells = {}
  with (fixturesDirectory / "yatesOatsVariety.csv").open() as handle:
    for row in csv.DictReader(handle):
      cells[(row["treatment"], int(row["block"]))] = float(row["yield"])
  return cells


def yatesPackage(extraAssessments=None):
  assessments = [{"assessmentCode": "YIELD", "name": "Grain yield", "dataType": "numeric",
                  "unit": "qtr-lb/plot", "minValue": 0}]
  if extraAssessments:
    assessments.extend(extraAssessments)
  return TrialPackage.model_validate({
    "schemaVersion": "0.1.0",
    "trial": {"trialCode": "YATES-OATS", "title": "Yates oats variety", "crop": "Oats",
              "season": "1935", "site": "Rothamsted", "objective": "Compare oat variety yield"},
    "treatments": [{"treatmentCode": code, "name": code} for code in ["GoldenRain", "Marvellous", "Victory"]],
    "design": {"designType": "rcbd", "replications": 6, "randomizationSeed": 1},
    "assessments": assessments,
  })


def yatesInputs(extraAssessments=None, cells=None):
  package = yatesPackage(extraAssessments)
  layout = generateRcbdLayout(package)
  cells = cells if cells is not None else loadYatesCells()
  observations = [
    Observation(plotNumber=plot.plotNumber, assessmentCode="YIELD",
                value=cells.get((plot.treatmentCode, plot.block)))
    for plot in layout.plots
  ]
  return package, layout, observations


syntheticCells = {
  ("A", 1): 106.0, ("A", 2): 99.0, ("A", 3): 95.0,
  ("B", 1): 103.0, ("B", 2): 100.0, ("B", 3): 94.0,
  ("C", 1): 86.0, ("C", 2): 79.0, ("C", 3): 75.0,
  ("D", 1): 83.0, ("D", 2): 80.0, ("D", 3): 74.0,
}


def syntheticInputs():
  package = TrialPackage.model_validate({
    "schemaVersion": "0.1.0",
    "trial": {"trialCode": "SYN", "title": "Synthetic", "crop": "x", "season": "x", "site": "x", "objective": "x"},
    "treatments": [{"treatmentCode": code, "name": code} for code in ["A", "B", "C", "D"]],
    "design": {"designType": "rcbd", "replications": 3, "randomizationSeed": 1},
    "assessments": [{"assessmentCode": "Y", "name": "Yield", "dataType": "numeric"}],
  })
  layout = generateRcbdLayout(package)
  observations = [
    Observation(plotNumber=plot.plotNumber, assessmentCode="Y", value=syntheticCells[(plot.treatmentCode, plot.block)])
    for plot in layout.plots
  ]
  return package, layout, observations


# ---- AOV Means Table rendering -------------------------------------------

def testReportRendersAovMeansTable():
  report = buildReport(*yatesInputs())

  assert "# Trial Report: Yates oats variety" in report
  assert "- Randomization seed: 1" in report
  assert "- Plots: 18" in report

  # ANOVA table figures (matching the published Yates table)
  assert "| Block | 5 | 3968.8194 | 793.7639 | 5.28 | 0.0124 |" in report
  assert "| Treatment | 2 | 446.5903 | 223.2951 | 1.49 | 0.2724 |" in report
  assert "| Error | 10 | 1503.3264 | 150.3326 | - | - |" in report
  assert "| Total | 17 | 5918.7361 | - | - | - |" in report

  assert "- Grand mean: 103.972 (qtr-lb/plot)" in report
  assert "- Coefficient of variation: 11.79%" in report

  # protected LSD: not significant -> all one letter
  assert "| Marvellous | 109.792 | a |" in report
  assert "| Victory | 97.625 | a |" in report
  assert "- LSD (alpha = 0.05): 15.773" in report
  assert "Treatment effect not significant (P = 0.2724)" in report
  assert "Means were not separated" in report

  # reproducibility block
  assert "Input hash (SHA-256): " in report
  assert "OpenFurrow 0.1.0" in report
  assert "numpy" in report


def testReportSeparatesSignificantTrial():
  report = buildReport(*syntheticInputs())
  assert "Treatment effect significant (P < 0.0001)" in report
  assert "| A | 100.000 | a |" in report
  assert "| B | 99.000 | a |" in report
  assert "| C | 80.000 | b |" in report
  assert "| D | 79.000 | b |" in report
  assert "Means were not separated" not in report


def testReportUnprotectedLabel():
  report = buildReport(*syntheticInputs(), protected=False)
  assert "Fisher's LSD (alpha = 0.05)" in report
  assert "Protected" not in report


# ---- input hash -----------------------------------------------------------

def testInputHashStable():
  packageA, _, observationsA = yatesInputs()
  packageB, _, observationsB = yatesInputs()
  assert inputHash(packageA, observationsA) == inputHash(packageB, observationsB)


def testInputHashSensitiveToValueChange():
  package, layout, observations = yatesInputs()
  baseline = inputHash(package, observations)
  perturbed = list(observations)
  perturbed[0] = Observation(
    plotNumber=observations[0].plotNumber,
    assessmentCode=observations[0].assessmentCode,
    value=observations[0].value + 1.0,
  )
  assert inputHash(package, perturbed) != baseline


def testInputHashOrderIndependent():
  package, layout, observations = yatesInputs()
  assert inputHash(package, observations) == inputHash(package, list(reversed(observations)))


# ---- transparent failure --------------------------------------------------

def testReportNotesMissingAssessment():
  cells = loadYatesCells()
  del cells[("GoldenRain", 3)]
  report = buildReport(*yatesInputs(cells=cells))
  # the design still renders, but the assessment is flagged with the reason
  assert "## Design" in report
  assert "## Assessment: Grain yield (YIELD)" in report
  assert "Not analyzed:" in report
  assert "missing values" in report
  # no AOV table for the unanalyzable assessment
  assert "### Analysis of variance" not in report


def testReportNotesNonNumericAssessment():
  report = buildReport(*yatesInputs(extraAssessments=[
    {"assessmentCode": "LODGE", "name": "Lodging", "dataType": "ordinal",
     "allowedValues": ["none", "slight", "severe"]},
  ]))
  assert "## Assessment: Lodging (LODGE)" in report
  assert "Not analyzed: AOV requires a numeric assessment" in report
  # the numeric assessment is still fully analyzed
  assert "### Analysis of variance" in report


def testReportRejectsLayoutPackageMismatch():
  package, layout, observations = yatesInputs()
  otherPackage = syntheticInputs()[0]
  with pytest.raises(AnalysisError, match="does not match package trial"):
    buildReport(otherPackage, layout, observations)
