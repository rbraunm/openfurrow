# SPDX-License-Identifier: Apache-2.0
"""OpenFurrow: open, reproducible management for agricultural trials.

This module is the **public API**. Everything a caller needs is importable from here:

    from openfurrow import TrialPackage, Workspace

    workspace = Workspace.create("trials.db")
    workspace.addPackage(TrialPackage.model_validate(designJson))
    workspace.importObservations("ESV-2025-01", "observations.csv", profile)
    print(workspace.buildReport("ESV-2025-01"))

The surface is deliberately narrow and has three parts:

- **`Workspace`** -- the facade, and the only way to act on a trial. Every operation
  (add, list, layout, import, analyze, separate means, assess assumptions, report,
  exchange, hash, verify, Field Book interop, delete) is a method on it.
- **The schema types** -- what goes in and comes out: the trial package a caller
  authors, the observations, the portable document, plus `contentHash` for fixity.
- **The result types** -- what the facade hands back (`AnovaResult`, `MeanSeparation`,
  `Assumptions`, `ImportResult`), the config that parameterizes import and analysis,
  and the error types to catch.

Everything else is internal. The store, the randomizer, the exchange writers, the
report builder, the observation importer, and the Field Book writers are reached
through `Workspace`, never imported directly -- that is what keeps a surface (the
CLI, the Flask service, a future app) from drifting from the core or re-implementing
part of it. The analysis primitives are internal for the same reason: the numbers a
caller sees must come from the one validated path, and `Workspace.analyze` and its
siblings return exactly the objects those primitives produce.

Importing from `openfurrow.store`, `openfurrow.design`, and the other internal
modules still works, but it is unsupported: those paths are free to change. This
module is the compatibility boundary.
"""

from openfurrow.analysis import (
  AnovaResult,
  AnovaSource,
  Assumptions,
  DiagnosticOutcome,
  FactorialResult,
  FactorSeparation,
  LevelGroup,
  LevelMean,
  MeanSeparation,
  SplitPlotResult,
  TreatmentGroup,
  TreatmentMean,
)
from openfurrow.config import (
  AnalysisSettings,
  ImportFormat,
  ImportProfile,
  LongColumns,
  MeanComparison,
  OpenFurrowConfig,
  ValueParsing,
  WideColumns,
  defaultConfig,
  defaultConfigRelativePath,
  loadConfig,
)
from openfurrow.importers import ImportResult, ImportWarning
from openfurrow.schema import (
  ActiveSubstance,
  Application,
  Assessment,
  AssessmentDataType,
  CheckArrangement,
  CheckPlot,
  Efficacy,
  EfficacyMethod,
  DesignSpecification,
  DesignType,
  Factor,
  FactorLevel,
  MeasurementKind,
  Observation,
  Planting,
  PlotDimensions,
  PlotAssignment,
  ProductKind,
  Quantity,
  RandomizationMethod,
  RateBasis,
  Rating,
  Soil,
  Setting,
  SiteDetails,
  SoilMoisture,
  Target,
  TargetKind,
  Transform,
  SubsampleRule,
  Subsamples,
  UntreatedCheck,
  Treatment,
  TreatmentLine,
  TreatmentRole,
  TrialDocument,
  TrialLayout,
  TrialMetadata,
  TrialPackage,
  WeatherRecord,
  canonicalBytes,
  contentHash,
)
from openfurrow.version import schemaVersion
from openfurrow.workspace import (
  AnalysisError,
  ExchangeError,
  ObservationImportError,
  RoundTripCheck,
  StoreError,
  Workspace,
)

__all__ = [
  # The facade -- the entry point for everything.
  "Workspace",
  "RoundTripCheck",
  # Errors a caller catches.
  "AnalysisError",
  "ExchangeError",
  "ObservationImportError",
  "StoreError",
  # Schema: what goes in and comes out.
  "ActiveSubstance",
  "Application",
  "Assessment",
  "AssessmentDataType",
  "CheckArrangement",
  "CheckPlot",
  "Efficacy",
  "EfficacyMethod",
  "DesignSpecification",
  "DesignType",
  "Factor",
  "FactorLevel",
  "MeasurementKind",
  "Observation",
  "Planting",
  "PlotDimensions",
  "PlotAssignment",
  "ProductKind",
  "Quantity",
  "RandomizationMethod",
  "RateBasis",
  "Rating",
  "Soil",
  "Setting",
  "SiteDetails",
  "SoilMoisture",
  "Target",
  "TargetKind",
  "Transform",
  "SubsampleRule",
  "Subsamples",
  "UntreatedCheck",
  "Treatment",
  "TreatmentLine",
  "TreatmentRole",
  "TrialDocument",
  "TrialLayout",
  "TrialMetadata",
  "TrialPackage",
  "WeatherRecord",
  "canonicalBytes",
  "contentHash",
  # Results handed back by the facade.
  "AnovaResult",
  "AnovaSource",
  "Assumptions",
  "DiagnosticOutcome",
  "FactorialResult",
  "FactorSeparation",
  "ImportResult",
  "ImportWarning",
  "LevelGroup",
  "LevelMean",
  "MeanSeparation",
  "SplitPlotResult",
  "TreatmentGroup",
  "TreatmentMean",
  # Configuration that parameterizes import and analysis.
  "AnalysisSettings",
  "ImportFormat",
  "ImportProfile",
  "LongColumns",
  "MeanComparison",
  "OpenFurrowConfig",
  "ValueParsing",
  "WideColumns",
  "defaultConfig",
  "defaultConfigRelativePath",
  "loadConfig",
  # Metadata.
  "schemaVersion",
]
