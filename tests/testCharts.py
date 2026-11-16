# SPDX-License-Identifier: Apache-2.0
"""Charts of separated means (decision 0032): geometry, error bars, and their place in the report."""

import math
import re
from xml.etree import ElementTree

import pytest

from openfurrow import Workspace
from openfurrow.analysis import MeanComparison, analyzeRcbd, compareWithControl, separateMeans
from openfurrow.analysis.distributions import tCriticalValue
from openfurrow.analysis.splitPlot import analyzeSplitPlot, separateFactorMeans
from openfurrow.analysis.transforms import TransformError, backTransformInterval
from openfurrow.i18n import translatorFor
from openfurrow.reports import buildReport
from openfurrow.reports.charts import ChartBar, MeansChart, axisRange, meansChartSvg, niceStep
from openfurrow.reports.report import buildReportWithCharts
from openfurrow.schema.assessment import Transform

_svg = "{http://www.w3.org/2000/svg}"


@pytest.mark.parametrize("span, step", [(10.0, 2.0), (1.0, 0.2), (7.3, 2.0), (120.0, 25.0), (0.04, 0.01), (3.0, 1.0)])
def testTickStepsAreRound(span, step):
  assert niceStep(span) == pytest.approx(step)


def chart(bars):
  return MeansChart(title="Yield", axisTitle="Mean (kg)", caption="c", decimals=1, bars=bars)


def testBarsAndWhiskersSitWhereTheirValuesAre():
  bars = [ChartBar(label="A", mean=12.0, low=10.5, high=13.5, group="a"),
          ChartBar(label="B", mean=4.0, low=3.0, high=5.0, group="b")]
  bottom, top, _ = axisRange(chart(bars))
  assert (bottom, top) == (0.0, 15.0)
  root = ElementTree.fromstring(meansChartSvg(chart(bars), translatorFor("en-US")))
  plot = 220.0

  def y(value):
    return 24.0 + plot * (top - value) / (top - bottom)

  marks = root.findall(f"{_svg}g")
  assert [mark.find(f"{_svg}title").text for mark in marks] == ["A: 12.0 (10.5 - 13.5) a", "B: 4.0 (3.0 - 5.0) b"]
  for mark, bar in zip(marks, bars):
    path = mark.find(f"{_svg}path[@class='chart-bar']").get("d")
    assert f"V{y(0.0):.1f}Z" in path and f" {y(bar.mean):.1f}H" in path
    error = [float(n) for n in re.findall(r"-?\d+\.\d", mark.find(f"{_svg}path[@class='chart-error']").get("d"))]
    assert (error[1], error[2]) == (round(y(bar.low), 1), round(y(bar.high), 1))
    assert mark.find(f"{_svg}text[@class='chart-letter']").text == bar.group
  ticks = [text.text for text in root.findall(f"{_svg}text[@class='chart-tick']")]
  assert ticks == ["0", "5", "10", "15"]


def testNegativeMeansHangFromTheBaseline():
  bars = [ChartBar(label="A", mean=-3.0, low=-4.0, high=-2.0)]
  bottom, top, _ = axisRange(chart(bars))
  assert (bottom, top) == (-4.0, 0.0)
  root = ElementTree.fromstring(meansChartSvg(chart(bars), translatorFor("en-US")))
  path = root.find(f".//{_svg}path[@class='chart-bar']").get("d")
  # The baseline (zero) is the top of the plot at 24; the bar ends at -3, three quarters down.
  assert path.startswith("M84.0 24.0V185.0") and " 189.0H" in path and path.endswith("V24.0Z")


def testAWhiskerMustHoldItsMean():
  with pytest.raises(ValueError, match="does not hold the mean"):
    meansChartSvg(chart([ChartBar(label="A", mean=5.0, low=6.0, high=7.0)]), translatorFor("en-US"))


