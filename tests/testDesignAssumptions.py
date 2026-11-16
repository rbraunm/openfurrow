# SPDX-License-Identifier: Apache-2.0
"""Assumption checks for the completely randomized and split-plot designs (decision 0006).

The residuals are checked against statsmodels' least-squares residuals of each design's
model; the tests on them against scipy's Brown-Forsythe and Shapiro-Wilk.
"""

import pytest

from openfurrow.analysis import assessAssumptions
from openfurrow.reports import buildReport

pandas = pytest.importorskip("pandas")
formula = pytest.importorskip("statsmodels.formula.api")
stats = pytest.importorskip("scipy.stats")


def plotFrame(package, layout, observations, code):
  levels = {t.treatmentCode: t.factorLevels for t in package.treatments}
  value = {o.plotNumber: o.value for o in observations if o.assessmentCode == code}
  return pandas.DataFrame([
    {"block": plot.block, "t": plot.treatmentCode, **(levels[plot.treatmentCode] or {}), "y": value[plot.plotNumber]}
    for plot in layout.plots
  ])


def testCrdChecksMatchTheOneWayModel():
  from testCrd import gomezInputs
  package, layout, observations = gomezInputs()
  frame = plotFrame(package, layout, observations, "Y")
  residuals = formula.ols("y ~ C(t)", data=frame).fit().resid
  assumptions = assessAssumptions("Y", package, layout, observations)
  reference = stats.shapiro(residuals)
  assert assumptions.normality.statistic == pytest.approx(reference.statistic, abs=1e-7)
  assert assumptions.normality.pValue == pytest.approx(reference.pvalue, abs=1e-6)
  levene = stats.levene(*(group["y"] for _, group in frame.groupby("t")), center="median")
  assert assumptions.equalVariance.statistic == pytest.approx(levene.statistic, rel=1e-9)
  assert assumptions.equalVariance.pValue == pytest.approx(levene.pvalue, abs=1e-9)
  assert (assumptions.equalVariance.numeratorDegreesOfFreedom, assumptions.equalVariance.denominatorDegreesOfFreedom) == (6, 21)
  assert assumptions.nonAdditivity is None and assumptions.mainPlotNormality is None
  assert assumptions.residualsNoteKey == "report.assumptions.residualsNote.crd"


def testSplitPlotChecksMatchEachStratum():
  from testSplitPlot import gomezInputs
  package, layout, observations = gomezInputs()
  code = package.assessments[0].assessmentCode
  design = package.design
  frame = plotFrame(package, layout, observations, code).rename(
    columns={design.mainPlotFactor: "main", design.subPlotFactor: "sub"})
  subResiduals = formula.ols("y ~ C(block) * C(main) + C(main) * C(sub)", data=frame).fit().resid
  mainPlots = frame.groupby(["block", "main"], as_index=False)["y"].mean()
  mainResiduals = formula.ols("y ~ C(block) + C(main)", data=mainPlots).fit().resid
  assumptions = assessAssumptions(code, package, layout, observations)
  for outcome, residuals in ((assumptions.mainPlotNormality, mainResiduals), (assumptions.normality, subResiduals)):
    reference = stats.shapiro(residuals)
    assert outcome.statistic == pytest.approx(reference.statistic, abs=1e-7)
    assert outcome.pValue == pytest.approx(reference.pvalue, abs=1e-6)
  assert assumptions.mainPlotNormality.nameKey == "diagnostic.mainPlotNormality.name"
  assert assumptions.normality.nameKey == "diagnostic.subPlotNormality.name"
  levene = stats.levene(*(group["y"] for _, group in frame.groupby("t")), center="median")
  assert assumptions.equalVariance.statistic == pytest.approx(levene.statistic, rel=1e-9)
  assert assumptions.nonAdditivity is None


def testReportGivesEachDesignsChecks():
  from testCrd import gomezInputs as crdInputs
  from testSplitPlot import gomezInputs as splitInputs
  crd = buildReport(*crdInputs())
  assert "- Normality of residuals (Shapiro-Wilk): W = 0.9857." in crd
  assert "Non-additivity" not in crd
  assert "Residuals are each plot's value less its treatment mean" in crd
  split = buildReport(*splitInputs())
  assert "- Normality of main-plot residuals (Shapiro-Wilk): W = 0.9480." in split
  assert "- Normality of subplot residuals (Shapiro-Wilk): W = 0.9656." in split
  assert "Main-plot residuals come from the main-plot means" in split
