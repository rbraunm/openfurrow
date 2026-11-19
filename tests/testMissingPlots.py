# SPDX-License-Identifier: Apache-2.0
"""Missing plots under the three policies (decisions 0003 and 0043).

The matrix of decision 0003 on stirret.borers, with cells removed in each pattern: under
`refuse` every pattern M1 to M4 rejects and names its plots; under `leastSquares` and
`estimate` M1 to M3 are analysed, M4 is refused as not estimable with its specific
reason, and M5 (the complete table) is analysed as it always was. In a single-factor RCBD
a treatment has one plot in each block, so M3 (a treatment absent from one block) is one
missing cell, here the untreated control's.

Every reported number of both methods is checked against statsmodels fitting the same
model to the plots present (an independent implementation, test-only): Type III sums of
squares, F, P, the adjusted means, their standard errors, every pairwise difference and
its standard error, across M1 to M3 on the registry's datasets and on generated
unbalanced tables. Yates' estimates are checked against the same fit's predictions for
the missing plots. Tolerances: 1e-9 relative on sums of squares, means and standard
errors, 1e-6 relative on P.
"""

import csv
import itertools
import math
from pathlib import Path

import numpy
import pandas
import pytest
import statsmodels.api as statsmodelsApi
import statsmodels.formula.api as statsmodelsFormula

from openfurrow import TrialPackage, schemaVersion
from openfurrow.analysis import (
  AnalysisError,
  MeanComparison,
  MissingHandling,
  MissingPlotPolicy,
  SumsOfSquares,
  analyzeCrd,
  analyzeEfficacy,
  analyzeFactorialRcbd,
  analyzeRcbd,
  analyzeSplitPlot,
  assessAssumptions,
  differenceStandardError,
  meanStandardError,
  separateMeans,
)
from openfurrow.analysis.yates import tolerance as yatesTolerance
from openfurrow.design import generateLayout
from openfurrow.schema.observation import Observation

fixtures = Path(__file__).parent / "fixtures"
handled = (MissingPlotPolicy.leastSquares, MissingPlotPolicy.estimate)


def readFixture(name):
  with (fixtures / name).open(newline="", encoding="utf-8") as handle:
    return list(csv.DictReader(handle))


def blockTrial(treatments, blockCount, cells, missing=(), rating=None, roles=None, assessment=None):
  """An RCBD of `cells` {(treatment, block): value}, the plots in `missing` left without a value."""
  roles = roles or {}
  package = TrialPackage.model_validate({
    "schemaVersion": schemaVersion,
    "trial": {"trialCode": "MISSING-1", "title": "Missing plots", "crop": "Maize", "season": "2026",
              "site": "Field 3", "objective": "Analyse a table with missing plots"},
    "treatments": [
      {"treatmentCode": code, "name": code} | ({"role": roles[code]} if code in roles else {}) for code in treatments
    ],
    "design": {"designType": "rcbd", "replications": blockCount, "randomizationMethod": "sha256FisherYates1",
               "randomizationSeed": 3},
    "ratings": [{"ratingCode": "Y", "name": "Response", "dataType": "numeric"} | (rating or {})],
    "assessments": [{"assessmentCode": "Y", "ratingCode": "Y"} | (assessment or {})],
  })
  layout = generateLayout(package)
  observations = [
    Observation(plotNumber=plot.plotNumber, assessmentCode="Y", value=cells[(plot.treatmentCode, plot.block)])
    for plot in layout.plots if (plot.treatmentCode, plot.block) not in missing
  ]
  return package, layout, observations


def plotOf(layout, treatment, block):
  return next(p.plotNumber for p in layout.plots if (p.treatmentCode, p.block) == (treatment, block))


stirretTreatments = ["None", "Early", "Late", "Both"]


def stirretCells(column="count1"):
  return {(row["trt"], int(row["block"])): float(row[column]) for row in readFixture("stirretBorers.csv")}


def stirret(missing=(), column="count1", **options):
  return blockTrial(stirretTreatments, 15, stirretCells(column), missing, **options)


# The matrix of decision 0003: (treatment, block) cells removed from stirret.borers.
matrix = {
  "M1": {("Late", 7)},
  "M2": {("None", 2), ("Early", 2), ("Late", 9), ("Both", 14), ("Early", 15)},
  "M3": {("None", 4)},
}
absentTreatment = {("Late", block) for block in range(1, 16)}
absentBlock = {(treatment, 6) for treatment in stirretTreatments}
disconnected = (
  {(treatment, block) for treatment in ("None", "Early") for block in range(8, 16)}
  | {(treatment, block) for treatment in ("Late", "Both") for block in range(1, 8)}
)
noErrorLeft = {(treatment, block) for treatment in ("Early", "Late", "Both") for block in range(2, 16)}


def registryDatasets():
  """The registry's RCBD datasets as (treatments, blocks, cells, rating, the transform as a function)."""
  larvae = {(row["treatment"], int(row["replication"])): float(row["larvae"]) for row in readFixture("gomezLarvae.csv")}
  return {
    "stirretCount1": (stirretTreatments, 15, stirretCells("count1"), None, None),
    "stirretCount2": (stirretTreatments, 15, stirretCells("count2"), None, None),
    "yatesOats": (
      ["GoldenRain", "Marvellous", "Victory"], 6,
      {(row["treatment"], int(row["block"])): float(row["yield"]) for row in readFixture("yatesOatsVariety.csv")},
      None, None,
    ),
    "clewerWheat": (
      ["V1", "V2", "V3", "V4"], 3,
      {(row["gen"], int(row["block"][1:])): float(row["yield"]) for row in readFixture("clewerWheat.csv")},
      None, None,
    ),
    "gomezSeedRate": (
      ["R25", "R50", "R75", "R100", "R125", "R150"], 4,
      {(f"R{row['rate']}", int(row["rep"][1:])): float(row["yield"]) for row in readFixture("gomezSeedRate.csv")},
      None, None,
    ),
    "gomezLarvae": (
      [f"T{index}" for index in range(1, 10)], 4, larvae,
      {"measurementKind": "count", "transform": "log10", "transformOffset": 1.0},
      lambda value: math.log10(value + 1.0),
    ),
  }


