# SPDX-License-Identifier: Apache-2.0
"""The report of an analysis with missing plots, and the setting behind it (decision 0043).

On the seeding-rate trial of Gomez and Gomez (1984), Table 2.5, with the missing values of
their sections 7.1.2.1 and 7.1.2.6: the report says which plots were missing, the policy,
that the means are adjusted, which sums of squares the table holds, and each pair's own
standard error; the reproducibility block records the policy and how each plot was
handled. The numbers asserted are those the analysis tests check against statsmodels and
the book.

In a store, the analysis follows `analysis.missingPlots` at the server, a place or the
trial; the result records what it ran under; an estimate is never stored, and neither the
policy nor an analysis changes the trial's content hash.
"""

import pytest

from openfurrow import Workspace
from openfurrow.analysis import AnalysisError, MeanComparison, MissingPlotPolicy
from openfurrow.i18n import availableLocales, loadCatalog
from openfurrow.reports import buildReport, inputHash
from openfurrow.reports.report import buildReportWithCharts
from openfurrow.schema.observation import Observation
from openfurrow.service import createApp
from openfurrow.settings import SettingError
from storeHelpers import standardPath, standardStudy

from testMissingPlots import (
  blockTrial,
  crdTrial,
  matrix,
  plotOf,
  registryDatasets,
  stirret,
  stirretCells,
  stirretTreatments,
)

rates = ["R25", "R50", "R75", "R100", "R125", "R150"]
oneMissing = {("R100", 2)}
twoMissing = {("R100", 2), ("R25", 1)}


def seedRate(missing):
  return blockTrial(rates, 4, registryDatasets()["gomezSeedRate"][2], missing)


def report(missing, policy, meanComparison=MeanComparison.protectedLSD, locale="en-US"):
  return buildReport(*seedRate(missing), meanComparison=meanComparison, missingPlots=MissingPlotPolicy(policy), locale=locale)


def testLeastSquaresReportSaysWhatWasMissingAndThatMeansAreAdjusted():
  package, layout, _ = seedRate(oneMissing)
  plot = plotOf(layout, "R100", 2)
  text = report(oneMissing, "leastSquares")
  assert (
    f"Missing plots: plot {plot} (treatment R100, block 2). They are left out, and the model is fitted by least "
    "squares to the plots that have a value (missing-plot policy leastSquares). The treatment means below are "
    "adjusted (least-squares) means."
  ) in text
  assert (
    "Sums of squares are Type III: block is adjusted for treatment and treatment for block, so the lines do not "
    "add up to the total.\n\n"
    "| Source | df | SS | MS | F | P |\n|---|---:|---:|---:|---:|---:|\n"
    "| Block | 3 | 2061636.9278 | 687212.3093 | 6.24 | 0.0065 |\n"
    "| Treatment | 5 | 1139954.2111 | 227990.8422 | 2.07 | 0.1301 |\n"
    "| Error | 14 | 1540725.9889 | 110051.8563 | - | - |\n"
    "| Total | 22 | 4783815.3043 | - | - | - |\n"
  ) in text
  assert "- Grand mean (of the adjusted treatment means): 4977.661\n" in text
  assert "- Coefficient of variation (on the adjusted grand mean): 6.66%\n" in text
  assert (
    "| Treatment | Adjusted mean | Plots | Standard error | Group |\n|---|---:|---:|---:|:--:|\n"
    "| R75 | 5304.250 | 4 | 165.870 | a |\n"
  ) in text
  assert "| R100 | 4956.217 | 3 | 196.260 | a |\n" in text
  assert "- LSD (alpha = 0.05), which differs by pair: 503.116 to 551.136\n" in text
  assert "- Means were not separated: the treatment effect was not significant (protected LSD)." in text
  assert (
    "#### Differences between pairs\n\n"
    "With missing plots the standard error of a difference depends on the pair, so each pair is held to a critical "
    "difference of its own.\n\n"
    "| Pair | Difference | Standard error | Critical difference | Different |\n|---|---:|---:|---:|:--:|\n"
    "| R75 - R25 | 180.250 | 234.576 | 503.116 | no |\n"
  ) in text
  assert "| R75 - R100 | 348.033 | 256.965 | 551.136 | no |\n" in text
  assert text.count(" | 256.965 | 551.136 | ") == 5 and text.count(" | 234.576 | 503.116 | ") == 10
  assert (
    f"- Missing plots: policy leastSquares; Y: least squares on the plots present, Type III sums of squares, "
    f"adjusted means, each comparison on its own standard error; left out: plot {plot} (treatment R100, block 2)\n"
  ) in text


