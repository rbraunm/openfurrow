# SPDX-License-Identifier: Apache-2.0
"""Split-plot analysis of variance (decision 0020).

Main plots stand in complete blocks and carry the levels of factor A; each main plot is
split into subplots carrying the levels of factor B. The analysis has two error strata,
after Gomez and Gomez (1984), section 3.4.2:

    Replication       r - 1
    A                 a - 1               tested against Error(a)
    Error(a)          (r - 1)(a - 1)      replication x A
    B                 b - 1               tested against Error(b)
    A x B             (a - 1)(b - 1)      tested against Error(b)
    Error(b)          a(r - 1)(b - 1)
    Total             rab - 1

Each factor's means are separated by Fisher's LSD on its own error: for A,
t(alpha/2, Error(a) df) * sqrt(2 MS Error(a) / rb); for B, the same on Error(b) with
ra. Inside the interaction (Gomez and Gomez, Tables 5.5 and 5.6) two B means at the same
level of A differ by sqrt(2 Eb / r), tested on Error(b); two A means at the same level of B
differ by sqrt(2 [(b - 1) Eb + Ea] / rb), tested on the t values of the two errors weighted
by (b - 1) Eb and Ea.
"""

from __future__ import annotations

import math

import numpy
from pydantic import BaseModel, ConfigDict

from openfurrow.analysis.anova import AnalysisError, AnovaSource, TreatmentMean, buildBlockTreatmentMatrix
from openfurrow.analysis.distributions import fDistributionSurvival, tCriticalValue
from openfurrow.analysis.meanSeparation import letterGroups, methodKeyFor
from openfurrow.schema.assessment import Transform
from openfurrow.schema.layout import TrialLayout
from openfurrow.schema.observation import Observation
from openfurrow.schema.trialPackage import DesignType, TrialPackage


class LevelMean(BaseModel):
  """The mean of one level of a factor, over the other factor and the blocks."""

  model_config = ConfigDict(extra="forbid")

  levelCode: str
  mean: float
  observationCount: int


class SplitPlotResult(BaseModel):
  """The split-plot ANOVA of one numeric assessment, with its two error strata."""

  model_config = ConfigDict(extra="forbid")

  assessmentCode: str
  designType: DesignType
  transform: Transform
  transformOffset: float
  mainPlotFactor: str
  subPlotFactor: str
  blockCount: int
  grandMean: float
  mainPlotErrorMeanSquare: float
  mainPlotErrorDegreesOfFreedom: int
  subPlotErrorMeanSquare: float
  subPlotErrorDegreesOfFreedom: int
  mainPlotCoefficientOfVariation: float
  subPlotCoefficientOfVariation: float
  table: list[AnovaSource]
  mainPlotMeans: list[LevelMean]
  subPlotMeans: list[LevelMean]
  treatmentMeans: list[TreatmentMean]


class LevelGroup(BaseModel):
  """A level's mean and its letter grouping."""

  model_config = ConfigDict(extra="forbid")

  levelCode: str
  mean: float
  group: str


class FactorSeparation(BaseModel):
  """Fisher's LSD over the levels of one factor of a split plot."""

  model_config = ConfigDict(extra="forbid")

  factorCode: str
  methodKey: str
  significanceLevel: float
  leastSignificantDifference: float
  factorSignificant: bool
  groups: list[LevelGroup]


