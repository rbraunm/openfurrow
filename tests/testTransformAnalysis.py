# SPDX-License-Identifier: Apache-2.0
"""Integration tests for analysis and diagnostics on the transformed scale (ADR 0006, slice 2b).

Checkpoint B wires the assessment's declared transform into the shared matrix
boundary, so both the ANOVA and the diagnostics run on the transformed scale. These
tests confirm the transformed-scale ANOVA matches statsmodels on the transformed
data, that treatment means are on the transformed scale and back-transform correctly,
that Protected LSD separates on that scale, and that domain and kind violations
surface as AnalysisError. Report labeling and back-transformed display are checkpoint C.
"""

import math

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import stats

from openfurrow.analysis import AnalysisError, analyzeRcbd, assessAssumptions, separateMeans
from openfurrow.analysis.transforms import backTransformMean
from openfurrow.design import generateRcbdLayout
from openfurrow.reports.report import buildReport
from openfurrow.schema import Transform, TrialPackage
from openfurrow.schema.observation import Observation


def buildRcbd(values, transform="none", measurementKind="unspecified"):
  treatments = sorted({treatment for treatment, _ in values})
  blocks = sorted({block for _, block in values})
  package = TrialPackage.model_validate({
    "schemaVersion": "0.1.0",
    "trial": {"trialCode": "TX", "title": "t", "crop": "Maize", "season": "2025",
              "site": "s", "objective": "o"},
    "treatments": [{"treatmentCode": treatment, "name": treatment} for treatment in treatments],
    "design": {"designType": "rcbd", "replications": len(blocks), "randomizationSeed": 1},
    "assessments": [{"assessmentCode": "Y", "name": "y", "dataType": "numeric",
                     "measurementKind": measurementKind, "transform": transform}],
  })
  layout = generateRcbdLayout(package)
  observations = [
    Observation(plotNumber=plot.plotNumber, assessmentCode="Y",
                value=values[(plot.treatmentCode, plot.block)])
    for plot in layout.plots
  ]
  return package, layout, observations


def syntheticCounts(seed=11, treatments=4, blocks=8):
  rng = np.random.default_rng(seed)
  base = rng.uniform(5.0, 30.0, treatments)
  blockEffect = rng.uniform(-3.0, 3.0, blocks)
  values = {}
  for treatmentIndex in range(treatments):
    for blockIndex in range(blocks):
      mean = max(1.0, base[treatmentIndex] + blockEffect[blockIndex])
      values[(f"T{treatmentIndex + 1}", blockIndex + 1)] = float(rng.poisson(mean))
  return values


def statsmodelsAnova(values, transformFunction):
  rows = [{"y": transformFunction(value), "trt": treatment, "block": f"B{block}"}
          for (treatment, block), value in values.items()]
  model = smf.ols("y ~ C(trt) + C(block)", data=pd.DataFrame(rows)).fit()
  return sm.stats.anova_lm(model, typ=1)


def sourceRow(result, source):
  return next(row for row in result.table if row.source == source)


def testAnalyzeOnSqrtScaleMatchesStatsmodels():
  values = syntheticCounts()
  package, layout, observations = buildRcbd(values, transform="sqrt", measurementKind="count")
  result = analyzeRcbd("Y", package, layout, observations)
  assert result.transform is Transform.sqrt

  reference = statsmodelsAnova(values, math.sqrt)
  treatment = sourceRow(result, "treatment")
  block = sourceRow(result, "block")
  error = sourceRow(result, "error")
  assert treatment.sumOfSquares == pytest.approx(float(reference.loc["C(trt)", "sum_sq"]), rel=1e-9)
  assert treatment.fStatistic == pytest.approx(float(reference.loc["C(trt)", "F"]), rel=1e-9)
  assert block.sumOfSquares == pytest.approx(float(reference.loc["C(block)", "sum_sq"]), rel=1e-9)
  assert error.sumOfSquares == pytest.approx(float(reference.loc["Residual", "sum_sq"]), rel=1e-9)


def testTreatmentMeansAreOnTransformedScaleAndBackTransform():
  values = syntheticCounts()
  package, layout, observations = buildRcbd(values, transform="sqrt", measurementKind="count")
  result = analyzeRcbd("Y", package, layout, observations)
  means = {mean.treatmentCode: mean.mean for mean in result.treatmentMeans}

  byTreatment = {}
  for (treatment, _), value in values.items():
    byTreatment.setdefault(treatment, []).append(math.sqrt(value))
  for treatment, transformedValues in byTreatment.items():
    expected = sum(transformedValues) / len(transformedValues)
    assert means[treatment] == pytest.approx(expected, rel=1e-9)
    # back-transform is a point estimate on the original scale (mean-of-sqrt, squared).
    assert backTransformMean(result.transform, means[treatment]) == pytest.approx(means[treatment] ** 2, rel=1e-12)