def testEstimateReportShowsTheEstimateAsAnEstimate():
  package, layout, _ = seedRate(oneMissing)
  plot = plotOf(layout, "R100", 2)
  text = report(oneMissing, "estimate", MeanComparison.lsd)
  assert (
    f"Missing plots: plot {plot} (treatment R100, block 2). For the arithmetic only, each is given Yates' estimate, "
    "the value that makes the error sum of squares smallest (missing-plot policy estimate). An estimate is not an "
    "observation and is never stored. The treatment means below are those of the completed table, which are the "
    "adjusted means.\n\n"
    "| Plot | Treatment | Block | Estimate |\n|---|---|---:|---:|\n"
    f"| {plot} | R100 | 2 | 5264.8667 |\n\n"
    "With one missing plot the estimate is Yates' closed form.\n\n"
    "Sums of squares are those of the completed table, and the degrees of freedom for error and for total are each "
    "reduced by 1. The treatment sum of squares is reduced by 551.8370, the upward bias the estimates give it, and "
    "the total with it. The block line is not corrected and is not tested.\n\n"
    "| Source | df | SS | MS | F | P |\n|---|---:|---:|---:|---:|---:|\n"
    "| Block | 3 | 2188656.6911 | 729552.2304 | - | - |\n"
    "| Treatment | 5 | 1139954.2111 | 227990.8422 | 2.07 | 0.1301 |\n"
    "| Error | 14 | 1540725.9889 | 110051.8563 | - | - |\n"
    "| Total | 22 | 4869336.8911 | - | - | - |\n"
  ) in text
  assert "| R100 | 4956.217 | 3 | 196.260 | ab |\n" in text
  assert "| R75 - R125 | 596.250 | 234.576 | 503.116 | yes |\n" in text
  assert (
    f"- Missing plots: policy estimate; Y: Yates' estimates on the analyzed scale (cycles 1, tolerance 1e-12), "
    f"completed-table sums of squares with treatment reduced by 551.8370, each comparison on its own standard error; "
    f"plot {plot} (treatment R100, block 2) estimated as 5264.8667\n"
  ) in text


def testSeveralEstimatesAreReportedWithTheirIteration():
  text = report(twoMissing, "estimate", MeanComparison.tukeyHSD)
  assert "| R25 | 1 | 5421.8482 |\n" in text and "| R100 | 2 | 5244.2768 |\n" in text
  assert (
    "The estimates were reached by Yates' iteration in 6 cycles, stopping when none moved by more than 1e-12 of the "
    "largest value; the starting values and the order are fixed, so the estimates are reproducible."
  ) in text
  assert "are each reduced by 2. The treatment sum of squares is reduced by 55487.2967," in text
  assert "| Treatment | 5 | 1196785.4254 | 239357.0851 | 2.10 | 0.1304 |\n" in text
  assert "| Error | 13 | 1481373.9412 | 113951.8416 | - | - |\n" in text
  # Tukey's test on pairs with standard errors of their own goes by its own name, and says what it is in blocks.
  assert "Mean separation: Tukey-Kramer (alpha = 0.05)." in text
  assert "- HSD (alpha = 0.05), which differs by pair: 791.545 to 946.077\n" in text
  assert "For adjusted means in blocks the Tukey-Kramer test holds its error rate only approximately." in text
  assert "| R25 - R100 | 250.143 | 285.297 | 946.077 | no |\n" in text