def analyzeSplitPlot(
  assessmentCode: str,
  package: TrialPackage,
  layout: TrialLayout,
  observations: list[Observation],
) -> SplitPlotResult:
  """Run the split-plot ANOVA for one numeric assessment."""
  if layout.designType is not DesignType.splitPlot:
    raise AnalysisError(f"analyzeSplitPlot requires a split-plot layout, got {layout.designType.value}")
  design = package.design
  matrix, treatmentCodes, blocks, transform = buildBlockTreatmentMatrix(
    assessmentCode, package, layout, observations,
  )
  factors = {factor.factorCode: factor for factor in package.factors}
  mainLevels = [level.levelCode for level in factors[design.mainPlotFactor].levels]
  subLevels = [level.levelCode for level in factors[design.subPlotFactor].levels]
  blockCount, mainCount, subCount = len(blocks), len(mainLevels), len(subLevels)

  values = numpy.empty((blockCount, mainCount, subCount), dtype=float)
  for treatmentIndex, treatmentCode in enumerate(treatmentCodes):
    levels = next(t for t in package.treatments if t.treatmentCode == treatmentCode).factorLevels
    values[:, mainLevels.index(levels[design.mainPlotFactor]), subLevels.index(levels[design.subPlotFactor])] = (
      matrix[:, treatmentIndex]
    )

  treatmentMeans = [
    TreatmentMean(treatmentCode=code, mean=float(matrix[:, index].mean()), observationCount=blockCount)
    for index, code in enumerate(treatmentCodes)
  ]
  return twoStrataAnova(
    assessmentCode, values, mainLevels, subLevels, design.mainPlotFactor, design.subPlotFactor,
    transform, package.ratingFor(assessmentCode).transformOffset, treatmentMeans, DesignType.splitPlot,
  )


