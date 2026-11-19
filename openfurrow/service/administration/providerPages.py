# SPDX-License-Identifier: Apache-2.0
"""Identity providers (decision 0040), for holders of manageAccess: the providers, a form for each kind made from the
kind's settings model, enabling and disabling, a SCIM provider's provisioning token, shown once, and what each kind
has to be told at the provider."""

from __future__ import annotations

from flask import Blueprint, Response, request, url_for

from openfurrow.identity.model import Permission
from openfurrow.identity.providers import Provider, ProviderKind, settingsModels
from openfurrow.service.administration.modelForm import formItems, postedForm, startingText, valuesFrom
from openfurrow.service.administration.pages import Pages, refusals
from openfurrow.workspace import IdentityError, Workspace

# A certificate is PEM text, which has lines; a one-line field would join them.
longTextSettings = frozenset({"signingCertificate"})


def registerProviderPages(blueprint: Blueprint, workspace: Workspace, pages: Pages) -> None:

  def providerNamed(name: str, translator) -> Provider:
    found = [provider for provider in workspace.providers() if provider.name == name]
    if not found:
      raise pages.unknown(translator, "provider", name)
    return found[0]

  def toRegister(provider: Provider) -> list[tuple[str, str | None]]:
    """What the provider's own administrator is given, by the catalog's name for each: addresses from the settings,
    and this server's address where the settings do not hold it."""
    settings, name = provider.settings, provider.name
    if provider.kind in (ProviderKind.saml, ProviderKind.samlFederation):
      return [("entityID", settings.entityID), ("signInAddress", settings.returnURL),
              ("signOutAddress", settings.singleLogoutURL),
              ("metadata", url_for("web.providerMetadata", name=name, _external=True))]
    if provider.kind is ProviderKind.openIDConnect:
      return [("signInAddress", settings.returnURL),
              ("backChannelSignOut", url_for("web.backChannelLogout", name=name, _external=True))]
    if provider.kind is ProviderKind.cas:
      return [("signInAddress", settings.returnURL)]
    if provider.kind is ProviderKind.scim:
      return [("provisioningAddress", settings.baseURL)]
    return []

  @blueprint.get("/administration/providers")
  def administrationProviders() -> Response:
    translator = pages.translator()
    return pages.render("administrationProviders.html", translator, providers=workspace.providers(),
                        kinds=[kind.value for kind in ProviderKind])

  @blueprint.route("/administration/providers/add/<kind>", methods=["GET", "POST"])
  def administrationProviderAdd(kind: str) -> Response:
    """Add a provider of one kind: its name, and a field for every setting of the kind."""
    translator = pages.translator()
    workspace.require(Permission.manageAccess, "server")
    if kind not in [known.value for known in ProviderKind]:
      raise pages.unknown(translator, "providerKind", kind)
    model = settingsModels[ProviderKind(kind)]
    items = formItems(model, longTextSettings)
    typed = startingText(items, translator.decimalSeparator)
    name = ""
    problems: list[str] = []
    if request.method == "POST":
      name = request.form.get("name", "").strip()
      items, typed = postedForm(model, request.form, longTextSettings)
      if "more" not in request.form:
        values, unreadable = valuesFrom(items, typed, translator.decimalSeparator)
        problems = [translator.text(f"web.administration.form.{problem.reason}", field=problem.name) for problem in unreadable]
        if not problems:
          try:
            workspace.addProvider(Provider.of(name, kind, values))
            return pages.back("web.administrationProvider", translator, name=name, done="added")
          except refusals as error:
            problems = pages.reasons(error)
    context = {"kind": kind, "items": items, "typed": typed, "name": name,
               "helpOf": lambda setting: translator.text(f"web.administration.provider.help.{setting}")}
    return pages.render("administrationProviderAdd.html", translator, problems, **context)

  @blueprint.route("/administration/providers/<name>", methods=["GET", "POST"])
  def administrationProvider(name: str) -> Response:
    """One provider: its settings, whether it is enabled, what to register at the provider, and for SCIM its token."""
    translator = pages.translator()
    provider = providerNamed(name, translator)
    newToken = None
    problems: list[str] = []
    if request.method == "POST":
      action = request.form.get("action")
      try:
        if action in ("enable", "disable"):
          workspace.setProviderEnabled(name, action == "enable")
          return pages.back("web.administrationProvider", translator, name=name, done=f"{action}d")
        if action != "token":
          raise IdentityError(f"unknown action '{action}'")
        newToken = workspace.issueProvisioningToken(name)
      except refusals as error:
        problems = pages.reasons(error)
    context = {"provider": provider, "settings": provider.settings.model_dump(mode="json"), "newToken": newToken,
               "toRegister": toRegister(provider), "isSCIM": provider.kind is ProviderKind.scim}
    response = pages.render("administrationProvider.html", translator, problems, **context)
    if newToken is not None:
      response.headers["Cache-Control"] = "no-store"
    return response
