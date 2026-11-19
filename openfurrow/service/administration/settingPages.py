# SPDX-License-Identifier: Apache-2.0
"""Settings by scope (decision 0035) and the sign-in mode (decision 0036): each setting's value where it is read, where
that value was set, and forms to set and clear it for those who hold, there, the permission the setting names: to
change settings, or for a retention rule to manage retention (decision 0044)."""

from __future__ import annotations

from flask import Blueprint, Response, request

from openfurrow.identity.model import Permission, SignInMode
from openfurrow.service.administration.pages import Pages, refusals
from openfurrow.settings import SettingScope, allowedValues, definitions, jsonValue, takesNumber
from openfurrow.workspace import IdentityError, Workspace

signInModeKey = "identity.signInMode"


def registerSettingPages(blueprint: Blueprint, workspace: Workspace, pages: Pages) -> None:

  def shown(key: str, value, translator) -> str:
    written = jsonValue(key, value)
    if written is None:
      return ""
    if isinstance(written, float):
      return repr(written).replace(".", translator.decimalSeparator)
    return str(written)

  def sourceName(source: str, translator) -> str:
    return translator.text("web.administration.settings.source.default") if source == "default" else pages.scopeName(source, translator)

  @blueprint.route("/administration/settings", methods=["GET", "POST"])
  def administrationSettings() -> Response:
    """Every setting at one scope, chosen from the hierarchy; set or clear one where the person may change settings."""
    translator = pages.translator()
    choices = pages.scopeChoices(translator)
    scope = pages.chosenScope(request.args.get("scope", "server"), choices, translator)
    typedKey, typedValue = None, ""
    problems: list[str] = []
    if request.method == "POST":
      action, typedKey = request.form.get("action"), request.form.get("key", "")
      typedValue = request.form.get("value", "").strip()
      try:
        if typedKey == signInModeKey:
          raise IdentityError(translator.text("web.administration.settings.onItsOwnPage"))
        if action == "set":
          value = typedValue.replace(translator.decimalSeparator, ".") if takesNumber(typedKey) else typedValue
          workspace.setSetting(scope, typedKey, value)
          return pages.back("web.administrationSettings", translator, scope=scope, done="set")
        if action == "clear":
          workspace.clearSetting(scope, typedKey)
          return pages.back("web.administrationSettings", translator, scope=scope, done="cleared")
        raise IdentityError(f"unknown action '{action}'")
      except refusals as error:
        problems = pages.reasons(error)
    scopeKind = SettingScope(scope.partition(":")[0])
    held = workspace.permissionsAt(scope)
    rows = [{
      "key": setting.key, "value": shown(setting.key, setting.value, translator),
      "source": sourceName(setting.source, translator), "setHere": setting.source == scope,
      "settable": scopeKind in definitions[setting.key].scopes, "choices": allowedValues(setting.key),
      "number": takesNumber(setting.key), "ownPage": setting.key == signInModeKey,
      "typed": typedValue if setting.key == typedKey else shown(setting.key, setting.value, translator),
      "mayChange": definitions[setting.key].permission in held,
      "permission": definitions[setting.key].permission.value,
    } for setting in workspace.effectiveSettings(scope)]
    context = {"rows": rows, "scope": scope, "scopeName": pages.scopeName(scope, translator), "scopeChoices": choices,
               "mayChange": any(row["mayChange"] for row in rows)}
    return pages.render("administrationSettings.html", translator, problems, **context)

  @blueprint.route("/administration/sign-in-mode", methods=["GET", "POST"])
  def administrationSignInMode() -> Response:
    """How the service knows who acts: open to everyone, or signed-in accounts. Opening it is confirmed."""
    translator = pages.translator()
    workspace.require(Permission.changeSettings, "server")
    typed = workspace.signInMode().value
    problems: list[str] = []
    if request.method == "POST":
      typed = request.form.get("mode", "")
      try:
        if typed == SignInMode.open.value and request.form.get("confirm") != "yes":
          raise IdentityError(translator.text("web.administration.confirmNeeded"))
        workspace.setSetting("server", signInModeKey, typed)
        return pages.back("web.administrationSignInMode", translator, done="saved")
      except refusals as error:
        problems = pages.reasons(error)
    return pages.render("administrationSignInMode.html", translator, problems, mode=workspace.signInMode().value,
                        modes=[mode.value for mode in SignInMode], typed=typed)