def patternFor(name, treatments, blockCount):
  """M1 to M3 on any table: one cell; scattered cells in different blocks; the first treatment's last block."""
  if name == "M1":
    return {(treatments[1], 2)}
  if name == "M2":
    return {(treatments[0], 1), (treatments[1], 3), (treatments[-1], 2)}
  return {(treatments[0], blockCount)}


def frameOf(treatments, cells, missing, transform):
  return pandas.DataFrame([
    {"treatment": treatment, "block": block, "y": value if transform is None else transform(value)}
    for (treatment, block), value in cells.items() if (treatment, block) not in missing
  ])


def meanContrast(fit, treatments, blocks, treatment):
  """The combination of statsmodels' coefficients that is one treatment's mean over every block alike."""
  contrast = pandas.Series(0.0, index=fit.params.index)
  contrast["Intercept"] = 1.0
  for name in contrast.index:
    if name.startswith("C(block"):
      contrast[name] = 1.0 / len(blocks)
  name = f"C(treatment, levels=treatments)[T.{treatment}]"
  if name in contrast.index:
    contrast[name] = 1.0
  return contrast.to_numpy()


def assertMeansMatchStatsmodels(result, fit, treatments, blocks):
  """Adjusted means, their standard errors, and every pairwise difference with its standard error."""
  contrasts = [meanContrast(fit, treatments, blocks, treatment) for treatment in treatments]
  assert [mean.treatmentCode for mean in result.treatmentMeans] == treatments
  for index, mean in enumerate(result.treatmentMeans):
    oracle = fit.t_test(contrasts[index])
    assert mean.mean == pytest.approx(float(oracle.effect[0]), rel=1e-9)
    assert meanStandardError(result, index) == pytest.approx(float(oracle.sd[0][0]), rel=1e-9)
  for first, second in itertools.combinations(range(len(treatments)), 2):
    oracle = fit.t_test(contrasts[first] - contrasts[second])
    assert result.treatmentMeans[first].mean - result.treatmentMeans[second].mean == pytest.approx(
      float(oracle.effect[0]), rel=1e-9, abs=1e-9)
    assert differenceStandardError(result, first, second) == pytest.approx(float(oracle.sd[0][0]), rel=1e-9)
  grandMean = sum(float(fit.t_test(contrast).effect[0]) for contrast in contrasts) / len(contrasts)
  assert result.grandMean == pytest.approx(grandMean, rel=1e-9)
  assert result.coefficientOfVariation == pytest.approx(100.0 * math.sqrt(fit.mse_resid) / abs(grandMean), rel=1e-9)


def assertBlockAnalysisMatchesStatsmodels(result, frame, treatments, blockCount, missing, cellsOnScale):
  """A missing-plot RCBD result against statsmodels' fit of blocks and treatments to the plots present."""
  blocks = list(range(1, blockCount + 1))
  fit = statsmodelsFormula.ols("y ~ C(block) + C(treatment, levels=treatments)", data=frame).fit()
  # Type III needs sum-to-zero coding in statsmodels; the model is the same one.
  typeIII = statsmodelsApi.stats.anova_lm(
    statsmodelsFormula.ols("y ~ C(block, Sum) + C(treatment, Sum)", data=frame).fit(), typ=3)
  rows = {row.source: row for row in result.table}
  errorDf = int(round(fit.df_resid))
  assert rows["error"].degreesOfFreedom == errorDf == len(frame) - (blockCount + len(treatments) - 1)
  assert rows["error"].sumOfSquares == pytest.approx(fit.ssr, rel=1e-9)
  assert result.errorMeanSquare == pytest.approx(fit.mse_resid, rel=1e-9)
  assert rows["treatment"].degreesOfFreedom == len(treatments) - 1
  assert rows["treatment"].sumOfSquares == pytest.approx(typeIII.loc["C(treatment, Sum)", "sum_sq"], rel=1e-9)
  assert rows["treatment"].fStatistic == pytest.approx(typeIII.loc["C(treatment, Sum)", "F"], rel=1e-9)
  assert rows["treatment"].pValue == pytest.approx(typeIII.loc["C(treatment, Sum)", "PR(>F)"], rel=1e-6, abs=1e-12)
  if result.missingPlotPolicy is MissingPlotPolicy.leastSquares:
    assert result.sumsOfSquares is SumsOfSquares.typeIII
    assert rows["block"].sumOfSquares == pytest.approx(typeIII.loc["C(block, Sum)", "sum_sq"], rel=1e-9)
    assert rows["block"].fStatistic == pytest.approx(typeIII.loc["C(block, Sum)", "F"], rel=1e-9)
    assert rows["block"].pValue == pytest.approx(typeIII.loc["C(block, Sum)", "PR(>F)"], rel=1e-6, abs=1e-12)
    assert rows["total"].sumOfSquares == pytest.approx(fit.centered_tss, rel=1e-9)
    assert rows["total"].degreesOfFreedom == len(frame) - 1
    assert all(cell.handling is MissingHandling.leftOut and cell.estimate is None for cell in result.missingCells)
  else:
    # The estimates are the fit's predictions for the missing plots, and the block line is the completed table's.
    assert result.sumsOfSquares is SumsOfSquares.completedTable
    completed = dict(cellsOnScale)
    for cell in result.missingCells:
      predicted = float(fit.predict(pandas.DataFrame({"treatment": [cell.treatmentCode], "block": [cell.block]})).iloc[0])
      assert cell.handling is MissingHandling.estimated
      assert cell.estimate == pytest.approx(predicted, rel=1e-9)
      completed[(cell.treatmentCode, cell.block)] = predicted
    table = numpy.array([[completed[(treatment, block)] for treatment in treatments] for block in blocks])
    blockSum = len(treatments) * float(((table.mean(axis=1) - table.mean()) ** 2).sum())
    treatmentSum = blockCount * float(((table.mean(axis=0) - table.mean()) ** 2).sum())
    assert rows["block"].sumOfSquares == pytest.approx(blockSum, rel=1e-9)
    assert rows["block"].fStatistic is None and rows["block"].pValue is None
    assert result.estimation.treatmentBias == pytest.approx(
      treatmentSum - typeIII.loc["C(treatment, Sum)", "sum_sq"], rel=1e-7, abs=1e-9 * treatmentSum)
    assert result.estimation.treatmentBias > 0.0
    assert rows["total"].degreesOfFreedom == blockCount * len(treatments) - 1 - len(missing)
    assert rows["total"].sumOfSquares == pytest.approx(
      rows["block"].sumOfSquares + rows["treatment"].sumOfSquares + rows["error"].sumOfSquares, rel=1e-12)
    assert result.estimation.tolerance == yatesTolerance
  assert sorted((cell.treatmentCode, cell.block) for cell in result.missingCells) == sorted(missing)
  assertMeansMatchStatsmodels(result, fit, treatments, blocks)
  present = frame.groupby("treatment").size()
  assert {mean.treatmentCode: mean.observationCount for mean in result.treatmentMeans} == present.to_dict()


