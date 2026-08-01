# SPDX-License-Identifier: Apache-2.0
"""The analyst web UI: server-rendered pages over the same facade (decisions 0009, 0012).

Server-rendered Flask templates, not a single-page app: fewer moving parts, works on
modest hardware and intermittent connections, no separate front-end build, and every
asset served locally so the tool works offline (decision 0012). Light client-side code
only where an interaction needs it -- D1 needs none.

Localization and right-to-left are first-class (decision 0007). Every user-facing
string is resolved from the message catalog through a request-scoped `Translator`; the
document's `lang` and `dir` come from the locale, so the layout mirrors for a
right-to-left locale rather than only the text. The display-only guardrail holds: the
locale chosen with `?locale=` selects catalog and number formatting and never touches
the trial's data or its content hash. Plot numbers, treatment codes, and the seed are
canonical identifiers and are shown verbatim, not localized.

Like the CLI and the JSON API, these views are thin over the `Workspace` facade: they
resolve a request into one or two facade calls and render. No statistics, no store
access, no layout logic lives here.

D1 scope: list trials, add a trial (submit or upload the canonical package JSON -- a
field-by-field design form is a later unit), and view the randomized field layout. The
report view and the analysis pages are D2.
"""

from __future__ import annotations

import json

import markdown as markdownLibrary
from flask import Blueprint, Response, redirect, render_template, request, url_for
from markupsafe import Markup

from openfurrow.config import OpenFurrowConfig, defaultConfig
from openfurrow.i18n import MessageError, availableLocales, sourceLocale, translatorFor
from openfurrow.schema import TrialPackage
from openfurrow.workspace import ObservationImportError, StoreError, Workspace
from pydantic import ValidationError

# Okabe-Ito, a colorblind-safe qualitative palette. Treatment colour is a *redundant*
# cue: every plot cell also shows its treatment code, so the map is readable without
# relying on colour at all. The palette cycles if a trial has more treatments than
# colours -- the code remains the definitive identifier.
_treatmentPalette = [
  "#E69F00", "#56B4E9", "#009E73", "#F0E442",
  "#0072B2", "#D55E00", "#CC79A7", "#7F7F7F",
]


def createWebBlueprint(workspace: Workspace, config: OpenFurrowConfig | None = None) -> Blueprint:
  """Build the HTML UI blueprint over `workspace`. Registered by `createApp`."""
  settings = config or defaultConfig()
  blueprint = Blueprint(
    "web", __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/static",
  )

  def _translator():
    # ?locale= is a display choice only. An unknown locale is a loud 400 via the
    # MessageError handler, not a silent fall back to the source language.
    return translatorFor(request.args.get("locale", sourceLocale))

  def _localeContext(translator):
    # Shared template context: the translator, the current locale, its direction, and
    # the locales offered in the switcher.
    return {
      "t": translator,
      "locale": translator.locale,
      "direction": translator.direction,
      "locales": availableLocales(),
    }

  def _trialContext(trialCode: str) -> dict:
    # Assembled once and reused by the trial page and the import handler that
    # re-renders it, so the two cannot drift.
    package = workspace.loadPackage(trialCode)
    layout = workspace.layoutFor(trialCode)
    return {
      "package": package,
      "observationCount": len(workspace.loadObservations(trialCode)),
      "contentHash": workspace.contentHashFor(trialCode),
      "blocks": _blocks(layout),
      "legend": _legend(package),
    }

  @blueprint.get("/")
  def index() -> Response:
    translator = _translator()
    trials = [
      {"trialCode": trialCode, "title": title, "package": workspace.loadPackage(trialCode)}
      for trialCode, title in workspace.listTrials()
    ]
    return Response(render_template("trials.html", trials=trials, **_localeContext(translator)))

  @blueprint.get("/trials/new")
  def newTrial() -> Response:
    translator = _translator()
    return Response(render_template(
      "add.html", example=_examplePackageJson(), error=None, submitted="",
      **_localeContext(translator),
    ))

  @blueprint.post("/trials/new")
  def createTrial() -> Response:
    translator = _translator()
    raw = _submittedPackage()
    try:
      package = TrialPackage.model_validate(json.loads(raw))
      workspace.addPackage(package)
    except (json.JSONDecodeError, ValidationError, StoreError) as error:
      # Re-render the form with the message and the text the user submitted, so nothing
      # they typed is lost. The form fails loud rather than discarding bad input.
      return Response(
        render_template(
          "add.html", example=_examplePackageJson(), error=str(error), submitted=raw,
          **_localeContext(translator),
        ),
        status=400,
      )
    return redirect(_localized(url_for("web.trial", trialCode=package.trial.trialCode), translator))

  @blueprint.get("/trials/<trialCode>")
  def trial(trialCode: str) -> Response:
    translator = _translator()
    context = _trialContext(trialCode) | {"result": None, "importError": None, "verifyResult": None}
    return Response(render_template("trial.html", **context, **_localeContext(translator)))

  @blueprint.get("/trials/<trialCode>/verify")
  def verify(trialCode: str) -> Response:
    # Read-only: exports and re-imports the trial and compares hashes. A GET is correct
    # -- it changes nothing -- and the result renders back on the trial page.
    translator = _translator()
    check = workspace.verifyRoundTrip(trialCode)
    context = _trialContext(trialCode) | {"result": None, "importError": None, "verifyResult": check}
    return Response(render_template("trial.html", **context, **_localeContext(translator)))

  @blueprint.get("/trials/<trialCode>/delete")
  def confirmDelete(trialCode: str) -> Response:
    # A confirmation page, not a JS dialog: deletion is destructive, and a plain page
    # works without JavaScript. Loading it fails loud (404) if the trial is unknown.
    translator = _translator()
    package = workspace.loadPackage(trialCode)
    return Response(render_template(
      "delete.html", trialCode=trialCode, title=package.trial.title, **_localeContext(translator),
    ))

  @blueprint.post("/trials/<trialCode>/delete")
  def deleteTrial(trialCode: str) -> Response:
    # Only a POST deletes; the GET above merely confirms. This is what keeps a crawler,
    # a prefetch, or an accidental link-follow from destroying data.
    translator = _translator()
    workspace.deleteTrial(trialCode)
    return redirect(_localized(url_for("web.index"), translator))

  @blueprint.post("/trials/<trialCode>/observations")
  def importObservations(trialCode: str) -> Response:
    translator = _translator()
    fieldFormat = request.form.get("format", "openfurrow")
    upload = request.files.get("file")
    result = None
    importError = None
    try:
      if not upload or not upload.filename:
        raise ObservationImportError("choose a CSV file to import")
      data = upload.read()
      with _temporaryCsv(data) as csvPath:
        if fieldFormat == "fieldbook":
          outcome = workspace.importFieldBook(trialCode, csvPath)
        else:
          outcome = workspace.importObservations(trialCode, csvPath, settings.importProfile)
      result = {
        "imported": len(outcome.observations),
        "warnings": [warning.message for warning in outcome.warnings],
      }
    except ObservationImportError as error:
      importError = str(error)

    context = _trialContext(trialCode) | {"result": result, "importError": importError, "verifyResult": None}
    status = 400 if importError else 200
    return Response(render_template("trial.html", **context, **_localeContext(translator)), status=status)

  @blueprint.get("/trials/<trialCode>/report")
  def report(trialCode: str) -> Response:
    translator = _translator()
    markdownReport = workspace.buildReport(
      trialCode,
      significanceLevel=settings.analysis.significanceLevel,
      protected=settings.analysis.meanComparison.value == "protectedLSD",
      locale=translator.locale,
    )
    context = {
      "trialCode": trialCode,
      "reportHtml": _renderMarkdown(markdownReport),
    }
    return Response(render_template("report.html", **context, **_localeContext(translator)))

  return blueprint


