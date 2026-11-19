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
a Workspace acting as the signed-in account, or as the workload rule that accepted the
request's token (decision 0042), through `actingAs`.

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

import dataclasses
import datetime
import json
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from carnelian.cas import CASRefused, Pending as CASPending, readLogoutRequest as _readCASLogout
from carnelian.ldap import DirectoryRefused
from carnelian.oidc import Pending as OpenIDConnectPending, SignInRefused
from carnelian.saml import Pending as SAMLPending, SAMLRefused, claimedIssuer as _claimedSAMLIssuer
from carnelian.scim import SCIMService
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
  MissingPlotPolicy,
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
from openfurrow.importers.weatherCsv import readWeatherCsv as _readWeatherCsv
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
  foldedUserName as _foldedUserName,
)
from openfurrow.schema.hierarchy import HierarchyLevel, Place
from openfurrow.settings import EffectiveSetting
from openfurrow.store.audit import AuditEvent, EventFilter, events as _auditEvents, record as _record
from openfurrow.store.identity import (
  actorForToken as _actorForToken,
  assignRole as _assignRole,
  assignmentsOfRule as _assignmentsOfRule,
  createAccount as _createAccount,
  createGroup as _createGroup,
  defineRole as _defineRole,
  deleteGroup as _deleteGroup,
  deleteRole as _deleteRole,
  issueToken as _issueToken,
  listAccounts as _listAccounts,
  listAssignments as _listAssignments,
  listGroups as _listGroups,
  permissionsAt as _permissionsAt,
  revokeToken as _revokeToken,
  roles as _roles,
  scopesGranting as _scopesGranting,
  scopesWithAssignments as _scopesWithAssignments,
  setActive as _setActive,
  setLocale as _setLocale,
  setMembership as _setMembership,
  setPassword as _setPassword,
  signIn as _signIn,
)
from openfurrow.identity.providers import (
  ProvidedIdentity,
  Provider,
  ProviderFailure,
  ProviderKind,
  casServer as _casServer,
  directory as _directory,
  federationMetadata as _federationMetadata,
  samlMetadata as _samlMetadata,
  federationServiceProvider as _federationServiceProvider,
  fromCAS as _fromCAS,
  fromDirectory as _fromDirectory,
  fetchDiscovery as _fetchDiscovery,
  fromFederation as _fromFederation,
  institution as _institution,
  fromOpenIDConnect as _fromOpenIDConnect,
  fromSAML as _fromSAML,
  relyingParty as _relyingParty,
  serviceProvider as _serviceProvider,
)
from openfurrow.store.providers import (
  LinkedIdentity,
  StoredReplays as _StoredReplays,
  addProvider as _addProvider,
  claimOnce as _claimOnce,
  completeSignIn as _completeSignIn,
  endProviderSessions as _endProviderSessions,
  identitiesOf as _identitiesOf,
  issueProvisioningToken as _issueProvisioningToken,
  linkIdentity as _linkIdentity,
  listProviders as _listProviders,
  provider as _providerNamed,
  providerSessionOf as _providerSessionOf,
  provisioningTokenMatches as _provisioningTokenMatches,
  recordProviderSession as _recordProviderSession,
  setProviderEnabled as _setProviderEnabled,
  startPending as _startPending,
  takePending as _takePending,
)
from openfurrow.store.provisioning import ProvisioningStore
from openfurrow.identity.workloads import (
  WorkloadRule,
  WorkloadTokenRefused,
  acceptingRule as _acceptingRule,
  claimedIssuer as _claimedWorkloadIssuer,
  isWorkloadToken as _isWorkloadToken,
  runOf as _runOf,
)
from openfurrow.store.workloads import (
  addRule as _addWorkloadRule,
  enabledRulesOf as _enabledRulesOf,
  listRules as _listWorkloadRules,
  removeRule as _removeWorkloadRule,
  rule as _workloadRuleNamed,
  setRuleEnabled as _setWorkloadRuleEnabled,
)
from openfurrow.store.discovery import (
  discoveryList as _discoveryList,
  isDiscovered as _isDiscovered,
  replaceDiscovery as _replaceDiscovery,
  searchDiscovery as _searchDiscovery,
)
from openfurrow.store.tasks import (
  createTask as _createTask,
  deleteTask as _deleteTask,
  heartbeat as _schedulerHeartbeat,
  listTasks as _listTasks,
  requestRun as _requestRun,
  rescheduleAll as _rescheduleAll,
  runs as _taskRuns,
  setEnabled as _setTaskEnabled,
  setSchedule as _setSchedule,
  setTimeLimit as _setTimeLimit,
  task as _taskNamed,
)
from openfurrow.tasks.kinds import registeredKinds as _registeredTaskKinds
from openfurrow.tasks.model import SchedulerHeartbeat, Task, TaskError, TaskKind, TaskRun

