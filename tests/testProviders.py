# SPDX-License-Identifier: Apache-2.0
"""Identity providers (decision 0040): the link policies, mirrored groups, SCIM provisioning,
signing in through Keycloak (OpenID Connect, SAML), Apereo CAS and a Samba directory (LDAP),
and signing out at either end."""

import base64
import html.parser
import http.cookiejar
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest
from carnelian.fetching import Fetcher, secureContext
from carnelian.keys import LocalSigningKey
from carnelian.oidc import Identity
from carnelian.saml import SAMLRefused, ServiceProvider, identityProviderFromMetadata
from pydantic import ValidationError
from sqlalchemy.orm import Session

from openIDConnectStandIn import StandInIssuer, clientID as standInClientID
from openfurrow import Workspace
from openfurrow.identity import RoleAssignment
from openfurrow.identity.model import IdentityError
from openfurrow.identity.providers import (ProvidedIdentity, Provider, ProviderFailure, _ProviderCache, fromOpenIDConnect,
                                          providerRefreshSeconds, serviceProvider)
from openfurrow.service import createApp
from openfurrow.store.database import createDatabase
from openfurrow.store.providers import StoredReplays, claimOnce, completeSignIn

password = "correct horse battery"
scimBase = "https://openfurrow.example.org/scim/entra/v2"
coreUser = "urn:ietf:params:scim:schemas:core:2.0:User"
coreGroup = "urn:ietf:params:scim:schemas:core:2.0:Group"
patchOp = "urn:ietf:params:scim:api:messages:2.0:PatchOp"


@pytest.fixture
def location(newStore):
  location = newStore("p")
  operator = Workspace.create(location)
  operator.createAccount("admin", "Administrator", None, password)
  operator.assignRole(RoleAssignment(roleCode="administrator", scope="server", userName="admin"))
  operator.setSetting("server", "identity.signInMode", "accounts")
  return location


def oidcSettings(**overrides):
  return {"issuer": "https://idp.example.org/realms/x", "clientID": "openfurrow",
          "clientSecretVariable": "OPENFURROW_TEST_SECRET", "returnURL": "https://openfurrow.example.org/back", **overrides}


# ---- settings ---------------------------------------------------------------

@pytest.mark.parametrize("name, kind, settings, why", [
  ("idp", "openIDConnect", oidcSettings(issuer="http://idp.example.org"), "must be an https address"),
  ("idp", "openIDConnect", oidcSettings(newAccounts="sometimes"), "newAccounts"),
  ("idp", "openIDConnect", {**oidcSettings(), "colour": "red"}, "colour"),
  ("Idp", "openIDConnect", oidcSettings(), "not a provider name"),
  ("idp", "scim", {"baseURL": "https://x.example.org/scim/"}, "without a trailing slash"),
  ("idp", "openIDConnect", oidcSettings(signOutEverywhere=True, signedOutURL="http://127.0.0.1/out"),
   "must be an https address"),
  ("idp", "openIDConnect", oidcSettings(signedOutURL="https://openfurrow.example.org/out"), "set signOutEverywhere too"),
  ("idp", "cas", {"serverURL": "https://cas.example.org/cas", "returnURL": "https://openfurrow.example.org/back",
                  "signedOutURL": "https://openfurrow.example.org/out"}, "set signOutEverywhere too"),
  ("idp", "openIDConnect", oidcSettings(signOutEverywhere="sometimes"), "signOutEverywhere"),
])
def testProviderSettingsAreChecked(name, kind, settings, why):
  with pytest.raises(ValidationError, match=why):
    Provider.of(name, kind, settings)


def testALoopbackReturnAddressMayBePlainHTTP():
  provider = Provider.of("idp", "openIDConnect", oidcSettings(returnURL="http://127.0.0.1:53682/callback"))
  assert provider.settings.returnURL == "http://127.0.0.1:53682/callback"


class Clock:
  def __init__(self):
    self.now = 1000.0

  def __call__(self):
    return self.now


def testAProviderIsBuiltOnceAndRebuiltAfterTheRefreshTime():
  clock, builds = Clock(), []
  cache = _ProviderCache(clock)
  settings = Provider.of("idp", "openIDConnect", oidcSettings()).settings
  build = lambda: builds.append(clock.now) or len(builds)
  assert [cache.get("metadata", settings, build), cache.get("metadata", settings, build)] == [1, 1]
  clock.now += providerRefreshSeconds - 1
  assert cache.get("metadata", settings, build) == 1
  clock.now += 1
  assert cache.get("metadata", settings, build) == 2 and builds == [1000.0, 1000.0 + providerRefreshSeconds]
  other = Provider.of("idp", "openIDConnect", oidcSettings(clientID="another")).settings
  assert cache.get("metadata", other, build) == 3
  assert cache.get("keys", settings, build) == 4 and cache.get("metadata", settings, build) == 2


def testAFailedBuildIsNotKept():
  cache, attempts = _ProviderCache(Clock()), []
  settings = Provider.of("idp", "openIDConnect", oidcSettings()).settings

  def failing():
    attempts.append(1)
    raise ProviderFailure("unreachable")

  for _ in range(2):
    with pytest.raises(ProviderFailure, match="unreachable"):
      cache.get("metadata", settings, failing)
  assert len(attempts) == 2 and cache.get("metadata", settings, lambda: "built") == "built"


@pytest.mark.parametrize("verified, kept", [(True, "ana@example.org"), (False, None)])
def testAnOpenIDConnectEmailIsKeptOnlyWhenVerified(verified, kept):
  identity = Identity(issuer="https://idp.example.org", subject="s1", userName="ana", email="ana@example.org",
                      emailVerified=verified, displayName="Ana", groups=(), claims={}, idToken="")
  assert fromOpenIDConnect(identity).email == kept


# ---- linking, by policy -------------------------------------------------------

def signInAs(location, provider, identity):
  with Session(createDatabase(location, create=False)) as session:
    account = completeSignIn(session, provider, identity)
    session.commit()
    return account


def person(subject="sub-1", userName="ana", groups=()):
  return ProvidedIdentity(subject=subject, userName=userName, displayName="Ana Lima", email="ana@example.org",
                          groups=tuple(groups))


def testRefuseIsTheDefaultAndALinkMadeByAnAdministratorWorks(location):
  provider = Provider.of("idp", "openIDConnect", oidcSettings())
  operator = Workspace.open(location)
  operator.addProvider(provider)
  with pytest.raises(IdentityError, match="no account here is linked to this idp identity"):
    signInAs(location, provider, person())
  operator.createAccount("ana", "Ana", None, None)
  operator.linkIdentity("idp", "sub-1", "ana")
  assert signInAs(location, provider, person()).userName == "ana"


