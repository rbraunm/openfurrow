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
succeeding. Persistence is a single SQLite file whose path the user gives
explicitly, so it is always visible and movable. Analysis settings come from the
project config (decision 0009): --config points at a config file, otherwise the
defaults apply.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from openfurrow.config import MeanComparison, defaultConfig, loadConfig
from openfurrow.schema import TrialPackage
from openfurrow.workspace import (
  AnalysisError,
  ExchangeError,
  MessageError,
  ObservationImportError,
  StoreError,
  Workspace,
  sourceLocale,
)
from pydantic import ValidationError


def main(argv: list[str] | None = None) -> int:
  """Parse arguments and run the requested command; return a process exit code."""
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
    ValidationError, OSError, json.JSONDecodeError,
  ) as error:
    print(f"error: {error}", file=sys.stderr)
    return 1


# ---- argument parser ------------------------------------------------------

def _buildParser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(prog="openfurrow", description="Reproducible agricultural trial management.")
  sub = parser.add_subparsers(dest="command")

  initParser = sub.add_parser("init", help="create a new trial database")
  initParser.add_argument("database")
  initParser.set_defaults(handler=_commandInit)

  addParser = sub.add_parser("add", help="add a validated trial package from JSON")
  addParser.add_argument("database")
  addParser.add_argument("package", help="path to a trial package JSON file")
  addParser.set_defaults(handler=_commandAdd)

  listParser = sub.add_parser("list", help="list trials in the database")
  listParser.add_argument("database")
  listParser.set_defaults(handler=_commandList)

  infoParser = sub.add_parser("info", help="show a trial summary")
  infoParser.add_argument("database")
  infoParser.add_argument("trialCode")
  infoParser.set_defaults(handler=_commandInfo)

  randomizeParser = sub.add_parser("randomize", help="print the randomized layout for a trial")
  randomizeParser.add_argument("database")
  randomizeParser.add_argument("trialCode")
  randomizeParser.set_defaults(handler=_commandRandomize)

  importParser = sub.add_parser("import", help="import observations from a CSV file")
  importParser.add_argument("database")
  importParser.add_argument("trialCode")
  importParser.add_argument("csv", help="path to an observations CSV file")
  importParser.add_argument("--config", help="path to a project config file")
  importParser.set_defaults(handler=_commandImport)

  reportParser = sub.add_parser("report", help="build the trial report (AOV Means Table)")
  reportParser.add_argument("database")
  reportParser.add_argument("trialCode")
  reportParser.add_argument("--output", help="write the report to this file instead of stdout")
  reportParser.add_argument("--config", help="path to a project config file")
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

  importJsonParser = sub.add_parser("import-json", help="import a trial document from JSON into the database")
  importJsonParser.add_argument("database")
  importJsonParser.add_argument("jsonFile", help="path to a trial document JSON file")
  importJsonParser.set_defaults(handler=_commandImportJson)

  verifyParser = sub.add_parser("verify", help="check a trial round-trips to the same content hash")
  verifyParser.add_argument("database")
  verifyParser.add_argument("trialCode")
  verifyParser.set_defaults(handler=_commandVerify)

  deleteParser = sub.add_parser("delete", help="delete a trial and all its data")
  deleteParser.add_argument("database")
  deleteParser.add_argument("trialCode")
  deleteParser.set_defaults(handler=_commandDelete)

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
  Workspace.create(args.database)
  print(f"Initialized database at {args.database}")
  return 0


def _commandAdd(args) -> int:
  package = _readPackage(args.package)
  workspace = Workspace.create(args.database)
  workspace.addPackage(package)
  print(
    f"Added trial '{package.trial.trialCode}' "
    f"({len(package.treatments)} treatments, {len(package.assessments)} assessments, {package.plotCount} plots)"
  )
  return 0


def _commandList(args) -> int:
  trials = Workspace.open(args.database).listTrials()
  if not trials:
    print("(no trials)")
  for trialCode, title in trials:
    print(f"{trialCode}\t{title}")
  return 0


def _commandInfo(args) -> int:
  workspace = Workspace.open(args.database)
  package = workspace.loadPackage(args.trialCode)
  observations = workspace.loadObservations(args.trialCode)
  trial = package.trial
  print(f"Trial: {trial.trialCode} - {trial.title}")
  print(f"Crop: {trial.crop}   Season: {trial.season}   Site: {trial.site}")
  print(
    f"Design: {package.design.designType.value}, {package.design.replications} blocks, "
    f"{len(package.treatments)} treatments, {package.plotCount} plots"
  )
  print(f"Randomization seed: {package.design.randomizationSeed}")
  print(f"Assessments: {', '.join(assessment.assessmentCode for assessment in package.assessments)}")
  print(f"Observations: {len(observations)}")
  print(f"Content hash: {workspace.contentHashFor(args.trialCode)}")
  return 0


def _commandRandomize(args) -> int:
  workspace = Workspace.open(args.database)
  package = workspace.loadPackage(args.trialCode)
  layout = workspace.layoutFor(args.trialCode)
  print(f"Layout for '{package.trial.trialCode}' (seed {package.design.randomizationSeed}):")
  print("plot\tblock\tposition\ttreatment")
  for plot in sorted(layout.plots, key=lambda plot: plot.plotNumber):
    print(f"{plot.plotNumber}\t{plot.block}\t{plot.positionInBlock}\t{plot.treatmentCode}")
  return 0


def _commandImport(args) -> int:
  workspace = Workspace.open(args.database)
  config = _configFor(args)
  result = workspace.importObservations(args.trialCode, args.csv, config.importProfile)
  print(f"Imported {len(result.observations)} observations for '{args.trialCode}'")
  for warning in result.warnings:
    print(f"  warning: {warning.message}")
  return 0


def _commandReport(args) -> int:
  workspace = Workspace.open(args.database)
  config = _configFor(args)
  protected = config.analysis.meanComparison is MeanComparison.protectedLSD
  report = workspace.buildReport(
    args.trialCode,
    significanceLevel=config.analysis.significanceLevel,
    protected=protected,
    locale=args.locale,
  )
  if args.output:
    Path(args.output).write_text(report, encoding="utf-8")
    print(f"Wrote report to {args.output}")
  else:
    print(report)
  return 0


def _commandExport(args) -> int:
  if not args.jsonPath and not args.csvPath:
    print("error: specify --json and/or --csv", file=sys.stderr)
    return 2
  workspace = Workspace.open(args.database)
  if args.jsonPath:
    workspace.exportDocument(args.trialCode, args.jsonPath)
    print(f"Wrote {args.jsonPath}")
  if args.csvPath:
    workspace.exportObservationsCsv(args.trialCode, args.csvPath)
    print(f"Wrote {args.csvPath}")
  return 0


def _commandImportJson(args) -> int:
  workspace = Workspace.create(args.database)
  trialCode = workspace.importDocument(args.jsonFile)
  count = len(workspace.loadObservations(trialCode))
  print(f"Imported trial '{trialCode}' with {count} observations")
  return 0


def _commandVerify(args) -> int:
  workspace = Workspace.open(args.database)
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
  Workspace.open(args.database).deleteTrial(args.trialCode)
  print(f"Deleted trial '{args.trialCode}'")
  return 0


if __name__ == "__main__":
  sys.exit(main())
