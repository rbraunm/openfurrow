# SPDX-License-Identifier: Apache-2.0
"""Two-factor treatments in randomized complete blocks (decision 0025).

Pinned against Gomez and Gomez (1984), section 3.3: the rice variety-by-nitrogen trial in
their Table 3.3 (fixture `gomezFactorial.csv`), analysed in Table 3.4 and the steps that
follow it, and cross-checked against statsmodels.
"""

import csv
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from openfurrow.analysis import MeanComparison
from openfurrow import ImportProfile, TrialPackage, Workspace, schemaVersion
from openfurrow.analysis import AnalysisError, analyzeFactorialRcbd, analyzeRcbd, separateFactorialMeans
from openfurrow.design import generateLayout
from openfurrow.reports import buildReport
from openfurrow.schema.observation import Observation
from storeHelpers import standardStudy

fixtures = Path(__file__).parent / "fixtures"
varieties = ["V1", "V2", "V3"]
nitrogen = ["N0", "N1", "N2", "N3", "N4"]


def packageDict():
  return {
    "schemaVersion": schemaVersion,
    "trial": {"trialCode": "GOMEZ-3.3", "title": "Rice variety by nitrogen", "crop": "Rice",
              "season": "1984", "site": "IRRI", "objective": "Gomez and Gomez Table 3.3"},
    "factors": [
      {"factorCode": "V", "name": "Variety", "levels": [{"levelCode": v, "name": v} for v in varieties]},
      {"factorCode": "N", "name": "Nitrogen", "levels": [{"levelCode": n, "name": n} for n in nitrogen]},
    ],
    "treatments": [{"treatmentCode": f"{v}{n}", "name": f"{v} {n}", "factorLevels": {"V": v, "N": n}}
                   for v in varieties for n in nitrogen],
    "design": {"designType": "rcbd", "replications": 4, "randomizationMethod": "sha256FisherYates1",
               "randomizationSeed": 33},
    "ratings": [{"ratingCode": "Y", "name": "Grain yield", "dataType": "numeric", "unit": "t/ha"}],
    "assessments": [{"assessmentCode": "Y", "ratingCode": "Y"}],
  }


def gomezInputs():
  package = TrialPackage.model_validate(packageDict())
  layout = generateLayout(package)
  with (fixtures / "gomezFactorial.csv").open(encoding="utf-8") as handle:
    yields = {(row["variety"] + row["nitrogen"], int(row["replication"])): float(row["yield"])
              for row in csv.DictReader(handle)}
  observations = [Observation(plotNumber=p.plotNumber, assessmentCode="Y", value=yields[(p.treatmentCode, p.block)])
                  for p in layout.plots]
  return package, layout, observations


def testMatchesGomezToItsPrintedPrecision():
  package, layout, observations = gomezInputs()
  result = analyzeFactorialRcbd("Y", package, layout, observations)
  rows = {row.source: row for row in result.table}
  # The book subtracts its correction factor rounded to 1,474.014 (exactly 1,474.0135), so each
  # sum of squares it works out as "sum of squares of totals less C.F." is short by the same
  # amount; the interaction and the error it then takes as differences of those printed figures.
  shortfall = 1474.014 - sum(o.value for o in observations) ** 2 / 60
  treatment = {row.source: row for row in analyzeRcbd("Y", package, layout, observations).table}["treatment"]
  book = {source: rows[source].sumOfSquares - shortfall for source in ("block", "firstFactor", "secondFactor", "total")}
  book["treatment"] = treatment.sumOfSquares - shortfall
  book = {source: round(value, 3) for source, value in book.items()}
  book["interaction"] = round(book["treatment"] - book["firstFactor"] - book["secondFactor"], 3)
  book["error"] = round(book["total"] - book["block"] - book["treatment"], 3)
  assert book == {"block": 2.599, "firstFactor": 1.052, "secondFactor": 41.234, "treatment": 44.578,
                  "interaction": 2.292, "error": 6.353, "total": 53.530}
  assert {source: row.degreesOfFreedom for source, row in rows.items()} == {
    "block": 3, "firstFactor": 2, "secondFactor": 4, "interaction": 8, "error": 42, "total": 59,
  }
  # The book divides mean squares cut to three decimals (0.526 / 0.151, 10.308 / 0.151,
  # 0.286 / 0.151); the error mean square alone, 0.15126 cut to 0.151, moves an F by 0.2 %.
  for source, printedF in (("firstFactor", 3.48), ("secondFactor", 68.26), ("interaction", 1.89)):
    assert abs(rows[source].fStatistic - printedF) / printedF < 0.005, source
  assert round(rows["block"].fStatistic, 2) == 5.73