def testCreateMakesAnAccountOnceAndNeverTakesAnExistingOne(location):
  provider = Provider.of("idp", "openIDConnect", oidcSettings(newAccounts="create"))
  operator = Workspace.open(location)
  operator.addProvider(provider)
  made = signInAs(location, provider, person())
  assert (made.userName, made.displayName, made.email) == ("ana", "Ana Lima", "ana@example.org")
  assert signInAs(location, provider, person()).accountID == made.accountID
  with pytest.raises(IdentityError, match="an account 'admin' exists but is not linked to idp"):
    signInAs(location, provider, person(subject="sub-2", userName="admin"))


def testLinkByUserNameLinksOnlyAnExistingAccountAndOnlyOnce(location):
  provider = Provider.of("idp", "openIDConnect", oidcSettings(newAccounts="linkByUserName"))
  operator = Workspace.open(location)
  operator.addProvider(provider)
  with pytest.raises(IdentityError, match="no account 'ana' here"):
    signInAs(location, provider, person())
  operator.createAccount("ana", "Ana", None, None)
  assert signInAs(location, provider, person()).userName == "ana"
  with pytest.raises(IdentityError, match="already linked to another idp identity"):
    signInAs(location, provider, person(subject="sub-other"))


def testADeactivatedAccountCannotSignInThroughAProvider(location):
  provider = Provider.of("idp", "openIDConnect", oidcSettings(newAccounts="create"))
  operator = Workspace.open(location)
  operator.addProvider(provider)
  signInAs(location, provider, person())
  operator.setAccountActive("ana", False)
  with pytest.raises(IdentityError, match="deactivated"):
    signInAs(location, provider, person())


def testMirroredGroupsFollowTheProviderAndOnlyIt(location):
  provider = Provider.of("idp", "openIDConnect", oidcSettings(newAccounts="create", groups="mirror"))
  operator = Workspace.open(location)
  operator.addProvider(provider)
  signInAs(location, provider, person(groups=["/field/team-a", "/analysts"]))
  members = {group.name: group.members for group in operator.groups()}
  assert members["idp/field/team-a"] == ["ana"] and members["idp/analysts"] == ["ana"]
  signInAs(location, provider, person(groups=["/analysts"]))
  members = {group.name: group.members for group in operator.groups()}
  assert members["idp/field/team-a"] == [] and members["idp/analysts"] == ["ana"]
  with pytest.raises(IdentityError, match="mirrored from idp"):
    operator.setMembership("idp/analysts", "admin", True)


# ---- message identifiers used once ----------------------------------------------

def testOfConcurrentClaimsExactlyOneWins(location):
  engine = createDatabase(location, create=False)
  start, results = threading.Barrier(8), []

  def claim():
    start.wait()
    results.append(claimOnce(engine, "scope", "message-1", time.time() + 60, time.time()))

  workers = [threading.Thread(target=claim) for _ in range(8)]
  for worker in workers:
    worker.start()
  for worker in workers:
    worker.join()
  assert sorted(results) == [False] * 7 + [True]


def testAClaimHoldsUntilItExpiresAndOnlyInItsScope(location):
  engine = createDatabase(location, create=False)
  now = time.time()
  assert claimOnce(engine, "a", "m", now + 10, now) is True
  assert claimOnce(engine, "a", "m", now + 10, now + 9) is False
  assert claimOnce(engine, "b", "m", now + 10, now) is True
  assert claimOnce(engine, "a", "m", now + 30, now + 10) is True


def testTheStoredReplaysRefuseASAMLMessageUsedTwice(location):
  replays = StoredReplays(createDatabase(location, create=False))
  now = time.time()
  replays.admit("https://idp.example.org", "_assertion-1", now + 60, now)
  with pytest.raises(SAMLRefused, match="'_assertion-1' from https://idp.example.org was already used"):
    replays.admit("https://idp.example.org", "_assertion-1", now + 60, now)
  replays.admit("https://other.example.org", "_assertion-1", now + 60, now)


# ---- signing out, with a stand-in OpenID Connect provider --------------------------

origin = {"Origin": "http://localhost"}


@pytest.fixture
def standIn(tmp_path):
  issuer = StandInIssuer(tmp_path)
  yield issuer
  issuer.close()


def addStandIn(location, standIn, monkeypatch, name="standin", realm="lab", **settings):
  monkeypatch.setenv("OPENFURROW_TEST_SECRET", "stand-in secret")
  Workspace.open(location).addProvider(Provider.of(name, "openIDConnect", {
    "issuer": standIn.issuer(realm), "clientID": standInClientID, "clientSecretVariable": "OPENFURROW_TEST_SECRET",
    "returnURL": f"https://openfurrow.example.org/signin/with/{name}/return",
    "certificateAuthority": str(standIn.certificateAuthority), "newAccounts": "create", **settings}))


def signedInAtStandIn(location, standIn, subject, sessionID, name="standin"):
  """A browser signed in through the stand-in as `subject` in its session `sessionID`."""
  client = createApp(location).test_client()
  standIn.nextPerson = {"sub": subject, "sid": sessionID, "preferred_username": subject}
  started = client.get(f"/signin/with/{name}")
  location, _ = Browser(secureContext(str(standIn.certificateAuthority))).open(started.headers["Location"])
  answered = client.get(f"/signin/with/{name}/return", query_string=urllib.parse.urlsplit(location).query)
  assert answered.status_code == 200, answered.get_data(as_text=True)[:500]
  assert signedIn(client)
  return client


def signedIn(client):
  return client.get("/account").status_code == 200


def auditOf(location, action):
  return [event.detail for event in Workspace.open(location).auditEvents() if event.action == action]


def claimsOf(token):
  return json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))


def testSigningOutWithoutSignOutEverywhereEndsOnlyTheSessionHere(location, standIn, monkeypatch):
  addStandIn(location, standIn, monkeypatch)
  client = signedInAtStandIn(location, standIn, "ana", "sid-1")
  left = client.post("/signout", headers=origin)
  assert left.status_code == 302 and left.headers["Location"] == "/signin"
  assert not signedIn(client)
  assert auditOf(location, "signOut") == [{"provider": "standin", "everywhere": False}]
  assert auditOf(location, "signOut.atProvider") == []