def _renderMarkdown(text: str) -> Markup:
  """Render the generated Markdown report to HTML for the browser view.

  The input is OpenFurrow's own report output, not user free-text, and Python-Markdown
  escapes literal HTML in the source rather than passing it through, so the result is
  safe to render. `tables` handles the AOV Means Table's pipe tables.
  """
  html = markdownLibrary.markdown(text, extensions=["tables"], output_format="html")
  return Markup(html)


# ---- view helpers ---------------------------------------------------------

def _submittedPackage() -> str:
  """The package JSON from the textarea, or an uploaded file if one was chosen."""
  uploaded = request.files.get("file")
  if uploaded and uploaded.filename:
    return uploaded.read().decode("utf-8")
  return request.form.get("package", "")


class _temporaryCsv:
  """Write uploaded CSV bytes to a temp file, since the importer reads from a path."""

  def __init__(self, data: bytes) -> None:
    import tempfile
    self._directory = tempfile.TemporaryDirectory()
    self._data = data

  def __enter__(self) -> str:
    from pathlib import Path
    path = Path(self._directory.name) / "upload.csv"
    path.write_bytes(self._data)
    return str(path)

  def __exit__(self, *exception) -> None:
    self._directory.cleanup()


def _localized(path: str, translator) -> str:
  """Carry the current locale across a redirect so the language does not reset."""
  if translator.locale == sourceLocale:
    return path
  separator = "&" if "?" in path else "?"
  return f"{path}{separator}locale={translator.locale}"


def _treatmentColors(package: TrialPackage) -> dict[str, str]:
  return {
    treatment.treatmentCode: _treatmentPalette[index % len(_treatmentPalette)]
    for index, treatment in enumerate(package.treatments)
  }


def _legend(package: TrialPackage) -> list[dict]:
  colors = _treatmentColors(package)
  return [
    {"code": treatment.treatmentCode, "name": treatment.name, "color": colors[treatment.treatmentCode]}
    for treatment in package.treatments
  ]


def _blocks(layout) -> list[dict]:
  """Group the layout's plots by block, ordered for a field-walk display."""
  grouped: dict[int, list] = {}
  for plot in layout.plots:
    grouped.setdefault(plot.block, []).append(plot)
  blocks = []
  for block in sorted(grouped):
    plots = sorted(grouped[block], key=lambda plot: plot.positionInBlock)
    blocks.append({
      "block": block,
      "plots": [
        {"plotNumber": plot.plotNumber, "treatmentCode": plot.treatmentCode}
        for plot in plots
      ],
    })
  return blocks


def _examplePackageJson() -> str:
  """A minimal, valid package to seed the add form -- editable, not written from scratch."""
  example = {
    "schemaVersion": "0.1.0",
    "trial": {
      "trialCode": "ESV-2025-01", "title": "Barley fungicide efficacy",
      "crop": "Barley", "season": "2025", "site": "North Field",
      "objective": "Compare fungicide programs for yield",
    },
    "treatments": [
      {"treatmentCode": "UTC", "name": "Untreated control"},
      {"treatmentCode": "A", "name": "Program A", "product": "Fungicide A", "rate": 1.0, "rateUnit": "L/ha"},
      {"treatmentCode": "B", "name": "Program B", "product": "Fungicide B", "rate": 0.75, "rateUnit": "L/ha"},
    ],
    "design": {"designType": "rcbd", "replications": 4, "randomizationSeed": 20250601},
    "assessments": [
      {"assessmentCode": "YIELD", "name": "Grain yield", "dataType": "numeric",
       "unit": "kg/ha", "minValue": 0},
    ],
  }
  return json.dumps(example, indent=2)
