# SPDX-License-Identifier: Apache-2.0
"""The HTTP API: one Flask app, thin controllers over the core facade (decision 0009).

This is the single HTTP interface behind every non-CLI surface. The controllers do
exactly three things: read the request, call one `Workspace` method, serialize the
result. No statistics, no store access, no layout regeneration, no business rules --
if a controller ever needs to compute something, the computation belongs on the facade
where the CLI and every future surface get it too (decision 0002: own the math once).

Errors are mapped, not swallowed. Every failure the core raises becomes a non-2xx
response carrying the core's own message: an unknown trial is 404, a conflicting write
is 409, bad input is 400. Nothing is caught and turned into a cheerful empty result.
The status mapping keys off the exception *type*, never the message text.

Authentication is deliberately absent: the first target is a local single-user tool
bound to loopback (decision 0005 defers the access model, and unit B5 is where it
arrives). This app must not be exposed to a network without that work.

JSON is serialized with the `json` module rather than `flask.jsonify`, per the house
rule; pydantic models are dumped in JSON mode so enums and dates come out canonical.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from flask import Flask, Response, request
from pydantic import BaseModel, ValidationError

from openfurrow.config import ImportProfile, OpenFurrowConfig, MeanComparison, defaultConfig
from openfurrow.i18n import MessageError, availableLocales, sourceLocale
from openfurrow.schema import TrialPackage
from openfurrow.service.web import createWebBlueprint
from openfurrow.store import TrialExistsError, TrialNotFoundError
from openfurrow.workspace import (
  AnalysisError,
  ExchangeError,
  ObservationImportError,
  StoreError,
  Workspace,
)

_jsonType = "application/json"


def createApp(databasePath: str, config: OpenFurrowConfig | None = None) -> Flask:
  """Build the Flask app over the trial database at `databasePath`.

  The Workspace holds a pooled engine and opens a session per call, so one app can
  serve many requests without sharing session state across them.
  """
  application = Flask(__name__)
  settings = config or defaultConfig()
  workspace = Workspace.open(databasePath)

  _registerErrorHandlers(application)
  _registerRoutes(application, workspace, settings)
  application.register_blueprint(createWebBlueprint(workspace))
  return application


# ---- serialization --------------------------------------------------------

def _json(payload: object, status: int = 200) -> Response:
  body = json.dumps(_serializable(payload), indent=2, sort_keys=False)
  return Response(body, status=status, mimetype=_jsonType)


def _serializable(payload: object) -> object:
  if isinstance(payload, BaseModel):
    return payload.model_dump(mode="json")
  if isinstance(payload, list):
    return [_serializable(item) for item in payload]
  if isinstance(payload, dict):
    return {key: _serializable(value) for key, value in payload.items()}
  return payload


def _error(message: str, status: int) -> Response:
  return Response(json.dumps({"error": message}), status=status, mimetype=_jsonType)


# ---- error mapping --------------------------------------------------------

def _registerErrorHandlers(application: Flask) -> None:
  # Order matters only in that the specific store errors are registered alongside the
  # general one; Flask dispatches to the most specific handler for the raised type.
  @application.errorhandler(TrialNotFoundError)
  def notFound(error: TrialNotFoundError) -> Response:
    return _error(str(error), 404)

  @application.errorhandler(TrialExistsError)
  def conflict(error: TrialExistsError) -> Response:
    return _error(str(error), 409)

  @application.errorhandler(StoreError)
  def storeFailure(error: StoreError) -> Response:
    return _error(str(error), 400)

  @application.errorhandler(ValidationError)
  def invalidPackage(error: ValidationError) -> Response:
    return _error(f"invalid trial package: {error}", 400)

  @application.errorhandler(ObservationImportError)
  def importFailure(error: ObservationImportError) -> Response:
    return _error(str(error), 400)

  @application.errorhandler(AnalysisError)
  def analysisFailure(error: AnalysisError) -> Response:
    return _error(str(error), 400)

  @application.errorhandler(ExchangeError)
  def exchangeFailure(error: ExchangeError) -> Response:
    return _error(str(error), 400)

  @application.errorhandler(MessageError)
  def localeFailure(error: MessageError) -> Response:
    return _error(str(error), 400)


# ---- routes ---------------------------------------------------------------

def _registerRoutes(application: Flask, workspace: Workspace, config: OpenFurrowConfig) -> None:

  def _alpha() -> float:
    value = request.args.get("significanceLevel")
    if value is None:
      return config.analysis.significanceLevel
    try:
      return float(value)
    except ValueError:
      raise AnalysisError(f"significanceLevel '{value}' is not a number")

  def _protected() -> bool:
    return config.analysis.meanComparison is MeanComparison.protectedLSD

  @application.get("/health")
  def health() -> Response:
    return _json({"status": "ok", "locales": availableLocales()})

  # -- trials --

  @application.get("/api/trials")
  def listTrials() -> Response:
    trials = [
      {"trialCode": trialCode, "title": title}
      for trialCode, title in workspace.listTrials()
    ]
    return _json(trials)

  @application.post("/api/trials")
  def addTrial() -> Response:
    package = TrialPackage.model_validate(_body())
    workspace.addPackage(package)
    trialCode = package.trial.trialCode
    return _json({"trialCode": trialCode, "contentHash": workspace.contentHashFor(trialCode)}, 201)

  @application.get("/api/trials/<trialCode>")
  def getTrial(trialCode: str) -> Response:
    package = workspace.loadPackage(trialCode)
    return _json({
      "package": package,
      "observationCount": len(workspace.loadObservations(trialCode)),
      "contentHash": workspace.contentHashFor(trialCode),
    })

  @application.delete("/api/trials/<trialCode>")
  def deleteTrial(trialCode: str) -> Response:
    workspace.deleteTrial(trialCode)
    return _json({"trialCode": trialCode, "deleted": True})

  @application.get("/api/trials/<trialCode>/layout")
  def getLayout(trialCode: str) -> Response:
    return _json(workspace.layoutFor(trialCode))

  # -- observations --

  @application.get("/api/trials/<trialCode>/observations")
  def getObservations(trialCode: str) -> Response:
    return _json(workspace.loadObservations(trialCode))

  @application.post("/api/trials/<trialCode>/observations")
  def importObservations(trialCode: str) -> Response:
    """Import a CSV body. The profile comes from config unless one is supplied."""
    profile = config.importProfile
    supplied = request.args.get("profile")
    if supplied:
      profile = ImportProfile.model_validate(json.loads(supplied))
    with _temporaryCsv(request.get_data()) as csvPath:
      result = workspace.importObservations(trialCode, csvPath, profile)
    return _json({
      "trialCode": trialCode,
      "imported": len(result.observations),
      "warnings": [warning.message for warning in result.warnings],
      "contentHash": workspace.contentHashFor(trialCode),
    }, 201)

  @application.post("/api/trials/<trialCode>/observations/fieldbook")
  def importFieldBook(trialCode: str) -> Response:
    """Import a Field Book database (long) export, posted as CSV."""
    with _temporaryCsv(request.get_data()) as csvPath:
      result = workspace.importFieldBook(trialCode, csvPath)
    return _json({
      "trialCode": trialCode,
      "imported": len(result.observations),
      "contentHash": workspace.contentHashFor(trialCode),
    }, 201)

  # -- analysis --

  @application.get("/api/trials/<trialCode>/analysis/<assessmentCode>")
  def analyze(trialCode: str, assessmentCode: str) -> Response:
    return _json(workspace.analyze(trialCode, assessmentCode))

  @application.get("/api/trials/<trialCode>/means/<assessmentCode>")
  def separateMeans(trialCode: str, assessmentCode: str) -> Response:
    return _json(workspace.separateMeans(
      trialCode, assessmentCode, significanceLevel=_alpha(), protected=_protected(),
    ))

  @application.get("/api/trials/<trialCode>/assumptions/<assessmentCode>")
  def assessAssumptions(trialCode: str, assessmentCode: str) -> Response:
    return _json(workspace.assessAssumptions(
      trialCode, assessmentCode, significanceLevel=_alpha(),
    ))

  @application.get("/api/trials/<trialCode>/report")
  def report(trialCode: str) -> Response:
    """The Markdown report. `locale` selects display text only; it never touches data."""
    markdown = workspace.buildReport(
      trialCode,
      significanceLevel=_alpha(),
      protected=_protected(),
      locale=request.args.get("locale", sourceLocale),
    )
    return Response(markdown, status=200, mimetype="text/markdown; charset=utf-8")

  # -- exchange and fixity --

  @application.get("/api/trials/<trialCode>/hash")
  def contentHash(trialCode: str) -> Response:
    return _json({"trialCode": trialCode, "contentHash": workspace.contentHashFor(trialCode)})

  @application.get("/api/trials/<trialCode>/verify")
  def verify(trialCode: str) -> Response:
    check = workspace.verifyRoundTrip(trialCode)
    return _json(check, 200 if check.matches else 409)

  @application.get("/api/trials/<trialCode>/document")
  def exportDocument(trialCode: str) -> Response:
    with tempfile.TemporaryDirectory() as directory:
      path = str(Path(directory) / "trial.json")
      workspace.exportDocument(trialCode, path)
      body = Path(path).read_text(encoding="utf-8")
    return Response(body, status=200, mimetype=_jsonType)

  @application.post("/api/documents")
  def importDocument() -> Response:
    with tempfile.TemporaryDirectory() as directory:
      path = Path(directory) / "trial.json"
      path.write_bytes(request.get_data())
      trialCode = workspace.importDocument(str(path))
    return _json({"trialCode": trialCode, "contentHash": workspace.contentHashFor(trialCode)}, 201)


# ---- request helpers ------------------------------------------------------

def _body() -> dict:
  """The request's JSON body; fails loud rather than silently treating it as empty."""
  data = request.get_data()
  if not data:
    raise StoreError("request body is empty; expected a JSON trial package")
  try:
    return json.loads(data)
  except json.JSONDecodeError as error:
    raise StoreError(f"request body is not valid JSON: {error}") from error


class _temporaryCsv:
  """Write an uploaded CSV to a temp file, because the importer reads from a path."""

  def __init__(self, data: bytes) -> None:
    if not data:
      raise ObservationImportError("request body is empty; expected CSV observation data")
    self._data = data
    self._directory = tempfile.TemporaryDirectory()

  def __enter__(self) -> str:
    path = Path(self._directory.name) / "upload.csv"
    path.write_bytes(self._data)
    return str(path)

  def __exit__(self, *exception) -> None:
    self._directory.cleanup()
