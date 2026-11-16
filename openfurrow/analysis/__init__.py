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
from openfurrow.analysis.diagnostics import (
  Assumptions,
  DiagnosticOutcome,
  assessAssumptions,
)
from openfurrow.analysis.splitPlot import (
  FactorSeparation,
  LevelGroup,
  LevelMean,
  SplitPlotResult,
  analyzeSplitPlot,
  separateFactorMeans,
)
from openfurrow.analysis.meanSeparation import (
  MeanSeparation,
  TreatmentGroup,
  methodKeyFor,
  separateMeans,
)

__all__ = [
  "AnalysisError",
  "AnovaResult",
  "AnovaSource",
  "Assumptions",
  "CheckPair",
  "DiagnosticOutcome",
  "FactorSeparation",
  "LevelGroup",
  "LevelMean",
  "MeanSeparation",
  "PairedComparison",
  "PlotEfficacy",
  "SplitPlotResult",
  "TreatmentGroup",
  "TreatmentMean",
  "analyzeEfficacy",
  "analyzeHalves",
  "analyzeRcbd",
  "analyzeSplitPlot",
  "assessAssumptions",
  "checkPairs",
  "compareWithChecks",
  "methodKeyFor",
  "plotEfficacies",
  "separateFactorMeans",
  "separateMeans",
]