# ---- the matrix of decision 0003 -----------------------------------------------

@pytest.mark.parametrize("pattern", ["M1", "M2", "M3"])
def testRefuseRejectsEveryPatternAndNamesItsPlots(pattern):
  package, layout, observations = stirret(matrix[pattern])
  with pytest.raises(AnalysisError) as raised:
    analyzeRcbd("Y", package, layout, observations, MissingPlotPolicy.refuse)
  message = str(raised.value)
  assert "RCBD ANOVA requires a complete table while the setting analysis.missingPlots is 'refuse'" in message
  for treatment, block in matrix[pattern]:
    assert f"plot {plotOf(layout, treatment, block)} (treatment {treatment}, block {block})" in message
  assert message.count("plot ") == len(matrix[pattern])


def testRefuseIsTheDefault():
  package, layout, observations = stirret(matrix["M1"])
  with pytest.raises(AnalysisError, match="analysis.missingPlots is 'refuse'"):
    analyzeRcbd("Y", package, layout, observations)


@pytest.mark.parametrize("policy", handled)
@pytest.mark.parametrize("pattern", ["M1", "M2", "M3"])
@pytest.mark.parametrize("column", ["count1", "count2"])
def testMatrixPatternsAreAnalysedAgainstStatsmodels(column, pattern, policy):
  missing = matrix[pattern]
  cells = stirretCells(column)
  package, layout, observations = stirret(missing, column)
  result = analyzeRcbd("Y", package, layout, observations, policy)
  assert result.missingPlotPolicy is policy
  assert [cell.plotNumber for cell in result.missingCells] == sorted(
    (plotOf(layout, treatment, block) for treatment, block in missing),
    key=lambda number: next((p.block, stirretTreatments.index(p.treatmentCode)) for p in layout.plots if p.plotNumber == number),
  )
  assertBlockAnalysisMatchesStatsmodels(
    result, frameOf(stirretTreatments, cells, missing, None), stirretTreatments, 15, missing, cells,
  )


def testOneMissingPlotIsAdjustedForTheBlockItMissed():
  """M1: the adjusted mean is not the mean of the fourteen plots left; it allows for the block that is gone."""
  cells = stirretCells()
  package, layout, observations = stirret(matrix["M1"])
  result = analyzeRcbd("Y", package, layout, observations, MissingPlotPolicy.leastSquares)
  means = {mean.treatmentCode: mean for mean in result.treatmentMeans}
  blockTotal = sum(cells[(treatment, 7)] for treatment in stirretTreatments if treatment != "Late")
  treatmentTotal = sum(cells[("Late", block)] for block in range(1, 16) if block != 7)
  grandTotal = sum(cells.values()) - cells[("Late", 7)]
  fitted = (15 * blockTotal + 4 * treatmentTotal - grandTotal) / (14 * 3)
  assert means["Late"].observationCount == 14
  assert means["Late"].mean == pytest.approx((treatmentTotal + fitted) / 15, rel=1e-12)
  assert means["Late"].mean != pytest.approx(treatmentTotal / 14, rel=1e-4)
  assert means["None"].mean == pytest.approx(sum(cells[("None", block)] for block in range(1, 16)) / 15, rel=1e-12)
  # sqrt(s^2 (2/r + t / (r (r - 1) (t - 1)))) for a pair with the short treatment, sqrt(2 s^2 / r) for any other.
  late, none, early = (stirretTreatments.index(code) for code in ("Late", "None", "Early"))
  assert differenceStandardError(result, late, none) == pytest.approx(
    math.sqrt(result.errorMeanSquare * (2 / 15 + 4 / (15 * 14 * 3))), rel=1e-12)
  assert differenceStandardError(result, none, early) == pytest.approx(math.sqrt(2 * result.errorMeanSquare / 15), rel=1e-12)
  assert meanStandardError(result, late) > meanStandardError(result, none)


@pytest.mark.parametrize("policy", handled)
@pytest.mark.parametrize("missing, reason, named", [
  (absentTreatment, "treatment 'Late' has no value in any block", "so its mean cannot be estimated"),
  (absentBlock, "block 6 has no value on any plot", "means adjusted to all 15 blocks cannot be estimated"),
  (disconnected, "the design is disconnected: the plots with values fall into 2 sets",
   "treatments ['None', 'Early'] in blocks [1, 2, 3, 4, 5, 6, 7]; treatments ['Late', 'Both'] in blocks "
   "[8, 9, 10, 11, 12, 13, 14, 15]"),
  (noErrorLeft, "no degrees of freedom are left for error", "18 plots have values, and the blocks and treatments take 18"),
])
def testNonEstimablePatternsAreRefusedWithTheirReason(missing, reason, named, policy):
  """M4: never a number. Each cause is named with the treatments, blocks or plots it concerns."""
  package, layout, observations = stirret(missing)
  with pytest.raises(AnalysisError) as raised:
    analyzeRcbd("Y", package, layout, observations, policy)
  message = str(raised.value)
  assert message.startswith("assessment 'Y' is not estimable with its missing plots: ")
  assert reason in message and named in message


