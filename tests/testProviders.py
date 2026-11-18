# SPDX-License-Identifier: Apache-2.0
"""Identity providers (decision 0040): the link policies, mirrored groups, SCIM provisioning,
and signing in through Keycloak (OpenID Connect, SAML) and a Samba directory (LDAP)."""

import html.parser
import http.cookiejar
import json
import urllib.error
import urllib.parse
import urllib.request

import pytest
from carnelian.fetching import secureContext
from pydantic import ValidationError
from sqlalchemy.orm import Session

from openfurrow import Workspace
from openfurrow.identity import RoleAssignment
from openfurrow.identity.model import IdentityError
from openfurrow.identity.providers import ProvidedIdentity, Provider
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
