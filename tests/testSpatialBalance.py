# SPDX-License-Identifier: Apache-2.0
"""Spatially balanced complete blocks, method sha256SpatialBalance1 (decision 0021).

The layout is pinned for one seed, the cost the search tracks is checked against a full
recount at several sizes, and the balance it reaches is compared with plain RCBD layouts
of the same sizes.
"""

import json
import statistics

import pytest
from pydantic import ValidationError

from openfurrow import ExchangeError, Workspace, schemaVersion
from openfurrow.design import generateLayout
from openfurrow.design.spatialBalance import balanceCost, spatiallyBalancedOrders
from openfurrow.design.stream import Sha256Stream, shuffled
from openfurrow.reports import buildReport
from openfurrow.schema import TrialPackage


def balancedPackageDict(treatmentCount=5, replications=4, seed=3):
  return {
    "schemaVersion": schemaVersion,
    "trial": {"trialCode": "SB-1", "title": "Balanced", "crop": "Maize", "season": "2026",
              "site": "Field 9", "objective": "Spatial balance"},
    "treatments": [{"treatmentCode": f"T{index}", "name": f"T{index}"} for index in range(1, treatmentCount + 1)],
    "design": {"designType": "rcbd", "replications": replications,
               "randomizationMethod": "sha256SpatialBalance1", "randomizationSeed": seed},
    "ratings": [{"ratingCode": "Y", "name": "Yield", "dataType": "numeric"}],
    "assessments": [{"assessmentCode": "Y", "ratingCode": "Y"}],
  }


def pairDistanceSpread(orders, treatmentCount):
  where = [{treatment: place for place, treatment in enumerate(order)} for order in orders]
  means = [
    sum(abs(w[a] - w[b]) for w in where) / len(orders)
    for a in range(treatmentCount) for b in range(a + 1, treatmentCount)
  ]
  return statistics.pstdev(means)


def testLayoutForSeed3MatchesKnownAnswer():
  plots = sorted(generateLayout(TrialPackage.model_validate(balancedPackageDict())).plots, key=lambda p: p.plotNumber)
  blocks = [[plot.treatmentCode for plot in plots if plot.block == block] for block in (1, 2, 3, 4)]
  assert blocks == [
    ["T1", "T5", "T2", "T3", "T4"],
    ["T2", "T3", "T1", "T4", "T5"],
    ["T3", "T1", "T4", "T5", "T2"],
    ["T4", "T2", "T5", "T1", "T3"],
  ]


@pytest.mark.parametrize("treatmentCount, blockCount, seed", [(3, 2, 1), (5, 4, 3), (8, 4, 11), (12, 5, 2), (7, 9, 4)])
def testTrackedCostIsTheFullRecount(treatmentCount, blockCount, seed):
  """The search updates the cost move by move; a wrong update would show here."""
  orders, cost = spatiallyBalancedOrders(treatmentCount, blockCount, seed, False)
  assert cost == balanceCost([list(order) for order in orders], treatmentCount)
  assert all(sorted(order) == list(range(treatmentCount)) for order in orders)


@pytest.mark.parametrize("treatmentCount, blockCount", [(5, 4), (8, 4), (10, 4), (12, 5), (20, 6)])
def testBalanceBeatsPlainShufflesOfTheSameSize(treatmentCount, blockCount):
  """Over five seeds, pair distances spread less, and no treatment repeats a position it need not."""
  plain, balanced = [], []
  for seed in range(5):
    stream = Sha256Stream(seed, "sha256FisherYates1")
    plain.append(pairDistanceSpread([shuffled(treatmentCount, stream) for _ in range(blockCount)], treatmentCount))
    orders, _ = spatiallyBalancedOrders(treatmentCount, blockCount, seed, False)
    balanced.append(pairDistanceSpread(orders, treatmentCount))
    for treatment in range(treatmentCount):
      places = [order.index(treatment) for order in orders]
      assert len(set(places)) == len(places)
  assert statistics.mean(balanced) < 0.8 * statistics.mean(plain)


def testFirstBlockInTreatmentOrderIsKept():
  orders, cost = spatiallyBalancedOrders(6, 4, 8, True)
  assert orders[0] == (0, 1, 2, 3, 4, 5)
  assert cost == balanceCost([list(order) for order in orders], 6)


def testSpatialBalanceOnASplitPlotRejected():
  from testSplitPlot import gomezPackageDict
  data = gomezPackageDict()
  data["design"]["randomizationMethod"] = "sha256SpatialBalance1"
  with pytest.raises(ValidationError, match="spatial balance applies to an RCBD's blocks, not to a split plot"):
    TrialPackage.model_validate(data)


def testDocumentWhoseLayoutIsNotTheBalancedOneRejected(tmp_path):
  package = TrialPackage.model_validate(balancedPackageDict())
  plots = [plot.model_dump() for plot in generateLayout(package).plots]
  first, second = plots[0], plots[1]
  first["treatmentCode"], second["treatmentCode"] = second["treatmentCode"], first["treatmentCode"]
  path = tmp_path / "doc.json"
  path.write_text(json.dumps({"package": package.model_dump(mode="json"), "layout": plots, "observations": []}),
                  encoding="utf-8")
  with pytest.raises(ExchangeError, match="not a valid trial document"):
    Workspace.create(str(tmp_path / "trials.db")).importDocument(str(path))


def testReportNamesTheArrangement():
  package = TrialPackage.model_validate(balancedPackageDict())
  report = buildReport(package, generateLayout(package), [])
  assert "- Arrangement: spatially balanced (van Es et al. 2007)" in report
  assert "- Randomization method: sha256SpatialBalance1" in report