def testAnAbsentTreatmentAndAnAbsentBlockAreNamedByTheirPlots():
  package, layout, observations = stirret(absentTreatment | absentBlock)
  with pytest.raises(AnalysisError) as raised:
    analyzeRcbd("Y", package, layout, observations, MissingPlotPolicy.leastSquares)
  message = str(raised.value)
  latePlots = sorted(plotOf(layout, "Late", block) for block in range(1, 16))
  blockPlots = sorted(plotOf(layout, treatment, 6) for treatment in stirretTreatments)
  assert f"treatment 'Late' has no value in any block (plots {latePlots})" in message
  assert f"block 6 has no value on any plot (plots {blockPlots})" in message


@pytest.mark.parametrize("missing", [absentTreatment, absentBlock, disconnected, noErrorLeft])
def testNonEstimablePatternsRejectUnderRefuseToo(missing):
  package, layout, observations = stirret(missing)
  with pytest.raises(AnalysisError, match="requires a complete table while the setting analysis.missingPlots is 'refuse'"):
    analyzeRcbd("Y", package, layout, observations, MissingPlotPolicy.refuse)


@pytest.mark.parametrize("policy", list(MissingPlotPolicy))
def testCompleteTableIsAnalysedAsBeforeUnderEveryPolicy(policy):
  """M5: no plot for the policy to act on; the classical table, with the policy recorded."""
  package, layout, observations = stirret()
  result = analyzeRcbd("Y", package, layout, observations, policy)
  reference = analyzeRcbd("Y", package, layout, observations)
  assert result.missingPlotPolicy is policy and result.missingCells == [] and result.estimation is None
  assert result.sumsOfSquares is SumsOfSquares.balanced
  assert result.model_dump(exclude={"missingPlotPolicy"}) == reference.model_dump(exclude={"missingPlotPolicy"})
  rows = {row.source: row for row in result.table}
  assert rows["treatment"].sumOfSquares == pytest.approx(5048.85, abs=0.005)
  assert rows["error"].degreesOfFreedom == 42
  assert result.meanCovariance[0][0] == 1 / 15 and result.meanCovariance[0][1] == 0.0


# ---- both methods against statsmodels on the registry's datasets ---------------------

@pytest.mark.parametrize("policy", handled)
@pytest.mark.parametrize("pattern", ["M1", "M2", "M3"])
@pytest.mark.parametrize("dataset", sorted(registryDatasets()))
def testRegistryDatasetsMatchStatsmodels(dataset, pattern, policy):
  treatments, blockCount, cells, rating, transform = registryDatasets()[dataset]
  missing = patternFor(pattern, treatments, blockCount)
  package, layout, observations = blockTrial(treatments, blockCount, cells, missing, rating)
  result = analyzeRcbd("Y", package, layout, observations, policy)
  onScale = {cell: value if transform is None else transform(value) for cell, value in cells.items()}
  assertBlockAnalysisMatchesStatsmodels(
    result, frameOf(treatments, cells, missing, transform), treatments, blockCount, missing, onScale,
  )


def generatedTable(seed):
  """A table of random size with random effects and a random set of cells removed, still estimable."""
  generator = numpy.random.default_rng(seed)
  treatmentCount, blockCount = int(generator.integers(3, 9)), int(generator.integers(3, 7))
  treatments = [f"T{index}" for index in range(1, treatmentCount + 1)]
  effects = generator.normal(0.0, 6.0, treatmentCount)
  blockEffects = generator.normal(0.0, 4.0, blockCount)
  cells = {
    (treatments[t], b + 1): float(round(50.0 + effects[t] + blockEffects[b] + generator.normal(0.0, 2.5), 2))
    for t in range(treatmentCount) for b in range(blockCount)
  }
  spare = (treatmentCount - 1) * (blockCount - 1) - 1
  wanted = int(generator.integers(1, min(spare, 6) + 1))
  missing = set()
  for index in generator.permutation(len(cells)):
    cell = list(cells)[index]
    trial = missing | {cell}
    frame = frameOf(treatments, cells, trial, None)
    exog = statsmodelsFormula.ols("y ~ C(block) + C(treatment)", data=frame).fit().model.exog
    connected = numpy.linalg.matrix_rank(exog) == blockCount + treatmentCount - 1
    if connected and frame["treatment"].nunique() == treatmentCount and frame["block"].nunique() == blockCount:
      missing = trial
    if len(missing) == wanted:
      break
  return treatments, blockCount, cells, missing


@pytest.mark.parametrize("policy", handled)
@pytest.mark.parametrize("seed", range(1, 13))
def testGeneratedUnbalancedTablesMatchStatsmodels(seed, policy):
  treatments, blockCount, cells, missing = generatedTable(seed)
  assert missing
  package, layout, observations = blockTrial(treatments, blockCount, cells, missing)
  result = analyzeRcbd("Y", package, layout, observations, policy)
  assertBlockAnalysisMatchesStatsmodels(
    result, frameOf(treatments, cells, missing, None), treatments, blockCount, missing, cells,
  )