def testSigningOutEverywhereSendsThePersonToTheProvidersEndSession(location, standIn, monkeypatch):
  addStandIn(location, standIn, monkeypatch, signOutEverywhere=True, signedOutURL="https://openfurrow.example.org/bye")
  client = signedInAtStandIn(location, standIn, "ana", "sid-1")
  left = client.post("/signout", headers=origin)
  assert left.status_code == 302
  address = urllib.parse.urlsplit(left.headers["Location"])
  assert f"{address.scheme}://{address.netloc}{address.path}" == f"{standIn.issuer('lab')}/logout"
  query = dict(urllib.parse.parse_qsl(address.query))
  assert (query["client_id"], query["post_logout_redirect_uri"]) == (standInClientID, "https://openfurrow.example.org/bye")
  assert {key: claimsOf(query["id_token_hint"])[key] for key in ("sub", "sid")} == {"sub": "ana", "sid": "sid-1"}
  assert not signedIn(client)
  assert auditOf(location, "signOut") == [{"provider": "standin", "everywhere": True}]
  assert auditOf(location, "signOut.atProvider") == [{"provider": "standin"}]


def testAProviderThatCannotSignOutLeavesTheSessionHereEndedAndSaysSo(location, standIn, monkeypatch):
  addStandIn(location, standIn, monkeypatch, realm="noLogout", signOutEverywhere=True)
  client = signedInAtStandIn(location, standIn, "ana", "sid-1")
  left = client.post("/signout", headers=origin)
  page = left.get_data(as_text=True)
  assert left.status_code == 200 and "You are signed out of OpenFurrow, but signing out at standin failed" in page
  assert "end_session_endpoint" in page
  assert any("openfurrowSession=;" in cookie for cookie in left.headers.getlist("Set-Cookie"))
  assert not signedIn(client)
  [failure] = auditOf(location, "signOut.atProvider.failed")
  assert failure["provider"] == "standin" and "end_session_endpoint" in failure["why"]


def backChannel(location, name, token):
  answered = createApp(location).test_client().post(f"/signin/with/{name}/backchannel-logout",
                                                    data={} if token is None else {"logout_token": token})
  assert answered.headers["Cache-Control"] == "no-store"
  return answered


def testABackChannelLogoutWithASessionIDEndsOnlyThatSession(location, standIn, monkeypatch):
  addStandIn(location, standIn, monkeypatch)
  first = signedInAtStandIn(location, standIn, "ana", "sid-1")
  second = signedInAtStandIn(location, standIn, "ana", "sid-2")
  other = signedInAtStandIn(location, standIn, "bea", "sid-3")
  answered = backChannel(location, "standin", standIn.logoutToken("lab", subject="ana", sessionID="sid-1"))
  assert answered.status_code == 200 and answered.data == b""
  assert [signedIn(first), signedIn(second), signedIn(other)] == [False, True, True]
  assert auditOf(location, "signOut.fromProvider") == [{"provider": "standin", "how": "backChannel", "sessionsEnded": 1}]


def testABackChannelLogoutWhoseSubjectIsNotTheSessionsEndsNothing(location, standIn, monkeypatch):
  addStandIn(location, standIn, monkeypatch)
  client = signedInAtStandIn(location, standIn, "ana", "sid-1")
  assert backChannel(location, "standin", standIn.logoutToken("lab", subject="bea", sessionID="sid-1")).status_code == 200
  assert signedIn(client)
  assert auditOf(location, "signOut.fromProvider")[0]["sessionsEnded"] == 0


def testABackChannelLogoutWithOnlyASubjectEndsEverySessionOfIt(location, standIn, monkeypatch):
  addStandIn(location, standIn, monkeypatch)
  first = signedInAtStandIn(location, standIn, "ana", "sid-1")
  second = signedInAtStandIn(location, standIn, "ana", "sid-2")
  other = signedInAtStandIn(location, standIn, "bea", "sid-3")
  assert backChannel(location, "standin", standIn.logoutToken("lab", subject="ana")).status_code == 200
  assert [signedIn(first), signedIn(second), signedIn(other)] == [False, False, True]
  assert auditOf(location, "signOut.fromProvider")[0]["sessionsEnded"] == 2


def testABackChannelLogoutTokenIsUsedOnce(location, standIn, monkeypatch):
  addStandIn(location, standIn, monkeypatch)
  token = standIn.logoutToken("lab", subject="ana")
  assert backChannel(location, "standin", token).status_code == 200
  client = signedInAtStandIn(location, standIn, "ana", "sid-1")
  replayed = backChannel(location, "standin", token)
  assert replayed.status_code == 400 and replayed.json["error"] == "invalid_request"
  assert "was already used" in replayed.json["error_description"]
  assert signedIn(client)


@pytest.mark.parametrize("token, why", [
  (lambda standIn: standIn.logoutToken("lab", subject="ana", audience="another-client"), "not for client 'openfurrow'"),
  (lambda standIn: standIn.logoutToken("elsewhere", subject="ana"), "is not 'https://127.0.0.1"),
  (lambda standIn: "not.a.token", "the logout token is refused"),
])
def testABackChannelLogoutTokenNotForThisClientIsRefused(location, standIn, monkeypatch, token, why):
  addStandIn(location, standIn, monkeypatch)
  client = signedInAtStandIn(location, standIn, "ana", "sid-1")
  refused = backChannel(location, "standin", token(standIn))
  assert refused.status_code == 400 and refused.json["error"] == "invalid_request"
  assert why in refused.json["error_description"]
  assert signedIn(client)
  assert auditOf(location, "signOut.fromProvider.refused")[0]["provider"] == "standin"


def testABackChannelLogoutWithoutATokenIsRefused(location, standIn, monkeypatch):
  addStandIn(location, standIn, monkeypatch)
  refused = backChannel(location, "standin", None)
  assert refused.status_code == 400 and refused.json["error_description"] == "the request carries no logout_token"


# ---- SCIM provisioning through the service ------------------------------------

@pytest.fixture
def provisioned(location):
  operator = Workspace.open(location)
  operator.addProvider(Provider.of("entra", "scim", {"baseURL": scimBase, "groups": "mirror"}))
  token = operator.issueProvisioningToken("entra")
  client = createApp(location).test_client()

  def call(method, path, body=None, query="", bearer=token):
    headers = {"Authorization": f"Bearer {bearer}"}
    data = None
    if body is not None:
      headers["Content-Type"] = "application/scim+json"
      data = json.dumps(body)
    response = client.open(f"/scim/entra/v2{path}", method=method, headers=headers, data=data, query_string=query)
    return response.status_code, (json.loads(response.data) if response.data else None)

  return call, operator