_redirectKinds = (ProviderKind.openIDConnect, ProviderKind.saml, ProviderKind.samlFederation, ProviderKind.cas)
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
  "EventFilter",
  "ExchangeError",
  "MessageError",
  "IdentityError",
  "NotFoundError",
  "NotPermitted",
  "ObservationImportError",
  "RoundTripCheck",
  "SignOutOutcome",
  "StoreError",
  "TaskError",
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

  def __init__(self, who: str, permission: Permission, scope: str) -> None:
    super().__init__(f"{who} may not {permission.value} at {scope}")
    self.permission = permission
    self.scope = scope


institutionSearchLimit = 50


def federationRefreshTaskName(providerName: str) -> str:
  return f"federationRefresh-{providerName}"


def _utcNow() -> datetime.datetime:
  return datetime.datetime.now(datetime.UTC)


@dataclasses.dataclass(frozen=True)
class AnalysisSettings:
  """The settings a trial's analyses run under (decision 0035), and every effective setting with where it was set."""

  significanceLevel: float
  meanComparison: MeanComparison
  missingPlots: MissingPlotPolicy
  effective: list[EffectiveSetting]


@dataclasses.dataclass(frozen=True)
class InstitutionChoices:
  """What a federation's choose-institution page shows: whether it searches a stored list, whether that list is loaded
  yet, the institutions to offer, and whether more matched than are shown."""

  searchable: bool
  loaded: bool
  institutions: list[tuple[str, str]]
  more: bool


@dataclasses.dataclass(frozen=True)
class DiscoveryOutcome:
  offered: int
  hidden: int
  skipped: list[tuple[str, str]]
  validUntil: datetime.datetime


