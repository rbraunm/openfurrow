# SPDX-License-Identifier: Apache-2.0
"""The untreated check in or out of an assessment's analysis (decision 0030)."""

import pytest
from pydantic import ValidationError

from openfurrow import TrialPackage
from openfurrow.analysis import MeanComparison, analyzeCrd, analyzeRcbd, assessAssumptions
from openfurrow.design import generateLayout
from openfurrow.reports import buildReport
from openfurrow.schema.observation import Observation

from testDunnett import checkTrial


def withPolicy(policy, trial=checkTrial):
  package, layout, observations = trial()
  data = package.model_dump(mode="json")
  data["assessments"][0]["untreatedCheck"] = policy
  package = TrialPackage.model_validate(data)
  return package, layout, observations


def testLeavingTheCheckOutAnalysesTheOtherTreatmentsOnly():
  pandas = pytest.importorskip("pandas")
  formula = pytest.importorskip("statsmodels.formula.api")
  anova = pytest.importorskip("statsmodels.stats.anova")
  package, layout, observations = withPolicy("excluded")
  result = analyzeRcbd("D", package, layout, observations)
  assert [mean.treatmentCode for mean in result.treatmentMeans] == ["A", "B", "C"]
  where = {p.plotNumber: (p.block, p.treatmentCode) for p in layout.plots}
  frame = pandas.DataFrame([{"block": where[o.plotNumber][0], "t": where[o.plotNumber][1], "y": o.value}
                            for o in observations if where[o.plotNumber][1] != "UTC"])
  table = anova.anova_lm(formula.ols("y ~ C(block) + C(t)", data=frame).fit(), typ=1)
  rows = {row.source: row for row in result.table}
  assert rows["treatment"].sumOfSquares == pytest.approx(table.loc["C(t)", "sum_sq"], rel=1e-12)
  assert rows["error"].degreesOfFreedom == 6
  assert assessAssumptions("D", package, layout, observations).normality.computed


def testCheckValuesAreNotNeededWhenItIsLeftOut():
  package, layout, observations = withPolicy("excluded")
  checkPlots = {p.plotNumber for p in layout.plots if p.treatmentCode == "UTC"}
  kept = [o for o in observations if o.plotNumber not in checkPlots]
  assert len(analyzeRcbd("D", package, layout, kept).treatmentMeans) == 3


def testReportSaysTheCheckIsLeftOutAndGivesItsMean():
  report = buildReport(*withPolicy("excluded"))
  assert "The untreated check (UTC) is left out of this analysis; its mean as recorded is 20.500." in report
  assert "| UTC |" not in report.split("### Treatment means")[1].split("##")[0]
  included = buildReport(*withPolicy("included"))
  assert "left out of this analysis" not in included


def testDunnettWithTheCheckLeftOutIsNamedNotRun():
  report = buildReport(*withPolicy("excluded"), meanComparison=MeanComparison.dunnett)
  assert "Not analyzed: the untreated check 'UTC' is left out of this assessment's analysis" in report


def testLeavingTheCheckOutNeedsOneUntreatedControl():
  with pytest.raises(ValidationError, match="needs exactly one treatment whose role is untreatedControl, got \\[\\]"):
    withPolicy("excluded", lambda: checkTrial((None, None, None, None)))


def testTwoFactorTrialsKeepEveryCombination():
  from testFactorial import packageDict
  data = packageDict()
  data["treatments"][0]["role"] = "untreatedControl"
  data["assessments"][0]["untreatedCheck"] = "excluded"
  with pytest.raises(ValidationError, match="a two-factor trial keeps every combination"):
    TrialPackage.model_validate(data)


def testCrdLeavesTheCheckOutToo():
  from testCrd import gomezInputs, packageDict
  data = packageDict()
  data["treatments"][-1]["role"] = "untreatedControl"
  data["assessments"][0]["untreatedCheck"] = "excluded"
  package = TrialPackage.model_validate(data)
  _, layout, observations = gomezInputs()
  result = analyzeCrd("Y", package, layout, observations)
  assert "Control" not in [mean.treatmentCode for mean in result.treatmentMeans]
  assert result.errorDegreesOfFreedom == 18