def twoStrataAnova(
  assessmentCode: str,
  values: numpy.ndarray,
  mainLevels: list[str],
  subLevels: list[str],
  mainPlotFactor: str,
  subPlotFactor: str,
  transform: Transform,
  transformOffset: float,
  treatmentMeans: list[TreatmentMean],
  designType: DesignType,
) -> SplitPlotResult:
  """The two-stratum ANOVA of values indexed [block, main-plot level, subplot level]."""
  blockCount, mainCount, subCount = values.shape
  grandMean = float(values.mean())
  blockMeans = values.mean(axis=(1, 2))
  mainMeans = values.mean(axis=(0, 2))
  subMeans = values.mean(axis=(0, 1))
  mainPlotMeansByBlock = values.mean(axis=2)
  cellMeans = values.mean(axis=0)

  sumOfSquaresTotal = float(((values - grandMean) ** 2).sum())
  sumOfSquaresBlock = float(mainCount * subCount * ((blockMeans - grandMean) ** 2).sum())
  sumOfSquaresMain = float(blockCount * subCount * ((mainMeans - grandMean) ** 2).sum())
  sumOfSquaresMainError = (
    float(subCount * ((mainPlotMeansByBlock - grandMean) ** 2).sum()) - sumOfSquaresBlock - sumOfSquaresMain
  )
  sumOfSquaresSub = float(blockCount * mainCount * ((subMeans - grandMean) ** 2).sum())
  sumOfSquaresInteraction = (
    float(blockCount * ((cellMeans - grandMean) ** 2).sum()) - sumOfSquaresMain - sumOfSquaresSub
  )
  sumOfSquaresSubError = (
    sumOfSquaresTotal - sumOfSquaresBlock - sumOfSquaresMain - sumOfSquaresMainError
    - sumOfSquaresSub - sumOfSquaresInteraction
  )
  tolerance = 1.0e-7 * max(1.0, sumOfSquaresTotal)
  if min(sumOfSquaresMainError, sumOfSquaresSubError) < -tolerance:
    raise AnalysisError("internal error: negative error sum of squares")
  sumOfSquaresMainError = max(sumOfSquaresMainError, 0.0)
  sumOfSquaresSubError = max(sumOfSquaresSubError, 0.0)

  dfBlock = blockCount - 1
  dfMain = mainCount - 1
  dfMainError = dfBlock * dfMain
  dfSub = subCount - 1
  dfInteraction = dfMain * dfSub
  dfSubError = mainCount * dfBlock * dfSub
  dfTotal = blockCount * mainCount * subCount - 1

  meanSquareMainError = sumOfSquaresMainError / dfMainError
  meanSquareSubError = sumOfSquaresSubError / dfSubError
  for name, meanSquare in (("Error(a)", meanSquareMainError), ("Error(b)", meanSquareSubError)):
    if meanSquare == 0.0:
      raise AnalysisError(f"assessment '{assessmentCode}': {name} mean square is zero; AOV cannot be computed")
  if grandMean == 0.0:
    raise AnalysisError(f"assessment '{assessmentCode}': grand mean is zero; coefficient of variation is undefined")

  def tested(source: str, df: int, sumOfSquares: float, errorMeanSquare: float, errorDf: int) -> AnovaSource:
    meanSquare = sumOfSquares / df
    fStatistic = meanSquare / errorMeanSquare
    return AnovaSource(
      source=source, degreesOfFreedom=df, sumOfSquares=sumOfSquares, meanSquare=meanSquare,
      fStatistic=fStatistic, pValue=fDistributionSurvival(fStatistic, df, errorDf),
    )

  table = [
    AnovaSource(source="block", degreesOfFreedom=dfBlock, sumOfSquares=sumOfSquaresBlock,
                meanSquare=sumOfSquaresBlock / dfBlock),
    tested("mainPlot", dfMain, sumOfSquaresMain, meanSquareMainError, dfMainError),
    AnovaSource(source="mainPlotError", degreesOfFreedom=dfMainError, sumOfSquares=sumOfSquaresMainError,
                meanSquare=meanSquareMainError),
    tested("subPlot", dfSub, sumOfSquaresSub, meanSquareSubError, dfSubError),
    tested("interaction", dfInteraction, sumOfSquaresInteraction, meanSquareSubError, dfSubError),
    AnovaSource(source="subPlotError", degreesOfFreedom=dfSubError, sumOfSquares=sumOfSquaresSubError,
                meanSquare=meanSquareSubError),
    AnovaSource(source="total", degreesOfFreedom=dfTotal, sumOfSquares=sumOfSquaresTotal),
  ]
  return SplitPlotResult(
    assessmentCode=assessmentCode,
    designType=designType,
    transform=transform,
    transformOffset=transformOffset,
    mainPlotFactor=mainPlotFactor,
    subPlotFactor=subPlotFactor,
    blockCount=blockCount,
    grandMean=grandMean,
    mainPlotErrorMeanSquare=meanSquareMainError,
    mainPlotErrorDegreesOfFreedom=dfMainError,
    subPlotErrorMeanSquare=meanSquareSubError,
    subPlotErrorDegreesOfFreedom=dfSubError,
    mainPlotCoefficientOfVariation=100.0 * math.sqrt(meanSquareMainError) / abs(grandMean),
    subPlotCoefficientOfVariation=100.0 * math.sqrt(meanSquareSubError) / abs(grandMean),
    table=table,
    mainPlotMeans=[
      LevelMean(levelCode=code, mean=float(mainMeans[index]), observationCount=blockCount * subCount)
      for index, code in enumerate(mainLevels)
    ],
    subPlotMeans=[
      LevelMean(levelCode=code, mean=float(subMeans[index]), observationCount=blockCount * mainCount)
      for index, code in enumerate(subLevels)
    ],
    treatmentMeans=treatmentMeans,
  )


def separateFactorMeans(
  result: SplitPlotResult,
  factor: str,
  significanceLevel: float = 0.05,
  protected: bool = True,
) -> FactorSeparation:
  """Separate the level means of the main-plot or the subplot factor by Fisher's LSD."""
  if factor == result.mainPlotFactor:
    means, source = result.mainPlotMeans, "mainPlot"
    errorMeanSquare, errorDf = result.mainPlotErrorMeanSquare, result.mainPlotErrorDegreesOfFreedom
  elif factor == result.subPlotFactor:
    means, source = result.subPlotMeans, "subPlot"
    errorMeanSquare, errorDf = result.subPlotErrorMeanSquare, result.subPlotErrorDegreesOfFreedom
  else:
    raise AnalysisError(
      f"'{factor}' is neither the main-plot factor '{result.mainPlotFactor}' "
      f"nor the subplot factor '{result.subPlotFactor}'"
    )
  row = next(row for row in result.table if row.source == source)
  return separateLevels(factor, means, errorMeanSquare, errorDf, row.pValue, significanceLevel, protected)


