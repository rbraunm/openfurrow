# SPDX-License-Identifier: Apache-2.0
"""Identity providers (decision 0040): the link policies, mirrored groups, SCIM provisioning,
and signing in through Keycloak (OpenID Connect, SAML) and a Samba directory (LDAP)."""

import html.parser
import http.cookiejar
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest
from carnelian.fetching import secureContext
from carnelian.oidc import Identity
from pydantic import ValidationError
from sqlalchemy.orm import Session

from openfurrow import Workspace
from openfurrow.identity import RoleAssignment
from openfurrow.identity.model import IdentityError
from openfurrow.identity.providers import (ProvidedIdentity, Provider, ProviderFailure, _ProviderCache, fromOpenIDConnect,
                                          providerRefreshSeconds)
from openfurrow.service import createApp
from openfurrow.store.database import createDatabase
from openfurrow.store.providers import completeSignIn

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
  assert [cache.get(settings, build), cache.get(settings, build)] == [1, 1]
  clock.now += providerRefreshSeconds - 1
  assert cache.get(settings, build) == 1
  clock.now += 1
  assert cache.get(settings, build) == 2 and builds == [1000.0, 1000.0 + providerRefreshSeconds]
  other = Provider.of("idp", "openIDConnect", oidcSettings(clientID="another")).settings
  assert cache.get(other, build) == 3


def testAFailedBuildIsNotKept():
  cache, attempts = _ProviderCache(Clock()), []
  settings = Provider.of("idp", "openIDConnect", oidcSettings()).settings

  def failing():
    attempts.append(1)
    raise ProviderFailure("unreachable")

  for _ in range(2):
    with pytest.raises(ProviderFailure, match="unreachable"):
      cache.get(settings, failing)
  assert len(attempts) == 2 and cache.get(settings, lambda: "built") == "built"


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


def atKeycloak(address, userName, secret, context):
  """What the person does in the browser: the redirect back (its query), or the page that posts back (its fields)."""
  opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context),
                                       urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), _Stop())
  form = _Forms()
  with opener.open(address, timeout=20) as response:
    form.feed(response.read().decode("utf-8"))
  data = urllib.parse.urlencode({"username": userName, "password": secret, "credentialId": ""}).encode()
  try:
    with opener.open(urllib.request.Request(form.action, data=data, method="POST"), timeout=20) as response:
      posted = _Forms()
      posted.feed(response.read().decode("utf-8"))
      return None, posted.fields
  except urllib.error.HTTPError as redirect:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(redirect.url).query)), None


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
    "signingKey": keyPair(keyed, "signing"), "decryptionKeys": [keyPair(keyed, "encryption")]}))
  answered = createApp(location).test_client().get("/signin/with/keycloak-saml/metadata")
  assert answered.status_code == 200 and answered.mimetype == "application/samlmetadata+xml"
  document = answered.get_data(as_text=True)
  assert 'entityID="https://openfurrow.example.org/saml"' in document and 'AuthnRequestsSigned="true"' in document
  assert document.count('use="signing"') == 1 and document.count('use="encryption"') == 1
  assert "aes256-gcm" in document and "aes256-cbc" not in document


@pytest.mark.parametrize("keys, why", [
  ({"allowCBC": True}, "allowCBC is a setting for decrypting"),
  ({"signingKey": {"keyFile": "k.pem", "certificateFile": "c.pem"},
    "decryptionKeys": [{"keyFile": "k.pem", "certificateFile": "c.pem"}]}, "different keys"),
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
