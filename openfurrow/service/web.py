# SPDX-License-Identifier: Apache-2.0
"""The analyst web UI: server-rendered pages over the same facade (decisions 0009, 0012).

Server-rendered Flask templates, not a single-page app: fewer moving parts, works on
modest hardware and intermittent connections, no separate front-end build, and every
asset served locally so the tool works offline (decision 0012). Light client-side code
only where an interaction needs it: the locale switch submits itself, and works without
script too.

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

The pages: list trials; add a trial (the trial form, or the canonical package JSON); view
a trial with its field layout; enter values; import observations from a CSV or an .xlsx
workbook through a preview and an explicit column mapping (decision 0031); read the
report; check reproducibility; delete a trial.
"""

from __future__ import annotations

import base64
import binascii
import html
import json
import secrets

import markdown as markdownLibrary
from flask import Blueprint, Response, current_app, g, redirect, render_template, request, url_for
from markupsafe import Markup

from openfurrow.config import OpenFurrowConfig, defaultConfig
from openfurrow.i18n import MessageError, availableLocales, sourceLocale, translatorFor
from openfurrow.importers.entry import EntryRefused, readEntry, writeEntry
from openfurrow.importers.layoutCsv import LayoutFileError, readLayoutCsv
from openfurrow.importers.weatherCsv import WeatherFileError
from openfurrow.reports.charts import meansFigure
from openfurrow.interop.fieldbook import fieldBookTraitColumn, fieldBookValueColumn, fieldUniqueIDColumn
from openfurrow.schema import TrialDocument
from openfurrow.service.trialForm import FormProblem, emptyForm, formFromRequest, packageFromForm
from openfurrow.schema import AssessmentDataType, Observation, RandomizationMethod, TrialPackage
from openfurrow.schema.document import isOutOfRange
from openfurrow.version import schemaVersion
from openfurrow.identity.providers import ProviderKind
from openfurrow.service.signIn import pendingCookie, sessionCookie
from openfurrow.workspace import IdentityError, ObservationImportError, StoreError, Workspace
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
    # MessageError handler, not a silent fall back to the source language. Without one,
    # a signed-in person's preferred language applies.
    chosen = request.args.get("locale")
    if chosen is None and g.signedIn is not None:
      chosen = workspace.account().locale
    return translatorFor(chosen or sourceLocale)

  def _localeContext(translator):
    # Shared template context: the translator, the current locale, its direction, and
    # the locales offered in the switcher.
    return {
      "t": translator,
      "locale": translator.locale,
      "direction": translator.direction,
      "locales": availableLocales(),
      "signedIn": g.signedIn,
    }

  def _levelName(level, translator) -> str:
    return level.name if level.name is not None else translator.text(f"hierarchy.level.{level.levelCode}")

  def _placeChoices(translator) -> dict:
    """The places a trial may go in: those of the last level."""
    levels = workspace.hierarchyLevels()
    if not levels:
      return {"levels": [], "lastLevel": None, "places": []}
    last = levels[-1]
    return {
      "levels": levels,
      "lastLevel": _levelName(last, translator),
      "places": [place for place in workspace.places() if place.levelCode == last.levelCode],
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
      "blocks": _blocks(layout, package),
      "legend": _legend(package),
      "weatherResult": None,
      "weatherError": None,
    }

  @blueprint.get("/")
  def index() -> Response:
    translator = _translator()
    trials = [
      {"trialCode": trialCode, "title": title, "package": workspace.loadPackage(trialCode),
       "place": workspace.placeOf(trialCode)}
      for trialCode, title in workspace.listTrials()
    ]
    return Response(render_template("trials.html", trials=trials, **_localeContext(translator)))

  @blueprint.get("/trials/new")
  def newTrial() -> Response:
    translator = _translator()
    return Response(render_template(
      "add.html", example=_examplePackageJson(), error=None, submitted="",
      placeChoices=_placeChoices(translator), selectedPlace=None, **_localeContext(translator),
    ))

  @blueprint.post("/trials/new")
  def createTrial() -> Response:
    translator = _translator()
    raw = _submittedPackage()
    try:
      package = TrialPackage.model_validate(json.loads(raw))
      workspace.addPackage(package, request.form.get("place") or None)
    except (json.JSONDecodeError, ValidationError, StoreError) as error:
      # Re-render the form with the message and the text the user submitted, so nothing
      # they typed is lost. The form fails loud rather than discarding bad input.
      return Response(
        render_template(
          "add.html", example=_examplePackageJson(), error=str(error), submitted=raw,
          placeChoices=_placeChoices(translator), selectedPlace=request.form.get("place"),
          **_localeContext(translator),
        ),
        status=400,
      )
    return redirect(_localized(url_for("web.trial", trialCode=package.trial.trialCode), translator))

  @blueprint.route("/trials/form", methods=["GET", "POST"])
  def trialForm() -> Response:
    """Set up a trial by filling in a form; the layout is generated or uploaded as planted."""
    translator = _translator()
    choices = {"placeChoices": _placeChoices(translator), "selectedPlace": request.form.get("place")}
    if request.method == "GET":
      return Response(render_template(
        "trialForm.html", typed=emptyForm(), error=None, **choices, **_localeContext(translator),
      ))
    typed = formFromRequest(request.form)
    place = request.form.get("place") or None
    if request.form.get("create") != "yes":
      return Response(render_template(
        "trialForm.html", typed=typed, error=None, **choices, **_localeContext(translator),
      ))
    try:
      data = packageFromForm(typed, translator.decimalSeparator)
      package = TrialPackage.model_validate(data)
      if typed["layoutSource"] == "upload":
        upload = request.files.get("layoutFile")
        if not upload or not upload.filename:
          raise FormProblem("web.form.problem.layoutFile")
        with _temporaryCsv(upload.read()) as csvPath:
          plots = readLayoutCsv(csvPath)
        workspace.addDocument(TrialDocument(package=package, layout=plots, observations=[]), place)
      else:
        workspace.addPackage(package, place)
    except FormProblem as problem:
      message = translator.text(problem.reasonKey, **problem.placeholders)
      return Response(render_template(
        "trialForm.html", typed=typed, error=message, **choices, **_localeContext(translator),
      ), status=400)
    except (ValidationError, StoreError, LayoutFileError) as error:
      return Response(render_template(
        "trialForm.html", typed=typed, error=str(error), **choices, **_localeContext(translator),
      ), status=400)
    return redirect(_localized(url_for("web.trial", trialCode=package.trial.trialCode), translator))

  def _target() -> str:
    target = request.args.get("next") or url_for("web.index")
    if not target.startswith("/") or target.startswith("//"):
      return url_for("web.index")
    return target

  def _withSession(response: Response, token: str) -> Response:
    hours = {s.key: s.value for s in workspace.effectiveSettings("server")}["identity.sessionHours"]
    response.set_cookie(sessionCookie, token, max_age=hours * 3600, httponly=True, samesite="Strict",
                        secure=current_app.config["openfurrowSecureCookies"])
    return response

  def _signInPage(translator, problem: str | None = None, userName: str = "", status: int = 200) -> Response:
    providers = workspace.signInProviders()
    context = {"problem": problem, "userName": userName, "next": _target(),
               "redirectProviders": [name for name, kind in providers if kind is not ProviderKind.ldap],
               "directories": [name for name, kind in providers if kind is ProviderKind.ldap]}
    return Response(render_template("signIn.html", **context, **_localeContext(translator)), status=status)

  @blueprint.route("/signin", methods=["GET", "POST"])
  def signIn() -> Response:
    """Sign in with a user name and password, this site's own or a directory's (decisions 0036, 0040)."""
    translator = _translator()
    if request.method == "POST":
      userName, password = request.form.get("userName", ""), request.form.get("password", "")
      directory = request.form.get("provider", "")
      try:
        if directory:
          _, token = workspace.signInWithDirectory(directory, userName, password, "web")
        else:
          _, token = workspace.signIn(userName, password, "web")
      except IdentityError as error:
        return _signInPage(translator, translator.text("web.signIn.refused", reason=str(error)), userName, 401)
      return _withSession(redirect(_target()), token)
    return _signInPage(translator)

  @blueprint.get("/signin/with/<name>/metadata")
  def providerMetadata(name: str) -> Response:
    """The service provider's metadata, for a SAML identity provider or a federation to register (decision 0040)."""
    return Response(workspace.samlMetadata(name), mimetype="application/samlmetadata+xml")

  @blueprint.get("/signin/with/<name>")
  def providerStart(name: str) -> Response:
    """Send the browser to a provider's own sign-in; a federation first asks which institution (decision 0040)."""
    institution = request.args.get("institution")
    try:
      if institution is None and dict(workspace.signInProviders()).get(name) is ProviderKind.samlFederation:
        translator = _translator()
        return Response(render_template("chooseInstitution.html", name=name, next=_target(),
                                        institutions=workspace.federationInstitutions(name, translator.locale),
                                        **_localeContext(translator)))
      address, key = workspace.beginProviderSignIn(name, _target(), institution)
    except IdentityError as error:
      return _signInPage(_translator(), _translator().text("web.signIn.refused", reason=str(error)), status=401)
    return _withPending(redirect(address), key)

  def _withPending(response: Response, key: str) -> Response:
    secure = current_app.config["openfurrowSecureCookies"]
    # SAML answers by a cross-site POST, which only a SameSite=None cookie goes with, and browsers take None only when Secure.
    response.set_cookie(pendingCookie, key, max_age=600, httponly=True, secure=secure,
                        samesite="None" if secure else "Lax", path="/signin/with")
    return response

  def _signedOutPage(translator, problem: str | None, status: int = 200) -> Response:
    g.signedIn = None
    return Response(render_template("signedOut.html", problem=problem, **_localeContext(translator)), status=status)

  @blueprint.route("/signin/with/<name>/return", methods=["GET", "POST"])
  def providerReturn(name: str) -> Response:
    """The provider's answer; on success a page of this site moves the browser on, so the Strict session cookie travels.
    A CAS server also posts its single-logout notices here, server to server."""
    if request.method == "POST" and "logoutRequest" in request.form:
      try:
        workspace.casSignOut(name, request.form["logoutRequest"], "web")
      except IdentityError as error:
        return Response(str(error), status=400, mimetype="text/plain")
      return Response("", status=200)
    translator = _translator()
    key = request.cookies.get(pendingCookie)
    try:
      if not key:
        raise IdentityError("this browser has no sign-in waiting; start again")
      answer = dict(request.form.items()) if request.method == "POST" else dict(request.args.items())
      _, token, target = workspace.finishProviderSignIn(key, answer, "web")
    except IdentityError as error:
      response = _signInPage(translator, translator.text("web.signIn.refused", reason=str(error)), status=401)
      response.delete_cookie(pendingCookie, path="/signin/with")
      return response
    response = Response(render_template("signedIn.html", target=target, **_localeContext(translator)))
    response.delete_cookie(pendingCookie, path="/signin/with")
    return _withSession(response, token)

  @blueprint.post("/signout")
  def signOut() -> Response:
    """End the session here; a provider whose signOutEverywhere is set is visited next (decision 0040)."""
    translator = _translator()
    token = request.cookies.get(sessionCookie)
    outcome = workspace.signOut(token, "web") if token else None
    if outcome is not None and outcome.problem is not None:
      response = _signedOutPage(translator, translator.text("web.signOut.atProviderFailed", provider=outcome.provider,
                                                            reason=outcome.problem))
    elif outcome is not None and outcome.address is not None:
      response = redirect(outcome.address)
      if outcome.pendingKey is not None:
        _withPending(response, outcome.pendingKey)
    else:
      response = redirect(url_for("web.signIn"))
    response.delete_cookie(sessionCookie)
    return response

  @blueprint.route("/signin/with/<name>/signout", methods=["GET", "POST"])
  def providerSignOut(name: str) -> Response:
    """A SAML identity provider's logout messages: its LogoutRequest, ending sessions here and answered; or its
    LogoutResponse to this site's own, finishing a sign-out begun here."""
    translator = _translator()
    query = request.query_string.decode("latin-1") if request.method == "GET" else None
    if "SAMLRequest" in request.values:
      try:
        address = workspace.samlSignOutRequest(name, query, request.form.get("SAMLRequest"),
                                               request.form.get("RelayState"), "web")
      except IdentityError as error:
        return _signedOutPage(translator, translator.text("web.signOut.fromProviderRefused", provider=name,
                                                          reason=str(error)), 400)
      return redirect(address)
    if "SAMLResponse" not in request.values:
      return _signedOutPage(translator, translator.text("web.signOut.notAnswer", provider=name), 400)
    key = request.cookies.get(pendingCookie)
    try:
      if not key:
        raise IdentityError("this browser has no sign-out waiting")
      target, problem = workspace.finishProviderSignOut(name, key, query, request.form.get("SAMLResponse"), "web")
    except IdentityError as error:
      target, problem = None, str(error)
    if problem is not None:
      response = _signedOutPage(translator, translator.text("web.signOut.atProviderFailed", provider=name,
                                                            reason=problem))
    else:
      response = redirect(target or url_for("web.signIn"))
    response.delete_cookie(pendingCookie, path="/signin/with")
    return response

  @blueprint.post("/signin/with/<name>/backchannel-logout")
  def backChannelLogout(name: str) -> Response:
    """An OpenID Connect provider's back-channel logout, server to server (Back-Channel Logout 1.0, section 2.8)."""
    noStore = {"Cache-Control": "no-store"}
    try:
      if "logout_token" not in request.form:
        raise IdentityError("the request carries no logout_token")
      workspace.backChannelSignOut(name, request.form["logout_token"], "web")
    except IdentityError as error:
      return Response(json.dumps({"error": "invalid_request", "error_description": str(error)}), status=400,
                      mimetype="application/json", headers=noStore)
    return Response("", status=200, headers=noStore)

  @blueprint.route("/account", methods=["GET", "POST"])
  def account() -> Response:
    """The signed-in person's language, password and API tokens."""
    translator = _translator()
    me = workspace.account()
    if me is None:
      return redirect(url_for("web.index"))
    context = {"problem": None, "notice": None, "newToken": None}
    if request.method == "POST":
      action = request.form.get("action")
      try:
        if action == "locale":
          workspace.setPreferredLocale(me.userName, request.form.get("preferredLocale") or None)
          return redirect(url_for("web.account"))
        if action == "password":
          workspace.setPassword(me.userName, request.form.get("newPassword", ""))
          context["notice"] = translator.text("web.account.passwordChanged")
        elif action == "token":
          name = request.form.get("tokenName", "").strip()
          if not name:
            raise IdentityError(translator.text("web.account.tokenNeedsName"))
          context["newToken"] = workspace.issueAPIToken(name, None)
        else:
          raise IdentityError(f"unknown action '{action}'")
      except IdentityError as error:
        context["problem"] = str(error)
      me = workspace.account()
    status = 400 if context["problem"] else 200
    return Response(render_template("account.html", account=me, **context, **_localeContext(translator)), status=status)

  @blueprint.route("/places", methods=["GET", "POST"])
  def places() -> Response:
    """The hierarchy's places, and a form to add one (decision 0034)."""
    translator = _translator()
    problem = None
    typed = {"code": "", "name": ""}
    if request.method == "POST":
      typed = {"code": request.form.get("code", "").strip(), "name": request.form.get("name", "").strip()}
      try:
        workspace.addPlace(request.form.get("parent") or None, typed["code"], typed["name"])
        return redirect(_localized(url_for("web.places"), translator))
      except (StoreError, ValueError) as error:
        problem = translator.text("web.places.problem", reason=str(error))
    levels = workspace.hierarchyLevels()
    every = workspace.places()
    context = {
      "levelNames": [_levelName(level, translator) for level in levels],
      "levelName": {level.levelCode: _levelName(level, translator) for level in levels},
      "places": every,
      "parents": [place for place in every if levels and place.levelCode != levels[-1].levelCode],
      "trialCounts": {place.path: len(workspace.trialsIn(place.path)) for place in every},
      "problem": problem,
      "typed": typed,
    }
    status = 400 if problem else 200
    return Response(render_template("places.html", **context, **_localeContext(translator)), status=status)

  @blueprint.get("/trials/<trialCode>")
  def trial(trialCode: str) -> Response:
    translator = _translator()
    context = _trialContext(trialCode) | {"verifyResult": None}
    return Response(render_template("trial.html", **context, **_localeContext(translator)))

  @blueprint.get("/trials/<trialCode>/verify")
  def verify(trialCode: str) -> Response:
    # Read-only: exports and re-imports the trial and compares hashes. A GET is correct
    # -- it changes nothing -- and the result renders back on the trial page.
    translator = _translator()
    check = workspace.verifyRoundTrip(trialCode)
    context = _trialContext(trialCode) | {"verifyResult": check}
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

  @blueprint.route("/trials/<trialCode>/import", methods=["GET", "POST"])
  def importFile(trialCode: str) -> Response:
    """Upload a file, preview it, map its columns, then import (decision 0031).

    Nothing is saved until the person has seen the table and pressed Import with a
    mapping they chose; the file travels with the form between the steps, so the server
    keeps nothing in between.
    """
    translator = _translator()
    package = workspace.loadPackage(trialCode)
    context = {
      "package": package, "table": None, "problem": None, "imported": None,
      "assessments": [
        {"code": assessment.assessmentCode, "rating": package.ratingFor(assessment.assessmentCode)}
        for assessment in package.assessments
      ],
      "subsampleAssessments": ", ".join(
        f"{a.assessmentCode} ({a.subsamples.count})" for a in package.assessments if a.subsamples is not None
      ),
    }
    if request.method == "GET":
      return Response(render_template("importFile.html", **context, **_localeContext(translator)))
    try:
      fileName, data = _submittedFile()
      requestedSheet = request.form.get("sheet") or None
      table = workspace.readObservationTable(fileName, data, requestedSheet)
      sameSheet = "shape" in request.form and request.form.get("previewedSheet", "") == (table.sheetName or "")
      mapping = _formMapping(table) if sameSheet else _suggestedMapping(table, package, settings.importProfile)
      context |= {
        "table": table, "fileName": fileName, "fileData": base64.b64encode(data).decode("ascii"),
        "mapping": mapping,
      }
      if request.form.get("action") == "import" and sameSheet:
        result = workspace.importObservationTable(trialCode, table, _profileFor(mapping, table, settings.importProfile, package))
        context["imported"] = {
          "count": len(result.observations),
          "warnings": [warning.message for warning in result.warnings],
          "assessments": workspace.countImported(trialCode, result),
          "plotCount": package.plotCount + len(workspace.layoutFor(trialCode).checkPlots),
        }
    except _MappingProblem as problem:
      context["problem"] = translator.text(problem.key)
    except (ObservationImportError, ValidationError) as error:
      context["problem"] = translator.text("web.import.error", reason=str(error))
    status = 400 if context["problem"] else 200
    return Response(render_template("importFile.html", **context, **_localeContext(translator)), status=status)

  @blueprint.route("/trials/<trialCode>/entry", methods=["GET", "POST"])
  def entry(trialCode: str) -> Response:
    """Type one assessment's values plot by plot (decision 0023)."""
    translator = _translator()
    package = workspace.loadPackage(trialCode)
    layout = workspace.layoutFor(trialCode)
    context = {
      "package": package,
      "assessments": [
        {"code": a.assessmentCode, "name": package.ratingFor(a.assessmentCode).name} for a in package.assessments
      ],
      "assessment": None,
    }
    assessmentCode = request.args.get("assessment")
    if assessmentCode is None:
      return Response(render_template("entry.html", **context, **_localeContext(translator)))
    if assessmentCode not in {a.assessmentCode for a in package.assessments}:
      return Response(f"no assessment '{assessmentCode}' in trial '{trialCode}'", status=404)
    rating = package.ratingFor(assessmentCode)
    subsamples = package.assessmentFor(assessmentCode).subsamples
    separator = translator.decimalSeparator
    stored = {
      (o.plotNumber, o.subsample): o for o in workspace.loadObservations(trialCode) if o.assessmentCode == assessmentCode
    }
    numbers = [None] if subsamples is None else list(range(1, subsamples.count + 1))
    rows = [
      {"plotNumber": p.plotNumber, "block": p.block, "treatmentCode": p.treatmentCode, "checkOf": None}
      for p in layout.plots
    ] + [
      {"plotNumber": c.plotNumber, "block": c.block, "treatmentCode": None,
       "checkOf": ", ".join(str(number) for number in c.pairedPlots)}
      for c in layout.checkPlots
    ]
    rows.sort(key=lambda row: row["plotNumber"])
    for row in rows:
      row["cells"] = []
      for subsample in numbers:
        observation = stored.get((row["plotNumber"], subsample))
        row["cells"].append({
          "name": str(row["plotNumber"]) if subsample is None else f"{row['plotNumber']}-{subsample}",
          "subsample": subsample,
          "text": writeEntry(observation.value if observation else None, separator),
          "confirmed": bool(observation and observation.outOfRangeConfirmed),
          "problem": None, "flagged": False,
        })

    saved = request.args.get("saved") == "1"
    refused = flagged = False
    if request.method == "POST":
      entered = []
      for row in rows:
        for cell in row["cells"]:
          cell["text"] = request.form.get(f"value-{cell['name']}", "")
          ticked = request.form.get(f"confirm-{cell['name']}") == "yes"
          try:
            value = readEntry(cell["text"], rating, separator)
          except EntryRefused as refusal:
            cell["problem"] = translator.text(refusal.reasonKey, **refusal.placeholders)
            refused = True
            continue
          outside = isinstance(value, float) and isOutOfRange(rating, value)
          cell["confirmed"] = outside and ticked
          if outside and not ticked:
            cell["flagged"] = flagged = True
          if value is not None:
            entered.append(Observation(
              plotNumber=row["plotNumber"], assessmentCode=assessmentCode, value=value,
              outOfRangeConfirmed=outside, subsample=cell["subsample"],
            ))
      if not refused and not flagged:
        workspace.recordValues(trialCode, assessmentCode, entered)
        return redirect(_localized(
          url_for("web.entry", trialCode=trialCode, assessment=assessmentCode, saved="1"), translator,
        ))
    context |= {
      "assessment": package.assessmentFor(assessmentCode),
      "rating": rating,
      "numeric": rating.dataType is AssessmentDataType.numeric,
      "limits": _limitsText(rating, translator),
      "rows": rows,
      "subsampleNumbers": [number for number in numbers if number is not None],
      "entered": sum(1 for row in rows if any(cell["text"].strip() for cell in row["cells"])),
      "saved": saved and request.method == "GET",
      "refused": refused,
      "flagged": flagged,
    }
    status = 400 if refused else 200
    return Response(render_template("entry.html", **context, **_localeContext(translator)), status=status)

  @blueprint.post("/trials/<trialCode>/weather")
  def importWeather(trialCode: str) -> Response:
    """Replace the trial's weather log from an uploaded CSV (worklist REC-13)."""
    translator = _translator()
    upload = request.files.get("file")
    weatherResult = weatherError = None
    try:
      if not upload or not upload.filename:
        raise WeatherFileError("choose a CSV file to import")
      with _temporaryCsv(upload.read()) as csvPath:
        weatherResult = workspace.importWeather(trialCode, csvPath)
    except (WeatherFileError, ValidationError) as error:
      weatherError = str(error)
    context = _trialContext(trialCode) | {
      "verifyResult": None, "weatherResult": weatherResult, "weatherError": weatherError,
    }
    status = 400 if weatherError else 200
    return Response(render_template("trial.html", **context, **_localeContext(translator)), status=status)

  @blueprint.get("/trials/<trialCode>/report")
  def report(trialCode: str) -> Response:
    translator = _translator()
    built = workspace.buildReportWithCharts(trialCode, secrets.token_hex(12), locale=translator.locale)
    reportHtml = str(_renderMarkdown(built.markdown))
    for index, chart in enumerate(built.charts):
      paragraph = f"<p>{built.markerFor(index)}</p>"
      if reportHtml.count(paragraph) != 1:
        raise RuntimeError(f"chart {index} has {reportHtml.count(paragraph)} places in the rendered report")
      reportHtml = reportHtml.replace(paragraph, meansFigure(chart, translator))
    context = {
      "trialCode": trialCode,
      "reportHtml": Markup(reportHtml),
    }
    return Response(render_template("report.html", **context, **_localeContext(translator)))

  return blueprint