def testTreatmentLineIsTheSumOfItsParts():
  """The plain RCBD treatment sum of squares (Table 3.4: 44.578) splits exactly into A, B and A x B."""
  package, layout, observations = gomezInputs()
  plain = {row.source: row for row in analyzeRcbd("Y", package, layout, observations).table}
  parts = {row.source: row for row in analyzeFactorialRcbd("Y", package, layout, observations).table}
  assert round(plain["treatment"].sumOfSquares, 3) == 44.578
  assert plain["treatment"].sumOfSquares == pytest.approx(
    parts["firstFactor"].sumOfSquares + parts["secondFactor"].sumOfSquares + parts["interaction"].sumOfSquares, rel=1e-12)
  assert plain["error"].sumOfSquares == pytest.approx(parts["error"].sumOfSquares, rel=1e-12)


def testAgreesWithStatsmodels():
  pandas = pytest.importorskip("pandas")
  formula = pytest.importorskip("statsmodels.formula.api")
  anova = pytest.importorskip("statsmodels.stats.anova")
  package, layout, observations = gomezInputs()
  levels = {t.treatmentCode: t.factorLevels for t in package.treatments}
  where = {p.plotNumber: (p.block, p.treatmentCode) for p in layout.plots}
  frame = pandas.DataFrame([{"rep": where[o.plotNumber][0], "V": levels[where[o.plotNumber][1]]["V"],
                             "N": levels[where[o.plotNumber][1]]["N"], "y": o.value} for o in observations])
  table = anova.anova_lm(formula.ols("y ~ C(rep) + C(V) * C(N)", data=frame).fit(), typ=1)
  rows = {row.source: row for row in analyzeFactorialRcbd("Y", package, layout, observations).table}
  for source, term in (("block", "C(rep)"), ("firstFactor", "C(V)"), ("secondFactor", "C(N)"),
                       ("interaction", "C(V):C(N)"), ("error", "Residual")):
    assert rows[source].sumOfSquares == pytest.approx(table.loc[term, "sum_sq"], rel=1e-9), source
  for source, term in (("firstFactor", "C(V)"), ("secondFactor", "C(N)"), ("interaction", "C(V):C(N)")):
    assert rows[source].pValue == pytest.approx(table.loc[term, "PR(>F)"], rel=1e-6), source


def testEachFactorIsSeparatedOnTheOneError():
  scipyStats = pytest.importorskip("scipy.stats")
  result = analyzeFactorialRcbd("Y", *gomezInputs())
  nitrogenSeparation = separateFactorialMeans(result, "N")
  assert nitrogenSeparation.criticalDifference == pytest.approx(
    scipyStats.t.ppf(0.975, 42) * math.sqrt(2 * result.errorMeanSquare / 12), rel=1e-9)
  # Nitrogen totals in the book: 41.800 for N0 up to 69.560 for N4, over 12 plots each.
  assert nitrogenSeparation.groups[0].levelCode == "N4" and nitrogenSeparation.groups[0].mean == pytest.approx(69.560 / 12)
  assert nitrogenSeparation.groups[-1].levelCode == "N0" and nitrogenSeparation.groups[-1].mean == pytest.approx(41.800 / 12)
  variety = separateFactorialMeans(result, "V")
  # F 3.48 on 2 and 42 df is significant at 5 % (P about 0.04).
  assert variety.factorSignificant
  with pytest.raises(AnalysisError, match="'X' is not a factor of this trial"):
    separateFactorialMeans(result, "X")


