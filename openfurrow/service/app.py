# SPDX-License-Identifier: Apache-2.0
"""The HTTP API: one Flask app, thin controllers over the core facade (decision 0009).

This is the single HTTP interface behind every non-CLI surface. The controllers do
exactly three things: read the request, call one `Workspace` method, serialize the
result. No statistics, no store access, no layout logic, no business rules --
if a controller ever needs to compute something, the computation belongs on the facade
where the CLI and every future surface get it too (decision 0002: own the math once).

Errors are mapped, not swallowed. Every failure the core raises becomes a non-2xx
response carrying the core's own message: an unknown trial is 404, a conflicting write
is 409, bad input is 400. Nothing is caught and turned into a cheerful empty result.
The status mapping keys off the exception *type*, never the message text.

Who a request acts as comes from the store's sign-in mode (decision 0036): everyone in
the open mode, otherwise the account, or the trusted workload (decision 0042), behind its
bearer token. The facade checks every
permission and writes every audit event, so the controllers stay free of both.

JSON is serialized with the `json` module rather than `flask.jsonify`, per the house
rule; pydantic models are dumped in JSON mode so enums and dates come out canonical.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from flask import Flask, Response, request
from pydantic import BaseModel, ValidationError
from werkzeug.exceptions import RequestEntityTooLarge

from openfurrow.config import ImportProfile, OpenFurrowConfig, defaultConfig
from openfurrow.i18n import MessageError, availableLocales, sourceLocale
from openfurrow.interop.fieldbook import fieldBookImportProfile
from openfurrow.schema import TrialPackage
from openfurrow.identity.model import Actor
from openfurrow.service.providerRoutes import installProvisioning
from openfurrow.service.signIn import RequestWorkspace, installSignIn
from openfurrow.service.web import createWebBlueprint
from openfurrow.store import NotFoundError, TrialExistsError
from openfurrow.store.hierarchy import ScopeError
from openfurrow.settings import SettingError
from openfurrow.workspace import (
  IdentityError,
  NotPermitted,
  AnalysisError,
  ExchangeError,
  ObservationImportError,
  StoreError,
  TaskError,
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
  # Bound request bodies so an oversize upload is rejected with 413 before being read
  # into memory, rather than letting it exhaust memory on a self-hosted server.
  application.config["MAX_CONTENT_LENGTH"] = settings.service.maxUploadBytes
  base = Workspace.open(databasePath, Actor.operator("service"))
  workspace = RequestWorkspace()
  installSignIn(application, base, settings.service.tls.enabled)
  installProvisioning(application, base)

  _registerErrorHandlers(application)
  _registerRoutes(application, workspace, settings)
  application.register_blueprint(createWebBlueprint(workspace, settings))
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
  @application.errorhandler(NotFoundError)
  def notFound(error: NotFoundError) -> Response:
    return _error(str(error), 404)

  @application.errorhandler(NotPermitted)
  def notPermitted(error: NotPermitted) -> Response:
    return _error(str(error), 403)

  @application.errorhandler(IdentityError)
  def identityFailure(error: IdentityError) -> Response:
    return _error(str(error), 400)

  @application.errorhandler(TaskError)
  def taskFailure(error: TaskError) -> Response:
    return _error(str(error), 400)

  @application.errorhandler(ScopeError)
  def scopeFailure(error: ScopeError) -> Response:
    return _error(str(error), 400)

  @application.errorhandler(SettingError)
  def settingFailure(error: SettingError) -> Response:
    return _error(str(error), 400)

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

  @application.errorhandler(RequestEntityTooLarge)
  def tooLarge(error: RequestEntityTooLarge) -> Response:
    return _error("request body too large", 413)


# ---- routes ---------------------------------------------------------------

def _registerRoutes(application: Flask, workspace: Workspace, config: OpenFurrowConfig) -> None:

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
    workspace.addPackage(package, request.args.get("place"))
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
    table = workspace.readObservationTable("upload.csv", _requestBody())
    result = workspace.importObservationTable(trialCode, table, profile)
    return _json({
      "trialCode": trialCode,
      "imported": len(result.observations),
      "warnings": [warning.message for warning in result.warnings],
      "contentHash": workspace.contentHashFor(trialCode),
    }, 201)

  @application.post("/api/trials/<trialCode>/observations/fieldbook")
  def importFieldBook(trialCode: str) -> Response:
    """Import a Field Book database (long) export, posted as CSV."""
    table = workspace.readObservationTable("upload.csv", _requestBody())
    result = workspace.importObservationTable(trialCode, table, fieldBookImportProfile())
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
    return _json(workspace.separateMeans(trialCode, assessmentCode))

  @application.get("/api/trials/<trialCode>/assumptions/<assessmentCode>")
  def assessAssumptions(trialCode: str, assessmentCode: str) -> Response:
    return _json(workspace.assessAssumptions(trialCode, assessmentCode))

  @application.get("/api/trials/<trialCode>/report")
  def report(trialCode: str) -> Response:
    """The Markdown report. `locale` selects display text only; it never touches data."""
    markdown = workspace.buildReport(trialCode, locale=request.args.get("locale", sourceLocale))
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
      trialCode = workspace.importDocument(str(path), request.args.get("place"))
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


def _requestBody() -> bytes:
  data = request.get_data()
  if not data:
    raise ObservationImportError("request body is empty; expected CSV observation data")
  return data