@pytest.mark.parametrize("seed", range(1, 13))
def testTheTwoMethodsGiveTheSameTestAndTheSameMeans(seed):
  """Yates' completed table and the least-squares fit are two routes to one treatment test and one set of means."""
  treatments, blockCount, cells, missing = generatedTable(seed)
  package, layout, observations = blockTrial(treatments, blockCount, cells, missing)
  fitted = analyzeRcbd("Y", package, layout, observations, MissingPlotPolicy.leastSquares)
  estimated = analyzeRcbd("Y", package, layout, observations, MissingPlotPolicy.estimate)
  rows = {policy: {row.source: row for row in result.table} for policy, result in (("fit", fitted), ("yates", estimated))}
  assert rows["yates"]["treatment"].sumOfSquares == pytest.approx(rows["fit"]["treatment"].sumOfSquares, rel=1e-9)
  assert rows["yates"]["error"].sumOfSquares == pytest.approx(rows["fit"]["error"].sumOfSquares, rel=1e-9)
  assert rows["yates"]["error"].degreesOfFreedom == rows["fit"]["error"].degreesOfFreedom
  assert [mean.mean for mean in estimated.treatmentMeans] == pytest.approx([mean.mean for mean in fitted.treatmentMeans], rel=1e-9)
  assert numpy.array(estimated.meanCovariance) == pytest.approx(numpy.array(fitted.meanCovariance), rel=1e-12, abs=1e-15)


def testTheEstimatesAreReproducible():
  """The same table gives the same estimates, cycle count included, whatever order its values arrive in."""
  treatments, blockCount, cells, missing = generatedTable(7)
  package, layout, observations = blockTrial(treatments, blockCount, cells, missing)
  first = analyzeRcbd("Y", package, layout, observations, MissingPlotPolicy.estimate)
  second = analyzeRcbd("Y", package, layout, list(reversed(observations)), MissingPlotPolicy.estimate)
  assert len(missing) > 1 and first.estimation.cycles > 1
  assert first.model_dump() == second.model_dump()


def testOneMissingPlotIsEstimatedInClosedForm():
  cells = stirretCells()
  package, layout, observations = stirret(matrix["M1"])
  result = analyzeRcbd("Y", package, layout, observations, MissingPlotPolicy.estimate)
  blockTotal = sum(cells[(treatment, 7)] for treatment in stirretTreatments if treatment != "Late")
  treatmentTotal = sum(cells[("Late", block)] for block in range(1, 16) if block != 7)
  grandTotal = sum(cells.values()) - cells[("Late", 7)]
  closedForm = (15 * blockTotal + 4 * treatmentTotal - grandTotal) / (14 * 3)
  assert result.estimation.cycles == 1
  assert result.missingCells[0].estimate == pytest.approx(closedForm, rel=1e-13)
  # Yates' correction for one missing plot, (B - (t - 1) X)^2 / (t (t - 1)), is the bias taken off.
  assert result.estimation.treatmentBias == pytest.approx((blockTotal - 3 * closedForm) ** 2 / 12, rel=1e-9)
  # The error and total give up one degree of freedom for the estimate.
  rows = {row.source: row for row in result.table}
  assert (rows["error"].degreesOfFreedom, rows["total"].degreesOfFreedom) == (41, 58)


# ---- the policy composes with the transform and with the untreated check ----------------

def testAValueOutsideTheTransformsDomainIsNotAMissingPlot():
  """A zero under a log is refused as a zero; only a plot without a recorded value is missing."""
  treatments, blockCount, cells, _, _ = registryDatasets()["gomezLarvae"]
  missing = {("T1", 1)}
  zero = next(cell for cell, value in cells.items() if value == 0.0)
  assert zero not in missing
  rating = {"measurementKind": "count", "transform": "log10"}
  for policy in MissingPlotPolicy:
    with pytest.raises(AnalysisError, match="log10 transform requires values > 0; offending values: 0"):
      analyzeRcbd("Y", *blockTrial(treatments, blockCount, cells, missing, rating), policy)


def testEstimatesAreOnTheAnalysedScale():
  """The closed form is worked on the transformed values of the plots present, not on the counts."""
  treatments, blockCount, cells, rating, transform = registryDatasets()["gomezLarvae"]
  missing = {("T3", 2)}
  result = analyzeRcbd("Y", *blockTrial(treatments, blockCount, cells, missing, rating), MissingPlotPolicy.estimate)

  def closedForm(values):
    blockTotal = sum(value for (treatment, block), value in values.items() if block == 2 and treatment != "T3")
    treatmentTotal = sum(value for (treatment, block), value in values.items() if treatment == "T3" and block != 2)
    grandTotal = sum(values.values()) - values[("T3", 2)]
    return (4 * blockTotal + 9 * treatmentTotal - grandTotal) / (3 * 8)

  onScale = {cell: transform(value) for cell, value in cells.items()}
  assert result.missingCells[0].estimate == pytest.approx(closedForm(onScale), rel=1e-12)
  assert result.missingCells[0].estimate != pytest.approx(transform(closedForm(cells)), rel=1e-3)
  assert result.transform.value == "log10" and result.transformOffset == 1.0


@pytest.mark.parametrize("policy", handled)
def testAnExcludedChecksPlotsAreNotMissingPlots(policy):
  """With the check left out (decision 0030) its plots are not wanted, so a gap there is not a missing plot."""
  cells = stirretCells()
  missing = {("None", 3), ("Early", 5)}
  package, layout, observations = stirret(
    missing, roles={"None": "untreatedControl"}, assessment={"untreatedCheck": "excluded"},
  )
  result = analyzeRcbd("Y", package, layout, observations, policy)
  kept = ["Early", "Late", "Both"]
  assert [(cell.treatmentCode, cell.block) for cell in result.missingCells] == [("Early", 5)]
  frame = frameOf(kept, {cell: value for cell, value in cells.items() if cell[0] != "None"}, {("Early", 5)}, None)
  assertBlockAnalysisMatchesStatsmodels(result, frame, kept, 15, {("Early", 5)}, cells)


def testAMissingCheckPlotIsAMissingPlotWhenTheCheckIsAnalysed():
  package, layout, observations = stirret({("None", 3)}, roles={"None": "untreatedControl"})
  result = analyzeRcbd("Y", package, layout, observations, MissingPlotPolicy.leastSquares)
  assert [(cell.treatmentCode, cell.block) for cell in result.missingCells] == [("None", 3)]


