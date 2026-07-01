# SPDX-License-Identifier: Apache-2.0
"""Known-answer hardening test on the stirret.borers RCBD (real field data).

Stirrett, Beall and Timonin (1937), Sci. Agric. 17:587-591, Table 2 -- control
of the European corn borer with the fungus Beauveria bassiana. The trial is a
4-treatment (None, Early, Late, Both) by 15-block randomized complete block
design with two borer-count assessments (count1 on Aug 18, count2 on Oct 19).

This is the registry's primary realistic case. It validates the RCBD ANOVA on
genuine count data at a larger scale than the Yates oats anchor, against two
independent references:

  1. the agridat package documentation, which publishes the count1 treatment
     means -- an external, software-independent known answer; and
  2. statsmodels recomputed on the same data (the tight cross-check). The
     reference numbers below were produced offline by statsmodels and match the
     analyzer to the stated precision, so these tests carry no runtime
     statistics dependency.

The count1 treatment effect is significant, so this case also exercises the
Protected LSD compact-letter separation into multiple groups, a path the
(non-significant) Yates case never reaches. The untreated control is named
"None" on purpose: it is a common trial label and is also a NA sentinel in some
CSV readers, so carrying it end to end guards the stdlib-csv import path.
"""

import csv
from pathlib import Path

import pytest

from openfurrow.analysis import analyzeRcbd, separateMeans
from openfurrow.design import generateRcbdLayout
from openfurrow.reports import buildReport
from openfurrow.schema import TrialPackage
from openfurrow.schema.observation import Observation

fixturesDirectory = Path(__file__).parent / "fixtures"
stirretTreatments = ["None", "Early", "Late", "Both"]

# agridat stirret.borers documentation (Examples): predicted count1 means.
publishedCount1Means = {
  "None": 61.13333,
  "Early": 62.93333,
  "Late": 40.93333,
  "Both": 47.86667,
}

# Reference ANOVA from statsmodels on the same data, computed offline.
# block/treatment: (df, sumOfSquares, meanSquare, fStatistic).
# error: (df, sumOfSquares, meanSquare). total: (df, sumOfSquares).
referenceAnova = {
  "count1": {
    "block": (14, 16148.4333, 1153.4595, 4.8861),
    "treatment": (3, 5048.8500, 1682.9500, 7.1291),
    "error": (42, 9914.9000, 236.0690),
    "total": (59, 31112.1833),
    "grandMean": 53.21667,
    "coefficientOfVariation": 28.8717,
    "treatmentPValue": 0.0006,
  },
  "count2": {
    "block": (14, 2516.4333, 179.7452, 2.9763),
    "treatment": (3, 4611.2500, 1537.0833, 25.4514),
    "error": (42, 2536.5000, 60.3929),
    "total": (59, 9664.1833),
    "grandMean": 20.38333,
    "coefficientOfVariation": 38.1257,
  },
}


def loadStirretCells():
  count1, count2 = {}, {}
  with (fixturesDirectory / "stirretBorers.csv").open() as handle:
    for row in csv.DictReader(handle):
      key = (row["trt"], int(row["block"]))
      count1[key] = float(row["count1"])
      count2[key] = float(row["count2"])
  return count1, count2


def stirretPackage():
  return TrialPackage.model_validate({
    "schemaVersion": "0.1.0",
    "trial": {
      "trialCode": "STIRRET-1935",
      "title": "European corn borer control by Beauveria bassiana",
      "crop": "Maize",
      "season": "1935",
      "site": "Ottawa",
      "objective": "Borer control by application of fungal spores",
    },
    "treatments": [{"treatmentCode": code, "name": code} for code in stirretTreatments],
    "design": {"designType": "rcbd", "replications": 15, "randomizationSeed": 1},
    "assessments": [
      {"assessmentCode": "count1", "name": "Borer count August 18", "dataType": "numeric", "minValue": 0},
      {"assessmentCode": "count2", "name": "Borer count October 19", "dataType": "numeric", "minValue": 0},
    ],
  })


def stirretObservations(package, layout):
  count1, count2 = loadStirretCells()
  observations = []
  for plot in layout.plots:
    observations.append(Observation(
      plotNumber=plot.plotNumber, assessmentCode="count1",
      value=count1[(plot.treatmentCode, plot.block)]))
    observations.append(Observation(
      plotNumber=plot.plotNumber, assessmentCode="count2",
      value=count2[(plot.treatmentCode, plot.block)]))
  return observations


def sourceRow(result, source):
  return next(row for row in result.table if row.source == source)