def testRefuseReportNamesThePlotsAndThePolicy():
  package, layout, _ = seedRate(oneMissing)
  text = report(oneMissing, "refuse")
  assert (
    "Not analyzed: assessment 'Y' has missing values; RCBD ANOVA requires a complete table while the setting "
    f"analysis.missingPlots is 'refuse'. Missing: plot {plotOf(layout, 'R100', 2)} (treatment R100, block 2)"
  ) in text
  assert "- Missing plots: policy refuse\n" in text
  assert "### Analysis of variance" not in text and "Adjusted mean" not in text


def testACompleteTablesReportIsUnchangedButForThePolicyLine():
  complete = {policy: report(set(), policy) for policy in ("refuse", "estimate", "leastSquares")}
  assert "| Treatment | Mean | Group |\n|---|---:|:--:|\n" in complete["refuse"]
  assert "- LSD (alpha = 0.05): " in complete["refuse"] and "Adjusted" not in complete["refuse"]
  assert "Differences between pairs" not in complete["refuse"] and "Missing plots: plot" not in complete["refuse"]
  for policy, text in complete.items():
    assert f"- Missing plots: policy {policy}\n" in text
    assert text.replace(f"policy {policy}", "policy refuse") == complete["refuse"]


def testTheInputHashIsTheSameUnderEveryPolicy():
  package, layout, observations = seedRate(oneMissing)
  expected = f"- Input hash (SHA-256): {inputHash(package, layout, observations)}\n"
  for policy in MissingPlotPolicy:
    assert expected in report(oneMissing, policy.value)


def testANonEstimablePatternIsNamedInTheReportNotAnalysed():
  text = report({(rate, 3) for rate in rates}, "leastSquares")
  assert "Not analyzed: assessment 'Y' is not estimable with its missing plots: block 3 has no value on any plot" in text
  assert "### Analysis of variance" not in text
  assert "- Missing plots: policy leastSquares\n" in text


def testDunnettTableGivesEachTreatmentsOwnCriticalDifference():
  cells = registryDatasets()["gomezSeedRate"][2]
  package, layout, observations = blockTrial(rates, 4, cells, oneMissing, roles={"R25": "untreatedControl"})
  text = buildReport(package, layout, observations, meanComparison=MeanComparison.dunnett,
                     missingPlots=MissingPlotPolicy.leastSquares)
  assert (
    "| Treatment | Adjusted mean | Plots | Standard error | Difference from R25 | Standard error of the difference "
    "| Critical difference | Different from R25 |\n|---|---:|---:|---:|---:|---:|---:|:--:|\n"
    "| R25 | 5124.000 | 4 | 165.870 | - | - | - | - |\n"
  ) in text
  assert "| R100 | 4956.217 | 3 | 196.260 | -167.783 | 256.965 | " in text
  assert "| R50 | 5070.250 | 4 | 165.870 | -53.750 | 234.576 | " in text
  assert "- Critical difference (Dunnett, alpha = 0.05), which differs by treatment: " in text


def testCrdReportSaysTheTreatmentsAreUnequallyReplicated():
  package, layout, observations, _, _, missing = crdTrial((4, 3, 4, 2))
  text = buildReport(package, layout, observations, meanComparison=MeanComparison.tukeyHSD,
                     missingPlots=MissingPlotPolicy.leastSquares)
  assert f"Missing plots: plot {missing[0]} (treatment T2), plot {missing[1]} (treatment T4), plot {missing[2]} (treatment T4)." in text
  assert (
    "The treatments are unequally replicated. The treatment sum of squares is Type III, which with a single factor "
    "is also the sequential one, so the lines add up to the total."
  ) in text
  assert "Mean separation: Tukey-Kramer (alpha = 0.05)." in text
  # Without blocks the Tukey-Kramer test is not the approximation it is for adjusted means in blocks.
  assert "only approximately" not in text
  assert "| T4 | " in text and " | 2 | " in text
  estimated = buildReport(package, layout, observations, missingPlots=MissingPlotPolicy.estimate)
  assert "Not analyzed: assessment 'Y' has missing values; the setting analysis.missingPlots is 'estimate', and Yates' estimates complete a table of blocks" in estimated


