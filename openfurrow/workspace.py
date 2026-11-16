# SPDX-License-Identifier: Apache-2.0
"""The OpenFurrow core facade -- the single surface every non-core caller uses.

Every non-core surface (the CLI, the HTTP service and its web interface, later apps)
reaches the core through a `Workspace` and the public schema/analysis result types,
never by importing store, analysis, exchange, or design internals directly. This is the
"one facade" invariant from the implementation plan: the math and the store have
exactly one caller-facing shape, so a surface can never drift from the core or
re-implement part of it.

A `Workspace` wraps one store (one system of record holding many trials) and exposes
the trial loop as methods: add a designed package, list and load trials, read the
layout, import observations, analyze, separate means, assess assumptions, build the
report, exchange portable files, hash, verify, and delete.

Every Workspace acts as someone (decisions 0036 to 0038). Each method checks that its
actor holds the permission it needs where it acts, and each change writes an audit event
in its own transaction. The command line and the library act as the store's operator,
and the open mode as everyone; both hold every permission. The service gives each request
a Workspace acting as the signed-in account (`actingAs`).

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

import datetime
import tempfile
from contextlib import contextmanager
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from openfurrow.analysis import (
  AnalysisError,
  AnovaResult,
  Assumptions,
  DunnettResult,
  FactorSeparation,
  FactorialResult,
  MeanComparison,
  MeanSeparation,
  SplitPlotResult,
  analyzeCrd as _analyzeCrd,
  compareWithControl as _compareWithControl,
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
  AssessmentCount,
  ImportResult,
  ObservationImportError,
  SheetTable,
  SpreadsheetError,
  countByAssessment as _countByAssessment,
  importTable as _importTable,
  readTable as _readTable,
)
from openfurrow.interop.fieldbook import (
  fieldBookImportProfile as _fieldBookImportProfile,
  writeFieldImport as _writeFieldImport,
  writeTraitFile as _writeTraitFile,
)
from openfurrow.reports import buildReport as _buildReport
from openfurrow.reports.report import ReportWithCharts, buildReportWithCharts as _buildReportWithCharts
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
from openfurrow.identity.model import (
  Account,
  Actor,
  ActorKind,
  Group,
  IdentityError,
  Permission,
  RoleAssignment,
  RoleDefinition,
  SignInMode,
)
from openfurrow.schema.hierarchy import HierarchyLevel, Place
from openfurrow.settings import EffectiveSetting
from openfurrow.store.audit import AuditEvent, events as _auditEvents, record as _record
from openfurrow.store.identity import (
  actorForToken as _actorForToken,
  assignRole as _assignRole,
  createAccount as _createAccount,
  createGroup as _createGroup,
  defineRole as _defineRole,
  deleteRole as _deleteRole,
  issueToken as _issueToken,
  listAccounts as _listAccounts,
  listAssignments as _listAssignments,
  listGroups as _listGroups,
  permissionsAt as _permissionsAt,
  revokeToken as _revokeToken,
  roles as _roles,
  scopesWithAssignments as _scopesWithAssignments,
  setActive as _setActive,
  setLocale as _setLocale,
  setMembership as _setMembership,
  setPassword as _setPassword,
  signIn as _signIn,
)
from openfurrow.store.hierarchy import (
  addPlace as _addPlace,
  deletePlace as _deletePlace,
  listPlaces as _listPlaces,
  loadLevels as _loadLevels,
  moveTrial as _moveTrial,
  replaceLevels as _replaceLevels,
  trialPlace as _trialPlace,
  trialsIn as _trialsIn,
)
from openfurrow.store.settingValues import (
  clearValue as _clearValue,
  effectiveSettings as _effectiveSettings,
  setValue as _setValue,
)
from openfurrow.store import (
  NotFoundError,
  StoreError,
  createDatabase as _createDatabase,
  isDatabaseURL as _isDatabaseURL,
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
  "IdentityError",
  "NotFoundError",
  "NotPermitted",
  "ObservationImportError",
  "RoundTripCheck",
  "StoreError",
  "Workspace",
  "availableLocales",
  "sourceLocale",
]


def _jsonSetting(setting: EffectiveSetting | None) -> dict | None:
  from openfurrow.settings import jsonValue
  if setting is None:
    return None
  return {"value": jsonValue(setting.key, setting.value), "source": setting.source}


class NotPermitted(PermissionError):
  """The actor does not hold the permission an operation needs where it acts; not bad input, so no form catches it."""


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
  """One store of trials -- a SQLite file or a PostgreSQL database -- and the trial loop over it.

  Construct with `Workspace.create(location)` for a new store or `Workspace.open(location)`
  for an existing one; `open` fails loud if the file is absent or the database holds no
  store, rather than silently creating an empty one. A location is a file path or a
  `postgresql+pg8000://` URL.
  """

  def __init__(self, engine, actor: Actor | None = None) -> None:
    # Code that holds the store's engine is its operator; a surface that serves people
    # gives each of them their own Workspace through actingAs.
    self._engine = engine
    self.actor = actor if actor is not None else Actor.operator("library")

  @classmethod
  def create(cls, location: str, actor: Actor | None = None) -> "Workspace":
    """Create (or open) the store at `location` and ensure its schema."""
    return cls(_createDatabase(location), actor)

  @classmethod
  def open(cls, location: str, actor: Actor | None = None) -> "Workspace":
    """Open an existing store; raise if the file does not exist or the database holds none."""
    if not _isDatabaseURL(location) and not Path(location).exists():
      raise StoreError(f"database '{location}' does not exist; create it first")
    return cls(_createDatabase(location, create=False), actor)

  def actingAs(self, actor: Actor) -> "Workspace":
    """The same store, acting as `actor`."""
    return Workspace(self._engine, actor)

  # ---- permissions and audit (decisions 0037, 0038) -----------------------

  def _require(self, session, permission: Permission, scope: str) -> None:
    held = _permissionsAt(session, self.actor, scope)
    if permission in held:
      return
    if Permission.view not in held and scope != "server":
      kind, _, name = scope.partition(":")
      raise NotFoundError(f"{kind} '{name}' not found")
    raise NotPermitted(f"{self.actor.label} may not {permission.value} at {scope}")

  @contextmanager
  def _acting(self, permission: Permission, scope: str):
    with _sessionScope(self._engine) as session:
      self._require(session, permission, scope)
      yield session

  def _audit(self, session, action: str, scope: str, detail: dict) -> None:
    _record(session, self.actor, action, scope, detail)

  def permissionsAt(self, scope: str) -> frozenset[Permission]:
    """What this workspace's actor may do at a scope."""
    with _sessionScope(self._engine) as session:
      return _permissionsAt(session, self.actor, scope)

  def auditEvents(self, scope: str = "server", limit: int = 200) -> list[AuditEvent]:
    """The latest audit events at a scope and inside it, newest first."""
    with self._acting(Permission.viewAudit, scope):
      pass
    with _sessionScope(self._engine) as session:
      return _auditEvents(session, None if scope == "server" else scope, limit)

  # ---- trial management ---------------------------------------------------

  def addPackage(self, package: TrialPackage, place: str | None) -> None:
    """Persist a validated trial package and the layout generated from its seed, in `place`.

    This is where a trial is randomized: once, here, and the layout is recorded. A
    package whose layout was made elsewhere carries no plots, so it cannot be added
    this way; such a trial comes in as a trial document (`importDocument`). The place is
    a path of the hierarchy's last level, or None when the store has no levels.
    """
    if package.design.randomizationMethod is RandomizationMethod.imported:
      raise StoreError(
        f"trial '{package.trial.trialCode}' declares an imported layout; supply it as a "
        f"trial document, which carries the plots"
      )
    layout = _generateLayout(package)
    scope = "server" if place is None else f"place:{place}"
    with self._acting(Permission.manageTrials, scope) as session:
      _savePackage(session, package, layout.plots, layout.checkPlots, place)
      self._audit(session, "trial.add", f"trial:{package.trial.trialCode}", {"place": place})

  def listTrials(self) -> list[tuple[str, str]]:
    """The trials the actor may view, as (trialCode, title) pairs."""
    with _sessionScope(self._engine) as session:
      return [
        (code, title) for code, title in _listTrials(session)
        if Permission.view in _permissionsAt(session, self.actor, f"trial:{code}")
      ]

  def loadPackage(self, trialCode: str) -> TrialPackage:
    """The trial package for `trialCode`; raises if the trial is unknown."""
    with self._acting(Permission.view, f"trial:{trialCode}") as session:
      return _loadPackage(session, trialCode)

  def loadObservations(self, trialCode: str) -> list[Observation]:
    """The stored observations for `trialCode` (empty if none imported yet)."""
    with self._acting(Permission.view, f"trial:{trialCode}") as session:
      return _loadObservations(session, trialCode)

  def deleteTrial(self, trialCode: str) -> None:
    """Delete a trial and all its observations."""
    with self._acting(Permission.manageTrials, f"trial:{trialCode}") as session:
      place = _trialPlace(session, trialCode)
      _deleteTrial(session, trialCode)
      self._audit(session, "trial.delete", f"trial:{trialCode}", {"place": place})

  # ---- hierarchy (decision 0034) ------------------------------------------

  def hierarchyLevels(self) -> list[HierarchyLevel]:
    """The hierarchy's levels, top first; the trial is always below the last."""
    with _sessionScope(self._engine) as session:
      return _loadLevels(session)

  def setHierarchyLevels(self, levels: list[HierarchyLevel]) -> None:
    """Replace the levels; only while the store holds no places and no trials."""
    with self._acting(Permission.manageStructure, "server") as session:
      _replaceLevels(session, levels)
      self._audit(session, "levels.set", "server", {"levels": [level.levelCode for level in levels]})

  def addPlace(self, parent: str | None, code: str, name: str) -> Place:
    """A new place inside `parent` (None for the first level)."""
    with self._acting(Permission.manageStructure, "server" if parent is None else f"place:{parent}") as session:
      place = _addPlace(session, parent, code, name)
      self._audit(session, "place.add", f"place:{place.path}", {"name": place.name})
      return place

  def places(self) -> list[Place]:
    """The places the actor may see: where it holds view, and the places above those."""
    with _sessionScope(self._engine) as session:
      every = _listPlaces(session)
      if self.actor.holdsEverything:
        return every
      visible = {place.path for place in every if Permission.view in _permissionsAt(session, self.actor, f"place:{place.path}")}
      for scope in _scopesWithAssignments(session, self.actor):
        if scope.startswith("trial:"):
          path = _trialPlace(session, scope.split(":", 1)[1])
        elif scope.startswith("place:"):
          path = scope.split(":", 1)[1]
        else:
          continue
        while path:
          visible.add(path)
          path = path.rpartition("/")[0]
      return [place for place in every if place.path in visible]

  def deletePlace(self, path: str) -> None:
    """Delete a place that holds no places and no trials."""
    with self._acting(Permission.manageStructure, f"place:{path}") as session:
      _deletePlace(session, path)
      self._audit(session, "place.delete", f"place:{path}", {})

  def placeOf(self, trialCode: str) -> str | None:
    with self._acting(Permission.view, f"trial:{trialCode}") as session:
      return _trialPlace(session, trialCode)

  def moveTrial(self, trialCode: str, place: str | None) -> None:
    """Put a trial in another place; the trial and its content hash are unchanged."""
    with self._acting(Permission.manageTrials, f"trial:{trialCode}") as session:
      self._require(session, Permission.manageTrials, "server" if place is None else f"place:{place}")
      before = _trialPlace(session, trialCode)
      _moveTrial(session, trialCode, place)
      self._audit(session, "trial.move", f"trial:{trialCode}", {"before": before, "after": place})

  def trialsIn(self, place: str) -> list[tuple[str, str]]:
    """The trials the actor may view anywhere inside a place, as (trialCode, title)."""
    with _sessionScope(self._engine) as session:
      return [
        (code, title) for code, title in _trialsIn(session, place)
        if Permission.view in _permissionsAt(session, self.actor, f"trial:{code}")
      ]

  # ---- settings (decision 0035) -------------------------------------------

  def setSetting(self, scope: str, key: str, value) -> None:
    """Set a setting at 'server', 'place:<path>' or 'trial:<code>'."""
    with self._acting(Permission.changeSettings, scope) as session:
      before = {setting.key: setting for setting in _effectiveSettings(session, scope)}.get(key)
      _setValue(session, scope, key, value)
      after = {setting.key: setting for setting in _effectiveSettings(session, scope)}[key]
      if key == "identity.signInMode" and after.value is SignInMode.accounts:
        self._requireAnAdministrator(session)
      self._audit(session, "setting.set", scope, {"key": key, "before": _jsonSetting(before), "after": _jsonSetting(after)})

  def clearSetting(self, scope: str, key: str) -> None:
    with self._acting(Permission.changeSettings, scope) as session:
      _clearValue(session, scope, key)
      after = {setting.key: setting for setting in _effectiveSettings(session, scope)}[key]
      if key == "identity.signInMode" and after.value is SignInMode.accounts:
        self._requireAnAdministrator(session)
      self._audit(session, "setting.clear", scope, {"key": key, "after": _jsonSetting(after)})

  def effectiveSettings(self, scope: str) -> list[EffectiveSetting]:
    """Every setting's value at a scope, and where it was set."""
    with self._acting(Permission.view, scope) if scope != "server" else _sessionScope(self._engine) as session:
      return _effectiveSettings(session, scope)

  def signInMode(self) -> SignInMode:
    """How the service knows who acts: everyone (open) or signed-in accounts."""
    with _sessionScope(self._engine) as session:
      return {s.key: s.value for s in _effectiveSettings(session, "server")}["identity.signInMode"]

  def _requireAnAdministrator(self, session) -> None:
    administrators = [
      assignment for assignment in _listAssignments(session)
      if assignment.roleCode == "administrator" and assignment.scope == "server" and assignment.userName is not None
    ]
    active = {account.userName for account in _listAccounts(session) if account.active}
    if not any(assignment.userName in active for assignment in administrators):
      raise IdentityError(
        "sign-in by accounts needs an active account that is administrator at the server first; "
        "otherwise nobody could sign in to manage the store"
      )

  def _analysisSettings(self, trialCode: str) -> tuple[float, MeanComparison, list[EffectiveSetting]]:
    effective = self.effectiveSettings(f"trial:{trialCode}")
    values = {setting.key: setting.value for setting in effective}
    return values["analysis.significanceLevel"], values["analysis.meanComparison"], effective


  # ---- accounts, groups and roles (decisions 0036, 0037) -------------------

  def createAccount(self, userName: str, displayName: str, email: str | None = None, password: str | None = None) -> Account:
    with self._acting(Permission.manageAccess, "server") as session:
      account = _createAccount(session, userName, displayName, email, password)
      self._audit(session, "account.create", "server", {"userName": account.userName})
      return account

  def accounts(self) -> list[Account]:
    with self._acting(Permission.manageAccess, "server") as session:
      return _listAccounts(session)

  def _selfOrManager(self, session, userName: str) -> None:
    if self.actor.kind is ActorKind.account and self.actor.userName == userName.strip().lower():
      return
    self._require(session, Permission.manageAccess, "server")

  def setPassword(self, userName: str, password: str) -> None:
    """A person sets their own password; an access manager sets anyone's."""
    with _sessionScope(self._engine) as session:
      self._selfOrManager(session, userName)
      _setPassword(session, userName, password)
      self._audit(session, "account.password", "server", {"userName": userName})

  def setAccountActive(self, userName: str, active: bool) -> None:
    """Deactivating an account ends its sessions and tokens."""
    with self._acting(Permission.manageAccess, "server") as session:
      _setActive(session, userName, active)
      self._audit(session, "account.active", "server", {"userName": userName, "active": active})

  def setPreferredLocale(self, userName: str, locale: str | None) -> None:
    from openfurrow.i18n import availableLocales
    if locale is not None and locale not in availableLocales():
      raise IdentityError(f"'{locale}' is not one of the locales {availableLocales()}")
    with _sessionScope(self._engine) as session:
      self._selfOrManager(session, userName)
      _setLocale(session, userName, locale)

  def createGroup(self, name: str) -> Group:
    with self._acting(Permission.manageAccess, "server") as session:
      group = _createGroup(session, name)
      self._audit(session, "group.create", "server", {"group": group.name})
      return group

  def setMembership(self, groupName: str, userName: str, member: bool) -> None:
    with self._acting(Permission.manageAccess, "server") as session:
      _setMembership(session, groupName, userName, member)
      self._audit(session, "group.member", "server", {"group": groupName, "userName": userName, "member": member})

  def groups(self) -> list[Group]:
    with self._acting(Permission.manageAccess, "server") as session:
      return _listGroups(session)

  def defineRole(self, role: RoleDefinition) -> None:
    with self._acting(Permission.manageAccess, "server") as session:
      _defineRole(session, role)
      self._audit(session, "role.define", "server", {"role": role.roleCode, "permissions": sorted(p.value for p in role.permissions)})

  def deleteRole(self, roleCode: str) -> None:
    with self._acting(Permission.manageAccess, "server") as session:
      _deleteRole(session, roleCode)
      self._audit(session, "role.delete", "server", {"role": roleCode})

  def roles(self) -> dict[str, RoleDefinition]:
    with _sessionScope(self._engine) as session:
      return _roles(session)

  def assignRole(self, assignment: RoleAssignment) -> None:
    """Give a role at a scope; an access manager there may give it."""
    with self._acting(Permission.manageAccess, assignment.scope) as session:
      _assignRole(session, assignment)
      self._audit(session, "role.assign", assignment.scope, assignment.model_dump(exclude_none=True))

  def unassignRole(self, assignment: RoleAssignment) -> None:
    with self._acting(Permission.manageAccess, assignment.scope) as session:
      _assignRole(session, assignment, given=False)
      self._audit(session, "role.unassign", assignment.scope, assignment.model_dump(exclude_none=True))

  def assignments(self) -> list[RoleAssignment]:
    with self._acting(Permission.manageAccess, "server") as session:
      return _listAssignments(session)

  # ---- signing in (decision 0036) -----------------------------------------

  def signIn(self, userName: str, password: str, surface: str) -> tuple[Account, str]:
    """Check a user name and password; return the account and a new session token."""
    with _sessionScope(self._engine) as session:
      hours = {s.key: s.value for s in _effectiveSettings(session, "server")}["identity.sessionHours"]
      try:
        account = _signIn(session, userName, password)
      except IdentityError:
        _record(session, Actor.everyone(surface), "signIn.refused", "server", {"userName": userName.strip().lower()})
        session.commit()
        raise
      token = _issueToken(session, account.userName, "session", datetime.timedelta(hours=hours), None)
      _record(session, Actor(kind=ActorKind.account, accountID=account.accountID, userName=account.userName, surface=surface),
              "signIn", "server", {})
      return account, token

  def actorForSession(self, token: str, surface: str) -> Actor:
    with _sessionScope(self._engine) as session:
      return _actorForToken(session, token, "session", surface)

  def actorForAPIToken(self, token: str, surface: str) -> Actor:
    with _sessionScope(self._engine) as session:
      return _actorForToken(session, token, "api", surface)

  def issueAPIToken(self, name: str, days: int | None) -> str:
    """A token for this workspace's own account, to use from scripts; shown once."""
    if self.actor.kind is not ActorKind.account:
      raise IdentityError("an API token belongs to an account; sign in first")
    with _sessionScope(self._engine) as session:
      token = _issueToken(session, self.actor.userName, "api", None if days is None else datetime.timedelta(days=days), name)
      self._audit(session, "token.issue", "server", {"name": name, "days": days})
      return token

  def signOut(self, token: str) -> None:
    with _sessionScope(self._engine) as session:
      _revokeToken(session, token)

  def account(self) -> Account | None:
    """The signed-in account this workspace acts as, if any."""
    if self.actor.kind is not ActorKind.account:
      return None
    with _sessionScope(self._engine) as session:
      return next(a for a in _listAccounts(session) if a.accountID == self.actor.accountID)

  # ---- layout -------------------------------------------------------------

  def layoutFor(self, trialCode: str) -> TrialLayout:
    """The trial's recorded layout."""
    with self._acting(Permission.view, f"trial:{trialCode}") as session:
      return self._layoutIn(session, _loadPackage(session, trialCode))

  # ---- observations -------------------------------------------------------

  @staticmethod
  def readObservationTable(fileName: str, data: bytes, sheetName: str | None = None) -> SheetTable:
    """Read a .csv or .xlsx file's bytes into a table to preview and map (decision 0031)."""
    try:
      return _readTable(fileName, data, sheetName)
    except SpreadsheetError as error:
      raise ObservationImportError(str(error)) from error

  def importObservations(
    self,
    trialCode: str,
    path: str,
    importProfile: ImportProfile,
    sheetName: str | None = None,
  ) -> ImportResult:
    """Import observations from a .csv or .xlsx file against the trial's layout and save them."""
    file = Path(path)
    return self.importObservationTable(
      trialCode, self.readObservationTable(file.name, file.read_bytes(), sheetName), importProfile,
    )

  def importObservationTable(self, trialCode: str, table: SheetTable, importProfile: ImportProfile) -> ImportResult:
    """Import a table's observations against the trial's layout and save them.

    Values are validated against the package and layout at the boundary; a bad plot,
    code, or out-of-domain value is rejected rather than partially saved. An import
    adds values and never replaces stored ones: a plot and assessment the trial already
    holds a value for refuses the whole file.
    """
    with self._acting(Permission.importValues, f"trial:{trialCode}") as session:
      package = _loadPackage(session, trialCode)
      layout = self._layoutIn(session, package)
      result = _importTable(table, package, layout, importProfile)
      stored = {(o.plotNumber, o.assessmentCode) for o in _loadObservations(session, trialCode)}
      clashes = sorted(
        (o.plotNumber, o.assessmentCode) for o in result.observations if (o.plotNumber, o.assessmentCode) in stored
      )
      if clashes:
        shown = ", ".join(f"plot {plot} '{code}'" for plot, code in clashes[:5])
        raise ObservationImportError(
          f"trial '{trialCode}' already holds {len(clashes)} of these values ({shown}"
          f"{', ...' if len(clashes) > 5 else ''}); an import never replaces stored values, so change "
          f"them on the entry page"
        )
      _saveObservations(session, trialCode, result.observations)
      self._audit(session, "values.import", f"trial:{trialCode}", {
        "file": table.fileName, "sheet": table.sheetName, "values": len(result.observations),
        "assessments": sorted({o.assessmentCode for o in result.observations}),
      })
    return result

  def countImported(self, trialCode: str, result: ImportResult) -> list[AssessmentCount]:
    """Each imported assessment's values against the trial's plots."""
    return _countByAssessment(result, self.layoutFor(trialCode))

  # ---- analysis -----------------------------------------------------------

  def analyze(self, trialCode: str, assessmentCode: str) -> AnovaResult | SplitPlotResult:
    """Run the ANOVA the trial's design calls for, for one numeric assessment."""
    package, layout, observations = self._loadContext(trialCode)
    if package.design.designType is DesignType.splitPlot:
      return _analyzeSplitPlot(assessmentCode, package, layout, observations)
    if package.design.designType is DesignType.crd:
      return _analyzeCrd(assessmentCode, package, layout, observations)
    return _analyzeRcbd(assessmentCode, package, layout, observations)

  def separateFactorMeans(self, trialCode: str, assessmentCode: str, factor: str) -> FactorSeparation:
    """Separate the level means of one factor of a split plot or a two-factor RCBD, by the trial's settings."""
    significanceLevel, meanComparison, _ = self._analysisSettings(trialCode)
    result = self.analyze(trialCode, assessmentCode)
    if isinstance(result, SplitPlotResult):
      return _separateFactorMeans(result, factor, significanceLevel=significanceLevel, meanComparison=meanComparison)
    package, layout, observations = self._loadContext(trialCode)
    if not package.factors:
      raise AnalysisError(f"trial '{trialCode}' has no factors to separate")
    factorial = _analyzeFactorialRcbd(assessmentCode, package, layout, observations)
    return _separateFactorialMeans(factorial, factor, significanceLevel=significanceLevel, meanComparison=meanComparison)

  def compareWithControl(self, trialCode: str, assessmentCode: str) -> DunnettResult:
    """Dunnett's two-sided test of every treatment against the untreated check (decision 0029)."""
    significanceLevel, _, _ = self._analysisSettings(trialCode)
    result = self.analyze(trialCode, assessmentCode)
    if isinstance(result, (SplitPlotResult, FactorialResult)):
      raise AnalysisError(f"trial '{trialCode}' compares factor levels, not treatments against a check")
    return _compareWithControl(result, self.loadPackage(trialCode), significanceLevel)

  def analyzeFactorial(self, trialCode: str, assessmentCode: str) -> FactorialResult:
    """The factorial ANOVA of a two-factor RCBD (decision 0025)."""
    package, layout, observations = self._loadContext(trialCode)
    return _analyzeFactorialRcbd(assessmentCode, package, layout, observations)

  def separateMeans(self, trialCode: str, assessmentCode: str) -> MeanSeparation:
    """Separate treatment means for one assessment, by the trial's settings."""
    significanceLevel, meanComparison, _ = self._analysisSettings(trialCode)
    result = self.analyze(trialCode, assessmentCode)
    if isinstance(result, SplitPlotResult):
      raise AnalysisError(
        f"trial '{trialCode}' is a split plot; its means are separated for each factor (separateFactorMeans)"
      )
    return _separateMeans(result, significanceLevel=significanceLevel, meanComparison=meanComparison)

  def assessAssumptions(self, trialCode: str, assessmentCode: str) -> Assumptions:
    """Compute the report-only ANOVA assumption diagnostics for one assessment."""
    significanceLevel, _, _ = self._analysisSettings(trialCode)
    package, layout, observations = self._loadContext(trialCode)
    return _assessAssumptions(assessmentCode, package, layout, observations, significanceLevel)

  # ---- reporting ----------------------------------------------------------

  def buildReport(self, trialCode: str, locale: str = sourceLocale) -> str:
    """Build the full Markdown trial report (the AOV Means Table and provenance), by the trial's settings.

    `locale` is a display choice only: it selects the message catalog and number
    formatting. It does not touch the stored data, the exchange, or the content hash.
    """
    significanceLevel, meanComparison, effective = self._analysisSettings(trialCode)
    package, layout, observations = self._loadContext(trialCode)
    return _buildReport(
      package, layout, observations,
      significanceLevel=significanceLevel, meanComparison=meanComparison, locale=locale, settingsUsed=effective,
    )

  def buildReportWithCharts(self, trialCode: str, marker: str, locale: str = sourceLocale) -> ReportWithCharts:
    """The report with a marker line where each chart of means goes, and the charts (decision 0032)."""
    significanceLevel, meanComparison, effective = self._analysisSettings(trialCode)
    package, layout, observations = self._loadContext(trialCode)
    return _buildReportWithCharts(
      package, layout, observations, marker,
      significanceLevel=significanceLevel, meanComparison=meanComparison, locale=locale, settingsUsed=effective,
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

  def importDocument(self, jsonPath: str, place: str | None) -> str:
    """Import a portable trial document JSON into this store, in `place`; return its trialCode."""
    return self.addDocument(_importJson(jsonPath), place)

  def addDocument(self, document: TrialDocument, place: str | None) -> str:
    """Store a validated trial document (its package, plots, checks and values) in `place`; return its trialCode."""
    trialCode = document.package.trial.trialCode
    with self._acting(Permission.manageTrials, "server" if place is None else f"place:{place}") as session:
      _savePackage(session, document.package, document.layout, document.checkPlots, place)
      _saveObservations(session, trialCode, document.observations)
      self._audit(session, "trial.add", f"trial:{trialCode}", {"place": place, "values": len(document.observations)})
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
    with self._acting(Permission.enterValues, f"trial:{trialCode}") as session:
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
      stored = {
        (o.plotNumber, o.subsample): o.value for o in _loadObservations(session, trialCode)
        if o.assessmentCode == assessmentCode
      }
      entered = {(o.plotNumber, o.subsample): o.value for o in observations}
      changes = [
        {"plot": plot, "subsample": subsample, "before": stored.get((plot, subsample)), "after": entered.get((plot, subsample))}
        for plot, subsample in sorted(set(stored) | set(entered), key=lambda key: (key[0], key[1] or 0))
        if stored.get((plot, subsample)) != entered.get((plot, subsample))
      ]
      _replaceAssessmentObservations(session, trialCode, assessmentCode, observations)
      self._audit(session, "values.record", f"trial:{trialCode}", {"assessment": assessmentCode, "changes": changes})

  def importWeather(self, trialCode: str, csvPath: str) -> int:
    """Replace the trial's weather log with the days a CSV lists; return how many (REC-13).

    The trial with its new log is validated as a whole before anything is saved.
    """
    records = _readWeatherCsv(csvPath)
    with self._acting(Permission.editRecord, f"trial:{trialCode}") as session:
      package = _loadPackage(session, trialCode)
      data = package.model_dump(mode="json")
      data["weather"] = [record.model_dump(mode="json") for record in records]
      TrialPackage.model_validate(data)
      _replaceWeather(session, trialCode, records)
      self._audit(session, "weather.import", f"trial:{trialCode}", {"file": Path(csvPath).name, "days": len(records)})
    return len(records)

  def importFieldBook(self, trialCode: str, databaseCsvPath: str) -> ImportResult:
    """Ingest a Field Book database (long) export into the trial's observations.

    Reuses the standard importer with the Field Book column mapping: the export's
    unique-id column is the plot, `trait` the assessment code, `value` the value;
    the provenance columns (timestamp, person, device_name, ...) are ignored.
    """
    return self.importObservations(trialCode, databaseCsvPath, _fieldBookImportProfile())

  # ---- internals ----------------------------------------------------------

  @staticmethod
  def _layoutIn(session, package: TrialPackage) -> TrialLayout:
    trialCode = package.trial.trialCode
    return TrialLayout.forPackage(package, _loadLayout(session, trialCode), _loadCheckPlots(session, trialCode))

  def _loadContext(self, trialCode: str) -> tuple[TrialPackage, TrialLayout, list[Observation]]:
    """Load the package, the layout and the observations in one session."""
    with self._acting(Permission.view, f"trial:{trialCode}") as session:
      package = _loadPackage(session, trialCode)
      layout = self._layoutIn(session, package)
      observations = _loadObservations(session, trialCode)
    return package, layout, observations

  def _documentFor(self, trialCode: str) -> TrialDocument:
    package, layout, observations = self._loadContext(trialCode)
    return TrialDocument(
      package=package, layout=layout.plots, checkPlots=layout.checkPlots, observations=observations,
    )