# ---- designs the methods do not cover refuse under every policy -------------------------

covered = "only for a single-factor RCBD and a completely randomized design, without untreated checks beside the plots"


@pytest.mark.parametrize("policy", list(MissingPlotPolicy))
def testATwoFactorRcbdRefusesAMissingPlot(policy):
  from testFactorial import gomezInputs
  package, layout, observations = gomezInputs()
  with pytest.raises(AnalysisError) as raised:
    analyzeRcbd("Y", package, layout, observations[1:], policy)
  assert "a two-factor RCBD requires a complete table under every policy" in str(raised.value)
  assert covered in str(raised.value) and f"plot {observations[0].plotNumber} (treatment" in str(raised.value)
  with pytest.raises(AnalysisError, match="this analysis requires a complete table under every policy"):
    analyzeFactorialRcbd("Y", package, layout, observations[1:])


def testASplitPlotRefusesAMissingPlot():
  from testSplitPlot import gomezInputs
  package, layout, observations = gomezInputs()
  with pytest.raises(AnalysisError) as raised:
    analyzeSplitPlot("Y", package, layout, observations[1:])
  assert "this analysis requires a complete table under every policy" in str(raised.value)
  assert covered in str(raised.value) and f"plot {observations[0].plotNumber} (treatment" in str(raised.value)


@pytest.mark.parametrize("policy", list(MissingPlotPolicy))
def testATrialWithChecksBesideItsPlotsRefusesAMissingPlot(policy):
  from testChecks import trial
  package, layout, observations = trial("paired", {"method": "abbott"})
  treated = layout.plots[0].plotNumber
  short = [o for o in observations if (o.plotNumber, o.assessmentCode) != (treated, "D7")]
  with pytest.raises(AnalysisError) as raised:
    analyzeRcbd("D7", package, layout, short, policy)
  assert "a trial with untreated checks beside its plots requires a complete table under every policy" in str(raised.value)
  assert covered in str(raised.value)
  with pytest.raises(AnalysisError, match=rf"comparing with the checks needs every plot and every check plot under every policy.*Missing: \[{treated}\]"):
    analyzeEfficacy("D7", package, layout, short, policy)


@pytest.mark.parametrize("policy", list(MissingPlotPolicy))
def testAnAssessmentWithSubsamplesRefusesAPlotWithoutAValue(policy):
  from testSubsamples import trial
  package, layout, _ = trial()
  plot = layout.plots[0].plotNumber
  _, _, empty = trial(drop={(plot, 1), (plot, 2), (plot, 3)})
  with pytest.raises(AnalysisError) as raised:
    analyzeRcbd("SEV", package, layout, empty, policy)
  assert "an assessment that takes subsamples requires a complete table under every policy" in str(raised.value)
  assert f"Missing: plot {plot} (treatment" in str(raised.value)


# ---- the completely randomized design -------------------------------------------------

def crdTrial(sizes, seed=4, replications=4, check=None):
  """A CRD whose treatments have `sizes` values each of `replications` plots; the rest are missing."""
  treatments = [f"T{index}" for index in range(1, len(sizes) + 1)]
  package = TrialPackage.model_validate({
    "schemaVersion": schemaVersion,
    "trial": {"trialCode": "MISSING-CRD", "title": "Pots", "crop": "Wheat", "season": "2026", "site": "Glasshouse 2",
              "objective": "Unequal replication"},
    "treatments": [
      {"treatmentCode": code, "name": code} | ({"role": "untreatedControl"} if code == check else {})
      for code in treatments
    ],
    "design": {"designType": "crd", "replications": replications, "randomizationMethod": "sha256FisherYates1",
               "randomizationSeed": 9},
    "ratings": [{"ratingCode": "Y", "name": "Height", "dataType": "numeric"}],
    "assessments": [{"assessmentCode": "Y", "ratingCode": "Y"}],
  })
  layout = generateLayout(package)
  generator = numpy.random.default_rng(seed)
  observations, rows, missing = [], [], []
  for index, code in enumerate(treatments):
    plots = sorted(plot.plotNumber for plot in layout.plots if plot.treatmentCode == code)
    for position, plotNumber in enumerate(plots):
      if position >= sizes[index]:
        missing.append(plotNumber)
        continue
      value = float(round(20.0 + 3.0 * index + generator.normal(0.0, 2.0), 2))
      observations.append(Observation(plotNumber=plotNumber, assessmentCode="Y", value=value))
      rows.append({"treatment": code, "y": value})
  return package, layout, observations, pandas.DataFrame(rows), treatments, missing


@pytest.mark.parametrize("sizes", [(4, 3, 4, 2), (3, 3, 3, 3, 4), (2, 4, 4), (4, 4, 1, 4, 3, 4)])
def testCrdWithUnequalReplicationMatchesStatsmodels(sizes):
  package, layout, observations, frame, treatments, missing = crdTrial(sizes)
  result = analyzeCrd("Y", package, layout, observations, MissingPlotPolicy.leastSquares)
  fit = statsmodelsFormula.ols("y ~ C(treatment, levels=treatments)", data=frame).fit()
  table = statsmodelsApi.stats.anova_lm(fit, typ=1)
  rows = {row.source: row for row in result.table}
  assert list(rows) == ["treatment", "error", "total"]
  assert rows["treatment"].sumOfSquares == pytest.approx(table.loc["C(treatment, levels=treatments)", "sum_sq"], rel=1e-9)
  assert rows["treatment"].fStatistic == pytest.approx(table.loc["C(treatment, levels=treatments)", "F"], rel=1e-9)
  assert rows["treatment"].pValue == pytest.approx(table.loc["C(treatment, levels=treatments)", "PR(>F)"], rel=1e-6, abs=1e-12)
  assert rows["error"].sumOfSquares == pytest.approx(fit.ssr, rel=1e-9)
  assert rows["error"].degreesOfFreedom == sum(sizes) - len(sizes)
  assert rows["total"].sumOfSquares == pytest.approx(fit.centered_tss, rel=1e-9)
  assert result.sumsOfSquares is SumsOfSquares.typeIII and result.missingPlotPolicy is MissingPlotPolicy.leastSquares
  assert [cell.plotNumber for cell in result.missingCells] == missing
  assert all(cell.handling is MissingHandling.leftOut for cell in result.missingCells)
  assertMeansMatchStatsmodels(result, fit, treatments, [])
  # Without blocks an adjusted mean is the mean of the treatment's own plots, on its own number of them.
  for index, mean in enumerate(result.treatmentMeans):
    own = frame.loc[frame["treatment"] == mean.treatmentCode, "y"]
    assert mean.mean == pytest.approx(own.mean(), rel=1e-12) and mean.observationCount == sizes[index]
    assert result.meanCovariance[index][index] == pytest.approx(1 / sizes[index], rel=1e-12)
  assert result.grandMean == pytest.approx(frame.groupby("treatment")["y"].mean().mean(), rel=1e-12)