def testChartWhiskersAreEachMeansOwnStandardError():
  built = buildReportWithCharts(*seedRate(oneMissing), marker="m0rk3r", missingPlots=MissingPlotPolicy.leastSquares)
  chart = built.charts[0]
  assert chart.title == "Treatment means: Adjusted mean"
  assert chart.caption == (
    "Bars are means; whiskers are one standard error of each mean (165.870 to 196.260, as their plots differ in "
    "number), from the error of the analysis. Bars sharing a letter do not differ significantly."
  )
  bars = {bar.label: bar for bar in chart.bars}
  assert bars["R100"].high - bars["R100"].mean == pytest.approx(196.2603, abs=5e-4)
  assert bars["R75"].high - bars["R75"].mean == pytest.approx(165.8703, abs=5e-4)
  complete = buildReportWithCharts(*seedRate(set()), marker="m0rk3r")
  assert "whiskers are one standard error of a mean (" in complete.charts[0].caption


@pytest.mark.parametrize("policy", ["leastSquares", "estimate"])
def testEveryLocaleRendersTheMissingPlotReport(policy):
  english = loadCatalog("en-US")
  for locale in availableLocales():
    text = report(twoMissing, policy, MeanComparison.tukeyHSD, locale)
    catalog = loadCatalog(locale)
    assert catalog.text("report.heading.pairs") in text, locale
    assert catalog.text("report.pairs.tukeyKramerInBlocks") in text, locale
    assert catalog.text("report.anova.adjustedGrandMean") in text, locale
    assert f"{catalog.text('report.reproducibility.missingPlots')}" in text, locale
    if locale in ("es", "fr", "ar"):
      for key in ("report.heading.pairs", "report.anova.adjustedGrandMean", "report.pairs.note",
                  "report.means.column.standardError"):
        assert english.text(key) not in text, f"{locale} carried the English text of {key}"
      # The trial's own title is "Missing plots"; the label of the reproducibility line must not be.
      assert f"- {english.text('report.reproducibility.missingPlots')}:" not in text, locale
  french = report(oneMissing, "leastSquares", locale="fr")
  assert "| R75 - R100 | 348,033 | 256,965 | 551,136 | non |" in french
  assert "PPDS (alpha = 0,05), qui diff\u00e8re selon la paire: 503,116 \u00e0 551,136" in french


def testTheReportPageAndTheStoredSettingAgree(newStore):
  location = newStore("missing")
  workspace = Workspace.create(location)
  package, layout, observations = seedRate(oneMissing)
  workspace.addPackage(package, standardStudy(workspace))
  workspace.recordValues("MISSING-1", "Y", observations)
  workspace.setSetting("trial:MISSING-1", "analysis.missingPlots", "leastSquares")
  text = workspace.buildReport("MISSING-1")
  assert "analysis.missingPlots = leastSquares (set for this trial)" in text
  assert "- Missing plots: policy leastSquares; Y: least squares on the plots present" in text
  body = createApp(location).test_client().get("/trials/MISSING-1/report").get_data(as_text=True)
  assert "Adjusted mean" in body and "<h4>Differences between pairs</h4>" in body
  assert "<td>R75 - R100</td>" in body and body.count('<figure class="chart">') == 1
  assert "whiskers are one standard error of each mean (165.870 to 196.260" in body
  recorded = sorted((o.plotNumber, o.value) for o in workspace.loadObservations("MISSING-1"))
  assert recorded == sorted((o.plotNumber, o.value) for o in observations)
  assert all(isinstance(o, Observation) for o in workspace.loadObservations("MISSING-1")) and len(recorded) == 23


# ---- the setting, what the result records, and what is never stored ----------------------

def stirretInStore(newStore, missing):
  workspace = Workspace.create(newStore("missing"))
  package, layout, _ = stirret()
  workspace.addPackage(package, standardStudy(workspace))
  cells = stirretCells()
  stored = workspace.layoutFor("MISSING-1")
  workspace.recordValues("MISSING-1", "Y", [
    Observation(plotNumber=plot.plotNumber, assessmentCode="Y", value=cells[(plot.treatmentCode, plot.block)])
    for plot in stored.plots if (plot.treatmentCode, plot.block) not in missing
  ])
  return workspace


