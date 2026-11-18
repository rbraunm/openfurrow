# SPDX-License-Identifier: Apache-2.0
"""OpenFurrow command-line interface.

A thin surface over the core facade (`openfurrow.workspace.Workspace`): it parses
arguments, reads and writes files, and prints results. It never imports the store,
analysis, exchange, or design internals -- every trial operation goes through the
Workspace, so the CLI cannot drift from the core or re-implement part of it. The
one core type it constructs directly is the public `TrialPackage`, when reading a
design document a user hands it to add.

Every command fails loud -- a missing trial, a bad package, an import error, or a
duplicate prints a clear message and exits non-zero rather than partially
succeeding. The store is a SQLite file or a PostgreSQL URL the user gives explicitly.
Trials live in places of the store's hierarchy (decision 0034), and the analysis follows
the store's settings (decision 0035); the config file (--config) holds the import
profile and the service's binding.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

from openfurrow.config import defaultConfig, loadConfig
from openfurrow.schema import AssessmentDataType, TrialPackage
from openfurrow.schema.hierarchy import HierarchyLevel
from openfurrow.settings import SettingError
from openfurrow.store.hierarchy import ScopeError
from openfurrow.identity import Actor, IdentityError, Permission, RoleAssignment, RoleDefinition
from openfurrow.identity.providers import Provider, ProviderKind
from openfurrow.importers.weatherCsv import WeatherFileError
from openfurrow.workspace import (
  AnalysisError,
  ExchangeError,
  MessageError,
  NotPermitted,
  ObservationImportError,
  StoreError,
  Workspace,
  sourceLocale,
)
from pydantic import ValidationError


def main(argv: list[str] | None = None) -> int:
  """Parse arguments and run the requested command; return a process exit code."""
  _useUTF8Streams()
  parser = _buildParser()
  args = parser.parse_args(argv)
  handler = getattr(args, "handler", None)
  if handler is None:
    parser.print_help()
    return 2
  try:
    return handler(args)
  except (
    StoreError, ExchangeError, ObservationImportError, AnalysisError, MessageError,
    ValidationError, OSError, json.JSONDecodeError, WeatherFileError, SettingError, ScopeError, IdentityError,
    NotPermitted,
  ) as error:
    print(f"error: {error}", file=sys.stderr)
    return 1


def _useUTF8Streams() -> None:
  # A report carries text in any shipped locale. Left to the platform, redirected
  # output on Windows is encoded with the ANSI code page: Arabic cannot be encoded at
  # all, and French comes out in an encoding the report does not declare.
  for stream in (sys.stdout, sys.stderr):
    if isinstance(stream, io.TextIOWrapper):
      stream.reconfigure(encoding="utf-8")


# ---- argument parser ------------------------------------------------------

def _buildParser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(prog="openfurrow", description="Reproducible agricultural trial management.")
  sub = parser.add_subparsers(dest="command")

  initParser = sub.add_parser("init", help="create a new trial database")
  initParser.add_argument("database")
  initParser.set_defaults(handler=_commandInit)

  addParser = sub.add_parser(
    "add", help="add a validated trial package from JSON",
    epilog="Each numeric assessment may declare 'transform' (none/sqrt/log/arcsinSqrt/logit) "
           "and 'measurementKind' in the package JSON; 'info' shows the current values.",
  )
  addParser.add_argument("database")
  addParser.add_argument("package", help="path to a trial package JSON file")
  addParser.add_argument("--place", help="the place the trial goes in, a path such as station/fungicides/wheat2025")
  addParser.set_defaults(handler=_commandAdd)

  levelsParser = sub.add_parser("levels", help="show the hierarchy's levels, or set them while the store is empty")
  levelsParser.add_argument("database")
  levelsParser.add_argument("--set", nargs="*", metavar="CODE[=NAME]",
                            help="the levels, top first; a level not built in needs a name")
  levelsParser.set_defaults(handler=_commandLevels)

  placeParser = sub.add_parser("place", help="add, list or delete places of the hierarchy")
  placeSub = placeParser.add_subparsers(dest="placeCommand", required=True)
  placeAdd = placeSub.add_parser("add", help="add a place; its path's last code is the new place")
  placeAdd.add_argument("database")
  placeAdd.add_argument("path")
  placeAdd.add_argument("name")
  placeAdd.set_defaults(handler=_commandPlaceAdd)
  placeList = placeSub.add_parser("list", help="list the places")
  placeList.add_argument("database")
  placeList.set_defaults(handler=_commandPlaceList)
  placeDelete = placeSub.add_parser("delete", help="delete an empty place")
  placeDelete.add_argument("database")
  placeDelete.add_argument("path")
  placeDelete.set_defaults(handler=_commandPlaceDelete)

  moveParser = sub.add_parser("move", help="put a trial in another place")
  moveParser.add_argument("database")
  moveParser.add_argument("trialCode")
  moveParser.add_argument("place")
  moveParser.set_defaults(handler=_commandMove)

  settingParser = sub.add_parser("setting", help="show, set or clear settings at a scope")
  settingSub = settingParser.add_subparsers(dest="settingCommand", required=True)
  settingShow = settingSub.add_parser("show", help="every setting's value at a scope, and where it was set")
  settingShow.add_argument("database")
  settingShow.add_argument("scope", help="'server', 'place:<path>' or 'trial:<code>'")
  settingShow.set_defaults(handler=_commandSettingShow)
  settingSet = settingSub.add_parser("set", help="set a setting at a scope")
  settingSet.add_argument("database")
  settingSet.add_argument("scope")
  settingSet.add_argument("key")
  settingSet.add_argument("value", help="read as JSON when it parses, otherwise as text")
  settingSet.set_defaults(handler=_commandSettingSet)
  settingClear = settingSub.add_parser("clear", help="remove a setting's value at a scope")
  settingClear.add_argument("database")
  settingClear.add_argument("scope")
  settingClear.add_argument("key")
  settingClear.set_defaults(handler=_commandSettingClear)

  listParser = sub.add_parser("list", help="list trials in the database")
  listParser.add_argument("database")
  listParser.set_defaults(handler=_commandList)

  infoParser = sub.add_parser("info", help="show a trial summary")
  infoParser.add_argument("database")
  infoParser.add_argument("trialCode")
  infoParser.set_defaults(handler=_commandInfo)

  randomizeParser = sub.add_parser("randomize", help="print the recorded layout of a trial")
  randomizeParser.add_argument("database")
  randomizeParser.add_argument("trialCode")
  randomizeParser.set_defaults(handler=_commandRandomize)

  importParser = sub.add_parser("import", help="import observations from a CSV file")
  importParser.add_argument("database")
  importParser.add_argument("trialCode")
  importParser.add_argument("csv", help="path to an observations CSV file")
  importParser.add_argument("--config", help="path to a project config file (see examples/openfurrow.yaml)")
  importParser.set_defaults(handler=_commandImport)

  reportParser = sub.add_parser("report", help="build the trial report (AOV Means Table)")
  reportParser.add_argument("database")
  reportParser.add_argument("trialCode")
  reportParser.add_argument("--output", help="write the report to this file instead of stdout")
  reportParser.add_argument(
    "--locale", default=sourceLocale,
    help=f"locale for the report's display text and numbers (default: {sourceLocale})",
  )
  reportParser.set_defaults(handler=_commandReport)

  exportParser = sub.add_parser("export", help="export a trial to JSON and/or CSV")
  exportParser.add_argument("database")
  exportParser.add_argument("trialCode")
  exportParser.add_argument("--json", dest="jsonPath", help="write the trial document to this JSON file")
  exportParser.add_argument("--csv", dest="csvPath", help="write observations to this CSV file")
  exportParser.set_defaults(handler=_commandExport)

  weatherParser = sub.add_parser("import-weather", help="replace a trial's weather log from a CSV file")
  weatherParser.add_argument("database")
  weatherParser.add_argument("trialCode")
  weatherParser.add_argument("csv", help="date, then any of rainfall, irrigation, minimumTemperature, "
                              "maximumTemperature with the unit in brackets, and notes")
  weatherParser.set_defaults(handler=_commandImportWeather)

  importJsonParser = sub.add_parser("import-json", help="import a trial document from JSON into the database")
  importJsonParser.add_argument("database")
  importJsonParser.add_argument("jsonFile", help="path to a trial document JSON file")
  importJsonParser.add_argument("--place", help="the place the trial goes in")
  importJsonParser.set_defaults(handler=_commandImportJson)

  verifyParser = sub.add_parser("verify", help="check a trial round-trips to the same content hash")
  verifyParser.add_argument("database")
  verifyParser.add_argument("trialCode")
  verifyParser.set_defaults(handler=_commandVerify)

  deleteParser = sub.add_parser("delete", help="delete a trial and all its data")
  deleteParser.add_argument("database")
  deleteParser.add_argument("trialCode")
  deleteParser.set_defaults(handler=_commandDelete)

  accountParser = sub.add_parser("account", help="add, list, activate or deactivate accounts")
  accountSub = accountParser.add_subparsers(dest="accountCommand", required=True)
  accountAdd = accountSub.add_parser("add", help="add an account; its password is read from standard input")
  accountAdd.add_argument("database")
  accountAdd.add_argument("userName")
  accountAdd.add_argument("displayName")
  accountAdd.add_argument("--email")
  accountAdd.add_argument("--no-password", dest="noPassword", action="store_true",
                          help="an account that signs in through an identity provider only")
  accountAdd.set_defaults(handler=_commandAccountAdd)
  accountPassword = accountSub.add_parser("password", help="set an account's password, read from standard input")
  accountPassword.add_argument("database")
  accountPassword.add_argument("userName")
  accountPassword.set_defaults(handler=_commandAccountPassword)
  accountList = accountSub.add_parser("list", help="list the accounts")
  accountList.add_argument("database")
  accountList.set_defaults(handler=_commandAccountList)
  for name, active in (("activate", True), ("deactivate", False)):
    toggle = accountSub.add_parser(name, help=f"{name} an account")
    toggle.add_argument("database")
    toggle.add_argument("userName")
    toggle.set_defaults(handler=_commandAccountActive, active=active)

  groupParser = sub.add_parser("group", help="add groups and their members")
  groupSub = groupParser.add_subparsers(dest="groupCommand", required=True)
  groupAdd = groupSub.add_parser("add", help="add a group")
  groupAdd.add_argument("database")
  groupAdd.add_argument("name")
  groupAdd.set_defaults(handler=_commandGroupAdd)
  groupMember = groupSub.add_parser("member", help="put an account in a group, or take it out with --remove")
  groupMember.add_argument("database")
  groupMember.add_argument("group")
  groupMember.add_argument("userName")
  groupMember.add_argument("--remove", action="store_true")
  groupMember.set_defaults(handler=_commandGroupMember)
  groupList = groupSub.add_parser("list", help="list the groups and their members")
  groupList.add_argument("database")
  groupList.set_defaults(handler=_commandGroupList)

  providerParser = sub.add_parser("provider", help="identity providers: sign-in and provisioning (decision 0040)")
  providerSub = providerParser.add_subparsers(dest="providerCommand", required=True)
  providerAdd = providerSub.add_parser("add", help="add a provider from a JSON file of its settings")
  providerAdd.add_argument("database")
  providerAdd.add_argument("name")
  providerAdd.add_argument("kind", choices=[kind.value for kind in ProviderKind])
  providerAdd.add_argument("settingsFile")
  providerAdd.set_defaults(handler=_commandProviderAdd)
  providerList = providerSub.add_parser("list", help="list the providers")
  providerList.add_argument("database")
  providerList.set_defaults(handler=_commandProviderList)
  for name, enabled in (("enable", True), ("disable", False)):
    toggle = providerSub.add_parser(name, help=f"{name} a provider")
    toggle.add_argument("database")
    toggle.add_argument("name")
    toggle.set_defaults(handler=_commandProviderEnabled, enabled=enabled)
  providerToken = providerSub.add_parser("token", help="a new bearer token for a SCIM provider, shown once")
  providerToken.add_argument("database")
  providerToken.add_argument("name")
  providerToken.set_defaults(handler=_commandProviderToken)
  providerLink = providerSub.add_parser("link", help="link a provider's identity (its subject) to an account")
  providerLink.add_argument("database")
  providerLink.add_argument("name")
  providerLink.add_argument("subject")
  providerLink.add_argument("userName")
  providerLink.set_defaults(handler=_commandProviderLink)

  roleParser = sub.add_parser("role", help="define roles and give them at a scope")
  roleSub = roleParser.add_subparsers(dest="roleCommand", required=True)
  roleList = roleSub.add_parser("list", help="the roles and their permissions")
  roleList.add_argument("database")
  roleList.set_defaults(handler=_commandRoleList)
  roleDefine = roleSub.add_parser("define", help="define or redefine a custom role")
  roleDefine.add_argument("database")
  roleDefine.add_argument("roleCode")
  roleDefine.add_argument("name")
  roleDefine.add_argument("permissions", nargs="+")
  roleDefine.set_defaults(handler=_commandRoleDefine)
  for name, given in (("assign", True), ("unassign", False)):
    assign = roleSub.add_parser(name, help=f"{name} a role to an account or a group at a scope")
    assign.add_argument("database")
    assign.add_argument("roleCode")
    assign.add_argument("scope", help="'server', 'place:<path>' or 'trial:<code>'")
    who = assign.add_mutually_exclusive_group(required=True)
    who.add_argument("--user", dest="userName")
    who.add_argument("--group", dest="groupName")
    assign.set_defaults(handler=_commandRoleAssign, given=given)
  roleAssignments = roleSub.add_parser("assignments", help="every role given, to whom and where")
  roleAssignments.add_argument("database")
  roleAssignments.set_defaults(handler=_commandRoleAssignments)

  auditParser = sub.add_parser("audit", help="the latest changes, who made them and from where")
  auditParser.add_argument("database")
  auditParser.add_argument("--scope", default="server", help="'server' (everything), 'place:<path>' or 'trial:<code>'")
  auditParser.add_argument("--limit", type=int, default=50)
  auditParser.set_defaults(handler=_commandAudit)

  serveParser = sub.add_parser("serve", help="run the HTTP service over a trial database")
  serveParser.add_argument("database")
  serveParser.add_argument("--config", help="path to a project config file (see examples/openfurrow.yaml)")
  serveParser.add_argument("--host", help="bind address (overrides config; default from config)")
  serveParser.add_argument("--port", type=int, help="bind port (overrides config)")
  serveParser.set_defaults(handler=_commandServe)

  return parser


# ---- helpers --------------------------------------------------------------

def _readPackage(path: str) -> TrialPackage:
  data = json.loads(Path(path).read_text(encoding="utf-8"))
  return TrialPackage.model_validate(data)


def _configFor(args) -> "object":
  configPath = getattr(args, "config", None)
  return loadConfig(configPath) if configPath else defaultConfig()


# ---- commands -------------------------------------------------------------

def _commandInit(args) -> int:
  Workspace.create(args.database, Actor.operator("cli"))
  print(f"Initialized database at {args.database}")
  return 0


def _commandAdd(args) -> int:
  package = _readPackage(args.package)
  workspace = Workspace.create(args.database, Actor.operator("cli"))
  workspace.addPackage(package, args.place)
  print(
    f"Added trial '{package.trial.trialCode}' "
    f"({len(package.treatments)} treatments, {len(package.ratings)} ratings, "
    f"{len(package.assessments)} assessments, {package.plotCount} plots)"
  )
  return 0


def _commandLevels(args) -> int:
  workspace = Workspace.open(args.database, Actor.operator("cli"))
  if args.set is not None:
    levels = []
    for entry in args.set:
      code, _, name = entry.partition("=")
      levels.append(HierarchyLevel(levelCode=code, name=name or None))
    workspace.setHierarchyLevels(levels)
  for level in workspace.hierarchyLevels():
    print(level.levelCode if level.name is None else f"{level.levelCode}\t{level.name}")
  print("trial")
  return 0


def _commandPlaceAdd(args) -> int:
  parent, _, code = args.path.rpartition("/")
  place = Workspace.open(args.database, Actor.operator("cli")).addPlace(parent or None, code, args.name)
  print(f"Added {place.levelCode} '{place.path}'")
  return 0


def _commandPlaceList(args) -> int:
  places = Workspace.open(args.database, Actor.operator("cli")).places()
  if not places:
    print("(no places)")
  for place in places:
    print(f"{place.path}\t{place.levelCode}\t{place.name}")
  return 0


def _commandPlaceDelete(args) -> int:
  Workspace.open(args.database, Actor.operator("cli")).deletePlace(args.path)
  print(f"Deleted place '{args.path}'")
  return 0


def _commandMove(args) -> int:
  Workspace.open(args.database, Actor.operator("cli")).moveTrial(args.trialCode, args.place)
  print(f"Moved trial '{args.trialCode}' to '{args.place}'")
  return 0


def _settingValue(text: str):
  try:
    return json.loads(text)
  except json.JSONDecodeError:
    return text


def _commandSettingShow(args) -> int:
  from openfurrow.settings import jsonValue
  for setting in Workspace.open(args.database, Actor.operator("cli")).effectiveSettings(args.scope):
    print(f"{setting.key}\t{json.dumps(jsonValue(setting.key, setting.value))}\t{setting.source}")
  return 0


def _commandSettingSet(args) -> int:
  Workspace.open(args.database, Actor.operator("cli")).setSetting(args.scope, args.key, _settingValue(args.value))
  print(f"Set {args.key} at {args.scope}")
  return 0


def _commandSettingClear(args) -> int:
  Workspace.open(args.database, Actor.operator("cli")).clearSetting(args.scope, args.key)
  print(f"Cleared {args.key} at {args.scope}")
  return 0


def _operator(database: str) -> Workspace:
  return Workspace.open(database, Actor.operator("cli"))


def _passwordFromInput() -> str:
  password = sys.stdin.readline().rstrip("\r\n")
  if not password:
    raise IdentityError("no password on standard input")
  return password


def _commandAccountAdd(args) -> int:
  password = None if args.noPassword else _passwordFromInput()
  account = _operator(args.database).createAccount(args.userName, args.displayName, args.email, password)
  print(f"Added account '{account.userName}'")
  return 0


def _commandAccountPassword(args) -> int:
  _operator(args.database).setPassword(args.userName, _passwordFromInput())
  print(f"Set the password of '{args.userName}'")
  return 0


def _commandAccountList(args) -> int:
  for account in _operator(args.database).accounts():
    print(f"{account.userName}\t{account.displayName}\t{'active' if account.active else 'inactive'}")
  return 0


def _commandAccountActive(args) -> int:
  _operator(args.database).setAccountActive(args.userName, args.active)
  print(f"{'Activated' if args.active else 'Deactivated'} '{args.userName}'")
  return 0


def _commandProviderAdd(args) -> int:
  settings = json.loads(Path(args.settingsFile).read_text(encoding="utf-8"))
  _operator(args.database).addProvider(Provider.of(args.name, args.kind, settings))
  print(f"Added {args.kind} provider '{args.name}'")
  return 0


def _commandProviderList(args) -> int:
  for provider in _operator(args.database).providers():
    print(f"{provider.name}\t{provider.kind.value}\t{'enabled' if provider.enabled else 'disabled'}")
  return 0


def _commandProviderEnabled(args) -> int:
  _operator(args.database).setProviderEnabled(args.name, args.enabled)
  print(f"{'Enabled' if args.enabled else 'Disabled'} '{args.name}'")
  return 0


def _commandProviderToken(args) -> int:
  print(_operator(args.database).issueProvisioningToken(args.name))
  return 0


def _commandProviderLink(args) -> int:
  _operator(args.database).linkIdentity(args.name, args.subject, args.userName)
  print(f"Linked {args.name} identity '{args.subject}' to '{args.userName}'")
  return 0


def _commandGroupAdd(args) -> int:
  _operator(args.database).createGroup(args.name)
  print(f"Added group '{args.name}'")
  return 0


def _commandGroupMember(args) -> int:
  _operator(args.database).setMembership(args.group, args.userName, not args.remove)
  print(f"{'Removed' if args.remove else 'Added'} '{args.userName}' {'from' if args.remove else 'to'} '{args.group}'")
  return 0


def _commandGroupList(args) -> int:
  for group in _operator(args.database).groups():
    print(f"{group.name}\t{', '.join(group.members)}")
  return 0


def _commandRoleList(args) -> int:
  for code, role in sorted(_operator(args.database).roles().items()):
    print(f"{code}\t{'built in' if role.builtIn else role.name}\t{' '.join(sorted(p.value for p in role.permissions))}")
  return 0


def _commandRoleDefine(args) -> int:
  role = RoleDefinition(roleCode=args.roleCode, name=args.name, permissions=frozenset(Permission(p) for p in args.permissions))
  _operator(args.database).defineRole(role)
  print(f"Defined role '{args.roleCode}'")
  return 0


def _commandRoleAssign(args) -> int:
  assignment = RoleAssignment(roleCode=args.roleCode, scope=args.scope, userName=args.userName, groupName=args.groupName)
  workspace = _operator(args.database)
  (workspace.assignRole if args.given else workspace.unassignRole)(assignment)
  print(f"{'Gave' if args.given else 'Took back'} '{args.roleCode}' at {args.scope}")
  return 0


def _commandRoleAssignments(args) -> int:
  for assignment in _operator(args.database).assignments():
    who = f"user {assignment.userName}" if assignment.userName else f"group {assignment.groupName}"
    print(f"{assignment.roleCode}\t{assignment.scope}\t{who}")
  return 0


def _commandAudit(args) -> int:
  for event in _operator(args.database).auditEvents(args.scope, args.limit):
    who = event.actorName or event.actorKind
    print(f"{event.at}\t{who}\t{event.surface}\t{event.action}\t{event.scope}\t{json.dumps(event.detail, sort_keys=True)}")
  return 0


def _commandList(args) -> int:
  trials = Workspace.open(args.database, Actor.operator("cli")).listTrials()
  if not trials:
    print("(no trials)")
  for trialCode, title in trials:
    print(f"{trialCode}\t{title}")
  return 0


def _commandInfo(args) -> int:
  workspace = Workspace.open(args.database, Actor.operator("cli"))
  package = workspace.loadPackage(args.trialCode)
  observations = workspace.loadObservations(args.trialCode)
  trial = package.trial
  print(f"Trial: {trial.trialCode} - {trial.title}")
  print(f"Crop: {trial.crop}   Season: {trial.season}   Site: {trial.site}")
  print(
    f"Design: {package.design.designType.value}, {package.design.replications} blocks, "
    f"{len(package.treatments)} treatments, {package.plotCount} plots"
  )
  print(f"Layout: {_layoutOrigin(package.design)}")
  if package.planting is not None:
    print(f"Planting: {_recordedFacts(package.planting)}")
  if package.soil is not None:
    print(f"Soil: {_recordedFacts(package.soil)}")
  if package.weather:
    print(f"Weather: {len(package.weather)} days, {package.weather[0].date} to {package.weather[-1].date}")
  if package.targets:
    print("Targets:")
    for target in package.targets:
      eppo = f"  eppo={target.eppoCode}" if target.eppoCode else ""
      print(f"  {target.targetCode}  {target.kind.value}  {target.name}{eppo}")
  print("Treatments:")
  for treatment in package.treatments:
    print(f"  {_treatmentLine(treatment)}")
  if package.applications:
    print("Applications:")
    for application in package.applications:
      print(f"  {_applicationLine(application)}")
  print("Ratings:")
  for rating in package.ratings:
    print(f"  {_ratingLine(rating)}")
  print("Assessments:")
  for assessment in package.assessments:
    print(f"  {_assessmentLine(package, assessment)}")
  print(f"Observations: {len(observations)}")
  print(f"Content hash: {workspace.contentHashFor(args.trialCode)}")
  return 0


def _recordedFacts(block) -> str:
  """The names of the facts a planting or soil block records, in schema order."""
  return ", ".join(name for name in type(block).model_fields if getattr(block, name) is not None)


def _layoutOrigin(design) -> str:
  """How the recorded layout came to be: the method and its seed, or 'imported'."""
  if design.randomizationSeed is None:
    return design.randomizationMethod.value
  origin = f"{design.randomizationMethod.value}, seed {design.randomizationSeed}"
  if design.firstBlockInTreatmentOrder:
    origin += ", block 1 in treatment order"
  return origin


def _treatmentLine(treatment) -> str:
  """One line for a treatment: its code, its role when stated, and what it is made of."""
  parts = [treatment.treatmentCode]
  if treatment.role is not None:
    parts.append(f"role={treatment.role.value}")
  for line in treatment.lines:
    applications = ",".join(line.applicationCodes)
    parts.append(
      f"{line.product} {line.rate.value} {line.rate.unit} ({line.rateBasis.value}) at {applications}"
    )
  return "  ".join(parts)


def _applicationLine(application) -> str:
  parts = [application.applicationCode]
  if application.timing:
    parts.append(f"timing={application.timing}")
  if application.date is not None:
    parts.append(f"date={application.date.isoformat()}")
  if application.time is not None:
    parts.append(f"time={application.time.isoformat()}")
  return "  ".join(parts)


def _ratingLine(rating) -> str:
  """One line describing a rating, including its transform and measurement kind.

  transform and measurementKind are only valid on numeric ratings and are shown even at
  their defaults (none / unspecified), so the current setting is visible from the CLI
  rather than only by reading the trial JSON. They are set in the package JSON (the
  canonical design); this surfaces them, it does not add a second way to set them.
  """
  parts = [f"{rating.ratingCode}  {rating.dataType.value}"]
  if rating.targetCode:
    parts.append(f"target={rating.targetCode}")
  if rating.unit:
    parts.append(f"unit={rating.unit}")
  if rating.dataType is AssessmentDataType.numeric:
    if rating.minValue is not None or rating.maxValue is not None:
      low = "" if rating.minValue is None else rating.minValue
      high = "" if rating.maxValue is None else rating.maxValue
      parts.append(f"range=[{low},{high}]")
    parts.append(f"transform={rating.transform.value}")
    parts.append(f"kind={rating.measurementKind.value}")
  else:
    parts.append("values=" + "/".join(rating.allowedValues))
  return "  ".join(parts)


def _assessmentLine(package, assessment) -> str:
  parts = [assessment.assessmentCode, f"rating={assessment.ratingCode}"]
  if assessment.timing:
    parts.append(f"timing={assessment.timing}")
  if assessment.date is not None:
    parts.append(f"date={assessment.date.isoformat()}")
  days = package.daysAfterApplication(assessment.assessmentCode)
  if days is not None:
    parts.append(f"{days} days after {assessment.timedFromApplicationCode}")
  return "  ".join(parts)


def _commandRandomize(args) -> int:
  workspace = Workspace.open(args.database, Actor.operator("cli"))
  package = workspace.loadPackage(args.trialCode)
  layout = workspace.layoutFor(args.trialCode)
  print(f"Layout for '{package.trial.trialCode}' ({_layoutOrigin(package.design)}):")
  print("plot\tblock\tposition\ttreatment")
  for plot in sorted(layout.plots, key=lambda plot: plot.plotNumber):
    print(f"{plot.plotNumber}\t{plot.block}\t{plot.positionInBlock}\t{plot.treatmentCode}")
  return 0


def _commandImport(args) -> int:
  workspace = Workspace.open(args.database, Actor.operator("cli"))
  config = _configFor(args)
  result = workspace.importObservations(args.trialCode, args.csv, config.importProfile)
  print(f"Imported {len(result.observations)} observations for '{args.trialCode}'")
  for warning in result.warnings:
    print(f"  warning: {warning.message}")
  return 0


def _commandReport(args) -> int:
  workspace = Workspace.open(args.database, Actor.operator("cli"))
  report = workspace.buildReport(args.trialCode, locale=args.locale)
  if args.output:
    Path(args.output).write_text(report, encoding="utf-8", newline="\n")
    print(f"Wrote report to {args.output}")
  else:
    print(report)
  return 0


def _commandExport(args) -> int:
  if not args.jsonPath and not args.csvPath:
    print("error: specify --json and/or --csv", file=sys.stderr)
    return 2
  workspace = Workspace.open(args.database, Actor.operator("cli"))
  if args.jsonPath:
    workspace.exportDocument(args.trialCode, args.jsonPath)
    print(f"Wrote {args.jsonPath}")
  if args.csvPath:
    workspace.exportObservationsCsv(args.trialCode, args.csvPath)
    print(f"Wrote {args.csvPath}")
  return 0


def _commandImportWeather(args) -> int:
  count = Workspace.open(args.database, Actor.operator("cli")).importWeather(args.trialCode, args.csv)
  print(f"Replaced the weather log of '{args.trialCode}' with {count} days")
  return 0


def _commandImportJson(args) -> int:
  workspace = Workspace.create(args.database, Actor.operator("cli"))
  trialCode = workspace.importDocument(args.jsonFile, args.place)
  count = len(workspace.loadObservations(trialCode))
  print(f"Imported trial '{trialCode}' with {count} observations")
  return 0


def _commandVerify(args) -> int:
  workspace = Workspace.open(args.database, Actor.operator("cli"))
  check = workspace.verifyRoundTrip(args.trialCode)
  if check.matches:
    print(f"PASS reproducibility check for '{args.trialCode}'")
    print(f"  content hash: {check.storedHash}")
    return 0
  print(f"FAIL reproducibility check for '{args.trialCode}'", file=sys.stderr)
  print(f"  stored:     {check.storedHash}", file=sys.stderr)
  print(f"  round-trip: {check.roundTripHash}", file=sys.stderr)
  return 1


def _commandDelete(args) -> int:
  Workspace.open(args.database, Actor.operator("cli")).deleteTrial(args.trialCode)
  print(f"Deleted trial '{args.trialCode}'")
  return 0


def _commandServe(args) -> int:
  # The service lives behind the optional 'service' extra (Flask). Import it here, not
  # at module load, so every other command works without Flask installed and 'serve'
  # gives a clear install hint instead of an opaque ImportError at startup.
  try:
    from openfurrow.service import createApp, runService, serviceUrl
  except ImportError as error:
    print(
      f"error: the HTTP service requires Flask, which is not installed ({error}). "
      f"Install it with: pip install 'openfurrow[service]'",
      file=sys.stderr,
    )
    return 1

  config = _configFor(args)
  # --host/--port override the config so an operator can bind without editing a file.
  if args.host or args.port is not None:
    service = config.service.model_copy(update={
      key: value for key, value in (("host", args.host), ("port", args.port))
      if value is not None
    })
    config = config.model_copy(update={"service": service})

  # Workspace.open fails loud here if the database does not exist, before we bind.
  application = createApp(args.database, config)
  print(f"Serving OpenFurrow on {serviceUrl(config)} (Ctrl-C to stop)")
  runService(application, config)
  return 0


if __name__ == "__main__":
  sys.exit(main())
