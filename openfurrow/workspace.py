# SPDX-License-Identifier: Apache-2.0
"""The OpenFurrow core facade -- the single surface every non-core caller uses.

Every non-core surface (the CLI, the future Flask service, later apps) reaches the
core through a `Workspace` and the public schema/analysis result types, never by
importing store, analysis, exchange, or design internals directly. This is the
"one facade" invariant from the implementation plan: the math and the store have
exactly one caller-facing shape, so a surface can never drift from the core or
re-implement part of it.

A `Workspace` wraps one SQLite database (one system of record holding many trials)
and exposes the trial loop as methods: add a designed package, list and load
trials, regenerate the layout, import observations, analyze, separate means, assess
assumptions, build the report, exchange portable files, hash, verify, and delete.

Lifetime: a Workspace holds the SQLAlchemy engine and opens a fresh session per
method call. The engine is the poolable, reusable resource (a long-running service
keeps one); the session is the unit of work (one CLI command or one HTTP request is
one transaction), so no session state leaks across calls. Composite operations that
need the package, layout, and observations together load them in a single session
and regenerate the layout from the recorded seed (the layout is derived, never
stored or hashed separately).

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
  MeanSeparation,
  analyzeRcbd as _analyzeRcbd,
  assessAssumptions as _assessAssumptions,
  separateMeans as _separateMeans,
)
from openfurrow.config import ImportProfile
from openfurrow.design import generateRcbdLayout as _generateRcbdLayout
from openfurrow.exchange import (
  ExchangeError,
  exportJson as _exportJson,
  exportObservationsCsv as _exportObservationsCsv,
  importJson as _importJson,
)
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
  Observation,
  TrialDocument,
  TrialLayout,
  TrialPackage,
  contentHash as _contentHash,
)
from openfurrow.store import (
  StoreError,
  createDatabase as _createDatabase,
  deleteTrial as _deleteTrial,
  listTrials as _listTrials,
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
  "ObservationImportError",
  "RoundTripCheck",
  "StoreError",
  "Workspace",
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
    """Persist a validated trial package (the design document for one trial)."""
    with _sessionScope(self._engine) as session:
      _savePackage(session, package)

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
    """Regenerate the randomized layout from the trial's recorded seed."""
    return _generateRcbdLayout(self.loadPackage(trialCode))

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
      layout = _generateRcbdLayout(package)
      result = _importObservations(csvPath, package, layout, importProfile)
      _saveObservations(session, trialCode, result.observations)
    return result

  # ---- analysis -----------------------------------------------------------

  def analyze(self, trialCode: str, assessmentCode: str) -> AnovaResult:
    """Run the RCBD ANOVA for one numeric assessment."""
    package, layout, observations = self._loadContext(trialCode)
    return _analyzeRcbd(assessmentCode, package, layout, observations)

  def separateMeans(
    self,
    trialCode: str,
    assessmentCode: str,
    significanceLevel: float = 0.05,
    protected: bool = True,
  ) -> MeanSeparation:
    """Separate treatment means by Fisher's (Protected) LSD for one assessment."""
    result = self.analyze(trialCode, assessmentCode)
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
  ) -> str:
    """Build the full Markdown trial report (the AOV Means Table and provenance)."""
    package, layout, observations = self._loadContext(trialCode)
    return _buildReport(
      package, layout, observations,
      significanceLevel=significanceLevel, protected=protected,
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
    document = _importJson(jsonPath)
    trialCode = document.package.trial.trialCode
    with _sessionScope(self._engine) as session:
      _savePackage(session, document.package)
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

  def importFieldBook(self, trialCode: str, databaseCsvPath: str) -> ImportResult:
    """Ingest a Field Book database (long) export into the trial's observations.

    Reuses the standard importer with the Field Book column mapping: the export's
    unique-id column is the plot, `trait` the assessment code, `value` the value;
    the provenance columns (timestamp, person, device_name, ...) are ignored.
    """
    with _sessionScope(self._engine) as session:
      package = _loadPackage(session, trialCode)
      layout = _generateRcbdLayout(package)
      result = _importObservations(databaseCsvPath, package, layout, _fieldBookImportProfile())
      _saveObservations(session, trialCode, result.observations)
    return result

  # ---- internals ----------------------------------------------------------

  def _loadContext(self, trialCode: str) -> tuple[TrialPackage, TrialLayout, list[Observation]]:
    """Load package and observations in one session and regenerate the layout."""
    with _sessionScope(self._engine) as session:
      package = _loadPackage(session, trialCode)
      observations = _loadObservations(session, trialCode)
    layout = _generateRcbdLayout(package)
    return package, layout, observations

  def _documentFor(self, trialCode: str) -> TrialDocument:
    package, _, observations = self._loadContext(trialCode)
    return TrialDocument(package=package, observations=observations)