def testProvisioningMakesAccountsAndMirroredGroups(provisioned):
  call, operator = provisioned
  status, ana = call("POST", "/Users", {"schemas": [coreUser], "userName": "Ana@Example.org",
                                        "name": {"givenName": "Ana", "familyName": "Lima"},
                                        "emails": [{"value": "ana@example.org", "type": "work", "primary": True}]})
  assert status == 201 and ana["meta"]["location"] == f"{scimBase}/Users/{ana['id']}"
  status, jose = call("POST", "/Users", {"schemas": [coreUser], "userName": "jose@example.org", "displayName": "Jos\u00e9 N\u00fa\u00f1ez"})
  status, inner = call("POST", "/Groups", {"schemas": [coreGroup], "displayName": "Team A",
                                           "members": [{"value": jose["id"]}]})
  status, outer = call("POST", "/Groups", {"schemas": [coreGroup], "displayName": "Field",
                                           "members": [{"value": ana["id"]}, {"value": inner["id"]}]})
  assert status == 201
  accounts = {account.userName: account for account in operator.accounts()}
  assert (accounts["ana@example.org"].displayName, accounts["ana@example.org"].email) == ("Ana Lima", "ana@example.org")
  assert accounts["jose@example.org"].displayName == "Jos\u00e9 N\u00fa\u00f1ez"
  members = {group.name: group.members for group in operator.groups()}
  assert members["entra/Field"] == ["ana@example.org", "jose@example.org"]
  assert members["entra/Team A"] == ["jose@example.org"]

  status, _ = call("PATCH", f"/Users/{ana['id']}", {"schemas": [patchOp],
                                                    "Operations": [{"op": "Replace", "path": "active", "value": False}]})
  assert status == 200
  assert not {account.userName: account for account in operator.accounts()}["ana@example.org"].active

  status, _ = call("DELETE", f"/Users/{jose['id']}")
  assert status == 204
  accounts = {account.userName: account for account in operator.accounts()}
  assert accounts["jose@example.org"].active is False
  members = {group.name: group.members for group in operator.groups()}
  assert members["entra/Field"] == ["ana@example.org"] and members["entra/Team A"] == []

  status, _ = call("PATCH", f"/Groups/{outer['id']}", {"schemas": [patchOp],
                                                       "Operations": [{"op": "Replace", "path": "displayName", "value": "Fields"}]})
  assert status == 204 and "entra/Fields" in [group.name for group in operator.groups()]
  actions = [event.action for event in operator.auditEvents()]
  assert actions.count("provision") == 7


def testProvisioningRefusesWhatItCannotTake(provisioned):
  call, operator = provisioned
  status, document = call("GET", "/Users", bearer="not-the-token")
  assert status == 401
  status, document = call("POST", "/Users", {"schemas": [coreUser], "userName": "admin"})
  assert status == 409 and "account 'admin' already exists" in document["detail"]
  status, document = call("POST", "/Users", {"schemas": [coreUser], "userName": "no spaces allowed"})
  assert status == 400 and "is not a user name" in document["detail"]
  assert [account.userName for account in operator.accounts()] == ["admin"]
  assert "provision.refused" in [event.action for event in operator.auditEvents()]


def testProvisioningAtAnUnknownOrSignInProviderIsNotFound(provisioned, location):
  call, operator = provisioned
  operator.addProvider(Provider.of("idp", "openIDConnect", oidcSettings()))
  client = createApp(location).test_client()
  for name in ("nobody", "idp"):
    assert client.get(f"/scim/{name}/v2/Users", headers={"Authorization": "Bearer x"}).status_code == 404


# ---- against the testbed's real providers -------------------------------------

class _Forms(html.parser.HTMLParser):
  def __init__(self):
    super().__init__()
    self.action, self.fields = None, {}

  def handle_starttag(self, tag, attributes):
    attributes = dict(attributes)
    if tag == "form" and attributes.get("id") == "kc-form-login":
      self.action = attributes["action"]
    if tag == "input" and attributes.get("name"):
      self.fields[attributes["name"]] = attributes.get("value", "")


class _Stop(urllib.request.HTTPRedirectHandler):
  def redirect_request(self, request, fp, code, message, headers, newURL):
    raise urllib.error.HTTPError(newURL, code, message, headers, fp)


class Browser:
  """A person's browser at the providers: its cookies kept from step to step, redirects reported rather than followed,
  since OpenFurrow is the test client and not reachable at its address."""

  def __init__(self, context):
    self.opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context),
                                              urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), _Stop())

  def open(self, address, form=None):
    """(the address redirected to, None), or (None, the page)."""
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    try:
      with self.opener.open(urllib.request.Request(address, data=data, method="POST" if form else "GET"),
                            timeout=20) as answer:
        return None, answer.read().decode("utf-8")
    except urllib.error.HTTPError as redirect:
      if redirect.code not in (302, 303):
        raise
      return redirect.url, None

  def atKeycloak(self, address, userName, secret):
    """What the person does at Keycloak: its login form, unless a session is open there already; then the redirect
    back (its query), or the page that posts back (its fields)."""
    location, page = self.open(address)
    if page is not None:
      form = _Forms()
      form.feed(page)
      if form.action is not None:
        location, page = self.open(form.action, {"username": userName, "password": secret, "credentialId": ""})
    if location is not None:
      return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(location).query)), None
    posted = _Forms()
    posted.feed(page)
    return None, posted.fields


def atKeycloak(address, userName, secret, context):
  return Browser(context).atKeycloak(address, userName, secret)


def account(testbed, userName):
  return next(entry for entry in testbed["accounts"] if entry["userName"] == userName)


def expectedGroups(prefix, paths):
  return sorted(f"{prefix}/{path.strip('/')}" for path in paths)


def mirroredOf(operator, userName, prefix):
  return sorted(group.name for group in operator.groups() if userName in group.members and group.name.startswith(prefix))


@pytest.mark.parametrize("userName", ["ana", "layla", "wei", "\u0645\u0631\u064a\u0645"])
def testSigningInThroughKeycloakByOpenIDConnect(testbed, location, monkeypatch, userName):
  settings = testbed["openIDConnect"]
  monkeypatch.setenv("OPENFURROW_TEST_SECRET", settings["clientSecret"])
  operator = Workspace.open(location)
  operator.addProvider(Provider.of("keycloak", "openIDConnect", {
    "issuer": settings["issuer"], "clientID": settings["clientID"], "clientSecretVariable": "OPENFURROW_TEST_SECRET",
    "returnURL": settings["redirectURI"], "certificateAuthority": testbed["certificateAuthority"],
    "newAccounts": "create", "groups": "mirror"}))
  client = createApp(location).test_client()
  started = client.get("/signin/with/keycloak?next=/account")
  assert started.status_code == 302 and started.headers["Location"].startswith(settings["issuer"])
  expected = account(testbed, userName)
  query, _ = atKeycloak(started.headers["Location"], userName, expected["password"], secureContext(testbed["certificateAuthority"]))
  answered = client.get("/signin/with/keycloak/return", query_string=query)
  assert answered.status_code == 200, answered.get_data(as_text=True)[:500]
  assert 'content="0; url=/account"' in answered.get_data(as_text=True)
  assert any("openfurrowSession=" in cookie and "SameSite=Strict" in cookie for cookie in answered.headers.getlist("Set-Cookie"))
  assert client.get("/account").status_code == 200
  assert client.get("/signin/with/keycloak/return", query_string=query).status_code == 401
  made = {entry.userName: entry for entry in operator.accounts()}[userName]
  assert made.email == expected["email"]
  assert mirroredOf(operator, userName, "keycloak/") == expectedGroups("keycloak", expected["groups"])


