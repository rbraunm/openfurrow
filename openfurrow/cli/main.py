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
profile, the service's binding and the largest file an import takes.
"""

from __future__ import annotations

import argparse
import datetime
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
from openfurrow.identity.workloads import claimsGiven, namedIssuers
from openfurrow.osService.deployment import DeploymentError, Role, ServiceState, serviceName
from openfurrow.retention import RetentionError, summaryOf
from openfurrow.workspace import (
  AnalysisError,
  ExchangeError,
  MessageError,
  NotPermitted,
  ObservationImportError,
  StoreError,
  TaskError,
  WeatherFileError,
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
    NotPermitted, TaskError, DeploymentError, RetentionError,
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

  exportParser = sub.add_parser("export", help="export a trial to JSON, CSV and/or a bundle with its received files")
  exportParser.add_argument("database")
  exportParser.add_argument("trialCode")
  exportParser.add_argument("--json", dest="jsonPath", help="write the trial document to this JSON file")
  exportParser.add_argument("--csv", dest="csvPath", help="write observations to this CSV file")
  exportParser.add_argument("--bundle", dest="bundlePath",
                            help="write the trial document and its files as received to this zip file")
  exportParser.set_defaults(handler=_commandExport)

  weatherParser = sub.add_parser("import-weather", help="replace a trial's weather log from a CSV file")
  weatherParser.add_argument("database")
  weatherParser.add_argument("trialCode")
  weatherParser.add_argument("csv", help="date, then any of rainfall, irrigation, minimumTemperature, "
                              "maximumTemperature with the unit in brackets, and notes")
  weatherParser.add_argument("--config", help="path to a project config file (see examples/openfurrow.yaml)")
  weatherParser.set_defaults(handler=_commandImportWeather)

  importJsonParser = sub.add_parser("import-json", help="import a trial document from JSON into the database")
  importJsonParser.add_argument("database")
  importJsonParser.add_argument("jsonFile", help="path to a trial document JSON file")
  importJsonParser.add_argument("--place", help="the place the trial goes in")
  importJsonParser.set_defaults(handler=_commandImportJson)

  importBundleParser = sub.add_parser("import-bundle", help="import a trial bundle: the trial and its received files")
  importBundleParser.add_argument("database")
  importBundleParser.add_argument("bundleFile", help="path to a bundle written by 'export --bundle'")
  importBundleParser.add_argument("--place", help="the place the trial goes in")
  importBundleParser.add_argument("--config", help="path to a project config file (see examples/openfurrow.yaml)")
  importBundleParser.set_defaults(handler=_commandImportBundle)

  receivedParser = sub.add_parser("received", help="the files a trial's imports received: list, download")
  receivedSub = receivedParser.add_subparsers(dest="receivedCommand", required=True)
  receivedList = receivedSub.add_parser("list", help="each file kept, its hash, column mapping and what it produced")
  receivedList.add_argument("database")
  receivedList.add_argument("trialCode")
  receivedList.set_defaults(handler=_commandReceivedList)
  receivedDownload = receivedSub.add_parser("download", help="write a received file's bytes exactly as they came")
  receivedDownload.add_argument("database")
  receivedDownload.add_argument("trialCode")
  receivedDownload.add_argument("fileID", type=int)
  receivedDownload.add_argument("output", help="the file to write")
  receivedDownload.set_defaults(handler=_commandReceivedDownload)

  closeParser = sub.add_parser("close", help="record the day a trial was closed; retention counts from it")
  closeParser.add_argument("database")
  closeParser.add_argument("trialCode")
  closeParser.add_argument("closedOn", help="the day, YYYY-MM-DD, today or earlier")
  closeParser.set_defaults(handler=_commandClose)
  reopenParser = sub.add_parser("reopen", help="clear a trial's closed date")
  reopenParser.add_argument("database")
  reopenParser.add_argument("trialCode")
  reopenParser.set_defaults(handler=_commandReopen)

  retentionParser = sub.add_parser(
    "retention", help="what the store holds, what its retention rules let go, holds (decision 0044)",
    epilog="A rule is the setting retention.<area>: keep, keepFor:<period> or keepUntilClosed:<period>, a period "
           "being P90D, P18M or P5Y; set one with 'setting set'.",
  )
  retentionSub = retentionParser.add_subparsers(dest="retentionCommand", required=True)
  retentionStatus = retentionSub.add_parser("status", help="each area's count, bytes, rule and where it was set; the holds")
  retentionStatus.add_argument("database")
  retentionStatus.set_defaults(handler=_commandRetentionStatus)
  retentionPreview = retentionSub.add_parser("preview", help="exactly what pruning now would remove; changes nothing")
  retentionPreview.add_argument("database")
  retentionPreview.set_defaults(handler=_commandRetentionPreview)
  retentionPrune = retentionSub.add_parser("prune", help="remove what the retention rules let go")
  retentionPrune.add_argument("database")
  retentionPrune.set_defaults(handler=_commandRetentionPrune)
  retentionHold = retentionSub.add_parser("hold", help="put a trial under a hold: nothing of it is pruned or deleted")
  retentionHold.add_argument("database")
  retentionHold.add_argument("trialCode")
  retentionHold.add_argument("reason")
  retentionHold.set_defaults(handler=_commandRetentionHold)
  retentionRelease = retentionSub.add_parser("release", help="release a trial's hold")
  retentionRelease.add_argument("database")
  retentionRelease.add_argument("trialCode")
  retentionRelease.add_argument("reason")
  retentionRelease.set_defaults(handler=_commandRetentionRelease)

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

  workloadParser = sub.add_parser(
    "workload", help="trusted workloads: CI and cloud jobs that prove what they are with their platform's token "
                     "(decision 0042)",
    epilog="A rule's roles are given with 'role assign ... --workload <name>'. Every token must name the audience "
           "in the server setting identity.workloadAudience.",
  )
  workloadSub = workloadParser.add_subparsers(dest="workloadCommand", required=True)
  workloadAdd = workloadSub.add_parser("add", help="trust the jobs whose tokens an issuer signs with exactly these claims")
  workloadAdd.add_argument("database")
  workloadAdd.add_argument("name")
  workloadAdd.add_argument("issuer", help=f"{' or '.join(namedIssuers)}, or the https address of an OpenID Connect issuer")
  workloadAdd.add_argument("claims", nargs="+", metavar="CLAIM=VALUE",
                           help="a claim every token must carry with exactly this value, such as repository_id=123456")
  workloadAdd.add_argument("--certificate-authority", dest="certificateAuthority", metavar="FILE",
                           help="a PEM file of the certificate authority of an issuer that has one of its own")
  workloadAdd.set_defaults(handler=_commandWorkloadAdd)
  workloadList = workloadSub.add_parser("list", help="list the workload rules")
  workloadList.add_argument("database")
  workloadList.set_defaults(handler=_commandWorkloadList)
  workloadShow = workloadSub.add_parser("show", help="one rule in full, with the roles given to it")
  workloadShow.add_argument("database")
  workloadShow.add_argument("name")
  workloadShow.set_defaults(handler=_commandWorkloadShow)
  for name, enabled in (("enable", True), ("disable", False)):
    toggle = workloadSub.add_parser(name, help=f"{name} a workload rule")
    toggle.add_argument("database")
    toggle.add_argument("name")
    toggle.set_defaults(handler=_commandWorkloadEnabled, enabled=enabled)
  workloadRemove = workloadSub.add_parser("remove", help="remove a workload rule and the roles given to it")
  workloadRemove.add_argument("database")
  workloadRemove.add_argument("name")
  workloadRemove.set_defaults(handler=_commandWorkloadRemove)

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
    assign = roleSub.add_parser(name, help=f"{name} a role to an account, a group or a workload rule at a scope")
    assign.add_argument("database")
    assign.add_argument("roleCode")
    assign.add_argument("scope", help="'server', 'place:<path>' or 'trial:<code>'")
    who = assign.add_mutually_exclusive_group(required=True)
    who.add_argument("--user", dest="userName")
    who.add_argument("--group", dest="groupName")
    who.add_argument("--workload", dest="ruleName", help="a workload rule's name")
    assign.set_defaults(handler=_commandRoleAssign, given=given)
  roleAssignments = roleSub.add_parser("assignments", help="every role given, to whom and where")
  roleAssignments.add_argument("database")
  roleAssignments.set_defaults(handler=_commandRoleAssignments)

  auditParser = sub.add_parser("audit", help="the latest changes, who made them and from where")
  auditParser.add_argument("database")
  auditParser.add_argument("--scope", default="server", help="'server' (everything), 'place:<path>' or 'trial:<code>'")
  auditParser.add_argument("--limit", type=int, default=50)
  auditParser.set_defaults(handler=_commandAudit)

  schedulerParser = sub.add_parser("scheduler", help="run the scheduler beside the web server (decision 0041)")
  schedulerParser.add_argument("database")
  schedulerParser.add_argument("--poll-seconds", dest="pollSeconds", type=float, default=2.0,
                               help="how often it looks for due tasks and requested runs (default 2)")
  schedulerParser.set_defaults(handler=_commandScheduler)

  taskParser = sub.add_parser("task", help="scheduled tasks: list, show, change, enable, disable, run, runs")
  taskSub = taskParser.add_subparsers(dest="taskCommand", required=True)
  taskList = taskSub.add_parser("list", help="every task, its schedule, next run and last outcome")
  taskList.add_argument("database")
  taskList.set_defaults(handler=_commandTaskList)
  taskShow = taskSub.add_parser("show", help="one task in full")
  taskShow.add_argument("database")
  taskShow.add_argument("name")
  taskShow.set_defaults(handler=_commandTaskShow)
  taskSet = taskSub.add_parser("set", help="change a task's schedule or time limit")
  taskSet.add_argument("database")
  taskSet.add_argument("name")
  taskSet.add_argument("--schedule", help="a five-field cron expression, read in the setting tasks.timeZone")
  taskSet.add_argument("--time-limit", dest="timeLimit", help="how long a run may take: 90s, 15m or 2h")
  taskSet.set_defaults(handler=_commandTaskSet)
  for name, enabled in (("enable", True), ("disable", False)):
    toggle = taskSub.add_parser(name, help=f"{name} a task's schedule")
    toggle.add_argument("database")
    toggle.add_argument("name")
    toggle.set_defaults(handler=_commandTaskEnabled, enabled=enabled)
  taskRun = taskSub.add_parser("run", help="request a run now; a running scheduler starts it")
  taskRun.add_argument("database")
  taskRun.add_argument("name")
  taskRun.set_defaults(handler=_commandTaskRun)
  taskRuns = taskSub.add_parser("runs", help="a task's runs, newest first")
  taskRuns.add_argument("database")
  taskRuns.add_argument("name")
  taskRuns.add_argument("--limit", type=int, default=20)
  taskRuns.add_argument("--output", action="store_true", help="print each run's output too")
  taskRuns.set_defaults(handler=_commandTaskRuns)

  serveParser = sub.add_parser("serve", help="run the HTTP service over a trial database")
  serveParser.add_argument("database")
  serveParser.add_argument("--config", help="path to a project config file (see examples/openfurrow.yaml)")
  serveParser.add_argument("--host", help="bind address (overrides config; default from config)")
  serveParser.add_argument("--port", type=int, help="bind port (overrides config)")
  serveParser.set_defaults(handler=_commandServe)

  serviceParser = sub.add_parser(
    "service", help="the web server and the scheduler as operating-system services (decision 0009)",
    epilog="A deployment is two services on one store: openfurrow-web and openfurrow-scheduler, with -<suffix> "
           "after each name when a suffix is given. Installing, uninstalling, starting and stopping need an "
           "elevated shell.",
  )
  serviceSub = serviceParser.add_subparsers(dest="serviceCommand", required=True)
  serviceInstall = serviceSub.add_parser("install", help="install both services on a store, to start with the machine")
  serviceInstall.add_argument("database", help="the store: a file in a folder of its own, or a PostgreSQL URL that "
                                               "the environment file also holds as OPENFURROW_STORE")
  serviceInstall.add_argument("--host", help="the address the web server listens on (default 127.0.0.1)")
  serviceInstall.add_argument("--port", type=int, help="the port the web server listens on (default 8420)")
  serviceInstall.add_argument("--suffix", help="set this deployment's services apart from another's on this machine")
  serviceInstall.add_argument("--environment-file", dest="environmentFile",
                              help="a file of NAME=value lines the services take their environment from: "
                                   "identity providers' secrets and the like")
  serviceInstall.add_argument("--logs", help="the folder for the services' logs (default: logs beside the store)")
  serviceInstall.set_defaults(handler=_commandServiceInstall)
  for name, handler, text in (
    ("uninstall", _commandServiceUninstall, "stop and remove both services; the store, its logs and the environment file stay"),
    ("start", _commandServiceStart, "start both services now"),
    ("stop", _commandServiceStop, "stop both services, the scheduler first; its running tasks finish or are recorded stopped"),
    ("status", _commandServiceStatus, "each service's state, and when the scheduler last checked in"),
  ):
    serviceAction = serviceSub.add_parser(name, help=text)
    serviceAction.add_argument("--suffix", help="the suffix the deployment was installed with")
    serviceAction.set_defaults(handler=handler)

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


def _importer(args, create: bool = False) -> Workspace:
  """The operator's workspace for a command that reads a file, taking files up to the configuration's limit."""
  start = Workspace.create if create else Workspace.open
  return start(args.database, Actor.operator("cli"), maximumFileBytes=_configFor(args).service.maxUploadBytes)


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
  assignment = RoleAssignment(roleCode=args.roleCode, scope=args.scope, userName=args.userName, groupName=args.groupName,
                              ruleName=args.ruleName)
  workspace = _operator(args.database)
  (workspace.assignRole if args.given else workspace.unassignRole)(assignment)
  print(f"{'Gave' if args.given else 'Took back'} '{args.roleCode}' at {args.scope}")
  return 0


def _commandRoleAssignments(args) -> int:
  for assignment in _operator(args.database).assignments():
    holders = (("user", assignment.userName), ("group", assignment.groupName), ("workload", assignment.ruleName))
    who = next(f"{kind} {name}" for kind, name in holders if name is not None)
    print(f"{assignment.roleCode}\t{assignment.scope}\t{who}")
  return 0


def _ruleLine(rule) -> str:
  claims = " ".join(f"{name}={value}" for name, value in sorted(rule.claims.items()))
  return f"{rule.name}\t{'enabled' if rule.enabled else 'disabled'}\t{rule.issuer}\t{claims}"


def _commandWorkloadAdd(args) -> int:
  rule = _operator(args.database).addWorkloadRule(args.name, args.issuer, claimsGiven(args.claims), args.certificateAuthority)
  print(f"Added workload rule '{rule.name}' for {rule.issuer}; it holds no role until one is given "
        f"(role assign ... --workload {rule.name})")
  return 0


def _commandWorkloadList(args) -> int:
  rules = _operator(args.database).workloadRules()
  if not rules:
    print("(no workload rules)")
  for rule in rules:
    print(_ruleLine(rule))
  return 0


def _commandWorkloadShow(args) -> int:
  rule, given = _operator(args.database).workloadRule(args.name)
  print(f"Workload rule: {rule.name}, {'enabled' if rule.enabled else 'disabled'}")
  print(f"Issuer: {rule.issuer}")
  for name, value in sorted(rule.claims.items()):
    print(f"Requires: {name}={value}")
  if rule.certificateAuthority is not None:
    print(f"Certificate authority: {rule.certificateAuthority}")
  print(f"Added: {_when(rule.createdAt)}")
  if not given:
    print("Roles: none")
  for assignment in given:
    print(f"Role: {assignment.roleCode} at {assignment.scope}")
  return 0


def _commandWorkloadEnabled(args) -> int:
  _operator(args.database).setWorkloadRuleEnabled(args.name, args.enabled)
  print(f"{'Enabled' if args.enabled else 'Disabled'} workload rule '{args.name}'")
  return 0


def _commandWorkloadRemove(args) -> int:
  _operator(args.database).removeWorkloadRule(args.name)
  print(f"Removed workload rule '{args.name}' and the roles given to it")
  return 0


def _commandAudit(args) -> int:
  for event in _operator(args.database).auditEvents(args.scope, args.limit):
    who = event.actorName or event.actorKind
    print(f"{event.at}\t{who}\t{event.surface}\t{event.action}\t{event.scope}\t{json.dumps(event.detail, sort_keys=True)}")
  return 0


def _commandScheduler(args) -> int:
  from openfurrow.tasks.scheduler import Scheduler
  scheduler = Scheduler(args.database, pollSeconds=args.pollSeconds)
  print(f"Scheduler running on {scheduler.host} (process {scheduler.processID}); Ctrl+C to stop", flush=True)
  scheduler.run()
  print("Scheduler stopped", flush=True)
  return 0


_durationUnits = {"s": 1, "m": 60, "h": 3600}


def _seconds(text: str) -> int:
  if len(text) < 2 or text[-1] not in _durationUnits or not text[:-1].isascii() or not text[:-1].isdigit():
    raise TaskError(f"'{text}' is not a duration: a whole number with s, m or h, such as 90s, 15m or 2h")
  return int(text[:-1]) * _durationUnits[text[-1]]


def _when(moment) -> str:
  return "-" if moment is None else moment.isoformat(timespec="seconds")


def _taskLine(task) -> str:
  last = task.lastRun
  outcome = "-" if last is None else f"{last.state.value} {_when(last.finishedAt or last.requestedAt)}"
  return (f"{task.name}\t{task.kind}\t{task.schedule}\t{'enabled' if task.enabled else 'disabled'}\t"
          f"next {_when(task.nextRunAt)}\tlast {outcome}")


def _commandTaskList(args) -> int:
  tasks = _operator(args.database).tasks()
  if not tasks:
    print("(no tasks)")
  for task in tasks:
    print(_taskLine(task))
  return 0


def _commandTaskShow(args) -> int:
  workspace = _operator(args.database)
  task = workspace.task(args.name)
  heartbeat = workspace.schedulerHeartbeat()
  print(f"Task: {task.name}")
  print(f"Kind: {task.kind}  parameters {json.dumps(task.parameters, sort_keys=True)}")
  print(f"Schedule: {task.schedule} ({task.timeZone}), {'enabled' if task.enabled else 'disabled'}")
  print(f"Next run: {_when(task.nextRunAt)}")
  print(f"Time limit: {task.timeLimitSeconds} seconds")
  if task.ownerProvider is not None:
    print(f"Kept for the identity provider '{task.ownerProvider}'")
  if task.ownerFeature is not None:
    print(f"Kept for the store's own {task.ownerFeature}")
  if task.lastRun is not None:
    print(f"Last run: {task.lastRun.runID} {task.lastRun.state.value} {_when(task.lastRun.finishedAt)} "
          f"{task.lastRun.summary or ''}".rstrip())
  print(_heartbeatLine(heartbeat))
  return 0


def _heartbeatLine(heartbeat) -> str:
  if heartbeat is None:
    return "Scheduler: never checked in"
  return f"Scheduler: last checked in {_when(heartbeat.lastSeenAt)} from {heartbeat.host} (process {heartbeat.processID})"


def _commandTaskSet(args) -> int:
  limit = None if args.timeLimit is None else _seconds(args.timeLimit)
  task = _operator(args.database).setTask(args.name, args.schedule, limit)
  print(f"Task '{task.name}': {task.schedule} ({task.timeZone}), time limit {task.timeLimitSeconds} seconds, "
        f"next run {_when(task.nextRunAt)}")
  return 0


def _commandTaskEnabled(args) -> int:
  task = _operator(args.database).setTaskEnabled(args.name, args.enabled)
  print(f"{'Enabled' if args.enabled else 'Disabled'} '{task.name}'; next run {_when(task.nextRunAt)}")
  return 0


def _commandTaskRun(args) -> int:
  runID = _operator(args.database).runTaskNow(args.name)
  print(f"Requested run {runID} of '{args.name}'")
  return 0


def _commandTaskRuns(args) -> int:
  runs = _operator(args.database).taskRuns(args.name, args.limit)
  if not runs:
    print("(no runs)")
  for run in runs:
    print(f"{run.runID}\t{run.state.value}\t{run.requestedBy}\trequested {_when(run.requestedAt)}\t"
          f"started {_when(run.startedAt)}\tfinished {_when(run.finishedAt)}\t{run.summary or ''}")
    if args.output and run.output:
      print(run.output.rstrip("\n"))
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
  result = _importer(args).importObservations(args.trialCode, args.csv, _configFor(args).importProfile)
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
  if not args.jsonPath and not args.csvPath and not args.bundlePath:
    print("error: specify --json, --csv and/or --bundle", file=sys.stderr)
    return 2
  workspace = Workspace.open(args.database, Actor.operator("cli"))
  if args.jsonPath:
    workspace.exportDocument(args.trialCode, args.jsonPath)
    print(f"Wrote {args.jsonPath}")
  if args.csvPath:
    workspace.exportObservationsCsv(args.trialCode, args.csvPath)
    print(f"Wrote {args.csvPath}")
  if args.bundlePath:
    workspace.exportBundle(args.trialCode, args.bundlePath)
    print(f"Wrote {args.bundlePath}")
  return 0


def _commandImportWeather(args) -> int:
  count = _importer(args).importWeather(args.trialCode, args.csv)
  print(f"Replaced the weather log of '{args.trialCode}' with {count} days")
  return 0


def _commandImportJson(args) -> int:
  workspace = Workspace.create(args.database, Actor.operator("cli"))
  trialCode = workspace.importDocument(args.jsonFile, args.place)
  count = len(workspace.loadObservations(trialCode))
  print(f"Imported trial '{trialCode}' with {count} observations")
  return 0


def _commandImportBundle(args) -> int:
  workspace = _importer(args, create=True)
  trialCode = workspace.importBundle(args.bundleFile, args.place)
  print(f"Imported trial '{trialCode}' with {len(workspace.loadObservations(trialCode))} observations and "
        f"{len(workspace.receivedFiles(trialCode))} received files")
  return 0


def _who(kind: str, name: str | None) -> str:
  return kind if name is None else f"{kind} {name}"


def _commandReceivedList(args) -> int:
  files = _operator(args.database).receivedFiles(args.trialCode)
  if not files:
    print("(no received files)")
  for file in files:
    print("\t".join([
      str(file.fileID), file.kind.value, file.fileName or "-", file.sheetName or "-", str(file.sizeBytes), file.sha256,
      _who(file.importedBy.kind.value, file.importedBy.name), _when(file.importedAt),
      json.dumps(file.produced, sort_keys=True), json.dumps(file.mapping, sort_keys=True),
    ]))
  return 0


def _commandReceivedDownload(args) -> int:
  file, content = _operator(args.database).receivedFile(args.trialCode, args.fileID)
  Path(args.output).write_bytes(content)
  print(f"Wrote {args.output} ({file.sizeBytes} bytes, SHA-256 {file.sha256})")
  return 0


def _commandClose(args) -> int:
  try:
    closedOn = datetime.date.fromisoformat(args.closedOn)
  except ValueError:
    raise RetentionError(f"'{args.closedOn}' is not a day; write it YYYY-MM-DD") from None
  _operator(args.database).closeTrial(args.trialCode, closedOn)
  print(f"Trial '{args.trialCode}' is closed on {closedOn.isoformat()}")
  return 0


def _commandReopen(args) -> int:
  _operator(args.database).reopenTrial(args.trialCode)
  print(f"Trial '{args.trialCode}' is open again")
  return 0


def _commandRetentionStatus(args) -> int:
  status = _operator(args.database).retentionStatus()
  for area in status.areas:
    print(f"{area.area.value}\t{area.count}\t{area.sizeBytes} bytes\t{area.rule}\t{area.source}")
    for below in area.setBelow:
      print(f"{area.area.value}\tset at {below.scope}\t{below.rule}")
  if not status.holds:
    print("(no holds)")
  for hold in status.holds:
    print(f"hold\t{hold.trialCode}\t{_who(hold.heldByKind, hold.heldByName)}\t{_when(hold.heldAt)}\t{hold.reason}")
  return 0


def _printPruning(report) -> None:
  for line in report.lines:
    print(f"{line.area.value}\t{line.scope}\t{line.count}\t{line.sizeBytes} bytes\t{line.rule}\t{line.source}")
    for file in line.detail.get("files", []):
      print(f"  file {file['fileID']}\t{file['fileName'] or '-'}\t{file['sizeBytes']} bytes\t{file['sha256']}")


def _commandRetentionPreview(args) -> int:
  report = _operator(args.database).previewPruning()
  if not report.lines:
    print("(nothing to prune)")
  _printPruning(report)
  return 0


def _commandRetentionPrune(args) -> int:
  report = _operator(args.database).prune()
  _printPruning(report)
  print(summaryOf(report))
  return 0


def _commandRetentionHold(args) -> int:
  hold = _operator(args.database).holdTrial(args.trialCode, args.reason)
  print(f"Trial '{hold.trialCode}' is under a hold: {hold.reason}")
  return 0


def _commandRetentionRelease(args) -> int:
  _operator(args.database).releaseHold(args.trialCode, args.reason)
  print(f"Released the hold on trial '{args.trialCode}'")
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


def _serviceSuffixHint(suffix: str | None) -> str:
  return f" --suffix {suffix}" if suffix else ""


def _commandServiceInstall(args) -> int:
  from openfurrow.osService import manage
  service = defaultConfig().service
  deployment = manage.install(args.database, args.host or service.host, service.port if args.port is None else args.port,
                              args.suffix, args.environmentFile, args.logs)
  print(f"Installed {deployment.name(Role.web)} and {deployment.name(Role.scheduler)}; they start with the machine")
  print(f"Web server: http://{deployment.host}:{deployment.port}")
  print(f"Logs: {deployment.logsFolder}")
  print(f"Start them now with: openfurrow service start{_serviceSuffixHint(deployment.suffix)}")
  return 0


def _commandServiceUninstall(args) -> int:
  from openfurrow.osService import manage
  removed = manage.uninstall(args.suffix)
  print(f"Uninstalled {' and '.join(removed)}; the store, its logs and the environment file are left as they are")
  return 0


def _commandServiceStart(args) -> int:
  from openfurrow.osService import manage
  deployment = manage.start(args.suffix)
  print(f"Started {deployment.name(Role.web)} on http://{deployment.host}:{deployment.port} and "
        f"{deployment.name(Role.scheduler)}")
  return 0


def _commandServiceStop(args) -> int:
  from openfurrow.osService import manage
  deployment = manage.stop(args.suffix)
  print(f"Stopped {deployment.name(Role.scheduler)} and {deployment.name(Role.web)}")
  return 0


def _commandServiceStatus(args) -> int:
  from openfurrow.osService import manage
  status = manage.status(args.suffix)
  for role, state in status.states.items():
    name = serviceName(role, args.suffix)
    if state is ServiceState.notInstalled:
      print(f"{name}\t{state.value}")
    elif role is Role.web:
      print(f"{name}\tinstalled\t{state.value}\thttp://{status.deployment.host}:{status.deployment.port}")
    else:
      print(f"{name}\tinstalled\t{state.value}")
  if status.states[Role.scheduler] is not ServiceState.notInstalled:
    print(_heartbeatLine(_operator(status.deployment.storeLocation()).schedulerHeartbeat()))
  return 0


if __name__ == "__main__":
  sys.exit(main())