def testTheAnalysisFollowsTheSettingAtEveryScope(newStore):
  workspace = stirretInStore(newStore, matrix["M1"])
  trial = "trial:MISSING-1"
  with pytest.raises(AnalysisError, match="analysis.missingPlots is 'refuse'"):
    workspace.analyze("MISSING-1", "Y")
  workspace.setSetting("server", "analysis.missingPlots", "leastSquares")
  assert workspace.analyze("MISSING-1", "Y").missingPlotPolicy is MissingPlotPolicy.leastSquares
  workspace.setSetting(f"place:{standardPath}", "analysis.missingPlots", "estimate")
  estimated = workspace.analyze("MISSING-1", "Y")
  assert estimated.missingPlotPolicy is MissingPlotPolicy.estimate and estimated.missingCells[0].estimate is not None
  workspace.setSetting(trial, "analysis.missingPlots", "refuse")
  with pytest.raises(AnalysisError, match="analysis.missingPlots is 'refuse'"):
    workspace.separateMeans("MISSING-1", "Y")
  with pytest.raises(AnalysisError, match="analysis.missingPlots is 'refuse'"):
    workspace.assessAssumptions("MISSING-1", "Y")
  workspace.setSetting(trial, "analysis.missingPlots", "leastSquares")
  effective = {setting.key: (setting.value, setting.source) for setting in workspace.effectiveSettings(trial)}
  assert effective["analysis.missingPlots"] == (MissingPlotPolicy.leastSquares, trial)
  assert workspace.separateMeans("MISSING-1", "Y").criticalDifference is None
  assert workspace.assessAssumptions("MISSING-1", "Y").normality.computed
  with pytest.raises(SettingError, match="does not take 'impute'"):
    workspace.setSetting(trial, "analysis.missingPlots", "impute")


def testTheResultRecordsThePolicyAndEveryMissingPlot(newStore):
  workspace = stirretInStore(newStore, matrix["M2"])
  workspace.setSetting("trial:MISSING-1", "analysis.missingPlots", "estimate")
  layout = workspace.layoutFor("MISSING-1")
  recorded = workspace.analyze("MISSING-1", "Y").model_dump(mode="json")
  assert recorded["missingPlotPolicy"] == "estimate" and recorded["sumsOfSquares"] == "completedTable"
  assert [(cell["plotNumber"], cell["treatmentCode"], cell["block"], cell["handling"]) for cell in recorded["missingCells"]] == [
    (plotOf(layout, treatment, block), treatment, block, "estimated")
    for block, treatment in sorted(((block, treatment) for treatment, block in matrix["M2"]),
                                   key=lambda cell: (cell[0], stirretTreatments.index(cell[1])))
  ]
  assert all(isinstance(cell["estimate"], float) for cell in recorded["missingCells"])
  assert recorded["estimation"]["tolerance"] == 1e-12 and recorded["estimation"]["cycles"] > 1
  # A setting changed afterwards changes the next analysis, never this record.
  workspace.setSetting("trial:MISSING-1", "analysis.missingPlots", "leastSquares")
  assert recorded["missingPlotPolicy"] == "estimate"
  assert workspace.analyze("MISSING-1", "Y").model_dump(mode="json")["missingPlotPolicy"] == "leastSquares"


def testAnEstimateIsNeverStoredAndThePolicyIsOutsideTheContentHash(newStore):
  workspace = stirretInStore(newStore, matrix["M2"])
  before = workspace.contentHashFor("MISSING-1")
  valuesBefore = sorted((o.plotNumber, o.value) for o in workspace.loadObservations("MISSING-1"))
  for policy in ("estimate", "leastSquares"):
    workspace.setSetting("trial:MISSING-1", "analysis.missingPlots", policy)
    workspace.analyze("MISSING-1", "Y")
    workspace.buildReport("MISSING-1")
    assert workspace.contentHashFor("MISSING-1") == before
  stored = workspace.loadObservations("MISSING-1")
  assert sorted((o.plotNumber, o.value) for o in stored) == valuesBefore
  assert len(stored) == 60 - len(matrix["M2"])
  package, layout, observations = stirret(matrix["M2"])
  assert inputHash(package, layout, observations) == before
