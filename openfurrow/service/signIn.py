# SPDX-License-Identifier: Apache-2.0
"""Who each request acts as (decision 0036).

In the open mode every request acts as everyone. With accounts, a web request carries a
session cookie (HttpOnly, SameSite=Strict, Secure under TLS) and an API request a bearer
token; anything else is sent to sign in (web) or refused with 401 (API). A web request
that changes something must also come from this site's own pages: its Origin, or failing
that its Referer, names this host, or it is refused with 403. Each request then gets a
Workspace acting as its account, so every permission check and audit event in the
facade names the person (decisions 0037, 0038).
"""

from __future__ import annotations

from urllib.parse import urlparse

from flask import Flask, Response, g, redirect, request, url_for

from openfurrow.identity.model import Actor, SignInMode
from openfurrow.workspace import IdentityError, Workspace

sessionCookie = "openfurrowSession"
pendingCookie = "openfurrowPending"
_open = {"health", "web.static", "web.signIn", "web.providerStart", "web.providerReturn"}
# A provider's answer arrives from the provider's site (SAML by POST); its signature is its proof, not its origin.
_crossSite = {"web.providerReturn"}


class RequestWorkspace:
  """The Workspace of the request being served; routes hold this and reach the request's actor through it."""

  def __getattr__(self, name):
    return getattr(g.workspace, name)


def _sameSite() -> bool:
  source = request.headers.get("Origin") or request.headers.get("Referer")
  if not source:
    return False
  parsed = urlparse(source)
  return f"{parsed.scheme}://{parsed.netloc}" == request.host_url.rstrip("/")


def installSignIn(application: Flask, base: Workspace, secureCookies: bool) -> None:
  application.config["openfurrowSecureCookies"] = secureCookies

  @application.before_request
  def actAsTheRequester():
    surface = "api" if request.path.startswith("/api/") else "web"
    g.signInMode = base.signInMode()
    g.signedIn = None
    if request.endpoint == "provisioning":
      g.workspace = base
      return None
    if g.signInMode is SignInMode.open:
      g.workspace = base.actingAs(Actor.everyone(surface))
      return None
    if surface == "api":
      authorization = request.headers.get("Authorization", "")
      if request.endpoint in _open:
        g.workspace = base.actingAs(Actor.everyone(surface))
        return None
      if not authorization.startswith("Bearer "):
        return Response('{"error": "sign in with an API token (Authorization: Bearer <token>)"}', 401,
                        mimetype="application/json", headers={"WWW-Authenticate": "Bearer"})
      try:
        actor = base.actorForAPIToken(authorization.removeprefix("Bearer ").strip(), surface)
      except IdentityError as error:
        return Response(f'{{"error": "{error}"}}', 401, mimetype="application/json", headers={"WWW-Authenticate": "Bearer"})
      g.workspace = base.actingAs(actor)
      return None
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.endpoint not in _crossSite and not _sameSite():
      return Response("refused: a change must come from this site's own pages", 403)
    if request.endpoint in _open:
      g.workspace = base.actingAs(Actor.everyone(surface))
      return None
    token = request.cookies.get(sessionCookie)
    try:
      if not token:
        raise IdentityError("not signed in")
      actor = base.actorForSession(token, surface)
    except IdentityError:
      return redirect(url_for("web.signIn", next=request.full_path.rstrip("?")))
    g.workspace = base.actingAs(actor)
    g.signedIn = actor
    return None
