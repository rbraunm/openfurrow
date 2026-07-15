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

from flask import Blueprint, Response, redirect, render_template, request, url_for

from openfurrow.i18n import MessageError, availableLocales, sourceLocale, translatorFor
from openfurrow.schema import TrialPackage
from openfurrow.workspace import StoreError, Workspace
from pydantic import ValidationError

# Okabe-Ito, a colorblind-safe qualitative palette. Treatment colour is a *redundant*
# cue: every plot cell also shows its treatment code, so the map is readable without
# relying on colour at all. The palette cycles if a trial has more treatments than
# colours -- the code remains the definitive identifier.
_treatmentPalette = [
  "#E69F00", "#56B4E9", "#009E73", "#F0E442",
  "#0072B2", "#D55E00", "#CC79A7", "#7F7F7F",
]


def createWebBlueprint(workspace: Workspace) -> Blueprint:
  """Build the HTML UI blueprint over `workspace`. Registered by `createApp`."""
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
    package = workspace.loadPackage(trialCode)
    layout = workspace.layoutFor(trialCode)
    context = {
      "package": package,
      "observationCount": len(workspace.loadObservations(trialCode)),
      "contentHash": workspace.contentHashFor(trialCode),
      "blocks": _blocks(layout),
      "legend": _legend(package),
    }
    return Response(render_template("trial.html", **context, **_localeContext(translator)))

  return blueprint


# ---- view helpers ---------------------------------------------------------

def _submittedPackage() -> str:
  """The package JSON from the textarea, or an uploaded file if one was chosen."""
  uploaded = request.files.get("file")
  if uploaded and uploaded.filename:
    return uploaded.read().decode("utf-8")
  return request.form.get("package", "")


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
