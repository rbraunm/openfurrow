# SPDX-License-Identifier: Apache-2.0
"""The OpenFurrow core facade -- the single surface every non-core caller uses.

Every non-core surface (the CLI, the HTTP service and its web interface, later apps)
reaches the core through a `Workspace` and the public schema/analysis result types,
never by importing store, analysis, exchange, or design internals directly. This is the
"one facade" invariant from the implementation plan: the math and the store have
exactly one caller-facing shape, so a surface can never drift from the core or
re-implement part of it.

A `Workspace` wraps one SQLite database (one system of record holding many trials)
and exposes the trial loop as methods: add a designed package, list and load
trials, read the layout, import observations, analyze, separate means, assess
assumptions, build the report, exchange portable files, hash, verify, and delete.

Lifetime: a Workspace holds the SQLAlchemy engine and opens a fresh session per
method call. The engine is the poolable, reusable resource (a long-running service
keeps one); the session is the unit of work (one CLI command or one HTTP request is
one transaction), so no session state leaks across calls. Composite operations that
need the package, layout, and observations together load them in a single session.
The layout is recorded with the trial (decision 0015): it is generated once, when a
package is added, and read from the store from then on.

Path-based methods exist only where a portable file is the thing being moved
(document/CSV import and export); the pure design operation `addPackage` takes a
validated `TrialPackage`, and the surface reads the JSON.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from openfurrow.analysis import (
  AnalysisError,
  AnovaResult,
  Assumptions,
  FactorSeparation,
  FactorialResult,
  MeanSeparation,
  SplitPlotResult,
  analyzeFactorialRcbd as _analyzeFactorialRcbd,
  analyzeRcbd as _analyzeRcbd,
  separateFactorialMeans as _separateFactorialMeans,
  analyzeSplitPlot as _analyzeSplitPlot,
  separateFactorMeans as _separateFactorMeans,
  assessAssumptions as _assessAssumptions,
  separateMeans as _separateMeans,
)
from openfurrow.config import ImportProfile
from openfurrow.importers.weatherCsv import WeatherFileError, readWeatherCsv as _readWeatherCsv
from openfurrow.design import generateLayout as _generateLayout
from openfurrow.exchange import (
  ExchangeError,
  exportJson as _exportJson,
  exportObservationsCsv as _exportObservationsCsv,
  importJson as _importJson,
)
from openfurrow.i18n import MessageError, availableLocales, sourceLocale
from openfurrow.importers import (
  ImportResult,
  ObservationImportError,
  importObservations as _importObservations,
)
from openfurrow.interop.fieldbook import (
  fieldBookImportProfile as _fieldBookImportProfile,
  writeFieldImport as _writeFieldImport,
  writeTraitFile as _writeTraitFile,
)
from openfurrow.reports import buildReport as _buildReport
from openfurrow.schema import (
  DesignType,
  Observation,
  RandomizationMethod,
  TrialDocument,
  TrialLayout,
  TrialPackage,
  contentHash as _contentHash,
)
from openfurrow.schema.document import checkObservationValues as _checkObservationValues
from openfurrow.store import (
  StoreError,
  createDatabase as _createDatabase,
  deleteTrial as _deleteTrial,
  listTrials as _listTrials,
  loadCheckPlots as _loadCheckPlots,
  replaceAssessmentObservations as _replaceAssessmentObservations,
  replaceWeather as _replaceWeather,
  loadLayout as _loadLayout,
  loadObservations as _loadObservations,
  loadPackage as _loadPackage,
  savePackage as _savePackage,
  saveObservations as _saveObservations,
  sessionScope as _sessionScope,
)

# Re-export the core error types so a surface catches them from the one facade
# module rather than reaching into the internals that raise them.
__all__ = [
  "AnalysisError",
  "ExchangeError",
  "MessageError",
  "ObservationImportError",
  "RoundTripCheck",
  "StoreError",
  "Workspace",
  "availableLocales",
  "sourceLocale",
]


class RoundTripCheck(BaseModel):
  """The result of a reproducibility round-trip: export to JSON and re-import.

  `matches` is the pass/fail; the two hashes are surfaced so a failing check can
  be reported precisely rather than as a bare boolean.
  """

  model_config = ConfigDict(extra="forbid")

  matches: bool
  storedHash: str
  roundTripHash: str


class Workspace:
  """One SQLite database of trials, and the trial loop over it.

  Construct with `Workspace.create(path)` for a new database or
  `Workspace.open(path)` for an existing one; `open` fails loud if the file is
  absent rather than silently creating an empty store.
  """

  def __init__(self, engine) -> None:
    # Prefer the create/open classmethods; __init__ takes an already-open engine
    # so tests and future surfaces can inject one if needed.
    self._engine = engine

  @classmethod
  def create(cls, databasePath: str) -> "Workspace":
    """Create (or open) the database at `databasePath` and ensure its schema."""
    return cls(_createDatabase(databasePath))

  @classmethod
  def open(cls, databasePath: str) -> "Workspace":
    """Open an existing database; raise if the file does not exist."""
    if not Path(databasePath).exists():
      raise StoreError(f"database '{databasePath}' does not exist; create it first")
    return cls(_createDatabase(databasePath))

  # ---- trial management ---------------------------------------------------

  def addPackage(self, package: TrialPackage) -> None:
    """Persist a validated trial package and the layout generated from its seed.

    This is where a trial is randomized: once, here, and the layout is recorded. A
    package whose layout was made elsewhere carries no plots, so it cannot be added
    this way; such a trial comes in as a trial document (`importDocument`).
    """
    if package.design.randomizationMethod is RandomizationMethod.imported:
      raise StoreError(
        f"trial '{package.trial.trialCode}' declares an imported layout; supply it as a "
        f"trial document, which carries the plots"
      )
    layout = _generateLayout(package)
    with _sessionScope(self._engine) as session:
      _savePackage(session, package, layout.plots, layout.checkPlots)

  def listTrials(self) -> list[tuple[str, str]]:
    """Every trial in the store as (trialCode, title) pairs."""
    with _sessionScope(self._engine) as session:
      return _listTrials(session)

  def loadPackage(self, trialCode: str) -> TrialPackage:
    """The trial package for `trialCode`; raises if the trial is unknown."""
    with _sessionScope(self._engine) as session:
      return _loadPackage(session, trialCode)

  def loadObservations(self, trialCode: str) -> list[Observation]:
    """The stored observations for `trialCode` (empty if none imported yet)."""
    with _sessionScope(self._engine) as session:
      return _loadObservations(session, trialCode)

  def deleteTrial(self, trialCode: str) -> None:
    """Delete a trial and all its observations."""
    with _sessionScope(self._engine) as session:
      _deleteTrial(session, trialCode)

  # ---- layout -------------------------------------------------------------

  def layoutFor(self, trialCode: str) -> TrialLayout:
    """The trial's recorded layout."""
    with _sessionScope(self._engine) as session:
      return self._layoutIn(session, _loadPackage(session, trialCode))

  # ---- observations -------------------------------------------------------

  def importObservations(
    self,
    trialCode: str,
    csvPath: str,
    importProfile: ImportProfile,
  ) -> ImportResult:
    """Import observations from a CSV file against the trial's layout and save them.

    Values are validated against the package and layout at the boundary; a bad
    plot, code, or out-of-domain value is rejected rather than partially saved.
    """
    with _sessionScope(self._engine) as session:
      package = _loadPackage(session, trialCode)
      layout = self._layoutIn(session, package)
      result = _importObservations(csvPath, package, layout, importProfile)
      _saveObservations(session, trialCode, result.observations)
    return result

  # ---- analysis -----------------------------------------------------------

  def analyze(self, trialCode: str, assessmentCode: str) -> AnovaResult | SplitPlotResult:
    """Run the ANOVA the trial's design calls for, for one numeric assessment."""
    package, layout, observations = self._loadContext(trialCode)
    if package.design.designType is DesignType.splitPlot:
      return _analyzeSplitPlot(assessmentCode, package, layout, observations)
    return _analyzeRcbd(assessmentCode, package, layout, observations)

  def separateFactorMeans(
    self,
    trialCode: str,
    assessmentCode: str,
    factor: str,
    significanceLevel: float = 0.05,
    protected: bool = True,
  ) -> FactorSeparation:
    """Separate the level means of one factor of a split plot or a two-factor RCBD by Fisher's (Protected) LSD."""
    result = self.analyze(trialCode, assessmentCode)
    if isinstance(result, SplitPlotResult):
      return _separateFactorMeans(result, factor, significanceLevel=significanceLevel, protected=protected)
    package, layout, observations = self._loadContext(trialCode)
    if not package.factors:
      raise AnalysisError(f"trial '{trialCode}' has no factors to separate")
    factorial = _analyzeFactorialRcbd(assessmentCode, package, layout, observations)
    return _separateFactorialMeans(factorial, factor, significanceLevel=significanceLevel, protected=protected)

  def analyzeFactorial(self, trialCode: str, assessmentCode: str) -> FactorialResult:
    """The factorial ANOVA of a two-factor RCBD (decision 0025)."""
    package, layout, observations = self._loadContext(trialCode)
    return _analyzeFactorialRcbd(assessmentCode, package, layout, observations)

  def separateMeans(
    self,
    trialCode: str,
    assessmentCode: str,
    significanceLevel: float = 0.05,
    protected: bool = True,
  ) -> MeanSeparation:
    """Separate treatment means by Fisher's (Protected) LSD for one assessment."""
    result = self.analyze(trialCode, assessmentCode)
    if isinstance(result, SplitPlotResult):
      raise AnalysisError(
        f"trial '{trialCode}' is a split plot; its means are separated for each factor (separateFactorMeans)"
      )
    return _separateMeans(result, significanceLevel=significanceLevel, protected=protected)

  def assessAssumptions(
    self,
    trialCode: str,
    assessmentCode: str,
    significanceLevel: float = 0.05,
  ) -> Assumptions:
    """Compute the report-only ANOVA assumption diagnostics for one assessment."""
    package, layout, observations = self._loadContext(trialCode)
    return _assessAssumptions(assessmentCode, package, layout, observations, significanceLevel)

  # ---- reporting ----------------------------------------------------------

  def buildReport(
    self,
    trialCode: str,
    significanceLevel: float = 0.05,
    protected: bool = True,
    locale: str = sourceLocale,
  ) -> str:
    """Build the full Markdown trial report (the AOV Means Table and provenance).

    `locale` is a display choice only: it selects the message catalog and number
    formatting. It does not touch the stored data, the exchange, or the content hash.
    """
    package, layout, observations = self._loadContext(trialCode)
    return _buildReport(
      package, layout, observations,
      significanceLevel=significanceLevel, protected=protected, locale=locale,
    )

  # ---- exchange, hashing, verification ------------------------------------

  def contentHashFor(self, trialCode: str) -> str:
    """The canonical content hash of the trial (package plus observations)."""
    return _contentHash(self._documentFor(trialCode))

  def exportDocument(self, trialCode: str, jsonPath: str) -> None:
    """Write the trial to a portable, deterministic JSON document."""
    _exportJson(self._documentFor(trialCode), jsonPath)

  def exportObservationsCsv(self, trialCode: str, csvPath: str) -> None:
    """Write the trial's observations as long-format CSV, annotated with block and treatment."""
    _exportObservationsCsv(self._documentFor(trialCode), csvPath)

  def importDocument(self, jsonPath: str) -> str:
    """Import a portable trial document JSON into this store; return its trialCode."""
    return self.addDocument(_importJson(jsonPath))

  def addDocument(self, document: TrialDocument) -> str:
    """Store a validated trial document (its package, plots, checks and values); return its trialCode."""
    trialCode = document.package.trial.trialCode
    with _sessionScope(self._engine) as session:
      _savePackage(session, document.package, document.layout, document.checkPlots)
      _saveObservations(session, trialCode, document.observations)
    return trialCode

  def verifyRoundTrip(self, trialCode: str) -> RoundTripCheck:
    """Check the trial exports to JSON and re-imports to the same content hash."""
    document = self._documentFor(trialCode)
    storedHash = _contentHash(document)
    with tempfile.TemporaryDirectory() as directory:
      jsonPath = str(Path(directory) / "roundtrip.json")
      _exportJson(document, jsonPath)
      reimported = _importJson(jsonPath)
    roundTripHash = _contentHash(reimported)
    return RoundTripCheck(
      matches=storedHash == roundTripHash,
      storedHash=storedHash,
      roundTripHash=roundTripHash,
    )

  # ---- Field Book interop -------------------------------------------------

  def exportFieldBook(self, trialCode: str, fieldPath: str, traitPath: str) -> None:
    """Write the trial's Field Book field-import CSV and legacy `.trt` trait file."""
    package, layout, _ = self._loadContext(trialCode)
    _writeFieldImport(package, layout, fieldPath)
    _writeTraitFile(package, traitPath)

  def recordValues(self, trialCode: str, assessmentCode: str, observations: list[Observation]) -> None:
    """Replace one assessment's values with those entered, after checking every one (decision 0023).

    Every observation belongs to the assessment and to a plot or check plot of the trial,
    and fits its rating; a value outside the limits must be confirmed. Nothing is saved
    unless all of them pass.
    """
    with _sessionScope(self._engine) as session:
      package = _loadPackage(session, trialCode)
      layout = self._layoutIn(session, package)
      package.assessmentFor(assessmentCode)
      plotNumbers = {plot.plotNumber for plot in layout.plots} | {check.plotNumber for check in layout.checkPlots}
      stray = sorted({observation.plotNumber for observation in observations} - plotNumbers)
      if stray:
        raise ObservationImportError(f"plots {stray} are not in trial '{trialCode}'")
      try:
        _checkObservationValues(package, observations)
      except ValueError as error:
        raise ObservationImportError(str(error)) from error
      _replaceAssessmentObservations(session, trialCode, assessmentCode, observations)

  def importWeather(self, trialCode: str, csvPath: str) -> int:
    """Replace the trial's weather log with the days a CSV lists; return how many (REC-13).

    The trial with its new log is validated as a whole before anything is saved.
    """
    records = _readWeatherCsv(csvPath)
    with _sessionScope(self._engine) as session:
      package = _loadPackage(session, trialCode)
      data = package.model_dump(mode="json")
      data["weather"] = [record.model_dump(mode="json") for record in records]
      TrialPackage.model_validate(data)
      _replaceWeather(session, trialCode, records)
    return len(records)

  def importFieldBook(self, trialCode: str, databaseCsvPath: str) -> ImportResult:
    """Ingest a Field Book database (long) export into the trial's observations.

    Reuses the standard importer with the Field Book column mapping: the export's
    unique-id column is the plot, `trait` the assessment code, `value` the value;
    the provenance columns (timestamp, person, device_name, ...) are ignored.
    """
    with _sessionScope(self._engine) as session:
      package = _loadPackage(session, trialCode)
      layout = self._layoutIn(session, package)
      result = _importObservations(databaseCsvPath, package, layout, _fieldBookImportProfile())
      _saveObservations(session, trialCode, result.observations)
    return result

  # ---- internals ----------------------------------------------------------

  @staticmethod
  def _layoutIn(session, package: TrialPackage) -> TrialLayout:
    trialCode = package.trial.trialCode
    return TrialLayout.forPackage(package, _loadLayout(session, trialCode), _loadCheckPlots(session, trialCode))

  def _loadContext(self, trialCode: str) -> tuple[TrialPackage, TrialLayout, list[Observation]]:
    """Load the package, the layout and the observations in one session."""
    with _sessionScope(self._engine) as session:
      package = _loadPackage(session, trialCode)
      layout = self._layoutIn(session, package)
      observations = _loadObservations(session, trialCode)
    return package, layout, observations

  def _documentFor(self, trialCode: str) -> TrialDocument:
    package, layout, observations = self._loadContext(trialCode)
    return TrialDocument(
      package=package, layout=layout.plots, checkPlots=layout.checkPlots, observations=observations,
    )