def _limitsText(rating, translator) -> str | None:
  """A numeric rating's limits in the reader's words; None when it has none."""
  if rating.dataType is not AssessmentDataType.numeric:
    return None
  low, high = rating.minValue, rating.maxValue

  def number(value: float) -> str:
    return writeEntry(value, translator.decimalSeparator)

  if low is not None and high is not None:
    return translator.text("report.ratings.range", low=number(low), high=number(high))
  if low is not None:
    return translator.text("report.ratings.atLeast", low=number(low))
  if high is not None:
    return translator.text("report.ratings.atMost", high=number(high))
  return None


def _renderMarkdown(text: str) -> Markup:
  """Render the generated Markdown report to HTML for the browser view.

  Security: a trial's fields (title, treatment names, units, ...) come from an imported
  package and are attacker-controllable, and trial packages are meant to be shared. If
  the raw report Markdown were rendered directly, a name like `<script>...</script>`
  would pass through Python-Markdown as raw HTML and execute -- stored XSS, and worse
  under the multi-user server of Phase 2.

  The report Markdown contains no intended HTML -- only headings, pipe tables, and lists
  -- so HTML metacharacters in the source are escaped before parsing. That neutralizes
  any injected tag (it renders as inert text) while leaving every Markdown structure
  intact; a literal like `<0.0001` still displays correctly. The result is wrapped in
  `Markup` because it is now known-safe generated HTML.
  """
  safeSource = html.escape(text)
  rendered = markdownLibrary.markdown(safeSource, extensions=["tables"], output_format="html")
  return Markup(rendered)