def separateLevels(
  factor: str,
  means: list[LevelMean],
  errorMeanSquare: float,
  errorDf: int,
  pValue: float | None,
  significanceLevel: float,
  protected: bool,
) -> FactorSeparation:
  """Fisher's LSD over the level means of one factor, on the error that factor is tested against."""
  if not 0.0 < significanceLevel < 1.0:
    raise AnalysisError(f"significance level must be in (0, 1), got {significanceLevel}")
  perLevel = means[0].observationCount
  leastSignificantDifference = (
    tCriticalValue(significanceLevel / 2.0, errorDf) * math.sqrt(2.0 * errorMeanSquare / perLevel)
  )
  significant = pValue is not None and pValue <= significanceLevel
  ordered = sorted(means, key=lambda mean: mean.mean, reverse=True)
  if protected and not significant:
    letters = ["a"] * len(ordered)
  else:
    letters = letterGroups([mean.mean for mean in ordered], leastSignificantDifference)
  return FactorSeparation(
    factorCode=factor,
    methodKey=methodKeyFor(protected),
    significanceLevel=significanceLevel,
    leastSignificantDifference=leastSignificantDifference,
    factorSignificant=significant,
    groups=[
      LevelGroup(levelCode=mean.levelCode, mean=mean.mean, group=letters[index])
      for index, mean in enumerate(ordered)
    ],
  )


class LeastSignificantDifference(BaseModel):
  """One LSD: the standard error of a difference, the t it is tested on, and their product."""

  model_config = ConfigDict(extra="forbid")

  standardError: float
  criticalT: float
  leastSignificantDifference: float


class InteractionComparisons(BaseModel):
  """The LSDs for comparing combination means inside a two-factor interaction."""

  model_config = ConfigDict(extra="forbid")

  significanceLevel: float
  interactionSignificant: bool
  secondWithinFirst: LeastSignificantDifference
  firstWithinSecond: LeastSignificantDifference


def weightedCriticalT(parts: list[tuple[float, float]]) -> float:
  """Gomez and Gomez Table 5.6: t values weighted by the error terms they belong to, as (weight, t)."""
  return sum(weight * t for weight, t in parts) / sum(weight for weight, _ in parts)


def _lsd(standardError: float, criticalT: float) -> LeastSignificantDifference:
  return LeastSignificantDifference(
    standardError=standardError, criticalT=criticalT, leastSignificantDifference=criticalT * standardError,
  )


def splitPlotInteractionComparisons(result: SplitPlotResult, significanceLevel: float = 0.05) -> InteractionComparisons:
  """The LSDs for two subplot means at one main-plot level, and two main-plot means at one subplot level."""
  if not 0.0 < significanceLevel < 1.0:
    raise AnalysisError(f"significance level must be in (0, 1), got {significanceLevel}")
  blocks = result.blockCount
  subLevels = len(result.subPlotMeans)
  errorA, errorB = result.mainPlotErrorMeanSquare, result.subPlotErrorMeanSquare
  tA = tCriticalValue(significanceLevel / 2.0, result.mainPlotErrorDegreesOfFreedom)
  tB = tCriticalValue(significanceLevel / 2.0, result.subPlotErrorDegreesOfFreedom)
  weightB = (subLevels - 1) * errorB
  interaction = next(row for row in result.table if row.source == "interaction")
  return InteractionComparisons(
    significanceLevel=significanceLevel,
    interactionSignificant=interaction.pValue is not None and interaction.pValue <= significanceLevel,
    secondWithinFirst=_lsd(math.sqrt(2.0 * errorB / blocks), tB),
    firstWithinSecond=_lsd(
      math.sqrt(2.0 * (weightB + errorA) / (blocks * subLevels)),
      weightedCriticalT([(weightB, tB), (errorA, tA)]),
    ),
  )
