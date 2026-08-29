# SPDX-License-Identifier: Apache-2.0
"""Tests for Fisher's (Protected) LSD mean separation.

The compact-letter algorithm is unit-tested directly on crafted means and an LSD.
End-to-end behavior is checked on the Yates oats RCBD (treatment F not significant
-> protected separation collapses to one group) and on a synthetic trial with a
strong, clean treatment effect (two well-separated pairs). The LSD value is
checked against the textbook formula evaluated with scipy's t quantile.
"""

import math

import pytest

from openfurrow.analysis import AnalysisError, analyzeRcbd, separateMeans
from openfurrow.analysis.meanSeparation import _letterFor, _letterGroups
from openfurrow.design import generateRcbdLayout
from openfurrow.schema import TrialPackage
from openfurrow.schema.observation import Observation


def buildResult(treatments, replications, cellValues, seed=1):
  package = TrialPackage.model_validate({
    "schemaVersion": "0.1.0",
    "trial": {"trialCode": "SEP", "title": "sep", "crop": "x", "season": "x", "site": "x", "objective": "x"},
    "treatments": [{"treatmentCode": code, "name": code} for code in treatments],
    "design": {"designType": "rcbd", "replications": replications, "randomizationSeed": seed},
    "assessments": [{"assessmentCode": "Y", "name": "y", "dataType": "numeric"}],
  })
  layout = generateRcbdLayout(package)
  observations = [
    Observation(plotNumber=plot.plotNumber, assessmentCode="Y", value=cellValues[(plot.treatmentCode, plot.block)])
    for plot in layout.plots
  ]
  return analyzeRcbd("Y", package, layout, observations)


# A synthetic RCBD with a strong, clean treatment effect: two close pairs
# (A approx B, C approx D) far apart. Designed so MS_error is small and the LSD
# falls between the within-pair gap (1) and the between-pair gap (19).
syntheticCells = {
  ("A", 1): 106.0, ("A", 2): 99.0, ("A", 3): 95.0,
  ("B", 1): 103.0, ("B", 2): 100.0, ("B", 3): 94.0,
  ("C", 1): 86.0, ("C", 2): 79.0, ("C", 3): 75.0,
  ("D", 1): 83.0, ("D", 2): 80.0, ("D", 3): 74.0,
}


def syntheticResult():
  return buildResult(["A", "B", "C", "D"], 3, syntheticCells)


# ---- letter algorithm (unit) ---------------------------------------------

def testLetterGroupsAllWithinLsdShareOneLetter():
  assert _letterGroups([109.79, 104.5, 97.625], 15.77) == ["a", "a", "a"]


def testLetterGroupsTwoCleanGroups():
  assert _letterGroups([100.0, 99.0, 80.0, 79.0], 2.31) == ["a", "a", "b", "b"]


def testLetterGroupsOverlap():
  # Middle mean is within the LSD of both ends, which are not within the LSD of
  # each other -> it shares both letters.
  assert _letterGroups([10.0, 7.0, 4.0], 3.5) == ["a", "ab", "b"]


def testLetterGroupsAllDifferent():
  assert _letterGroups([10.0, 5.0, 0.0], 1.0) == ["a", "b", "c"]


def testLetterForSequence():
  assert _letterFor(0) == "a"
  assert _letterFor(25) == "z"
  assert _letterFor(26) == "aa"
  assert _letterFor(27) == "ab"


# ---- protected behavior ---------------------------------------------------

def testProtectedSeparatesSignificantTrial():
  separation = separateMeans(syntheticResult(), significanceLevel=0.05, protected=True)
  assert separation.treatmentSignificant is True
  assert separation.methodKey == "report.method.fisherProtectedLSD"
  byTreatment = {group.treatmentCode: group.group for group in separation.groups}
  assert byTreatment == {"A": "a", "B": "a", "C": "b", "D": "b"}
  # groups are ordered by descending mean
  assert [group.treatmentCode for group in separation.groups] == ["A", "B", "C", "D"]


def testProtectedCollapsesWhenTreatmentNotSignificant():
  # Yates oats: treatment F is not significant (p approx 0.27), so a protected LSD
  # performs no separation and every mean shares one letter.
  cells = {
    ("GoldenRain", 1): 133.25, ("GoldenRain", 2): 113.25, ("GoldenRain", 3): 86.75,
    ("GoldenRain", 4): 108.0, ("GoldenRain", 5): 95.5, ("GoldenRain", 6): 90.25,
    ("Marvellous", 1): 129.75, ("Marvellous", 2): 121.25, ("Marvellous", 3): 118.5,
    ("Marvellous", 4): 95.0, ("Marvellous", 5): 85.25, ("Marvellous", 6): 109.0,
    ("Victory", 1): 143.0, ("Victory", 2): 87.25, ("Victory", 3): 82.5,
    ("Victory", 4): 91.5, ("Victory", 5): 92.0, ("Victory", 6): 89.5,
  }
  result = buildResult(["GoldenRain", "Marvellous", "Victory"], 6, cells)
  separation = separateMeans(result, significanceLevel=0.05, protected=True)
  assert separation.treatmentSignificant is False
  assert {group.group for group in separation.groups} == {"a"}


def testUnprotectedRunsAndIsLabelled():
  separation = separateMeans(syntheticResult(), significanceLevel=0.05, protected=False)
  assert separation.methodKey == "report.method.fisherLSD"
  byTreatment = {group.treatmentCode: group.group for group in separation.groups}
  assert byTreatment == {"A": "a", "B": "a", "C": "b", "D": "b"}


# ---- LSD value ------------------------------------------------------------

def testLeastSignificantDifferenceMatchesFormula():
  from scipy import stats

  result = syntheticResult()
  separation = separateMeans(result, significanceLevel=0.05)
  perTreatment = result.blockCount
  expected = stats.t.ppf(0.975, result.errorDegreesOfFreedom) * math.sqrt(
    2.0 * result.errorMeanSquare / perTreatment
  )
  assert separation.leastSignificantDifference == pytest.approx(expected, rel=1e-9)


# ---- fail-loud ------------------------------------------------------------

def testInvalidSignificanceLevelRejected():
  with pytest.raises(AnalysisError, match="significance level must be in"):
    separateMeans(syntheticResult(), significanceLevel=1.5)