def testSigningOutEverywhereAtKeycloakByOpenIDConnect(testbed, location, monkeypatch):
  settings = testbed["openIDConnect"]
  monkeypatch.setenv("OPENFURROW_TEST_SECRET", settings["clientSecret"])
  Workspace.open(location).addProvider(Provider.of("keycloak", "openIDConnect", {
    "issuer": settings["issuer"], "clientID": settings["clientID"], "clientSecretVariable": "OPENFURROW_TEST_SECRET",
    "returnURL": settings["redirectURI"], "certificateAuthority": testbed["certificateAuthority"],
    "newAccounts": "create", "signOutEverywhere": True, "signedOutURL": "https://openfurrow.example.org/bye"}))
  client = createApp(location).test_client()
  started = client.get("/signin/with/keycloak")
  query, _ = atKeycloak(started.headers["Location"], "ana", account(testbed, "ana")["password"],
                        secureContext(testbed["certificateAuthority"]))
  assert client.get("/signin/with/keycloak/return", query_string=query).status_code == 200
  left = client.post("/signout", headers=origin)
  assert left.status_code == 302
  address = urllib.parse.urlsplit(left.headers["Location"])
  assert f"{address.scheme}://{address.netloc}{address.path}" == settings["issuer"] + "/protocol/openid-connect/logout"
  sent = dict(urllib.parse.parse_qsl(address.query))
  assert (sent["client_id"], sent["post_logout_redirect_uri"]) == (settings["clientID"], "https://openfurrow.example.org/bye")
  hint = claimsOf(sent["id_token_hint"])
  assert hint["iss"] == settings["issuer"] and hint["preferred_username"] == "ana" and hint["sid"]
  assert not signedIn(client)


def testSigningInThroughKeycloakBySAML(testbed, location):
  settings = testbed["saml"]
  operator = Workspace.open(location)
  operator.addProvider(Provider.of("keycloak-saml", "saml", {
    "metadataURL": settings["metadataURL"], "identityProviderEntityID": settings["identityProviderEntityID"],
    "entityID": settings["entities"]["response"], "returnURL": settings["consumerURL"],
    "emailAttribute": "email", "groupsAttribute": "groups", "certificateAuthority": testbed["certificateAuthority"],
    "newAccounts": "create", "groups": "mirror"}))
  client = createApp(location).test_client()
  started = client.get("/signin/with/keycloak-saml")
  assert started.status_code == 302
  expected = account(testbed, "jose")
  _, fields = atKeycloak(started.headers["Location"], "jose", expected["password"], secureContext(testbed["certificateAuthority"]))
  assert "SAMLResponse" in fields
  answered = client.post("/signin/with/keycloak-saml/return", data=fields, headers={"Origin": "https://keycloak.example"})
  assert answered.status_code == 200, answered.get_data(as_text=True)[:500]
  assert client.get("/account").status_code == 200
  made = {entry.userName: entry for entry in operator.accounts()}["jose"]
  assert made.email == expected["email"]
  assert mirroredOf(operator, "jose", "keycloak-saml/") == expectedGroups("keycloak-saml", expected["groups"])


def keyPair(keyed, kind):
  return {"keyFile": keyed[f"{kind}Key"], "certificateFile": keyed[f"{kind}Certificate"]}


@pytest.mark.parametrize("client, keys", [
  ("encryptsGCM", {"decryptionKeys": ["encryption"]}),
  ("encryptsCBC", {"decryptionKeys": ["encryption"], "allowCBC": True}),
  ("signsRequests", {"signingKey": "signing"}),
])
def testSigningInThroughKeycloakWithTheServicesOwnKeys(testbed, location, client, keys):
  settings, keyed = testbed["saml"], testbed["saml"]["keyed"]
  own = {name: ([keyPair(keyed, kind) for kind in value] if name == "decryptionKeys" else
                keyPair(keyed, value) if name == "signingKey" else value) for name, value in keys.items()}
  operator = Workspace.open(location)
  operator.addProvider(Provider.of("keycloak-saml", "saml", {
    "metadataURL": settings["metadataURL"], "identityProviderEntityID": settings["identityProviderEntityID"],
    "entityID": keyed["entities"][client], "returnURL": settings["consumerURL"], "emailAttribute": "email",
    "certificateAuthority": testbed["certificateAuthority"], "newAccounts": "create", **own}))
  web = createApp(location).test_client()
  started = web.get("/signin/with/keycloak-saml")
  assert started.status_code == 302
  assert ("Signature=" in started.headers["Location"]) == ("signingKey" in keys)
  expected = account(testbed, "jose")
  _, fields = atKeycloak(started.headers["Location"], "jose", expected["password"], secureContext(testbed["certificateAuthority"]))
  answered = web.post("/signin/with/keycloak-saml/return", data=fields, headers={"Origin": "https://keycloak.example"})
  assert answered.status_code == 200, answered.get_data(as_text=True)[:500]
  assert {entry.userName: entry for entry in operator.accounts()}["jose"].email == expected["email"]


def testAnEncryptedAssertionIsRefusedWithoutADecryptionKey(testbed, location):
  settings, keyed = testbed["saml"], testbed["saml"]["keyed"]
  Workspace.open(location).addProvider(Provider.of("keycloak-saml", "saml", {
    "metadataURL": settings["metadataURL"], "identityProviderEntityID": settings["identityProviderEntityID"],
    "entityID": keyed["entities"]["encryptsGCM"], "returnURL": settings["consumerURL"],
    "certificateAuthority": testbed["certificateAuthority"], "newAccounts": "create"}))
  web = createApp(location).test_client()
  started = web.get("/signin/with/keycloak-saml")
  _, fields = atKeycloak(started.headers["Location"], "jose", account(testbed, "jose")["password"],
                         secureContext(testbed["certificateAuthority"]))
  answered = web.post("/signin/with/keycloak-saml/return", data=fields, headers={"Origin": "https://keycloak.example"})
  assert answered.status_code == 401 and "encrypted" in answered.get_data(as_text=True)
  assert "jose" not in {entry.userName for entry in Workspace.open(location).accounts()}


