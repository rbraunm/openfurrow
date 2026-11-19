# SPDX-License-Identifier: Apache-2.0
"""Dunnett's test of every treatment against the untreated check (decision 0029).

The distribution is computed natively; it must equal the two-sided t with one comparison,
agree with scipy.stats.dunnett on simulated trials, and give the critical value Dunnett's
table prints for six comparisons on 24 df.
"""

import math

import numpy
import pytest

from openfurrow import TrialPackage, Workspace, schemaVersion
from openfurrow.analysis import AnalysisError, MeanComparison, analyzeRcbd, compareWithControl, separateMeans
from openfurrow.analysis.dunnett import dunnettCdf, dunnettQuantile, equalLoadings
from openfurrow.design import generateLayout
from openfurrow.reports import buildReport
from openfurrow.schema.observation import Observation
from storeHelpers import standardStudy


@pytest.mark.parametrize("degreesOfFreedom", [3, 5, 12, 24, 60])
def testOneComparisonIsTheTwoSidedT(degreesOfFreedom):
  tDistribution = pytest.importorskip("scipy.stats").t
  for d in (1.0, 2.0, 2.8, 4.0):
    assert dunnettCdf(d, equalLoadings(1), degreesOfFreedom) == pytest.approx(1 - 2 * tDistribution.sf(d, degreesOfFreedom), abs=1e-10)


def testCriticalValueMatchesDunnettsTable():
  # Dunnett (1955), two-sided, alpha 0.05: 2.76 for six treatments against a control on 24 df.
  assert round(dunnettQuantile(0.95, equalLoadings(6), 24), 2) == 2.76


@pytest.mark.parametrize("comparisons, perGroupDf", [(3, 4), (6, 4), (9, 3)])
def testPValuesAgreeWithScipy(comparisons, perGroupDf):
  stats = pytest.importorskip("scipy.stats")
  generator = numpy.random.default_rng(comparisons)
  groups = [generator.normal(10 + index * 0.4, 1.0, perGroupDf + 1) for index in range(comparisons + 1)]
  result = stats.dunnett(*groups[1:], control=groups[0], random_state=numpy.random.default_rng(1))
  errorDf = (comparisons + 1) * perGroupDf
  # scipy integrates the multivariate t by quasi-Monte Carlo, to about 1e-4.
  for statistic, pValue in zip(result.statistic, result.pvalue):
    assert 1 - dunnettCdf(abs(statistic), equalLoadings(comparisons), errorDf) == pytest.approx(pValue, abs=2e-4)


def checkTrial(roles=("untreatedControl", None, None, None)):
  values = {"UTC": [20, 22, 19, 21], "A": [12, 14, 13, 11], "B": [18, 21, 19, 20], "C": [9, 10, 12, 11]}
  treatments = []
  for code, role in zip(values, roles):
    treatment = {"treatmentCode": code, "name": code}
    if role:
      treatment["role"] = role
    treatments.append(treatment)
  package = TrialPackage.model_validate({
    "schemaVersion": schemaVersion,
    "trial": {"trialCode": "DUN-1", "title": "Against the check", "crop": "Wheat", "season": "2026",
              "site": "Field 1", "objective": "Compare with the untreated"},
    "treatments": treatments,
    "design": {"designType": "rcbd", "replications": 4, "randomizationMethod": "sha256FisherYates1", "randomizationSeed": 2},
    "ratings": [{"ratingCode": "D", "name": "Disease", "dataType": "numeric", "unit": "%"}],
    "assessments": [{"assessmentCode": "D", "ratingCode": "D"}],
  })
  layout = generateLayout(package)
  observations = [Observation(plotNumber=p.plotNumber, assessmentCode="D", value=float(values[p.treatmentCode][p.block - 1]))
                  for p in layout.plots]
  return package, layout, observations


def testEachTreatmentAgainstTheCheck():
  package, layout, observations = checkTrial()
  result = analyzeRcbd("D", package, layout, observations)
  comparison = compareWithControl(result, package)
  expected = dunnettQuantile(0.95, equalLoadings(3), result.errorDegreesOfFreedom) * math.sqrt(2 * result.errorMeanSquare / 4)
  assert comparison.criticalDifference == pytest.approx(expected, rel=1e-12)
  verdicts = {row.treatmentCode: (round(row.difference, 2), row.significant) for row in comparison.comparisons}
  assert verdicts == {"A": (-8.0, True), "B": (-1.0, False), "C": (-10.0, True)}
  assert comparison.checkCode == "UTC"


@pytest.mark.parametrize("roles, found", [((None, None, None, None), "has 0"),
                                          (("untreatedControl", "untreatedControl", None, None), "has 2")])
def testTheCheckMustBeOneUntreatedControl(roles, found):
  package, layout, observations = checkTrial(roles)
  with pytest.raises(AnalysisError, match=f"whose role is untreatedControl; trial 'DUN-1' {found}"):
    compareWithControl(analyzeRcbd("D", package, layout, observations), package)


def testLetterSeparationRefusesDunnett():
  package, layout, observations = checkTrial()
  with pytest.raises(AnalysisError, match="use compareWithControl"):
    separateMeans(analyzeRcbd("D", package, layout, observations), meanComparison=MeanComparison.dunnett)


def testReportShowsEachTreatmentAgainstTheCheck(tmp_path, newStore):
  report = buildReport(*checkTrial(), meanComparison=MeanComparison.dunnett)
  assert "Each treatment against UTC by Dunnett's two-sided test (alpha = 0.05)" in report
  assert "| Treatment | Mean (%) | Difference from UTC | Different from UTC |" in report
  assert "| UTC | 20.500 | - | - |" in report
  assert "| A | 12.500 | -8.000 | yes |" in report and "| B | 19.500 | -1.000 | no |" in report
  assert "- Critical difference (Dunnett, alpha = 0.05): " in report
  assert "RCBD ANOVA; Dunnett's test (alpha = 0.05)" in report
  workspace = Workspace.create(newStore("t"))
  package, _, observations = checkTrial()
  workspace.addPackage(package, standardStudy(workspace))
  csvPath = tmp_path / "d.csv"
  csvPath.write_text("plotNumber,assessmentCode,value\n" + "".join(f"{o.plotNumber},D,{o.value}\n" for o in observations),
                     encoding="utf-8")
  from openfurrow import ImportProfile
  workspace.importObservations("DUN-1", str(csvPath), ImportProfile())
  assert workspace.compareWithControl("DUN-1", "D").checkCode == "UTC"


def testFactorMeansFallBackToTheProtectedLsdUnderDunnett():
  from testSplitPlot import gomezInputs
  report = buildReport(*gomezInputs(), meanComparison=MeanComparison.dunnett)
  assert "Mean separation: Fisher's Protected LSD (alpha = 0.05), on this factor's own error." in report