def testCrdRefusesByPolicy():
  package, layout, observations, _, _, missing = crdTrial((4, 3, 4, 2))
  with pytest.raises(AnalysisError) as raised:
    analyzeCrd("Y", package, layout, observations)
  assert "the ANOVA requires every plot while the setting analysis.missingPlots is 'refuse'" in str(raised.value)
  assert all(f"plot {number} (treatment " in str(raised.value) for number in missing)
  with pytest.raises(AnalysisError, match="Yates' estimates complete a table of blocks and treatments, which a "
                                          "completely randomized design does not have.*'leastSquares' analyses"):
    analyzeCrd("Y", package, layout, observations, MissingPlotPolicy.estimate)


def testCrdNonEstimablePatternsAreRefusedWithTheirReason():
  package, layout, observations, _, _, missing = crdTrial((4, 0, 4, 2))
  with pytest.raises(AnalysisError) as raised:
    analyzeCrd("Y", package, layout, observations, MissingPlotPolicy.leastSquares)
  assert "is not estimable with its missing plots: treatment 'T2' has no value on any plot" in str(raised.value)
  assert str(sorted(missing[:4])) in str(raised.value)
  package, layout, observations, _, _, _ = crdTrial((1, 1, 1))
  with pytest.raises(AnalysisError, match="no degrees of freedom are left for error: 3 plots have values, and the "
                                          "treatments take 3"):
    analyzeCrd("Y", package, layout, observations, MissingPlotPolicy.leastSquares)


def testCompleteCrdIsAnalysedAsBeforeUnderEveryPolicy():
  package, layout, observations, _, _, _ = crdTrial((4, 4, 4))
  reference = analyzeCrd("Y", package, layout, observations)
  for policy in MissingPlotPolicy:
    result = analyzeCrd("Y", package, layout, observations, policy)
    assert result.missingPlotPolicy is policy and result.sumsOfSquares is SumsOfSquares.balanced
    assert result.model_dump(exclude={"missingPlotPolicy"}) == reference.model_dump(exclude={"missingPlotPolicy"})


# ---- a fit with no residual variation is refused, not reported -----------------------

def testAnExactlyAdditiveTableWithAMissingPlotHasNoError():
  treatments, blocks = ["A", "B", "C"], 4
  cells = {(treatment, block): 10.0 * block + 3.0 * index for index, treatment in enumerate(treatments) for block in range(1, blocks + 1)}
  for policy in handled:
    with pytest.raises(AnalysisError, match="error mean square is zero"):
      analyzeRcbd("Y", *blockTrial(treatments, blocks, cells, {("B", 2)}), policy)


# ---- the assumption checks run on the plots present -------------------------------------

def testAssumptionChecksUseThePlotsPresent():
  from scipy import stats
  missing = matrix["M2"]
  cells = stirretCells()
  package, layout, observations = stirret(missing)
  frame = frameOf(stirretTreatments, cells, missing, None)
  with pytest.raises(AnalysisError, match="analysis.missingPlots is 'refuse'"):
    assessAssumptions("Y", package, layout, observations)
  for policy in handled:
    assumptions = assessAssumptions("Y", package, layout, observations, 0.05, policy)
    levene = stats.levene(*(frame.loc[frame["treatment"] == code, "y"] for code in stirretTreatments), center="median")
    assert assumptions.equalVariance.statistic == pytest.approx(levene.statistic, rel=1e-9)
    assert assumptions.equalVariance.pValue == pytest.approx(levene.pvalue, rel=1e-6)
    assert assumptions.equalVariance.denominatorDegreesOfFreedom == len(frame) - 4
    fit = statsmodelsFormula.ols("y ~ C(block) + C(treatment)", data=frame).fit()
    shapiro = stats.shapiro(fit.resid.to_numpy())
    assert assumptions.normality.statistic == pytest.approx(shapiro.statistic, abs=1e-7)
    assert assumptions.normality.pValue == pytest.approx(shapiro.pvalue, abs=1e-6)
    # Tukey's one degree of freedom, as the regression on the squared fitted values that it is.
    frame["fittedSquared"] = fit.fittedvalues ** 2
    augmented = statsmodelsFormula.ols("y ~ C(block) + C(treatment) + fittedSquared", data=frame).fit()
    assert assumptions.nonAdditivity.statistic == pytest.approx(float(augmented.tvalues["fittedSquared"]) ** 2, rel=1e-7)
    assert assumptions.nonAdditivity.pValue == pytest.approx(float(augmented.pvalues["fittedSquared"]), rel=1e-6)
    assert assumptions.nonAdditivity.denominatorDegreesOfFreedom == int(fit.df_resid) - 1