def testTheMetadataListsTheServicesKeys(testbed, location):
  keyed = testbed["saml"]["keyed"]
  Workspace.open(location).addProvider(Provider.of("keycloak-saml", "saml", {
    "metadataURL": testbed["saml"]["metadataURL"], "entityID": "https://openfurrow.example.org/saml",
    "returnURL": "https://openfurrow.example.org/signin/with/keycloak-saml/return",
    "singleLogoutURL": "https://openfurrow.example.org/signin/with/keycloak-saml/signout",
    "signingKey": keyPair(keyed, "signing"), "decryptionKeys": [keyPair(keyed, "encryption")]}))
  answered = createApp(location).test_client().get("/signin/with/keycloak-saml/metadata")
  assert answered.status_code == 200 and answered.mimetype == "application/samlmetadata+xml"
  document = answered.get_data(as_text=True)
  assert 'entityID="https://openfurrow.example.org/saml"' in document and 'AuthnRequestsSigned="true"' in document
  assert document.count('<md:SingleLogoutService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-') == 2
  assert document.count('Location="https://openfurrow.example.org/signin/with/keycloak-saml/signout"') == 2
  assert document.count('use="signing"') == 1 and document.count('use="encryption"') == 1
  assert "aes256-gcm" in document and "aes256-cbc" not in document


@pytest.mark.parametrize("keys, why", [
  ({"allowCBC": True}, "allowCBC is a setting for decrypting"),
  ({"signingKey": {"keyFile": "k.pem", "certificateFile": "c.pem"},
    "decryptionKeys": [{"keyFile": "k.pem", "certificateFile": "c.pem"}]}, "different keys"),
  ({"signOutEverywhere": True, "signingKey": {"keyFile": "k.pem", "certificateFile": "c.pem"}}, "needs singleLogoutURL"),
  ({"singleLogoutURL": "https://sp.example.org/signin/with/idp/signout"}, "single logout needs signingKey"),
  ({"singleLogoutURL": "http://sp.example.org/signin/with/idp/signout",
    "signingKey": {"keyFile": "k.pem", "certificateFile": "c.pem"}}, "must be an https address"),
])
def testSAMLKeySettingsAreChecked(keys, why):
  with pytest.raises(ValidationError, match=why):
    Provider.of("idp", "saml", {"metadataURL": "https://idp.example.org/metadata", "entityID": "https://sp.example.org",
                                "returnURL": "https://sp.example.org/back", **keys})


def testAMissingKeyFileIsRefusedByName(location, tmp_path):
  Workspace.open(location).addProvider(Provider.of("idp", "saml", {
    "metadataURL": "https://idp.example.org/metadata", "entityID": "https://sp.example.org",
    "returnURL": "https://sp.example.org/back",
    "signingKey": {"keyFile": str(tmp_path / "absent.pem"), "certificateFile": str(tmp_path / "absent.crt")}}))
  with pytest.raises(IdentityError, match=r"the private key file .*absent\.pem cannot be read"):
    Workspace.open(location).samlMetadata("idp")


def singleLogoutSettings(testbed, client, **overrides):
  settings, keyed = testbed["saml"], testbed["saml"]["keyed"]
  return {"metadataURL": settings["metadataURL"], "identityProviderEntityID": settings["identityProviderEntityID"],
          "entityID": keyed["entities"][client], "returnURL": settings["consumerURL"],
          "singleLogoutURL": keyed["singleLogoutURLs"][client], "signingKey": keyPair(keyed, "signing"),
          "certificateAuthority": testbed["certificateAuthority"], "newAccounts": "create", **overrides}


def signedInBySAML(client, name, browser, testbed, userName="jose"):
  started = client.get(f"/signin/with/{name}")
  _, fields = browser.atKeycloak(started.headers["Location"], userName, account(testbed, userName)["password"])
  answered = client.post(f"/signin/with/{name}/return", data=fields, headers={"Origin": "https://keycloak.example"})
  assert answered.status_code == 200, answered.get_data(as_text=True)[:500]
  assert signedIn(client)


def testSigningOutEverywhereThroughKeycloakBySAMLSingleLogout(testbed, location):
  keyed = testbed["saml"]["keyed"]
  Workspace.open(location).addProvider(Provider.of("keycloak-saml", "saml", singleLogoutSettings(
    testbed, "logsOut", signOutEverywhere=True, signedOutURL="https://openfurrow.example.org/bye")))
  client = createApp(location).test_client()
  browser = Browser(secureContext(testbed["certificateAuthority"]))
  signedInBySAML(client, "keycloak-saml", browser, testbed)
  left = client.post("/signout", headers=origin)
  assert left.status_code == 302 and "SAMLRequest=" in left.headers["Location"] and "Signature=" in left.headers["Location"]
  assert any(cookie.startswith("openfurrowPending=") for cookie in left.headers.getlist("Set-Cookie"))
  assert not signedIn(client)
  redirected, page = browser.open(left.headers["Location"])
  assert redirected is not None and redirected.startswith(keyed["singleLogoutURLs"]["logsOut"] + "?"), page
  finished = client.get("/signin/with/keycloak-saml/signout?" + urllib.parse.urlsplit(redirected).query)
  assert finished.status_code == 302 and finished.headers["Location"] == "https://openfurrow.example.org/bye"
  assert auditOf(location, "signOut.atProvider.finished") == [{"provider": "keycloak-saml"}]
  again = client.get("/signin/with/keycloak-saml/signout?" + urllib.parse.urlsplit(redirected).query)
  assert again.status_code == 200 and "this browser has no sign-out waiting" in again.get_data(as_text=True)
  _, page = browser.open(client.get("/signin/with/keycloak-saml").headers["Location"])
  assert page is not None and 'id="kc-form-login"' in page