def testReportSplitsTheTreatmentLine():
  report = buildReport(*gomezInputs())
  assert "### Factorial analysis" in report
  assert (
    "| Block | 3 | 2.5998 | 0.8666 | 5.73 | 0.0022 |\n"
    "| Variety | 2 | 1.0528 | 0.5264 | 3.48 | 0.0400 |\n"
    "| Nitrogen | 4 | 41.2347 | 10.3087 | 68.15 | < 0.0001 |\n"
    "| Variety \u00d7 Nitrogen | 8 | 2.2907 | 0.2863 | 1.89 | 0.0867 |\n"
    "| Error | 42 | 6.3528 | 0.1513 | - | - |\n"
  ) in report
  assert "### Means of Variety" in report and "### Means of Nitrogen" in report
  assert "| V | N0 | N1 | N2 | N3 | N4 |" in report
  # The plain RCBD tables stay: the factorial lines are added, not substituted.
  assert "| Treatment | 14 |" in report


def testWorkspaceSeparatesAFactorOfAFactorialTrial(tmp_path, newStore):
  workspace = Workspace.create(newStore("trials"))
  package, _, observations = gomezInputs()
  workspace.addPackage(package, standardStudy(workspace))
  path = tmp_path / "y.csv"
  path.write_text("plotNumber,assessmentCode,value\n" + "".join(f"{o.plotNumber},Y,{o.value}\n" for o in observations),
                  encoding="utf-8")
  workspace.importObservations("GOMEZ-3.3", str(path), ImportProfile())
  assert workspace.separateFactorMeans("GOMEZ-3.3", "Y", "N").groups[0].levelCode == "N4"
  assert round(workspace.analyzeFactorial("GOMEZ-3.3", "Y").errorMeanSquare, 3) == 0.151


def rejected(data):
  with pytest.raises(ValidationError) as excInfo:
    TrialPackage.model_validate(data)
  return " | ".join(error["msg"] for error in excInfo.value.errors())


def testThreeFactorsAreRefusedForNow():
  data = packageDict()
  data["factors"].append({"factorCode": "S", "name": "Spacing", "levels": [{"levelCode": "a", "name": "a"},
                                                                         {"levelCode": "b", "name": "b"}]})
  assert "a factorial rcbd has two factors so far" in rejected(data)


def testMissingCombinationIsRefused():
  data = packageDict()
  data["treatments"] = data["treatments"][1:]
  assert "absent [('V1', 'N0')]" in rejected(data)


def testFactorLevelsWithoutFactorsAreRefused(validPackageDict):
  validPackageDict["treatments"][0]["factorLevels"] = {"N": "N0"}
  assert "a treatment states factor levels, but the trial declares no factors" in rejected(validPackageDict)


def testFactorialCombinationsUseTheOneError():
  scipyStats = pytest.importorskip("scipy.stats")
  from openfurrow.analysis import factorialInteractionComparisons
  result = analyzeFactorialRcbd("Y", *gomezInputs())
  comparisons = factorialInteractionComparisons(result)
  expected = scipyStats.t.ppf(0.975, 42) * math.sqrt(2 * result.errorMeanSquare / 4)
  assert comparisons.secondWithinFirst.leastSignificantDifference == pytest.approx(expected, rel=1e-9)
  assert comparisons.firstWithinSecond == comparisons.secondWithinFirst
  # The interaction is not significant here (P = 0.087), so the protected table carries no letters.
  assert not comparisons.interactionSignificant
  report = buildReport(*gomezInputs())
  assert "No letters: the Variety × Nitrogen interaction is not significant" in report
  assert "| V1 | 3.124 | 4.724 | 4.460 | 5.717 | 5.823 |" in report
  unprotected = buildReport(*gomezInputs(), meanComparison=MeanComparison.lsd)
  assert "Letters in a row compare the Nitrogen levels at that Variety level." in unprotected