def testCrdAssumptionChecksUseThePlotsPresent():
  from scipy import stats
  package, layout, observations, frame, treatments, _ = crdTrial((4, 3, 4, 2))
  assumptions = assessAssumptions("Y", package, layout, observations, 0.05, MissingPlotPolicy.leastSquares)
  # A treatment on two plots still has a median to deviate from, so the test runs on unequal groups.
  levene = stats.levene(*(frame.loc[frame["treatment"] == code, "y"] for code in treatments), center="median")
  assert assumptions.equalVariance.statistic == pytest.approx(levene.statistic, rel=1e-9)
  residuals = frame["y"] - frame.groupby("treatment")["y"].transform("mean")
  assert assumptions.normality.statistic == pytest.approx(stats.shapiro(residuals.to_numpy()).statistic, abs=1e-7)
  assert assumptions.nonAdditivity is None


# ---- separation on each pair's own standard error ---------------------------------------

def testLsdUsesEachPairsOwnStandardError():
  from scipy import stats
  missing = matrix["M2"]
  package, layout, observations = stirret(missing)
  result = analyzeRcbd("Y", package, layout, observations, MissingPlotPolicy.leastSquares)
  separation = separateMeans(result, meanComparison=MeanComparison.lsd)
  frame = frameOf(stirretTreatments, stirretCells(), missing, None)
  treatments = stirretTreatments
  fit = statsmodelsFormula.ols("y ~ C(block) + C(treatment, levels=treatments)", data=frame).fit()
  contrasts = {code: meanContrast(fit, treatments, list(range(1, 16)), code) for code in treatments}
  critical = stats.t.ppf(0.975, fit.df_resid)
  assert separation.criticalValue == pytest.approx(critical, rel=1e-9)
  assert separation.criticalDifference is None and separation.standardError is None
  assert len(separation.comparisons) == 6
  for pair in separation.comparisons:
    oracle = fit.t_test(contrasts[pair.firstTreatmentCode] - contrasts[pair.secondTreatmentCode])
    assert pair.difference == pytest.approx(float(oracle.effect[0]), rel=1e-9) and pair.difference >= 0.0
    assert pair.standardError == pytest.approx(float(oracle.sd[0][0]), rel=1e-9)
    assert pair.criticalDifference == pytest.approx(critical * float(oracle.sd[0][0]), rel=1e-9)
    assert pair.significant == (float(numpy.ravel(oracle.pvalue)[0]) < 0.05)
  # Early lacks two plots and the others one each, so the pairs do not share one standard error.
  assert len({round(pair.standardError, 9) for pair in separation.comparisons}) > 1
  letters = {group.treatmentCode: set(group.group) for group in separation.groups}
  for pair in separation.comparisons:
    assert bool(letters[pair.firstTreatmentCode] & letters[pair.secondTreatmentCode]) == (not pair.significant)
  assert [group.treatmentCode for group in separation.groups] == sorted(
    treatments, key=lambda code: -next(m.mean for m in result.treatmentMeans if m.treatmentCode == code))


def testProtectedLsdDeclaresNoPairWhenFIsNotSignificant():
  treatments, blockCount, cells, _, _ = registryDatasets()["yatesOats"]
  result = analyzeRcbd("Y", *blockTrial(treatments, blockCount, cells, {("Victory", 2)}), MissingPlotPolicy.leastSquares)
  separation = separateMeans(result)
  assert separation.treatmentSignificant is False
  assert {group.group for group in separation.groups} == {"a"}
  assert not any(pair.significant for pair in separation.comparisons)
  assert separation.methodKey == "report.method.fisherProtectedLSD"


@pytest.mark.parametrize("sizes", [(4, 3, 4, 2), (4, 4, 1, 4, 3, 4)])
def testTukeyKramerMatchesStatsmodelsPairByPair(sizes):
  multicomp = pytest.importorskip("statsmodels.stats.multicomp")
  package, layout, observations, frame, treatments, _ = crdTrial(sizes, seed=8)
  result = analyzeCrd("Y", package, layout, observations, MissingPlotPolicy.leastSquares)
  separation = separateMeans(result, meanComparison=MeanComparison.tukeyHSD)
  assert separation.methodKey == "report.method.tukeyKramer" and separation.criticalDifference is None
  tukey = multicomp.pairwise_tukeyhsd(frame["y"], frame["treatment"])
  oracle = {}
  for row, (low, high) in zip(tukey.summary().data[1:], tukey.confint):
    oracle[frozenset((row[0], row[1]))] = (abs(float(tukey.meandiffs[len(oracle)])), (high - low) / 2.0, bool(row[-1]))
  assert len(separation.comparisons) == len(oracle) == len(sizes) * (len(sizes) - 1) // 2
  for pair in separation.comparisons:
    difference, halfWidth, reject = oracle[frozenset((pair.firstTreatmentCode, pair.secondTreatmentCode))]
    assert pair.difference == pytest.approx(difference, rel=1e-9)
    assert pair.criticalDifference == pytest.approx(halfWidth, rel=1e-6)
    assert pair.significant == reject
  letters = {group.treatmentCode: set(group.group) for group in separation.groups}
  for pair in separation.comparisons:
    assert bool(letters[pair.firstTreatmentCode] & letters[pair.secondTreatmentCode]) == (not pair.significant)


def testEquallyThinnedTreatmentsKeepOneCriticalDifference():
  """Every treatment short of one plot is equal replication again: one LSD, and Tukey's test under its own name."""
  package, layout, observations, _, _, _ = crdTrial((3, 3, 3, 3))
  result = analyzeCrd("Y", package, layout, observations, MissingPlotPolicy.leastSquares)
  separation = separateMeans(result, meanComparison=MeanComparison.tukeyHSD)
  assert separation.methodKey == "report.method.tukeyHSD"
  assert separation.criticalDifference == pytest.approx(
    separation.criticalValue * math.sqrt(2 * result.errorMeanSquare / 3), rel=1e-12)
  assert separation.standardError == pytest.approx(math.sqrt(result.errorMeanSquare / 3), rel=1e-12)