# ---- view helpers ---------------------------------------------------------

class _MappingProblem(Exception):
  """A choice missing from the column mapping, named by its catalog key."""

  def __init__(self, key: str) -> None:
    super().__init__(key)
    self.key = key


_plotColumnNames = {"plotnumber", "plot", "plotno", "plotid", "parcela", "parcelle"}
_assessmentColumnNames = {"assessmentcode", "assessment", "trait"}
_valueColumnNames = {"value", "valor", "valeur"}
_subsampleColumnNames = {"subsample", "subsamplenumber", "submuestra", "souséchantillon", "sample"}


def _normalized(name: str) -> str:
  return "".join(character for character in name.lower() if character.isalnum())


def _submittedFile() -> tuple[str, bytes]:
  upload = request.files.get("file")
  if upload and upload.filename:
    return upload.filename, upload.read()
  fileName, encoded = request.form.get("fileName", ""), request.form.get("fileData", "")
  if not fileName or not encoded:
    raise _MappingProblem("web.importFile.problem.noFile")
  try:
    return fileName, base64.b64decode(encoded, validate=True)
  except binascii.Error as error:
    raise ObservationImportError("the file sent with the form is damaged; choose it again") from error


def _suggestedMapping(table, package, profile) -> dict:
  """A first mapping by column names, shown for the person to confirm or change."""
  names = [_normalized(name) for name in table.header]

  def find(candidates):
    return next((index for index, name in enumerate(names) if name in candidates), None)

  plot = find(_plotColumnNames | {_normalized(profile.long.plotNumber), _normalized(profile.wide.plotNumber),
                                  _normalized(fieldUniqueIDColumn)})
  assessment = find(_assessmentColumnNames | {_normalized(profile.long.assessmentCode), _normalized(fieldBookTraitColumn)})
  value = find(_valueColumnNames | {_normalized(profile.long.value), _normalized(fieldBookValueColumn)})
  subsample = find(_subsampleColumnNames)
  codes = {_normalized(a.assessmentCode): a.assessmentCode for a in package.assessments}
  return {
    "shape": "long" if assessment is not None and value is not None else "wide",
    "plot": plot,
    "columns": {index: codes.get(name, "") for index, name in enumerate(names) if index != plot},
    "longPlot": plot,
    "longAssessment": assessment,
    "longValue": value,
    "longSubsample": subsample,
    "decimal": profile.parsing.decimalSeparator,
  }


