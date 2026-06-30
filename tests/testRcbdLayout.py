# SPDX-License-Identifier: Apache-2.0
"""Tests for RCBD layout generation.

Two kinds of assertion: pinned known answers that lock the seed-to-layout
contract (if the randomization stream ever changes, these break, which is the
point), and algorithm-independent structural invariants that must hold for any
valid RCBD regardless of the particular permutation drawn.
"""

import copy

import pytest
from pydantic import ValidationError

from openfurrow.design import generateRcbdLayout
from openfurrow.schema import TrialPackage

# Pinned known answers: plotNumber -> treatmentCode for the 3-treatment, 4-block
# package in conftest, at two seeds. Reproducible via numpy PCG64.
_seed42Arrangement = {
  101: "T3", 102: "T2", 103: "T1",
  201: "T1", 202: "T3", 203: "T2",
  301: "T2", 302: "T3", 303: "T1",
  401: "T3", 402: "T1", 403: "T2",
}
_seed7Arrangement = {
  101: "T1", 102: "T3", 103: "T2",
  201: "T2", 202: "T3", 203: "T1",
  301: "T1", 302: "T2", 303: "T3",
  401: "T1", 402: "T3", 403: "T2",
}


def arrangementOf(layout):
  return {plot.plotNumber: plot.treatmentCode for plot in layout.plots}


def packageWithSeed(validPackageDict, seed):
  validPackageDict["design"]["randomizationSeed"] = seed
  return TrialPackage.model_validate(validPackageDict)


# ---- reproducibility / known answers ------------------------------------

def testSeed42LayoutMatchesKnownAnswer(validPackageDict):
  layout = generateRcbdLayout(packageWithSeed(validPackageDict, 42))
  assert arrangementOf(layout) == _seed42Arrangement


def testSeed7LayoutMatchesKnownAnswer(validPackageDict):
  layout = generateRcbdLayout(packageWithSeed(validPackageDict, 7))
  assert arrangementOf(layout) == _seed7Arrangement


def testSameSeedProducesIdenticalLayout(validPackageDict):
  first = generateRcbdLayout(packageWithSeed(copy.deepcopy(validPackageDict), 42))
  second = generateRcbdLayout(packageWithSeed(copy.deepcopy(validPackageDict), 42))
  assert arrangementOf(first) == arrangementOf(second)


def testDifferentSeedChangesArrangement(validPackageDict):
  bySeed42 = arrangementOf(generateRcbdLayout(packageWithSeed(copy.deepcopy(validPackageDict), 42)))
  bySeed7 = arrangementOf(generateRcbdLayout(packageWithSeed(copy.deepcopy(validPackageDict), 7)))
  assert bySeed42 != bySeed7


# ---- structural invariants ----------------------------------------------

def testEveryBlockContainsEachTreatmentExactlyOnce(validPackageDict):
  package = packageWithSeed(validPackageDict, 42)
  expected = sorted(treatment.treatmentCode for treatment in package.treatments)
  layout = generateRcbdLayout(package)
  byBlock = {}
  for plot in layout.plots:
    byBlock.setdefault(plot.block, []).append(plot.treatmentCode)
  assert sorted(byBlock) == [1, 2, 3, 4]
  for block, codes in byBlock.items():
    assert sorted(codes) == expected, f"block {block} is not a complete set"


def testPlotCountEqualsTreatmentsTimesReplications(validPackageDict):
  package = packageWithSeed(validPackageDict, 42)
  layout = generateRcbdLayout(package)
  assert len(layout.plots) == 12
  assert len(layout.plots) == package.plotCount


def testPlotNumbersFollowBlockTimesHundredScheme(validPackageDict):
  layout = generateRcbdLayout(packageWithSeed(validPackageDict, 42))
  for plot in layout.plots:
    assert plot.plotNumber == plot.block * 100 + plot.positionInBlock


def testLayoutCarriesSeedAndCodesFromPackage(validPackageDict):
  package = packageWithSeed(validPackageDict, 42)
  layout = generateRcbdLayout(package)
  assert layout.randomizationSeed == 42
  assert layout.replications == 4
  assert layout.treatmentCodes == ["T1", "T2", "T3"]


# ---- fail-loud guards ---------------------------------------------------

def testTooManyTreatmentsRejected(validPackageDict):
  validPackageDict["treatments"] = [
    {"treatmentCode": f"T{index:03d}", "name": f"Treatment {index}"}
    for index in range(1, 101)  # 100 treatments, exceeds the 99-per-block scheme
  ]
  validPackageDict["design"]["replications"] = 2
  package = TrialPackage.model_validate(validPackageDict)
  with pytest.raises(ValueError, match="exceeds the 99-per-block"):
    generateRcbdLayout(package)
