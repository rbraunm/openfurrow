# SPDX-License-Identifier: Apache-2.0
"""Two-factor treatments in randomized complete blocks (decision 0025).

The treatments are every combination of two factors, laid out as an ordinary RCBD. The
treatment sum of squares is split into its factorial parts, after Gomez and Gomez (1984),
section 3.3:

    Replication       r - 1
    A                 a - 1
    B                 b - 1
    A x B             (a - 1)(b - 1)
    Error             (r - 1)(ab - 1)
    Total             rab - 1

Every line is tested against the one error, and each factor's means are separated by
Fisher's LSD on it: t(alpha/2, error df) * sqrt(2 MS error / n), n being the plots per level.
"""

from __future__ import annotations

import math

import numpy
from pydantic import BaseModel, ConfigDict

from openfurrow.analysis.anova import AnalysisError, AnovaSource, TreatmentMean, buildRcbdMatrix
from openfurrow.analysis.distributions import fDistributionSurvival
from openfurrow.analysis.splitPlot import FactorSeparation, LevelMean, separateLevels
from openfurrow.schema.assessment import Transform
from openfurrow.schema.layout import TrialLayout
from openfurrow.schema.observation import Observation
from openfurrow.schema.trialPackage import DesignType, TrialPackage


class FactorialResult(BaseModel):
  """The factorial ANOVA of one numeric assessment of a two-factor RCBD."""

  model_config = ConfigDict(extra="forbid")

  assessmentCode: str
  designType: DesignType
  transform: Transform
  firstFactor: str
  secondFactor: str
  blockCount: int
  grandMean: float
  errorMeanSquare: float
  errorDegreesOfFreedom: int
  coefficientOfVariation: float
  table: list[AnovaSource]
  firstFactorMeans: list[LevelMean]
  secondFactorMeans: list[LevelMean]
  treatmentMeans: list[TreatmentMean]


def analyzeFactorialRcbd(
  assessmentCode: str,
  package: TrialPackage,
  layout: TrialLayout,
  observations: list[Observation],
) -> FactorialResult:
  """Run the two-factor ANOVA of an RCBD whose treatments are the combinations of two factors."""
  if len(package.factors) != 2:
    raise AnalysisError(f"trial '{package.trial.trialCode}' is not a two-factor trial")
  matrix, treatmentCodes, blocks, transform = buildRcbdMatrix(assessmentCode, package, layout, observations)
  first, second = package.factors
  firstLevels = [level.levelCode for level in first.levels]
  secondLevels = [level.levelCode for level in second.levels]
  blockCount, firstCount, secondCount = len(blocks), len(firstLevels), len(secondLevels)
  levelsOf = {treatment.treatmentCode: treatment.factorLevels for treatment in package.treatments}
  values = numpy.empty((blockCount, firstCount, secondCount), dtype=float)
  for index, code in enumerate(treatmentCodes):
    levels = levelsOf[code]
    values[:, firstLevels.index(levels[first.factorCode]), secondLevels.index(levels[second.factorCode])] = matrix[:, index]

  grandMean = float(values.mean())
  firstMeans = values.mean(axis=(0, 2))
  secondMeans = values.mean(axis=(0, 1))
  sumOfSquaresTotal = float(((values - grandMean) ** 2).sum())
  sumOfSquaresBlock = float(firstCount * secondCount * ((values.mean(axis=(1, 2)) - grandMean) ** 2).sum())
  sumOfSquaresFirst = float(blockCount * secondCount * ((firstMeans - grandMean) ** 2).sum())
  sumOfSquaresSecond = float(blockCount * firstCount * ((secondMeans - grandMean) ** 2).sum())
  sumOfSquaresInteraction = (
    float(blockCount * ((values.mean(axis=0) - grandMean) ** 2).sum()) - sumOfSquaresFirst - sumOfSquaresSecond
  )
  sumOfSquaresError = (
    sumOfSquaresTotal - sumOfSquaresBlock - sumOfSquaresFirst - sumOfSquaresSecond - sumOfSquaresInteraction
  )
  if sumOfSquaresError < -1.0e-7 * max(1.0, sumOfSquaresTotal):
    raise AnalysisError("internal error: negative error sum of squares")
  sumOfSquaresError = max(sumOfSquaresError, 0.0)

  dfBlock = blockCount - 1
  dfError = dfBlock * (firstCount * secondCount - 1)
  meanSquareError = sumOfSquaresError / dfError
  if meanSquareError == 0.0:
    raise AnalysisError(f"assessment '{assessmentCode}': error mean square is zero; AOV cannot be computed")
  if grandMean == 0.0:
    raise AnalysisError(f"assessment '{assessmentCode}': grand mean is zero; coefficient of variation is undefined")

  def tested(source: str, df: int, sumOfSquares: float) -> AnovaSource:
    meanSquare = sumOfSquares / df
    fStatistic = meanSquare / meanSquareError
    return AnovaSource(source=source, degreesOfFreedom=df, sumOfSquares=sumOfSquares, meanSquare=meanSquare,
                       fStatistic=fStatistic, pValue=fDistributionSurvival(fStatistic, df, dfError))

  return FactorialResult(
    assessmentCode=assessmentCode,
    designType=DesignType.rcbd,
    transform=transform,
    firstFactor=first.factorCode,
    secondFactor=second.factorCode,
    blockCount=blockCount,
    grandMean=grandMean,
    errorMeanSquare=meanSquareError,
    errorDegreesOfFreedom=dfError,
    coefficientOfVariation=100.0 * math.sqrt(meanSquareError) / abs(grandMean),
    table=[
      tested("block", dfBlock, sumOfSquaresBlock),
      tested("firstFactor", firstCount - 1, sumOfSquaresFirst),
      tested("secondFactor", secondCount - 1, sumOfSquaresSecond),
      tested("interaction", (firstCount - 1) * (secondCount - 1), sumOfSquaresInteraction),
      AnovaSource(source="error", degreesOfFreedom=dfError, sumOfSquares=sumOfSquaresError, meanSquare=meanSquareError),
      AnovaSource(source="total", degreesOfFreedom=blockCount * firstCount * secondCount - 1, sumOfSquares=sumOfSquaresTotal),
    ],
    firstFactorMeans=[
      LevelMean(levelCode=code, mean=float(firstMeans[index]), observationCount=blockCount * secondCount)
      for index, code in enumerate(firstLevels)
    ],
    secondFactorMeans=[
      LevelMean(levelCode=code, mean=float(secondMeans[index]), observationCount=blockCount * firstCount)
      for index, code in enumerate(secondLevels)
    ],
    treatmentMeans=[
      TreatmentMean(treatmentCode=code, mean=float(matrix[:, index].mean()), observationCount=blockCount)
      for index, code in enumerate(treatmentCodes)
    ],
  )


def separateFactorialMeans(
  result: FactorialResult, factor: str, significanceLevel: float = 0.05, protected: bool = True,
) -> FactorSeparation:
  """Separate the level means of one factor of a two-factor RCBD by Fisher's LSD on the error."""
  if factor == result.firstFactor:
    means, source = result.firstFactorMeans, "firstFactor"
  elif factor == result.secondFactor:
    means, source = result.secondFactorMeans, "secondFactor"
  else:
    raise AnalysisError(f"'{factor}' is not a factor of this trial ({result.firstFactor}, {result.secondFactor})")
  row = next(row for row in result.table if row.source == source)
  return separateLevels(
    factor, means, result.errorMeanSquare, result.errorDegreesOfFreedom, row.pValue, significanceLevel, protected,
  )