def _formMapping(table) -> dict:
  def index(field):
    text = request.form.get(field, "")
    return int(text) if text.isdigit() and int(text) < len(table.header) else None

  return {
    "shape": request.form.get("shape", ""),
    "plot": index("plot"),
    "columns": {column: request.form.get(f"column-{column}", "") for column in range(len(table.header))},
    "longPlot": index("longPlot"),
    "longAssessment": index("longAssessment"),
    "longValue": index("longValue"),
    "longSubsample": index("longSubsample"),
    "decimal": request.form.get("decimal", ""),
  }


def _profileFor(mapping, table, base, package):
  """The import profile the person's mapping states; every choice must be made."""
  if mapping["decimal"] not in (".", ","):
    raise _MappingProblem("web.importFile.problem.decimal")
  header = table.header
  parsing = {"decimalSeparator": mapping["decimal"]}
  if mapping["shape"] == "wide":
    if mapping["plot"] is None:
      raise _MappingProblem("web.importFile.problem.plotColumn")
    columns = {header[index]: code for index, code in mapping["columns"].items() if code}
    if not columns:
      raise _MappingProblem("web.importFile.problem.noAssessmentColumn")
    takesSubsamples = {a.assessmentCode for a in package.assessments if a.subsamples is not None}
    codes = [code for code in columns.values() if code not in takesSubsamples]
    if len(set(codes)) != len(codes):
      raise _MappingProblem("web.importFile.problem.repeatedAssessment")
    return base.withOverrides(
      format="wide", parsing=parsing,
      wide={"plotNumber": header[mapping["plot"]], "assessmentColumns": columns, "ignoreColumns": []},
    )
  if mapping["shape"] == "long":
    chosen = [mapping["longPlot"], mapping["longAssessment"], mapping["longValue"]]
    if None in chosen:
      raise _MappingProblem("web.importFile.problem.longColumns")
    subsample = mapping["longSubsample"]
    if len(set(chosen + ([subsample] if subsample is not None else []))) != len(chosen) + (subsample is not None):
      raise _MappingProblem("web.importFile.problem.sameColumn")
    return base.withOverrides(
      format="long", parsing=parsing,
      long={"plotNumber": header[chosen[0]], "assessmentCode": header[chosen[1]], "value": header[chosen[2]],
            "subsample": None if subsample is None else header[subsample]},
    )
  raise _MappingProblem("web.importFile.problem.shape")


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


