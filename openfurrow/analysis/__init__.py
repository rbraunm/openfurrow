# SPDX-License-Identifier: Apache-2.0
"""Analysis: native statistics for trial data."""

from openfurrow.analysis.anova import (
  AnalysisError,
  AnovaResult,
  AnovaSource,
  TreatmentMean,
  analyzeRcbd,
)
from openfurrow.analysis.checks import (
  CheckPair,
  PairedComparison,
  PlotEfficacy,
  analyzeEfficacy,
  analyzeHalves,
  checkPairs,
  compareWithChecks,
  plotEfficacies,
)
from openfurrow.analysis.factorial import (
  FactorialResult,
  analyzeFactorialRcbd,
  factorialInteractionComparisons,
  separateFactorialMeans,
)
from openfurrow.analysis.crd import analyzeCrd
from openfurrow.analysis.dunnett import (
  CheckComparison,
  DunnettResult,
  compareWithControl,
  dunnettCdf,
  dunnettQuantile,
)
from openfurrow.analysis.diagnostics import (
  Assumptions,
  DiagnosticOutcome,
  assessAssumptions,
)
from openfurrow.analysis.splitPlot import (
  FactorSeparation,
  LevelGroup,
  LevelMean,
  InteractionComparisons,
  LeastSignificantDifference,
  SplitPlotResult,
  analyzeSplitPlot,
  splitPlotInteractionComparisons,
  weightedCriticalT,
  separateFactorMeans,
)
from openfurrow.analysis.meanSeparation import (
  MeanComparison,
  MeanSeparation,
  TreatmentGroup,
  criticalDifference,
  letterGroups,
  methodKeyFor,
  separateMeans,
)

__all__ = [
  "AnalysisError",
  "AnovaResult",
  "AnovaSource",
  "CheckComparison",
  "Assumptions",
  "CheckPair",
  "DiagnosticOutcome",
  "DunnettResult",
  "FactorialResult",
  "InteractionComparisons",
  "LeastSignificantDifference",
  "FactorSeparation",
  "LevelGroup",
  "LevelMean",
  "MeanComparison",
  "MeanSeparation",
  "PairedComparison",
  "PlotEfficacy",
  "SplitPlotResult",
  "TreatmentGroup",
  "TreatmentMean",
  "analyzeCrd",
  "analyzeEfficacy",
  "analyzeFactorialRcbd",
  "factorialInteractionComparisons",
  "analyzeHalves",
  "analyzeRcbd",
  "analyzeSplitPlot",
  "assessAssumptions",
  "checkPairs",
  "compareWithChecks",
  "compareWithControl",
  "criticalDifference",
  "dunnettCdf",
  "dunnettQuantile",
  "letterGroups",
  "methodKeyFor",
  "plotEfficacies",
  "separateFactorMeans",
  "separateFactorialMeans",
  "separateMeans",
  "splitPlotInteractionComparisons",
  "weightedCriticalT",
]
