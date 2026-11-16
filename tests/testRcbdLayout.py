# SPDX-License-Identifier: Apache-2.0
"""Tests for RCBD layout generation (method sha256FisherYates1, decision 0015).

Three kinds of assertion. The procedure is pinned against values computed outside it:
the stream is checked against SHA-256 of the documented text, and a bounded draw
against the documented rejection rule. Known layouts are pinned, so a change to the
procedure breaks them, which is the point. And structural invariants must hold for any
valid RCBD regardless of the particular permutation drawn.
"""

import copy
import hashlib
from collections import Counter

import pytest
from pydantic import ValidationError

from openfurrow.design import generateRcbdLayout
from openfurrow.design.stream import Sha256Stream
from openfurrow.schema import TrialPackage

# Pinned known answers: plotNumber -> treatmentCode for the 3-treatment, 4-block
# package in conftest, at two seeds.
_seed42Arrangement = {
  101: "T2", 102: "T3", 103: "T1",
  201: "T2", 202: "T3", 203: "T1",
  301: "T3", 302: "T2", 303: "T1",
  401: "T1", 402: "T2", 403: "T3",
}
_seed7Arrangement = {
  101: "T3", 102: "T2", 103: "T1",
  201: "T2", 202: "T1", 203: "T3",
  301: "T2", 302: "T1", 303: "T3",
  401: "T3", 402: "T2", 403: "T1",
}


def arrangementOf(layout):
  return {plot.plotNumber: plot.treatmentCode for plot in layout.plots}


def packageWithSeed(validPackageDict, seed):
  validPackageDict["design"]["randomizationSeed"] = seed
  return TrialPackage.model_validate(validPackageDict)


# ---- the documented procedure ---------------------------------------------

def testStreamIsSha256OfTheDocumentedText():
  stream = Sha256Stream(42, "sha256FisherYates1")
  words = [stream.nextWord() for _ in range(8)]
  expected = b"".join(
    hashlib.sha256(f"sha256FisherYates1:42:{counter}".encode("ascii")).digest()
    for counter in range(2)
  )
  assert words == [int.from_bytes(expected[index:index + 8], "big") for index in range(0, 64, 8)]


def testFirstBlockOfSeed42FollowsFromTheFirstTwoWords(validPackageDict):
  # Worked by hand from the stream. The first word is a multiple of 3, so position 3
  # swaps with position 1: T1 T2 T3 becomes T3 T2 T1. The second word is even, so
  # position 2 swaps with position 1: T2 T3 T1.
  stream = Sha256Stream(42, "sha256FisherYates1")
  first, second = stream.nextWord(), stream.nextWord()
  assert (first % 3, second % 2) == (0, 0)
  layout = generateRcbdLayout(packageWithSeed(validPackageDict, 42))
  assert [plot.treatmentCode for plot in layout.plots[:3]] == ["T2", "T3", "T1"]


def testBoundedDrawDiscardsWordsAboveTheLargestMultiple():
  class FixedWords(Sha256Stream):
    def __init__(self, words):
      self._words = iter(words)

    def nextWord(self):
      return next(self._words)

  # 2**64 is 1 more than a multiple of 3 and 5, so only the top word is discarded.
  top = 2**64 - 1
  assert FixedWords([top, 7]).below(3) == 1
  assert FixedWords([top - 1]).below(3) == 2
  assert FixedWords([top, top, 12]).below(5) == 2


def testBoundedDrawsAreSpreadEvenly():
  stream = Sha256Stream(2026, "sha256FisherYates1")
  counts = Counter(stream.below(6) for _ in range(6000))
  assert sorted(counts) == [0, 1, 2, 3, 4, 5]
  # Each value is expected 1000 times; 150 either way is beyond four standard deviations.
  assert all(abs(count - 1000) < 150 for count in counts.values())


# ---- reproducibility / known answers ------------------------------------

def testFirstBlockInTreatmentOrderDrawsNothing(validPackageDict):
  """Block 1 keeps package order; the next blocks get what blocks 1, 2, 3 would have got."""
  shuffled = generateRcbdLayout(TrialPackage.model_validate(validPackageDict))
  validPackageDict["design"]["firstBlockInTreatmentOrder"] = True
  ordered = generateRcbdLayout(TrialPackage.model_validate(validPackageDict))

  def blockOrder(layout, block):
    plots = sorted((plot for plot in layout.plots if plot.block == block), key=lambda plot: plot.positionInBlock)
    return [plot.treatmentCode for plot in plots]

  assert blockOrder(ordered, 1) == ["T1", "T2", "T3"]
  assert [blockOrder(ordered, block) for block in (2, 3, 4)] == [blockOrder(shuffled, block) for block in (1, 2, 3)]


def testImportedLayoutCannotClaimAnOrderedFirstBlock(validPackageDict):
  validPackageDict["design"] = {"designType": "rcbd", "replications": 4, "randomizationMethod": "imported",
                                "firstBlockInTreatmentOrder": True}
  with pytest.raises(ValidationError, match="firstBlockInTreatmentOrder applies to generated ones"):
    TrialPackage.model_validate(validPackageDict)


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


def testLayoutCarriesDesignAndCodesFromPackage(validPackageDict):
  package = packageWithSeed(validPackageDict, 42)
  layout = generateRcbdLayout(package)
  assert layout.trialCode == "ESV-2025-01"
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


def testImportedLayoutIsNotGenerated(validPackageDict):
  validPackageDict["design"] = {"designType": "rcbd", "replications": 4, "randomizationMethod": "imported"}
  package = TrialPackage.model_validate(validPackageDict)
  with pytest.raises(ValueError, match="is supplied with the trial, not generated"):
    generateRcbdLayout(package)