def _blocks(layout, package) -> list[dict]:
  """The layout as the field is walked: blocks, the main plots of a split plot, and the plots.

  A check plot is drawn right after the last plot it serves, so a strip between plots
  sits where it lies and a half or a partner sits beside its plot.
  """
  levelNames = {}
  if package.design.mainPlotFactor is not None:
    factor = next(f for f in package.factors if f.factorCode == package.design.mainPlotFactor)
    levelNames = {level.levelCode: level.name for level in factor.levels}
  checksAfter: dict[int, list] = {}
  positionOf = {plot.plotNumber: (plot.block, plot.positionInBlock) for plot in layout.plots}
  for check in layout.checkPlots:
    last = max(check.pairedPlots, key=lambda number: positionOf[number])
    checksAfter.setdefault(last, []).append(check)
  grouped: dict[int, list] = {}
  for plot in layout.plots:
    grouped.setdefault(plot.block, []).append(plot)
  blocks = []
  for block in sorted(grouped):
    groups: list[dict] = []
    for plot in sorted(grouped[block], key=lambda plot: plot.positionInBlock):
      if not groups or groups[-1]["mainPlot"] != plot.mainPlot:
        level = layout.mainPlotLevels[plot.treatmentCode] if plot.mainPlot is not None else None
        groups.append({"mainPlot": plot.mainPlot, "level": levelNames.get(level), "cells": []})
      groups[-1]["cells"].append({"plotNumber": plot.plotNumber, "treatmentCode": plot.treatmentCode, "isCheck": False})
      for check in sorted(checksAfter.get(plot.plotNumber, []), key=lambda check: check.plotNumber):
        groups[-1]["cells"].append({"plotNumber": check.plotNumber, "treatmentCode": None, "isCheck": True})
    blocks.append({"block": block, "groups": groups})
  return blocks