def testProtectedLsdSeparatesAllTreatmentsOnTransformedScale():
  values = syntheticCounts()
  package, layout, observations = buildRcbd(values, transform="sqrt", measurementKind="count")
  result = analyzeRcbd("Y", package, layout, observations)
  separation = separateMeans(result, significanceLevel=0.05, protected=True)
  assert {row.treatmentCode for row in separation.groups} == {m.treatmentCode for m in result.treatmentMeans}


def testLogDomainViolationRaisesAnalysisError():
  values = {("T1", 1): 5.0, ("T1", 2): 0.0, ("T1", 3): 3.0,
            ("T2", 1): 4.0, ("T2", 2): 6.0, ("T2", 3): 2.0}
  package, layout, observations = buildRcbd(values, transform="log", measurementKind="continuous")
  with pytest.raises(AnalysisError, match="values > 0"):
    analyzeRcbd("Y", package, layout, observations)


def testKindViolationRaisesAnalysisError():
  values = syntheticCounts(blocks=4)
  package, layout, observations = buildRcbd(values, transform="logit", measurementKind="count")
  with pytest.raises(AnalysisError, match="not appropriate"):
    analyzeRcbd("Y", package, layout, observations)


def testDiagnosticsRunOnTransformedScale():
  values = syntheticCounts()
  packageRaw, layoutRaw, observationsRaw = buildRcbd(values, transform="none")
  packageSqrt, layoutSqrt, observationsSqrt = buildRcbd(values, transform="sqrt", measurementKind="count")

  rawVariance = assessAssumptions("Y", packageRaw, layoutRaw, observationsRaw).equalVariance.statistic
  transformed = assessAssumptions("Y", packageSqrt, layoutSqrt, observationsSqrt)
  # The transform reaches the diagnostics: raw and transformed statistics differ.
  assert transformed.equalVariance.statistic != pytest.approx(rawVariance)

  # And the transformed diagnostic matches scipy on the sqrt-transformed columns.
  treatments = sorted({treatment for treatment, _ in values})
  blocks = sorted({block for _, block in values})
  columns = [[math.sqrt(values[(treatment, block)]) for block in blocks] for treatment in treatments]
  reference = stats.levene(*columns, center="median")
  assert transformed.equalVariance.statistic == pytest.approx(reference.statistic, abs=1e-9)


# ---- checkpoint C: report surfacing ----------------------------------------

def testReportLabelsScaleBackTransformsMeansAndRecordsTransform():
  values = syntheticCounts()
  package, layout, observations = buildRcbd(values, transform="sqrt", measurementKind="count")
  report = buildReport(package, layout, observations)
  assert "square-root scale" in report
  assert "back-transformed to the original scale" in report
  assert "- Transforms: Y = sqrt" in report
  # the displayed mean is the back-transformed (original-scale) point estimate
  result = analyzeRcbd("Y", package, layout, observations)
  displayed = backTransformMean(Transform.sqrt, result.treatmentMeans[0].mean)
  assert f"{displayed:.3f}" in report


def testReportOmitsTransformArtifactsWhenNone():
  values = syntheticCounts()
  package, layout, observations = buildRcbd(values, transform="none")
  report = buildReport(package, layout, observations)
  assert "scale" not in report.lower()
  assert "- Transforms:" not in report
  assert "back-transformed" not in report


def testReportSurfacesRecommendationWhenFlagged():
  # Deliberately heteroscedastic counts: Brown-Forsythe flags, kind declared, no transform.
  columns = {"T1": [10, 10, 11, 10, 11, 10], "T2": [2, 40, 5, 38, 3, 41],
             "T3": [20, 20, 21, 20, 21, 20], "T4": [1, 50, 2, 49, 3, 48]}
  values = {}
  for treatment, series in columns.items():
    for index, value in enumerate(series):
      values[(treatment, index + 1)] = float(value)
  package, layout, observations = buildRcbd(values, transform="none", measurementKind="count")

  assumptions = assessAssumptions("Y", package, layout, observations)
  assert assumptions.equalVariance.pValue < 0.05
  assert assumptions.recommendation is not None and "sqrt" in assumptions.recommendation

  report = buildReport(package, layout, observations)
  assert "Recommendation:" in report
  assert "sqrt" in report.split("Recommendation:", 1)[1]
