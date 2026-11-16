# SPDX-License-Identifier: Apache-2.0
"""Transforms with an offset, and the base-10 log (decision 0026).

Pinned against Gomez and Gomez (1984), Tables 7.14 to 7.17: living larvae on rice under
nine insecticide treatments in four replications, analysed as log10(count + 1)
(fixture `gomezLarvae.csv`, via agridat's gomez.nonnormal1).
"""

import csv
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from openfurrow import TrialPackage, schemaVersion
from openfurrow.analysis import analyzeRcbd, separateMeans
from openfurrow.analysis.transforms import TransformError, applyTransform, backTransformMean
from openfurrow.design import generateLayout
from openfurrow.reports import buildReport
from openfurrow.schema import Transform
from openfurrow.schema.observation import Observation

fixtures = Path(__file__).parent / "fixtures"


def larvaeInputs(transform="log10", offset=1.0):
  rating = {"ratingCode": "L", "name": "Living larvae", "dataType": "numeric", "unit": "per hill",
            "measurementKind": "count", "transform": transform, "transformOffset": offset}
  package = TrialPackage.model_validate({
    "schemaVersion": schemaVersion,
    "trial": {"trialCode": "GOMEZ-7.14", "title": "Insecticides on rice", "crop": "Rice", "season": "1984",
              "site": "IRRI", "objective": "Gomez and Gomez Table 7.14"},
    "treatments": [{"treatmentCode": f"T{index}", "name": f"T{index}"} for index in range(1, 10)],
    "design": {"designType": "rcbd", "replications": 4, "randomizationMethod": "sha256FisherYates1",
               "randomizationSeed": 714},
    "ratings": [rating],
    "assessments": [{"assessmentCode": "L", "ratingCode": "L"}],
  })
  layout = generateLayout(package)
  with (fixtures / "gomezLarvae.csv").open(encoding="utf-8") as handle:
    counts = {(row["treatment"], int(row["replication"])): float(row["larvae"]) for row in csv.DictReader(handle)}
  observations = [Observation(plotNumber=p.plotNumber, assessmentCode="L", value=counts[(p.treatmentCode, p.block)])
                  for p in layout.plots]
  return package, layout, observations


def testMatchesGomezTable716():
  result = analyzeRcbd("L", *larvaeInputs())
  rows = {row.source: row for row in result.table}
  assert {source: round(rows[source].sumOfSquares, 5) for source in ("block", "treatment", "error", "total")} == {
    "block": 0.95666, "treatment": 3.98235, "error": 2.09615, "total": 7.03516,
  }
  assert round(rows["treatment"].fStatistic, 2) == 5.70


def testTransformedMeansMatchGomezTable717():
  # The book averages per-plot values it rounded to four decimals (Table 7.15), which moves a
  # mean by up to 0.00005: T7 is exactly 0.075257, printed 0.0752.
  result = analyzeRcbd("L", *larvaeInputs())
  printed = {"T1": 0.6037, "T2": 0.6831, "T3": 0.8428, "T4": 0.8306, "T5": 1.1963,
             "T6": 1.1750, "T7": 0.0752, "T8": 0.4549, "T9": 0.9307}
  for mean in result.treatmentMeans:
    assert abs(mean.mean - printed[mean.treatmentCode]) <= 0.00006, mean.treatmentCode


def testLsdOnTheTransformedScaleMatchesGomez():
  scipyStats = pytest.importorskip("scipy.stats")
  separation = separateMeans(analyzeRcbd("L", *larvaeInputs()), protected=False)
  # The book prints 0.4313 from its tabulated t (2.064, exactly 2.0639) and its rounded error MS.
  assert round(separation.leastSignificantDifference, 4) == round(
    scipyStats.t.ppf(0.975, 24) * math.sqrt(2 * 2.09615 / 24 / 4), 4)
  assert abs(separation.leastSignificantDifference - 0.4313) < 0.0005


def testNaturalLogGivesTheSameF():
  """The base of the log scales every sum of squares alike, so F does not change."""
  base10 = {row.source: row for row in analyzeRcbd("L", *larvaeInputs("log10")).table}
  natural = {row.source: row for row in analyzeRcbd("L", *larvaeInputs("log")).table}
  assert natural["treatment"].fStatistic == pytest.approx(base10["treatment"].fStatistic, rel=1e-12)
  assert natural["treatment"].sumOfSquares == pytest.approx(base10["treatment"].sumOfSquares * math.log(10) ** 2, rel=1e-12)


def testBackTransformTakesTheOffsetOff():
  assert backTransformMean(Transform.log10, math.log10(8.0 + 1.0), 1.0) == pytest.approx(8.0)
  assert backTransformMean(Transform.sqrt, math.sqrt(3.0 + 0.5), 0.5) == pytest.approx(3.0)
  assert backTransformMean(Transform.log, math.log(2.0 + 1.0), 1.0) == pytest.approx(2.0)


def testZerosNeedTheOffset():
  with pytest.raises(TransformError, match=r"log10 transform requires values > 0; offending values: 0"):
    applyTransform(Transform.log10, [0.0, 5.0], 0.0)
  assert applyTransform(Transform.log10, [0.0, 9.0], 1.0) == pytest.approx([0.0, 1.0])
  with pytest.raises(TransformError, match=r"values \+ 0.5 >= 0; offending values: -1"):
    applyTransform(Transform.sqrt, [-1.0], 0.5)


def testReportNamesTheScaleWithItsOffset():
  report = buildReport(*larvaeInputs())
  assert "Analyzed on the base-10 log of (x + 1) scale" in report
  assert "- Transforms: L = log10(x + 1)" in report


@pytest.mark.parametrize("transform", ["none", "arcsinSqrt", "logit"])
def testOffsetOnlyGoesWithALogOrASquareRoot(transform):
  with pytest.raises(ValidationError, match=f"a transformOffset goes with a log, log10 or sqrt transform, not {transform}"):
    larvaeInputs(transform, 1.0)


def testNegativeOffsetRefused():
  with pytest.raises(ValidationError, match="greater than or equal to 0"):
    larvaeInputs("log10", -1.0)