def _examplePackageJson() -> str:
  """A minimal, valid package to seed the add form -- editable, not written from scratch."""
  example = {
    "schemaVersion": schemaVersion,
    "trial": {
      "trialCode": "ESV-2025-01", "title": "Barley fungicide efficacy",
      "crop": "Barley", "season": "2025", "site": "North Field",
      "objective": "Compare fungicide programs for yield",
    },
    "treatments": [
      {"treatmentCode": "UTC", "name": "Untreated control", "role": "untreatedControl"},
      {"treatmentCode": "A", "name": "Program A", "role": "test", "lines": [
        {"product": "Fungicide A", "kind": "fungicide", "rate": {"value": 1.0, "unit": "L/ha"},
         "rateBasis": "formulatedProduct", "applicationCodes": ["A"]},
      ]},
      {"treatmentCode": "B", "name": "Program B", "role": "reference", "lines": [
        {"product": "Fungicide B", "kind": "fungicide", "rate": {"value": 0.75, "unit": "L/ha"},
         "rateBasis": "formulatedProduct", "applicationCodes": ["A"]},
      ]},
    ],
    "applications": [
      {"applicationCode": "A", "timing": "BBCH 31", "method": "Broadcast spray"},
    ],
    "design": {"designType": "rcbd", "replications": 4,
               "randomizationMethod": RandomizationMethod.sha256FisherYates1.value,
               "randomizationSeed": 20250601},
    "ratings": [
      {"ratingCode": "YIELD", "name": "Grain yield", "dataType": "numeric",
       "unit": "kg/ha", "minValue": 0},
    ],
    "assessments": [
      {"assessmentCode": "YIELD", "ratingCode": "YIELD", "timing": "Harvest"},
    ],
  }
  return json.dumps(example, indent=2)