def testBackTransformedWhiskersStopAtTheScalesEdge():
  assert backTransformInterval(Transform.sqrt, -0.5, 2.0, 0.5) == (-0.5, 3.5)
  low, high = backTransformInterval(Transform.arcsinSqrt, 1.4, 1.7, 0.0)
  assert (low, high) == (pytest.approx(math.sin(1.4) ** 2), 1.0)
  assert backTransformInterval(Transform.log, 0.0, 1.0, 0.0) == (1.0, pytest.approx(math.e))
  with pytest.raises(TransformError, match="out of order"):
    backTransformInterval(Transform.none, 2.0, 1.0, 0.0)


def testStandardErrorOfATreatmentMeanAgreesWithStatsmodels():
  pandas = pytest.importorskip("pandas")
  formula = pytest.importorskip("statsmodels.formula.api")
  from testDunnett import checkTrial
  package, layout, observations = checkTrial()
  result = analyzeRcbd("D", package, layout, observations)
  separation = separateMeans(result)
  where = {p.plotNumber: (p.block, p.treatmentCode) for p in layout.plots}
  frame = pandas.DataFrame([{"block": where[o.plotNumber][0], "t": where[o.plotNumber][1], "y": o.value} for o in observations])
  fit = formula.ols("y ~ C(block) + C(t, Treatment('UTC'))", data=frame).fit()
  blocks = sorted(frame["block"].unique())
  contrast = [1.0] + [1.0 / len(blocks)] * (len(blocks) - 1) + [0.0] * (len(fit.params) - len(blocks))
  assert separation.standardError == pytest.approx(float(fit.t_test(contrast).sd[0][0]), rel=1e-10)
  assert compareWithControl(result, package).standardError == separation.standardError


def testFactorStandardErrorsMatchTheirLsd():
  from testSplitPlot import gomezInputs
  package, layout, observations = gomezInputs()
  result = analyzeSplitPlot(package.assessments[0].assessmentCode, package, layout, observations)
  for factor, errorDf in ((result.mainPlotFactor, result.mainPlotErrorDegreesOfFreedom),
                          (result.subPlotFactor, result.subPlotErrorDegreesOfFreedom)):
    separation = separateFactorMeans(result, factor, meanComparison=MeanComparison.lsd)
    assert separation.criticalDifference == pytest.approx(
      tCriticalValue(0.025, errorDf) * math.sqrt(2.0) * separation.standardError, rel=1e-12)


def testEveryTableOfMeansGetsItsChartOnThePageOnly(tmp_path):
  from testSplitPlot import gomezInputs
  inputs = gomezInputs()
  plain = buildReport(*inputs)
  built = buildReportWithCharts(*inputs, marker="m0rk3r")
  assert built.markdown.replace("m0rk3r0\n\n", "").replace("m0rk3r1\n\n", "") == plain
  assert [c.title for c in built.charts] == ["Means of Nitrogen", "Means of Variety"]
  assert len(built.charts[0].bars) == 6 and all(bar.group for bar in built.charts[0].bars)
  with pytest.raises(ValueError, match="letters and digits only"):
    buildReportWithCharts(*inputs, marker="<p>")


def testTheReportPageDrawsTheCharts(tmp_path):
  from openfurrow.service import createApp
  from testDunnett import checkTrial
  package, _, observations = checkTrial()
  path = str(tmp_path / "t.db")
  workspace = Workspace.create(path)
  workspace.addPackage(package)
  workspace.recordValues("DUN-1", "D", observations)
  body = createApp(path).test_client().get("/trials/DUN-1/report").get_data(as_text=True)
  assert body.count('<figure class="chart">') == 1
  assert 'aria-label="Treatment means: Mean (%)"' in body
  assert "Bars sharing a letter do not differ significantly." in body
  separation = separateMeans(analyzeRcbd("D", *checkTrial()))
  assert separation.standardError == pytest.approx(0.577, abs=5e-4)
  assert "<title>UTC: 20.500 (19.923 - 21.077) a</title>" in body