def testKeycloaksOwnSingleLogoutEndsTheSessionHere(testbed, location):
  keyed = testbed["saml"]["keyed"]
  context = secureContext(testbed["certificateAuthority"])
  Workspace.open(location).addProvider(Provider.of("keycloak-saml", "saml", singleLogoutSettings(testbed, "logsOutToo")))
  client = createApp(location).test_client()
  browser = Browser(context)
  signedInBySAML(client, "keycloak-saml", browser, testbed)
  identityProvider = identityProviderFromMetadata(Fetcher(context).getBytes(
    testbed["saml"]["metadataURL"], "application/samlmetadata+xml, application/xml;q=0.9"),
    testbed["saml"]["identityProviderEntityID"])
  elsewhere = ServiceProvider(keyed["entities"]["logsOut"], testbed["saml"]["consumerURL"], identityProvider,
                              signingKey=LocalSigningKey(Path(keyed["signingKey"]).read_bytes(),
                                                         Path(keyed["signingCertificate"]).read_bytes()),
                              singleLogoutURL=keyed["singleLogoutURLs"]["logsOut"])
  address, started = elsewhere.beginSignIn()
  _, fields = browser.atKeycloak(address, "jose", account(testbed, "jose")["password"])
  identity = elsewhere.finishSignIn(started, fields["SAMLResponse"])
  address, leaving = elsewhere.beginSignOut(identity.nameID, identity.nameIDFormat, identity.sessionIndex)
  redirected, page = browser.open(address)
  assert redirected is not None and redirected.startswith(keyed["singleLogoutURLs"]["logsOutToo"] + "?"), page
  answered = client.get("/signin/with/keycloak-saml/signout?" + urllib.parse.urlsplit(redirected).query)
  assert answered.status_code == 302 and "SAMLResponse=" in answered.headers["Location"]
  assert not signedIn(client)
  assert auditOf(location, "signOut.fromProvider") == [{"provider": "keycloak-saml", "how": "saml", "sessionsEnded": 1}]
  redirected, page = browser.open(answered.headers["Location"])
  assert redirected is not None and redirected.startswith(keyed["singleLogoutURLs"]["logsOut"] + "?"), page
  elsewhere.finishSignOut(leaving, query=urllib.parse.urlsplit(redirected).query)


def testALogoutRequestFromAFederationIsRefusedByName(testbed, location):
  keyed = testbed["saml"]["keyed"]
  Workspace.open(location).addProvider(Provider.of("fed", "samlFederation", federationSettings(
    testbed, signingKey=keyPair(keyed, "signing"), singleLogoutURL="https://openfurrow.example.org/signin/with/fed/signout")))
  refused = createApp(location).test_client().get("/signin/with/fed/signout?SAMLRequest=anything")
  assert refused.status_code == 400
  assert "logout requests from a federation&#39;s institutions are refused" in refused.get_data(as_text=True)
  assert "federation" in auditOf(location, "signOut.fromProvider.refused")[0]["why"]


def testAServiceProviderIsMadeForEachUseWithTheReplaysOfItsStore(testbed, newStore):
  settings = Provider.of("keycloak-saml", "saml", singleLogoutSettings(testbed, "logsOut")).settings
  stores = [StoredReplays(createDatabase(newStore(name))) for name in ("a", "b")]
  first, second = (serviceProvider(settings, replays) for replays in stores)
  assert first is not second and (first.replayCache, second.replayCache) == tuple(stores)
  assert first.identityProvider is second.identityProvider and first.signingKey is second.signingKey
  now = time.time()
  first.replayCache.admit(first.identityProvider.entityID, "_logout-1", now + 60, now)
  with pytest.raises(SAMLRefused, match="already used"):
    first.replayCache.admit(first.identityProvider.entityID, "_logout-1", now + 60, now)
  second.replayCache.admit(second.identityProvider.entityID, "_logout-1", now + 60, now)


@pytest.fixture
def directory(request, testbed, location, monkeypatch):
  if not request.config.getoption("--directory"):
    pytest.skip("directory test: run with --directory against a testbed whose Samba is running")
  settings = testbed["directory"]
  monkeypatch.setenv("OPENFURROW_TEST_DIRECTORY", settings["servicePassword"])
  Workspace.open(location).addProvider(Provider.of("ad", "ldap", {
    "host": settings["host"], "port": settings["ldapsPort"], "baseDN": settings["baseDN"],
    "serviceName": settings["serviceDN"], "servicePasswordVariable": "OPENFURROW_TEST_DIRECTORY",
    "certificateAuthority": testbed["certificateAuthority"], "newAccounts": "create", "groups": "mirror"}))
  return createApp(location).test_client()


@pytest.mark.parametrize("userName", ["jose", "\u0645\u0631\u064a\u0645"])
def testSigningInThroughTheDirectory(testbed, location, directory, userName):
  expected = account(testbed, userName)
  page = directory.get("/signin").get_data(as_text=True)
  assert '<option value="ad">ad</option>' in page
  refused = directory.post("/signin", data={"provider": "ad", "userName": userName, "password": "wrong"},
                           headers={"Origin": "http://localhost"})
  assert refused.status_code == 401 and "the user name or the password is wrong" in refused.get_data(as_text=True)
  signed = directory.post("/signin?next=/account", data={"provider": "ad", "userName": userName, "password": expected["password"]},
                          headers={"Origin": "http://localhost"})
  assert signed.status_code == 302 and signed.headers["Location"] == "/account"
  operator = Workspace.open(location)
  groups = {segment for path in expected["groups"] for segment in path.strip("/").split("/")}
  assert mirroredOf(operator, userName, "ad/") == sorted(f"ad/{group}" for group in groups)


# ---- a research federation (the testbed's, vouching for its Keycloak) -----------

def federationSettings(testbed, **overrides):
  settings, saml = testbed["federation"], testbed["saml"]
  return {"mdqURL": settings["mdqURL"], "signingCertificate": Path(settings["signingCertificate"]).read_text(encoding="ascii"),
          "institutions": [settings["institution"]], "entityID": saml["entities"]["response"], "returnURL": saml["consumerURL"],
          "subjectAttribute": "subjectID", "userNameAttribute": "email", "emailAttribute": "email",
          "organizationName": "Example Station", "informationURL": "https://openfurrow.example.org/about",
          "privacyStatementURL": "https://openfurrow.example.org/privacy", "technicalContact": "it@example.org",
          "certificateAuthority": testbed["certificateAuthority"], "newAccounts": "create", **overrides}


@pytest.mark.parametrize("overrides, why", [
  ({"institutions": []}, "one or more institutions"),
  ({"signingCertificate": "not a certificate"}, "not a PEM certificate"),
  ({"mdqURL": "http://mdq.example.org"}, "must be an https address"),
  ({"subjectAttribute": "nameID"}, "subjectAttribute"),
])
def testFederationSettingsAreChecked(testbed, overrides, why):
  with pytest.raises(ValidationError, match=why):
    Provider.of("fed", "samlFederation", federationSettings(testbed, **overrides))


