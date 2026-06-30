# SPDX-License-Identifier: Apache-2.0
"""Tests for the RCBD ANOVA.

The Yates oats variety RCBD is the known-answer anchor: results are checked
against its published ANOVA table (independent of any software) and against
statsmodels recomputed on the same data (the tight cross-check). Further tests
cover the descriptive statistics and the fail-loud paths, including the
decision-0003 reject on missing cells.
"""

import csv
from pathlib import Path

import pytest

from openfurrow.analysis import AnalysisError, analyzeRcbd
from openfurrow.design import generateRcbdLayout
from openfurrow.schema import TrialPackage
from openfurrow.schema.observation import Observation

fixturesDirectory = Path(__file__).parent / "fixtures"
yatesTreatments = ["GoldenRain", "Marvellous", "Victory"]


def loadYatesCells():
  cells = {}
  with (fixturesDirectory / "yatesOatsVariety.csv").open() as handle:
    for row in csv.DictReader(handle):
      cells[(row["treatment"], int(row["block"]))] = float(row["yield"])
  return cells


def yatesPackage(extraAssessments=None):
  assessments = [{"assessmentCode": "YIELD", "name": "Grain yield", "dataType": "numeric", "minValue": 0}]
  if extraAssessments:
    assessments.extend(extraAssessments)
  return TrialPackage.model_validate({
    "schemaVersion": "0.1.0",
    "trial": {"trialCode": "YATES-OATS", "title": "Yates oats variety", "crop": "Oats",
              "season": "1935", "site": "Rothamsted", "objective": "variety yield"},
    "treatments": [{"treatmentCode": code, "name": code} for code in yatesTreatments],
    "design": {"designType": "rcbd", "replications": 6, "randomizationSeed": 1},
    "assessments": assessments,
  })


def yatesObservations(package, layout, cells=None):
  cells = cells if cells is not None else loadYatesCells()
  return [
    Observation(plotNumber=plot.plotNumber, assessmentCode="YIELD",
                value=cells.get((plot.treatmentCode, plot.block)))
    for plot in layout.plots
  ]


def sourceRow(result, source):
  return next(row for row in result.table if row.source == source)


# ---- known-answer: published table ---------------------------------------

def testYatesMatchesPublishedTable():
  package = yatesPackage()
  layout = generateRcbdLayout(package)
  result = analyzeRcbd("YIELD", package, layout, yatesObservations(package, layout))

  block = sourceRow(result, "block")
  assert block.degreesOfFreedom == 5
  assert block.sumOfSquares == pytest.approx(3969, abs=1.0)
  assert block.meanSquare == pytest.approx(794, abs=1.0)
  assert block.fStatistic == pytest.approx(5.28, abs=0.01)
  assert block.pValue == pytest.approx(0.012, abs=0.001)

  treatment = sourceRow(result, "treatment")
  assert treatment.degreesOfFreedom == 2
  assert treatment.sumOfSquares == pytest.approx(447, abs=1.0)
  assert treatment.meanSquare == pytest.approx(223, abs=1.0)
  assert treatment.fStatistic == pytest.approx(1.49, abs=0.01)
  assert treatment.pValue == pytest.approx(0.272, abs=0.001)

  error = sourceRow(result, "error")
  assert error.degreesOfFreedom == 10
  assert error.sumOfSquares == pytest.approx(1503, abs=1.0)
  assert error.meanSquare == pytest.approx(150, abs=1.0)
  assert error.fStatistic is None and error.pValue is None

  total = sourceRow(result, "total")
  assert total.degreesOfFreedom == 17
  assert total.meanSquare is None


# ---- known-answer: independent implementation -----------------------------

def testYatesMatchesStatsmodels():
  import pandas
  import statsmodels.api as statsmodelsApi
  import statsmodels.formula.api as smf

  cells = loadYatesCells()
  package = yatesPackage()
  layout = generateRcbdLayout(package)
  result = analyzeRcbd("YIELD", package, layout, yatesObservations(package, layout, cells))

  frame = pandas.DataFrame(
    [{"block": str(block), "treatment": treatment, "value": value}
     for (treatment, block), value in cells.items()]
  )
  model = smf.ols("value ~ C(block) + C(treatment)", data=frame).fit()
  oracle = statsmodelsApi.stats.anova_lm(model, typ=1)

  block = sourceRow(result, "block")
  assert block.sumOfSquares == pytest.approx(oracle.loc["C(block)", "sum_sq"], rel=1e-6)
  assert block.meanSquare == pytest.approx(oracle.loc["C(block)", "mean_sq"], rel=1e-6)
  assert block.fStatistic == pytest.approx(oracle.loc["C(block)", "F"], rel=1e-6)
  assert block.pValue == pytest.approx(oracle.loc["C(block)", "PR(>F)"], rel=1e-6)

  treatment = sourceRow(result, "treatment")
  assert treatment.sumOfSquares == pytest.approx(oracle.loc["C(treatment)", "sum_sq"], rel=1e-6)
  assert treatment.fStatistic == pytest.approx(oracle.loc["C(treatment)", "F"], rel=1e-6)
  assert treatment.pValue == pytest.approx(oracle.loc["C(treatment)", "PR(>F)"], rel=1e-6)

  error = sourceRow(result, "error")
  assert error.meanSquare == pytest.approx(oracle.loc["Residual", "mean_sq"], rel=1e-6)