@dataclasses.dataclass(frozen=True)
class SignOutOutcome:
  """A sign-out, the session here already ended: the provider it came from, and where the browser goes next to sign
  out there too (with the key of the pending logout's cookie when an answer comes back), or why it cannot."""

  provider: str | None
  address: str | None = None
  pendingKey: str | None = None
  problem: str | None = None


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
    raise NotPermitted(self.actor.label, permission, scope)

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

  def require(self, permission: Permission, scope: str) -> None:
    """Refuse unless this workspace's actor holds a permission at a scope: for a page made of reads that are open
    to everyone but that is meant for the holders of one permission."""
    with self._acting(permission, scope):
      pass

  def scopesGranting(self, permission: Permission) -> list[str]:
    """The scopes where a role given to this workspace's actor carries a permission, the server first."""
    with _sessionScope(self._engine) as session:
      return _scopesGranting(session, self.actor, permission)

  def auditEvents(self, scope: str = "server", limit: int = 200, chosen: EventFilter = EventFilter()) -> list[AuditEvent]:
    """The latest audit events at a scope and inside it, newest first: at the server every event; at a place its
    own, those of the places inside it and of the trials in them; at a trial its own. `chosen` narrows them."""
    with self._acting(Permission.viewAudit, scope) as session:
      kind, _, name = scope.partition(":")
      if scope == "server":
        return _auditEvents(session, limit=limit, chosen=chosen)
      if kind == "place":
        return _auditEvents(session, name, [code for code, _ in _trialsIn(session, name)], limit, chosen)
      return _auditEvents(session, None, [name], limit, chosen)

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
      if key == "tasks.timeZone":
        _rescheduleAll(session, _utcNow())
      self._audit(session, "setting.set", scope, {"key": key, "before": _jsonSetting(before), "after": _jsonSetting(after)})

  def clearSetting(self, scope: str, key: str) -> None:
    with self._acting(Permission.changeSettings, scope) as session:
      _clearValue(session, scope, key)
      after = {setting.key: setting for setting in _effectiveSettings(session, scope)}[key]
      if key == "identity.signInMode" and after.value is SignInMode.accounts:
        self._requireAnAdministrator(session)
      if key == "tasks.timeZone":
        _rescheduleAll(session, _utcNow())
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

  def _analysisSettings(self, trialCode: str) -> AnalysisSettings:
    effective = [setting for setting in self.effectiveSettings(f"trial:{trialCode}") if setting.key.startswith("analysis.")]
    values = {setting.key: setting.value for setting in effective}
    return AnalysisSettings(
      significanceLevel=values["analysis.significanceLevel"], meanComparison=values["analysis.meanComparison"],
      missingPlots=values["analysis.missingPlots"], effective=effective,
    )


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
    if self.actor.kind is ActorKind.account and self.actor.userName == _foldedUserName(userName):
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

  def deleteGroup(self, name: str) -> None:
    """Delete a group and, with it, its memberships and every role given to it; a mirrored group is its provider's."""
    with self._acting(Permission.manageAccess, "server") as session:
      given = _deleteGroup(session, name)
      self._audit(session, "group.delete", "server", {
        "group": name, "roles": [{"roleCode": roleCode, "scope": scope} for roleCode, scope in given]})

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
        _record(session, Actor.everyone(surface), "signIn.refused", "server", {"userName": _foldedUserName(userName)})
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

  def actorForBearerToken(self, token: str, surface: str) -> Actor:
    """Who a request's bearer token stands for: a workload when the token has the form of a JSON Web Token (decision
    0042), otherwise the account whose API token it is."""
    if _isWorkloadToken(token):
      return self.actorForWorkloadToken(token, surface)
    return self.actorForAPIToken(token, surface)

  def issueAPIToken(self, name: str, days: int | None) -> str:
    """A token for this workspace's own account, to use from scripts; shown once."""
    if self.actor.kind is not ActorKind.account:
      raise IdentityError("an API token belongs to an account; sign in first")
    with _sessionScope(self._engine) as session:
      token = _issueToken(session, self.actor.userName, "api", None if days is None else datetime.timedelta(days=days), name)
      self._audit(session, "token.issue", "server", {"name": name, "days": days})
      return token

  def signOut(self, token: str, surface: str) -> SignOutOutcome:
    """End a session here; when it came from a provider whose signOutEverywhere is set, also say where the browser
    goes to sign out there. A failure at the provider leaves the session here ended, and is said and audited."""
    with _sessionScope(self._engine) as session:
      try:
        actor = _actorForToken(session, token, "session", surface)
      except IdentityError:
        return SignOutOutcome(provider=None)
      held = _providerSessionOf(session, token)
      provider = _providerNamed(session, held.providerName) if held is not None else None
      everywhere = provider is not None and provider.settings.signOutEverywhere
      _revokeToken(session, token)
      detail = {"everywhere": everywhere} | ({"provider": provider.name} if provider is not None else {})
      _record(session, actor, "signOut", "server", detail)
      session.commit()
      if not everywhere:
        return SignOutOutcome(provider=provider.name if provider is not None else None)
      try:
        address, key = self._signOutAt(session, provider, held, actor)
      except (SignInRefused, SAMLRefused, CASRefused, IdentityError) as error:
        session.rollback()
        _record(session, actor, "signOut.atProvider.failed", "server", {"provider": provider.name, "why": str(error)})
        return SignOutOutcome(provider=provider.name, problem=str(error))
      _record(session, actor, "signOut.atProvider", "server", {"provider": provider.name})
      return SignOutOutcome(provider=provider.name, address=address, pendingKey=key)

  def _signOutAt(self, session, provider: Provider, held, actor: Actor) -> tuple[str, str | None]:
    settings = provider.settings
    if provider.kind is ProviderKind.openIDConnect:
      return _relyingParty(settings).logoutAddress(held.detail["idToken"], settings.signedOutURL), None
    if provider.kind is ProviderKind.cas:
      return _casServer(settings).logoutAddress(settings.signedOutURL), None
    institution = held.detail.get("institution")
    address, pending = self._samlServiceProvider(provider, institution).beginSignOut(
      held.detail["nameID"], held.detail["nameIDFormat"], held.detail["sessionIndex"])
    key = _startPending(session, provider.name, {"purpose": "signOut", "protocol": dataclasses.asdict(pending),
                                                 "institution": institution, "accountID": actor.accountID,
                                                 "userName": actor.userName})
    return address, key

  def _samlServiceProvider(self, provider: Provider, institution: str | None):
    if provider.kind is ProviderKind.saml:
      return _serviceProvider(provider.settings, _StoredReplays(self._engine))
    return _federationServiceProvider(provider.settings, _institution(provider.settings, institution),
                                      _StoredReplays(self._engine))

  def finishProviderSignOut(self, name: str, key: str, query: str | None, samlResponse: str | None,
                            surface: str) -> tuple[str | None, str | None]:
    """A SAML identity provider's answer to signing out there: where the person goes next (the provider's signedOutURL,
    if any), and why the answer is refused, if it is; the session here ended already."""
    with _sessionScope(self._engine) as session:
      pendingName, state = _takePending(session, key)
      session.commit()
      if pendingName != name or state["purpose"] != "signOut":
        raise IdentityError(f"this browser is not signing out at {name}")
      actor = Actor(kind=ActorKind.account, accountID=state["accountID"], userName=state["userName"], surface=surface)
      provider = _providerNamed(session, name)
      try:
        self._samlServiceProvider(provider, state["institution"]).finishSignOut(
          SAMLPending(**state["protocol"]), query=query, samlResponse=samlResponse)
      except (SAMLRefused, IdentityError) as error:
        _record(session, actor, "signOut.atProvider.failed", "server", {"provider": name, "why": str(error)})
        return None, str(error)
      _record(session, actor, "signOut.atProvider.finished", "server", {"provider": name})
      return provider.settings.signedOutURL, None

  def _signedOutByProvider(self, session, name: str, how: str, ended: int, surface: str) -> None:
    _record(session, Actor.everyone(surface), "signOut.fromProvider", "server",
            {"provider": name, "how": how, "sessionsEnded": ended})

  def _refusedSignOutFromProvider(self, session, name: str, how: str, why: str, surface: str) -> None:
    session.rollback()
    _record(session, Actor.everyone(surface), "signOut.fromProvider.refused", "server",
            {"provider": name, "how": how, "why": why})
    session.commit()

  def backChannelSignOut(self, name: str, logoutToken: str, surface: str) -> int:
    """An OpenID Connect provider's back-channel logout token (Back-Channel Logout 1.0): the sessions it names ended
    here, and how many; a token refused, or already used, is a ProviderFailure."""
    with _sessionScope(self._engine) as session:
      provider = self._enabledProvider(session, name, (ProviderKind.openIDConnect,))
      try:
        notice = _relyingParty(provider.settings).checkLogoutToken(logoutToken)
      except SignInRefused as error:
        self._refusedSignOutFromProvider(session, name, "backChannel", str(error), surface)
        raise ProviderFailure(str(error)) from None
      scope = json.dumps(["openIDConnect", notice.issuer, notice.clientID])
      if not _claimOnce(self._engine, scope, notice.tokenID, notice.rememberUntil, time.time()):
        why = f"logout token {notice.tokenID!r} was already used"
        self._refusedSignOutFromProvider(session, name, "backChannel", why, surface)
        raise ProviderFailure(why)
      if notice.sessionID is not None:
        ended = _endProviderSessions(session, name, subject=notice.subject, sessionIDs=(notice.sessionID,))
      else:
        ended = _endProviderSessions(session, name, subject=notice.subject)
      self._signedOutByProvider(session, name, "backChannel", ended, surface)
      return ended

  def samlSignOutRequest(self, name: str, query: str | None, samlRequest: str | None, relayState: str | None,
                         surface: str) -> str:
    """A SAML identity provider's LogoutRequest: the sessions of its NameID (with its SessionIndexes, when it gives
    any) ended here, and the address of the signed answer to send the browser to."""
    with _sessionScope(self._engine) as session:
      provider = self._enabledProvider(session, name, (ProviderKind.saml, ProviderKind.samlFederation))
      try:
        institution = None
        if provider.kind is ProviderKind.samlFederation:
          # Only chooses whose keys check the request: an institution's name forged here fails at its own keys.
          institution = _claimedSAMLIssuer("SAMLRequest", query=query, posted=samlRequest)
          self._requireOffered(session, provider, institution)
        serviceProvider = self._samlServiceProvider(provider, institution)
        asked = serviceProvider.readSignOutRequest(query=query, samlRequest=samlRequest, relayState=relayState)
      except (SAMLRefused, IdentityError) as error:
        self._refusedSignOutFromProvider(session, name, "saml", str(error), surface)
        raise ProviderFailure(f"{name}'s logout request is refused: {error}") from None
      if institution is None:
        ended = _endProviderSessions(session, name, subject=asked.nameID, sessionIDs=asked.sessionIndexes or None)
      else:
        ended = _endProviderSessions(session, name, sessionIDs=asked.sessionIndexes or None,
                                     detail={"institution": institution, "nameID": asked.nameID})
      self._signedOutByProvider(session, name, "saml", ended, surface)
      session.commit()
      return serviceProvider.answerSignOut(asked)

  def casSignOut(self, name: str, logoutRequest: str, surface: str) -> int:
    """A CAS server's single-logout notice: the one session its service ticket started ended here, and how many."""
    with _sessionScope(self._engine) as session:
      self._enabledProvider(session, name, (ProviderKind.cas,))
      try:
        ticket = _readCASLogout(logoutRequest)
      except CASRefused as error:
        self._refusedSignOutFromProvider(session, name, "cas", str(error), surface)
        raise ProviderFailure(f"{name}'s logout notice is refused: {error}") from None
      ended = _endProviderSessions(session, name, sessionIDs=(ticket,))
      self._signedOutByProvider(session, name, "cas", ended, surface)
      return ended

  def account(self) -> Account | None:
    """The signed-in account this workspace acts as, if any."""
    if self.actor.kind is not ActorKind.account:
      return None
    with _sessionScope(self._engine) as session:
      return next(a for a in _listAccounts(session) if a.accountID == self.actor.accountID)

  # ---- trusted workloads (decision 0042) --------------------------------------

  def _workloadAudience(self, session) -> str | None:
    return {s.key: s.value for s in _effectiveSettings(session, "server")}["identity.workloadAudience"]

  def addWorkloadRule(self, name: str, issuer: str, claims: dict[str, str],
                      certificateAuthority: str | None = None) -> WorkloadRule:
    """Trust the jobs whose tokens `issuer` signs with exactly these claims. The rule holds no role until one is
    given to it (`assignRole`)."""
    with self._acting(Permission.manageAccess, "server") as session:
      if self._workloadAudience(session) is None:
        raise IdentityError("set the server setting identity.workloadAudience before adding a workload rule: it is "
                            "the audience every workload token must name, and it has no default")
      rule = WorkloadRule(name=name, issuer=issuer, claims=claims, certificateAuthority=certificateAuthority,
                          createdAt=_utcNow().replace(tzinfo=None))
      _addWorkloadRule(session, rule)
      self._audit(session, "workload.add", "server", {"rule": rule.name, "issuer": rule.issuer, "claims": rule.claims,
                                                      "certificateAuthority": rule.certificateAuthority})
      return rule

  def workloadRules(self) -> list[WorkloadRule]:
    with self._acting(Permission.manageAccess, "server") as session:
      return _listWorkloadRules(session)

  def workloadRule(self, name: str) -> tuple[WorkloadRule, list[RoleAssignment]]:
    """A rule and the roles given to it."""
    with self._acting(Permission.manageAccess, "server") as session:
      return _workloadRuleNamed(session, name), _assignmentsOfRule(session, name)

  def setWorkloadRuleEnabled(self, name: str, enabled: bool) -> None:
    """A disabled rule accepts no token and holds nothing; its roles wait for it to be enabled again."""
    with self._acting(Permission.manageAccess, "server") as session:
      _setWorkloadRuleEnabled(session, name, enabled)
      self._audit(session, "workload.enable", "server", {"rule": name, "enabled": enabled})

  def removeWorkloadRule(self, name: str) -> None:
    """Remove a rule and, with it, every role given to it."""
    with self._acting(Permission.manageAccess, "server") as session:
      given = _assignmentsOfRule(session, name)
      _removeWorkloadRule(session, name)
      self._audit(session, "workload.remove", "server", {
        "rule": name, "roles": [{"roleCode": assignment.roleCode, "scope": assignment.scope} for assignment in given]})

  def actorForWorkloadToken(self, token: str, surface: str) -> Actor:
    """The workload a platform's token proves: the one enabled rule, among those of the issuer the token names, whose
    checks it passes. The token is used for this and not kept."""
    with _sessionScope(self._engine) as session:
      audience = self._workloadAudience(session)
      if audience is None:
        raise WorkloadTokenRefused("workload tokens are not accepted here: the server setting "
                                   "identity.workloadAudience is not set")
      candidates = _enabledRulesOf(session, _claimedWorkloadIssuer(token))
    rule, identity = _acceptingRule(token, candidates, audience)
    return Actor.workload(rule.name, _runOf(identity), surface)

  # ---- identity providers (decision 0040) ------------------------------------

  def addProvider(self, provider: Provider) -> None:
    """Add a provider; a federation read from a discovery aggregate gets its refresh task, which reads it at once."""
    with self._acting(Permission.manageAccess, "server") as session:
      _addProvider(session, provider)
      self._audit(session, "provider.add", "server", {"provider": provider.name, "kind": provider.kind.value})
      if provider.kind is ProviderKind.samlFederation and provider.settings.discoveryAggregate is not None:
        name, at = federationRefreshTaskName(provider.name), _utcNow()
        _createTask(session, name, "federationRefresh", {"provider": provider.name}, at, ownerProvider=provider.name)
        runID = _requestRun(session, name, self.actor.label, at)
        self._audit(session, "task.create", "server", {"task": name, "kind": "federationRefresh",
                                                       "ownerProvider": provider.name, "runID": runID})

  def providers(self) -> list[Provider]:
    with self._acting(Permission.manageAccess, "server") as session:
      return _listProviders(session)

  def setProviderEnabled(self, name: str, enabled: bool) -> None:
    with self._acting(Permission.manageAccess, "server") as session:
      _setProviderEnabled(session, name, enabled)
      self._audit(session, "provider.enable", "server", {"provider": name, "enabled": enabled})

  def issueProvisioningToken(self, name: str) -> str:
    """A new bearer token for a SCIM provider, replacing the old one; shown once."""
    with self._acting(Permission.manageAccess, "server") as session:
      token = _issueProvisioningToken(session, name)
      self._audit(session, "provider.token", "server", {"provider": name})
      return token

  def linkIdentity(self, name: str, subject: str, userName: str) -> None:
    with self._acting(Permission.manageAccess, "server") as session:
      _linkIdentity(session, name, subject, userName)
      self._audit(session, "provider.link", "server", {"provider": name, "subject": subject, "userName": userName})

  def linkedIdentities(self, userName: str) -> list[LinkedIdentity]:
    """The providers' identities an account is linked to."""
    with self._acting(Permission.manageAccess, "server") as session:
      return _identitiesOf(session, userName)

  def signInProviders(self) -> list[tuple[str, ProviderKind]]:
    """The enabled providers a person can sign in with, for the sign-in page."""
    with _sessionScope(self._engine) as session:
      return [(provider.name, provider.kind) for provider in _listProviders(session)
              if provider.enabled and provider.kind is not ProviderKind.scim]

  def _enabledProvider(self, session, name: str, kinds: tuple[ProviderKind, ...]) -> Provider:
    provider = _providerNamed(session, name)
    if not provider.enabled or provider.kind not in kinds:
      raise IdentityError(f"'{name}' is not a provider to sign in with here")
    return provider

  def federationChoices(self, name: str, locale: str, query: str) -> InstitutionChoices:
    """The institutions a federation provider offers, as (entity ID, display name in the locale): every configured
    one, by name; or, from a discovery aggregate, those the query finds in the stored list, at most
    `institutionSearchLimit`."""
    with _sessionScope(self._engine) as session:
      provider = self._enabledProvider(session, name, (ProviderKind.samlFederation,))
      if provider.settings.discoveryAggregate is not None:
        if _discoveryList(session, name) is None:
          return InstitutionChoices(searchable=True, loaded=False, institutions=[], more=False)
        found = _searchDiscovery(session, name, query, locale, institutionSearchLimit)
        return InstitutionChoices(searchable=True, loaded=True, institutions=found.institutions, more=found.more)
    chosen = [_institution(provider.settings, entityID) for entityID in provider.settings.institutions]
    return InstitutionChoices(searchable=False, loaded=True, more=False, institutions=sorted(
      ((one.entityID, one.displayName(locale)) for one in chosen), key=lambda pair: pair[1].casefold()))

  def _requireOffered(self, session, provider: Provider, entityID: str) -> None:
    if provider.settings.discoveryAggregate is not None:
      offered = _isDiscovered(session, provider.name, entityID)
    else:
      offered = entityID in provider.settings.institutions
    if not offered:
      raise IdentityError(f"'{entityID}' is not an institution offered here")

  def refreshFederationDiscovery(self, name: str) -> DiscoveryOutcome:
    """Read a federation provider's discovery aggregate and, once it has verified, replace its stored list with it."""
    with self._acting(Permission.manageAccess, "server") as session:
      provider = _providerNamed(session, name)
    if provider.kind is not ProviderKind.samlFederation:
      raise IdentityError(f"'{name}' is not a federation provider")
    discovery = _fetchDiscovery(name, provider.settings)
    with self._acting(Permission.manageAccess, "server") as session:
      _replaceDiscovery(session, name, discovery, _utcNow().replace(tzinfo=None))
      outcome = DiscoveryOutcome(offered=len(discovery.institutions), hidden=discovery.hidden,
                                 skipped=list(discovery.skipped),
                                 validUntil=datetime.datetime.fromtimestamp(discovery.validUntil, datetime.UTC))
      self._audit(session, "provider.discovery", "server", {"provider": name, "offered": outcome.offered,
                                                            "hidden": outcome.hidden, "skipped": len(outcome.skipped)})
      return outcome

  def samlMetadata(self, name: str) -> bytes:
    """The metadata a SAML identity provider, or a federation, registers for this service."""
    with _sessionScope(self._engine) as session:
      provider = self._enabledProvider(session, name, (ProviderKind.saml, ProviderKind.samlFederation))
    if provider.kind is ProviderKind.saml:
      return _samlMetadata(provider.settings)
    return _federationMetadata(provider.settings)

  def beginProviderSignIn(self, name: str, next: str, institution: str | None = None) -> tuple[str, str]:
    """Where to send the browser for a provider's sign-in, and the key its pending-sign-in cookie carries."""
    with _sessionScope(self._engine) as session:
      provider = self._enabledProvider(session, name, _redirectKinds)
      if (institution is not None) != (provider.kind is ProviderKind.samlFederation):
        raise IdentityError("an institution is chosen for a federation, and only for one")
      if institution is not None:
        self._requireOffered(session, provider, institution)
      if provider.kind is ProviderKind.openIDConnect:
        address, pending = _relyingParty(provider.settings).beginSignIn()
      elif provider.kind is ProviderKind.cas:
        address, pending = _casServer(provider.settings).beginSignIn()
      else:
        address, pending = self._samlServiceProvider(provider, institution).beginSignIn()
      key = _startPending(session, name, {"purpose": "signIn", "protocol": dataclasses.asdict(pending), "next": next,
                                          "institution": institution})
      return address, key

  def finishProviderSignIn(self, key: str, answer: dict[str, str], surface: str) -> tuple[Account, str, str]:
    """The provider's answer checked: the account, a new session token, and where the person was going."""
    with _sessionScope(self._engine) as session:
      name, state = _takePending(session, key)
      session.commit()
      if state["purpose"] != "signIn":
        raise IdentityError("this browser is signing out, not in; start again")
      provider = self._enabledProvider(session, name, _redirectKinds)
      try:
        if provider.kind is ProviderKind.openIDConnect:
          identity = _fromOpenIDConnect(_relyingParty(provider.settings).finishSignIn(
            OpenIDConnectPending(**state["protocol"]), answer))
        elif provider.kind is ProviderKind.cas:
          identity = _fromCAS(provider.settings, _casServer(provider.settings).finishSignIn(
            CASPending(**state["protocol"]), answer))
        else:
          if "SAMLResponse" not in answer:
            raise IdentityError("the provider's answer has no SAMLResponse")
          replays = _StoredReplays(self._engine)
          if provider.kind is ProviderKind.saml:
            identity = _fromSAML(provider.settings, _serviceProvider(provider.settings, replays).finishSignIn(
              SAMLPending(**state["protocol"]), answer["SAMLResponse"]))
          else:
            chosen = _institution(provider.settings, state["institution"])
            identity = _fromFederation(provider.settings, chosen, _federationServiceProvider(
              provider.settings, chosen, replays).finishSignIn(SAMLPending(**state["protocol"]), answer["SAMLResponse"]))
      except (SignInRefused, SAMLRefused, CASRefused) as error:
        self._refusedSignIn(session, name, surface, str(error))
        raise ProviderFailure(f"{name} refused the sign-in: {error}") from None
      account, token = self._providerSession(session, provider, identity, surface)
      return account, token, state["next"]

  def signInWithDirectory(self, name: str, userName: str, password: str, surface: str) -> tuple[Account, str]:
    with _sessionScope(self._engine) as session:
      provider = self._enabledProvider(session, name, (ProviderKind.ldap,))
      try:
        identity = _fromDirectory(_directory(provider.settings).signIn(userName, password))
      except DirectoryRefused as error:
        self._refusedSignIn(session, name, surface, str(error), _foldedUserName(userName))
        raise IdentityError(str(error)) from None
      return self._providerSession(session, provider, identity, surface)

  def _refusedSignIn(self, session, name: str, surface: str, why: str, userName: str | None = None) -> None:
    detail = {"provider": name, "why": why}
    if userName is not None:
      detail["userName"] = userName
    _record(session, Actor.everyone(surface), "signIn.refused", "server", detail)
    session.commit()

  def _providerSession(self, session, provider: Provider, identity: ProvidedIdentity, surface: str) -> tuple[Account, str]:
    try:
      account = _completeSignIn(session, provider, identity)
    except IdentityError as error:
      session.rollback()
      self._refusedSignIn(session, provider.name, surface, str(error), identity.userName)
      raise
    hours = {s.key: s.value for s in _effectiveSettings(session, "server")}["identity.sessionHours"]
    token = _issueToken(session, account.userName, "session", datetime.timedelta(hours=hours), None)
    if provider.kind is not ProviderKind.ldap:
      _recordProviderSession(session, token, provider.name, identity)
    _record(session, Actor(kind=ActorKind.account, accountID=account.accountID, userName=account.userName,
                           surface=surface), "signIn", "server", {"provider": provider.name})
    return account, token

  def handleProvisioning(self, name: str, method: str, path: str, query: str, headers: dict[str, str], body: bytes):
    """One SCIM request from a provider, answered by Carnelian over this store, in one transaction."""
    with _sessionScope(self._engine) as session:
      try:
        provider = _providerNamed(session, name)
      except IdentityError:
        raise NotFoundError(f"no provisioning at '{name}'") from None
      if provider.kind is not ProviderKind.scim or not provider.enabled:
        raise NotFoundError(f"no provisioning at '{name}'")
      service = SCIMService(ProvisioningStore(session, provider), provider.settings.baseURL,
                            lambda token: _provisioningTokenMatches(session, name, token))
      response = service.handle(method, path, query, headers, body)
      if response.status >= 400:
        session.rollback()
        if response.status != 401:
          _record(session, Actor(kind=ActorKind.everyone, surface="provisioning"), "provision.refused", "server",
                  {"provider": name, "method": method, "path": path, "status": response.status})
        return response
      _record(session, Actor(kind=ActorKind.everyone, surface="provisioning"), "provision", "server",
              {"provider": name, "method": method, "path": path, "status": response.status})
      return response

  # ---- scheduled tasks (decision 0041) ---------------------------------------

  def createTask(self, name: str, kind: str, parameters: dict) -> Task:
    """Configure a task of a kind, with the kind's default schedule and time limit, enabled."""
    with self._acting(Permission.manageTasks, "server") as session:
      _createTask(session, name, kind, parameters, _utcNow())
      created = _taskNamed(session, name)
      self._audit(session, "task.create", "server", {"task": name, "kind": kind, "parameters": created.parameters})
      return created

  def taskKinds(self) -> list[TaskKind]:
    """The kinds a task can be of, by name."""
    with self._acting(Permission.manageTasks, "server"):
      return _registeredTaskKinds()

  def deleteTask(self, name: str) -> None:
    """Delete a task and its runs; refused for a task its feature keeps and while a run of it is requested or
    running."""
    with self._acting(Permission.manageTasks, "server") as session:
      deleted = _taskNamed(session, name)
      _deleteTask(session, name)
      self._audit(session, "task.delete", "server", {"task": name, "kind": deleted.kind,
                                                     "parameters": deleted.parameters})

  def tasks(self) -> list[Task]:
    with self._acting(Permission.manageTasks, "server") as session:
      return _listTasks(session)

  def task(self, name: str) -> Task:
    with self._acting(Permission.manageTasks, "server") as session:
      return _taskNamed(session, name)

  def setTask(self, name: str, schedule: str | None = None, timeLimitSeconds: int | None = None) -> Task:
    """Change a task's schedule, its time limit, or both."""
    if schedule is None and timeLimitSeconds is None:
      raise TaskError("name a schedule, a time limit or both to change")
    with self._acting(Permission.manageTasks, "server") as session:
      before = _taskNamed(session, name)
      if schedule is not None:
        _setSchedule(session, name, schedule, _utcNow())
      if timeLimitSeconds is not None:
        _setTimeLimit(session, name, timeLimitSeconds)
      after = _taskNamed(session, name)
      self._audit(session, "task.set", "server", {
        "task": name, "before": {"schedule": before.schedule, "timeLimitSeconds": before.timeLimitSeconds},
        "after": {"schedule": after.schedule, "timeLimitSeconds": after.timeLimitSeconds}})
      return after

  def setTaskEnabled(self, name: str, enabled: bool) -> Task:
    with self._acting(Permission.manageTasks, "server") as session:
      _setTaskEnabled(session, name, enabled, _utcNow())
      self._audit(session, "task.enable", "server", {"task": name, "enabled": enabled})
      return _taskNamed(session, name)

  def runTaskNow(self, name: str) -> int:
    """Request a run of a task at once, recorded as asked for by this actor; the scheduler starts it."""
    with self._acting(Permission.manageTasks, "server") as session:
      runID = _requestRun(session, name, self.actor.label, _utcNow())
      self._audit(session, "task.run", "server", {"task": name, "runID": runID})
      return runID

  def taskRuns(self, name: str, limit: int = 50) -> list[TaskRun]:
    """A task's runs, newest first, with their output."""
    with self._acting(Permission.manageTasks, "server") as session:
      return _taskRuns(session, name, limit)

  def schedulerHeartbeat(self) -> SchedulerHeartbeat | None:
    """When a scheduler last checked in; None when none ever has."""
    with self._acting(Permission.manageTasks, "server") as session:
      return _schedulerHeartbeat(session)

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
    """Run the ANOVA the trial's design calls for, for one numeric assessment, by the trial's settings.

    A plot without a value is handled as the trial's `analysis.missingPlots` says
    (decision 0043); the result records the policy and every missing plot.
    """
    missingPlots = self._analysisSettings(trialCode).missingPlots
    package, layout, observations = self._loadContext(trialCode)
    if package.design.designType is DesignType.splitPlot:
      return _analyzeSplitPlot(assessmentCode, package, layout, observations)
    if package.design.designType is DesignType.crd:
      return _analyzeCrd(assessmentCode, package, layout, observations, missingPlots)
    return _analyzeRcbd(assessmentCode, package, layout, observations, missingPlots)

  def separateFactorMeans(self, trialCode: str, assessmentCode: str, factor: str) -> FactorSeparation:
    """Separate the level means of one factor of a split plot or a two-factor RCBD, by the trial's settings."""
    settings = self._analysisSettings(trialCode)
    result = self.analyze(trialCode, assessmentCode)
    if isinstance(result, SplitPlotResult):
      return _separateFactorMeans(
        result, factor, significanceLevel=settings.significanceLevel, meanComparison=settings.meanComparison,
      )
    package, layout, observations = self._loadContext(trialCode)
    if not package.factors:
      raise AnalysisError(f"trial '{trialCode}' has no factors to separate")
    factorial = _analyzeFactorialRcbd(assessmentCode, package, layout, observations)
    return _separateFactorialMeans(
      factorial, factor, significanceLevel=settings.significanceLevel, meanComparison=settings.meanComparison,
    )

  def compareWithControl(self, trialCode: str, assessmentCode: str) -> DunnettResult:
    """Dunnett's two-sided test of every treatment against the untreated check (decision 0029)."""
    significanceLevel = self._analysisSettings(trialCode).significanceLevel
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
    settings = self._analysisSettings(trialCode)
    result = self.analyze(trialCode, assessmentCode)
    if isinstance(result, SplitPlotResult):
      raise AnalysisError(
        f"trial '{trialCode}' is a split plot; its means are separated for each factor (separateFactorMeans)"
      )
    return _separateMeans(result, significanceLevel=settings.significanceLevel, meanComparison=settings.meanComparison)

  def assessAssumptions(self, trialCode: str, assessmentCode: str) -> Assumptions:
    """Compute the report-only ANOVA assumption diagnostics for one assessment."""
    settings = self._analysisSettings(trialCode)
    package, layout, observations = self._loadContext(trialCode)
    return _assessAssumptions(
      assessmentCode, package, layout, observations, settings.significanceLevel, settings.missingPlots,
    )

  # ---- reporting ----------------------------------------------------------

  def buildReport(self, trialCode: str, locale: str = sourceLocale) -> str:
    """Build the full Markdown trial report (the AOV Means Table and provenance), by the trial's settings.

    `locale` is a display choice only: it selects the message catalog and number
    formatting. It does not touch the stored data, the exchange, or the content hash.
    """
    settings = self._analysisSettings(trialCode)
    package, layout, observations = self._loadContext(trialCode)
    return _buildReport(
      package, layout, observations,
      significanceLevel=settings.significanceLevel, meanComparison=settings.meanComparison, locale=locale,
      settingsUsed=settings.effective, missingPlots=settings.missingPlots,
    )

  def buildReportWithCharts(self, trialCode: str, marker: str, locale: str = sourceLocale) -> ReportWithCharts:
    """The report with a marker line where each chart of means goes, and the charts (decision 0032)."""
    settings = self._analysisSettings(trialCode)
    package, layout, observations = self._loadContext(trialCode)
    return _buildReportWithCharts(
      package, layout, observations, marker,
      significanceLevel=settings.significanceLevel, meanComparison=settings.meanComparison, locale=locale,
      settingsUsed=settings.effective, missingPlots=settings.missingPlots,
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