@pytest.mark.parametrize("userName", ["ana", "\u0645\u0631\u064a\u0645"])
def testSigningInThroughAFederation(testbed, location, userName):
  operator = Workspace.open(location)
  operator.addProvider(Provider.of("fed", "samlFederation", federationSettings(testbed)))
  client = createApp(location).test_client()
  assert b"OpenFurrow" in client.get("/signin/with/fed/metadata").data
  assert "/signin/with/fed" in client.get("/signin").get_data(as_text=True)
  chooser = client.get("/signin/with/fed?locale=ar").get_data(as_text=True)
  assert "\u062c\u0627\u0645\u0639\u0629 \u0643\u0627\u0631\u0646\u064a\u0644\u064a\u0627\u0646" in chooser
  refused = client.get("/signin/with/fed", query_string={"institution": "https://elsewhere.example.edu/idp"})
  assert refused.status_code == 401 and "is not an institution offered here" in refused.get_data(as_text=True)
  expected = account(testbed, userName)
  for attempt in range(2):
    started = client.get("/signin/with/fed", query_string={"institution": testbed["federation"]["institution"]})
    assert started.status_code == 302
    _, fields = atKeycloak(started.headers["Location"], userName, expected["password"],
                           secureContext(testbed["certificateAuthority"]))
    answered = client.post("/signin/with/fed/return", data=fields)
    assert answered.status_code == 200, answered.get_data(as_text=True)[:500]
  made = [entry for entry in operator.accounts() if entry.email == expected["email"]]
  assert [entry.userName for entry in made] == [expected["email"]]


# ---- CAS (the testbed's Apereo CAS) ----------------------------------------------

class _CASLogin(html.parser.HTMLParser):
  def __init__(self):
    super().__init__()
    self.action, self.fields = None, {}

  def handle_starttag(self, tag, attributes):
    attributes = dict(attributes)
    if tag == "form" and attributes.get("id") == "fm1":
      self.action = attributes.get("action")
    if tag == "input" and attributes.get("type") == "hidden" and attributes.get("name"):
      self.fields[attributes["name"]] = attributes.get("value", "")


def atCAS(address, userName, secret, context):
  """What the person does in the browser: the query CAS sends back, or None when it refuses."""
  opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context),
                                       urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), _Stop())
  form = _CASLogin()
  with opener.open(address, timeout=30) as response:
    form.feed(response.read().decode("utf-8"))
  target = urllib.parse.urljoin(address, form.action) if form.action else address
  data = urllib.parse.urlencode({**form.fields, "username": userName, "password": secret, "_eventId": "submit"}).encode()
  try:
    with opener.open(urllib.request.Request(target, data=data, method="POST"), timeout=30):
      return None
  except urllib.error.HTTPError as redirect:
    if redirect.code not in (301, 302, 303):
      return None
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(redirect.url).query))


@pytest.mark.parametrize("userName", ["jose", "\u0645\u0631\u064a\u0645"])
def testSigningInThroughCAS(testbed, location, userName):
  settings = testbed["cas"]
  operator = Workspace.open(location)
  operator.addProvider(Provider.of("university", "cas", {
    "serverURL": settings["serverURL"], "returnURL": settings["serviceURL"], "groupsAttribute": "memberOf",
    "certificateAuthority": testbed["certificateAuthority"], "newAccounts": "create", "groups": "mirror"}))
  client = createApp(location).test_client()
  started = client.get("/signin/with/university?next=/account")
  assert started.status_code == 302 and started.headers["Location"].startswith(settings["serverURL"] + "/login?")
  expected = account(testbed, userName)
  query = atCAS(started.headers["Location"], userName, expected["password"], secureContext(testbed["certificateAuthority"]))
  answered = client.get("/signin/with/university/return", query_string=query)
  assert answered.status_code == 200, answered.get_data(as_text=True)[:500]
  assert client.get("/account").status_code == 200
  made = {entry.userName: entry for entry in operator.accounts()}[userName]
  assert (made.email, made.displayName) == (expected["email"], f"{expected['firstName']} {expected['lastName']}")
  assert mirroredOf(operator, userName, "university/") == expectedGroups("university", expected["groups"])


def casLogoutRequest(ticket):
  return ('<samlp:LogoutRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
          'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="LR-1" Version="2.0" IssueInstant="2026-11-18T10:00:00Z">'
          f'<saml:NameID>@NOT_USED@</saml:NameID><samlp:SessionIndex>{ticket}</samlp:SessionIndex></samlp:LogoutRequest>')


def signedInByCAS(location, testbed, userName="jose"):
  """A browser signed in through the testbed's CAS, and the service ticket that started its session."""
  client = createApp(location).test_client()
  started = client.get("/signin/with/university")
  query = atCAS(started.headers["Location"], userName, account(testbed, userName)["password"],
                secureContext(testbed["certificateAuthority"]))
  assert client.get("/signin/with/university/return", query_string=query).status_code == 200
  assert signedIn(client)
  return client, query["ticket"]


def addCAS(location, testbed, **overrides):
  settings = testbed["cas"]
  Workspace.open(location).addProvider(Provider.of("university", "cas", {
    "serverURL": settings["serverURL"], "returnURL": settings["serviceURL"],
    "certificateAuthority": testbed["certificateAuthority"], "newAccounts": "create", **overrides}))


def testACASLogoutNoticeEndsExactlyTheSessionItsTicketStarted(testbed, location):
  addCAS(location, testbed)
  first, firstTicket = signedInByCAS(location, testbed)
  second, _ = signedInByCAS(location, testbed)
  server = createApp(location).test_client()
  wrong = server.post("/signin/with/university/return", data={"logoutRequest": casLogoutRequest("ST-1-not-a-ticket-here")})
  assert wrong.status_code == 200 and [signedIn(first), signedIn(second)] == [True, True]
  ended = server.post("/signin/with/university/return", data={"logoutRequest": casLogoutRequest(firstTicket)})
  assert ended.status_code == 200 and [signedIn(first), signedIn(second)] == [False, True]
  assert [event["sessionsEnded"] for event in auditOf(location, "signOut.fromProvider")] == [1, 0]
  refused = server.post("/signin/with/university/return", data={"logoutRequest": "<not-a-notice/>"})
  assert refused.status_code == 400 and "logout notice is refused" in refused.get_data(as_text=True)


def testSigningOutEverywhereSendsThePersonToCASLogout(testbed, location):
  addCAS(location, testbed, signOutEverywhere=True, signedOutURL="https://openfurrow.example.org/bye")
  client, _ = signedInByCAS(location, testbed)
  left = client.post("/signout", headers=origin)
  assert left.status_code == 302
  assert left.headers["Location"] == (testbed["cas"]["serverURL"] + "/logout?service="
                                      + urllib.parse.quote("https://openfurrow.example.org/bye", safe=""))
  assert not signedIn(client)