# ---- descriptive statistics ----------------------------------------------

def testDescriptiveStatistics():
  cells = loadYatesCells()
  package = yatesPackage()
  layout = generateRcbdLayout(package)
  result = analyzeRcbd("YIELD", package, layout, yatesObservations(package, layout, cells))

  allValues = list(cells.values())
  assert result.grandMean == pytest.approx(sum(allValues) / len(allValues), rel=1e-9)

  means = {mean.treatmentCode: mean for mean in result.treatmentMeans}
  assert means["GoldenRain"].mean == pytest.approx(104.5, abs=1e-9)
  assert means["GoldenRain"].observationCount == 6
  assert means["Marvellous"].mean == pytest.approx(109.79166667, abs=1e-6)
  assert means["Victory"].mean == pytest.approx(97.625, abs=1e-9)

  import math
  expectedCv = 100.0 * math.sqrt(result.errorMeanSquare) / result.grandMean
  assert result.coefficientOfVariation == pytest.approx(expectedCv, rel=1e-12)


# ---- fail-loud: missing data (decision 0003) ------------------------------

def testMissingCellRejected():
  cells = loadYatesCells()
  del cells[("GoldenRain", 3)]  # one missing cell -> M1
  package = yatesPackage()
  layout = generateRcbdLayout(package)
  with pytest.raises(AnalysisError, match="missing values; RCBD ANOVA requires a complete table"):
    analyzeRcbd("YIELD", package, layout, yatesObservations(package, layout, cells))


def testMissingValueNoneRejected():
  cells = loadYatesCells()
  cells[("Victory", 2)] = None  # present row, explicitly missing value
  package = yatesPackage()
  layout = generateRcbdLayout(package)
  observations = [
    Observation(plotNumber=plot.plotNumber, assessmentCode="YIELD",
                value=cells.get((plot.treatmentCode, plot.block)))
    for plot in layout.plots
  ]
  with pytest.raises(AnalysisError, match="treatment Victory, block 2"):
    analyzeRcbd("YIELD", package, layout, observations)


def testWholeTreatmentMissingRejected():
  cells = {key: value for key, value in loadYatesCells().items() if key[0] != "Victory"}
  package = yatesPackage()
  layout = generateRcbdLayout(package)
  with pytest.raises(AnalysisError) as excInfo:
    analyzeRcbd("YIELD", package, layout, yatesObservations(package, layout, cells))
  # all six Victory cells are reported missing
  assert str(excInfo.value).count("treatment Victory") == 6


# ---- fail-loud: preconditions --------------------------------------------

def testNonNumericAssessmentRejected():
  package = yatesPackage(extraAssessments=[
    {"assessmentCode": "RATING", "name": "Lodging rating", "dataType": "ordinal",
     "allowedValues": ["none", "slight", "severe"]},
  ])
  layout = generateRcbdLayout(package)
  with pytest.raises(AnalysisError, match="requires a numeric assessment"):
    analyzeRcbd("RATING", package, layout, yatesObservations(package, layout))


def testUnknownAssessmentRejected():
  package = yatesPackage()
  layout = generateRcbdLayout(package)
  with pytest.raises(AnalysisError, match="not defined in the trial package"):
    analyzeRcbd("BOGUS", package, layout, yatesObservations(package, layout))


def testZeroErrorMeanSquareRejected():
  # Perfectly additive data: value = blockEffect + treatmentEffect, so the
  # no-interaction model fits exactly and the error sum of squares is zero.
  package = TrialPackage.model_validate({
    "schemaVersion": "0.1.0",
    "trial": {"trialCode": "ADDITIVE", "title": "additive", "crop": "x", "season": "x",
              "site": "x", "objective": "x"},
    "treatments": [{"treatmentCode": "T1", "name": "T1"}, {"treatmentCode": "T2", "name": "T2"}],
    "design": {"designType": "rcbd", "replications": 2, "randomizationSeed": 1},
    "assessments": [{"assessmentCode": "Y", "name": "y", "dataType": "numeric"}],
  })
  layout = generateRcbdLayout(package)
  additive = {("T1", 1): 11.0, ("T2", 1): 12.0, ("T1", 2): 21.0, ("T2", 2): 22.0}
  observations = [
    Observation(plotNumber=plot.plotNumber, assessmentCode="Y",
                value=additive[(plot.treatmentCode, plot.block)])
    for plot in layout.plots
  ]
  with pytest.raises(AnalysisError, match="error mean square is zero"):
    analyzeRcbd("Y", package, layout, observations)