def analyze(assessmentCode):
  package = stirretPackage()
  layout = generateRcbdLayout(package)
  observations = stirretObservations(package, layout)
  return analyzeRcbd(assessmentCode, package, layout, observations)


# ---- fixture guard ---------------------------------------------------------

def testFixtureIsCompleteBalancedRcbd():
  count1, count2 = loadStirretCells()
  assert len(count1) == 60 and len(count2) == 60
  treatments = {treatment for treatment, _ in count1}
  blocks = {block for _, block in count1}
  assert treatments == set(stirretTreatments)
  assert blocks == set(range(1, 16))
  for treatment in stirretTreatments:
    assert sum(1 for code, _ in count1 if code == treatment) == 15


# ---- known-answer: agridat published means ---------------------------------

def testCount1ReproducesPublishedMeans():
  result = analyze("count1")
  means = {mean.treatmentCode: mean.mean for mean in result.treatmentMeans}
  for treatment, expected in publishedCount1Means.items():
    assert means[treatment] == pytest.approx(expected, abs=1e-4)


# ---- tight cross-check: statsmodels-recomputed ANOVA ------------------------

def _assertAnovaMatches(assessmentCode):
  reference = referenceAnova[assessmentCode]
  result = analyze(assessmentCode)

  block = sourceRow(result, "block")
  assert block.degreesOfFreedom == reference["block"][0]
  assert block.sumOfSquares == pytest.approx(reference["block"][1], abs=0.01)
  assert block.meanSquare == pytest.approx(reference["block"][2], abs=0.01)
  assert block.fStatistic == pytest.approx(reference["block"][3], abs=1e-3)

  treatment = sourceRow(result, "treatment")
  assert treatment.degreesOfFreedom == reference["treatment"][0]
  assert treatment.sumOfSquares == pytest.approx(reference["treatment"][1], abs=0.01)
  assert treatment.meanSquare == pytest.approx(reference["treatment"][2], abs=0.01)
  assert treatment.fStatistic == pytest.approx(reference["treatment"][3], abs=1e-3)

  error = sourceRow(result, "error")
  assert error.degreesOfFreedom == reference["error"][0]
  assert error.sumOfSquares == pytest.approx(reference["error"][1], abs=0.01)
  assert error.meanSquare == pytest.approx(reference["error"][2], abs=0.01)

  total = sourceRow(result, "total")
  assert total.degreesOfFreedom == reference["total"][0]
  assert total.sumOfSquares == pytest.approx(reference["total"][1], abs=0.01)

  assert result.grandMean == pytest.approx(reference["grandMean"], abs=1e-3)
  assert result.coefficientOfVariation == pytest.approx(reference["coefficientOfVariation"], abs=1e-3)
  return result


def testCount1MatchesReferenceAnova():
  result = _assertAnovaMatches("count1")
  treatment = sourceRow(result, "treatment")
  assert treatment.pValue == pytest.approx(referenceAnova["count1"]["treatmentPValue"], abs=1e-4)


def testCount2MatchesReferenceAnova():
  result = _assertAnovaMatches("count2")
  treatment = sourceRow(result, "treatment")
  assert treatment.pValue < 1e-6


# ---- pipeline: Protected LSD separates real groups --------------------------

def testProtectedLsdSeparatesCount1Groups():
  result = analyze("count1")
  separation = separateMeans(result, significanceLevel=0.05, protected=True)
  assert separation.treatmentSignificant is True
  assert separation.leastSignificantDifference == pytest.approx(11.322116964764346, abs=1e-6)
  group = {row.treatmentCode: row.group for row in separation.groups}
  # The two effective spore programs (Both, Late) separate from None and Early.
  assert group["Early"] == group["None"]
  assert group["Both"] == group["Late"]
  assert group["Early"] != group["Both"]
  assert len({row.group for row in separation.groups}) == 2


# ---- pipeline: full report renders on real multi-assessment count data ------

def testReportRendersForRealCountTrial():
  package = stirretPackage()
  layout = generateRcbdLayout(package)
  observations = stirretObservations(package, layout)
  report = buildReport(package, layout, observations, significanceLevel=0.05, protected=True)
  assert len(report.strip()) > 500
  assert "Borer count August 18" in report
  assert "Borer count October 19" in report
  assert "Protected" in report
  # The report-only assumption checks (decision 0006), one block per assessment.
  assert report.count("### Assumption checks") == 2
  assert "Brown-Forsythe" in report
  assert "Tukey" in report
  assert "Shapiro-Wilk" in report
