# SPDX-License-Identifier: Apache-2.0
"""The administration pages for identity providers and trusted workload rules (worklist GOV-6; decisions 0040, 0042):
a form for each kind of provider with a field and its help for every setting of the kind, found from the settings
models themselves; adding one of each kind; a provisioning token shown once; what to register at a provider; and
workload rules with their roles."""

import re
import typing

import pytest
from markupsafe import escape
from pydantic import BaseModel

from openIDConnectStandIn import loopbackCertificates
from openfurrow import Workspace
from openfurrow.i18n import loadCatalog, translatorFor
from openfurrow.identity.providers import Provider, ProviderKind, settingsModels
from openfurrow.service import createApp

from administrationHelpers import audited, formWith, held, origin, seededStore, signedIn, text, trialCode

english = translatorFor("en-US")
helpPrefix = "web.administration.provider.help."
server = "https://openfurrow.example.org"
samlSettings = {
  "metadataURL": "https://idp.example.org/metadata", "entityID": f"{server}/saml",
  "returnURL": f"{server}/signin/with/idp/return", "singleLogoutURL": f"{server}/signin/with/idp/signout",
  "signingKey": {"keyFile": "/srv/keys/signing.key", "certificateFile": "/srv/keys/signing.crt"},
}


@pytest.fixture
def location(newStore, validPackageDict):
  return seededStore(newStore, validPackageDict)


def shown(written: str) -> str:
  return str(escape(written))


def modelInside(annotation) -> tuple[type[BaseModel] | None, bool]:
  """The settings model an annotation holds, and whether it holds a list of them; None for a plain setting."""
  if isinstance(annotation, type) and issubclass(annotation, BaseModel):
    return annotation, False
  for argument in typing.get_args(annotation):
    model, _ = modelInside(argument)
    if model is not None:
      return model, typing.get_origin(annotation) is list
  return None, False


def settingsOf(model: type[BaseModel], prefix: str = "") -> tuple[list[str], set[str]]:
  """Every setting of a settings model, read from the model alone: the names a form posts them under, in the model's
  order (a model inside by its path, a list of them by its first row), and each setting's own name."""
  posted, named = [], set()
  for name, field in model.model_fields.items():
    named.add(name)
    inside, listed = modelInside(field.annotation)
    if inside is None:
      posted.append(prefix + name)
    else:
      insidePosted, insideNamed = settingsOf(inside, f"{prefix}{name}.0." if listed else f"{prefix}{name}.")
      posted += insidePosted
      named |= insideNamed
  return posted, named


def testEveryKindsFormHasAFieldWithItsHelpForEverySettingOfItsModel(location):
  admin = signedIn(location, "admin")
  everySetting: set[str] = set()
  for kind, model in settingsModels.items():
    posted, named = settingsOf(model)
    assert posted, kind
    everySetting |= named
    for locale in ("en-US", "ar"):
      translator = translatorFor(locale)
      page = text(admin.get(f"/administration/providers/add/{kind.value}?locale={locale}"))
      fields = [name for name in re.findall(r'<(?:input|select|textarea)[^>]* name="([^"]+)"', page)
                if name not in ("locale", "name") and not name.endswith(".rows")]
      assert fields == posted, (kind, locale)
      for name in posted:
        assert f'for="field-{name}"' in page and f'aria-describedby="field-{name}-help"' in page, (kind, name)
      for setting in named:
        assert shown(translator.text(f"{helpPrefix}{setting}")) in page, (kind, locale, setting)
  assert set(settingsModels) == set(ProviderKind)
  helped = {key.removeprefix(helpPrefix) for key in loadCatalog("en-US").keys if key.startswith(helpPrefix)}
  assert helped == everySetting


def testAProviderOfEveryKindIsAddedFromItsFormAsTyped(location, tmp_path):
  operator = Workspace.open(location)
  admin = signedIn(location, "admin")
  certificate = loopbackCertificates(tmp_path)[0].read_text(encoding="ascii")
  published = {"entityID": f"{server}/saml", "organizationName": "Example Station", "informationURL": f"{server}/about",
               "privacyStatementURL": f"{server}/privacy", "technicalContact": "it@example.org"}
  # For each kind: what is typed over the form's starting values, the boxes ticked, and the settings that makes.
  cases = {
    "openIDConnect": (
      {"issuer": "https://login.example.org/realms/station", "clientID": "openfurrow",
       "clientSecretVariable": "OPENFURROW_CLIENT_SECRET", "returnURL": f"{server}/signin/with/oidc/return",
       "newAccounts": "create", "groups": "mirror", "signedOutURL": f"{server}/"}, ["signOutEverywhere"],
      {"issuer": "https://login.example.org/realms/station", "clientID": "openfurrow",
       "clientSecretVariable": "OPENFURROW_CLIENT_SECRET", "returnURL": f"{server}/signin/with/oidc/return",
       "newAccounts": "create", "groups": "mirror", "signOutEverywhere": True, "signedOutURL": f"{server}/"}),
    "ldap": (
      {"host": "ad.example.org", "port": "389", "baseDN": "dc=example,dc=org",
       "serviceName": "cn=openfurrow,dc=example,dc=org", "servicePasswordVariable": "OPENFURROW_LDAP_PASSWORD",
       "userAttribute": "uid", "newAccounts": "linkByUserName"}, ["startTLS"],
      {"host": "ad.example.org", "port": 389, "startTLS": True, "baseDN": "dc=example,dc=org",
       "serviceName": "cn=openfurrow,dc=example,dc=org", "servicePasswordVariable": "OPENFURROW_LDAP_PASSWORD",
       "userAttribute": "uid", "newAccounts": "linkByUserName"}),
    "scim": ({"baseURL": f"{server}/scim/scim/v2", "groups": "mirror"}, [],
             {"baseURL": f"{server}/scim/scim/v2", "groups": "mirror"}),
    "cas": ({"serverURL": "https://cas.example.org/cas", "returnURL": f"{server}/signin/with/cas/return",
             "emailAttribute": "", "groupsAttribute": "memberOf"}, [],
            {"serverURL": "https://cas.example.org/cas", "returnURL": f"{server}/signin/with/cas/return",
             "displayNameAttribute": "displayName", "emailAttribute": None, "groupsAttribute": "memberOf"}),
    "samlFederation": (
      {"mdqURL": "https://mdq.federation.example.org", "signingCertificate": certificate.replace("\n", "\r\n"),
       "institutions": "https://idp.one.example.org/shibboleth\r\n\r\n  https://idp.two.example.org/shibboleth\r\n",
       "returnURL": f"{server}/signin/with/samlfederation/return", "subjectAttribute": "pairwiseID"} | published, [],
      {"mdqURL": "https://mdq.federation.example.org", "signingCertificate": certificate,
       "institutions": ["https://idp.one.example.org/shibboleth", "https://idp.two.example.org/shibboleth"],
       "returnURL": f"{server}/signin/with/samlfederation/return", "subjectAttribute": "pairwiseID"} | published),
  }
  for kind, (typed, ticked, settings) in cases.items():
    name = kind.lower()
    address = f"/administration/providers/add/{kind}"
    fields = formWith(text(admin.get(address)), "name") | typed | {"name": name} | dict.fromkeys(ticked, "yes")
    added = admin.post(address, data=fields, headers=origin)
    assert added.status_code == 302 and added.headers["Location"] == f"/administration/providers/{name}?done=added", (kind, text(added))
    stored = next(provider for provider in operator.providers() if provider.name == name)
    assert (stored.kind.value, stored.enabled) == (kind, True)
    assert stored.settings == settingsModels[ProviderKind(kind)].model_validate(settings), kind
    assert audited(operator, "provider.add")[0] == ("admin", "provider.add", {"provider": name, "kind": kind})
  listed = text(admin.get("/administration/providers"))
  for kind in cases:
    assert f'href="/administration/providers/{kind.lower()}"' in listed and english.text(f"web.administration.provider.kind.{kind}") in listed


def testASAMLProviderTakesItsKeysInRowsAndTheFormKeepsThemWhenARowIsAdded(location):
  operator = Workspace.open(location)
  admin = signedIn(location, "admin")
  address = "/administration/providers/add/saml"
  fields = formWith(text(admin.get(address)), "name") | {
    "name": "idp", "metadataURL": samlSettings["metadataURL"], "entityID": samlSettings["entityID"],
    "returnURL": samlSettings["returnURL"], "singleLogoutURL": samlSettings["singleLogoutURL"],
    "signingKey.keyFile": "/srv/keys/signing.key", "signingKey.certificateFile": "/srv/keys/signing.crt",
    "decryptionKeys.0.keyFile": "/srv/keys/new.key", "decryptionKeys.0.certificateFile": "/srv/keys/new.crt"}
  assert fields["decryptionKeys.rows"] == "1"
  another = admin.post(address, data=fields | {"more": "decryptionKeys"}, headers=origin)
  assert another.status_code == 200 and operator.providers() == []
  fields = formWith(text(another), "name")
  assert fields["decryptionKeys.rows"] == "2" and fields["decryptionKeys.0.keyFile"] == "/srv/keys/new.key"
  assert (fields["name"], fields["metadataURL"], fields["decryptionKeys.1.keyFile"]) == ("idp", samlSettings["metadataURL"], "")
  fields |= {"decryptionKeys.1.keyFile": "/srv/keys/old.key", "decryptionKeys.1.certificateFile": "/srv/keys/old.crt",
             "decryptionKeys.1.passwordVariable": "OLD_KEY_PASSWORD"}
  assert admin.post(address, data=fields, headers=origin).status_code == 302
  [stored] = operator.providers()
  assert stored.settings == settingsModels[ProviderKind.saml].model_validate(samlSettings | {"decryptionKeys": [
    {"keyFile": "/srv/keys/new.key", "certificateFile": "/srv/keys/new.crt"},
    {"keyFile": "/srv/keys/old.key", "certificateFile": "/srv/keys/old.crt", "passwordVariable": "OLD_KEY_PASSWORD"}]})


def testAProviderFormSaysWhatIsWrongAndKeepsWhatWasTyped(location):
  operator = Workspace.open(location)
  admin = signedIn(location, "admin")
  address = "/administration/providers/add/openIDConnect"
  fields = formWith(text(admin.get(address)), "name") | {
    "name": "Campus Login", "issuer": "http://login.example.org", "clientSecretVariable": "OPENFURROW_CLIENT_SECRET",
    "returnURL": f"{server}/signin/with/campus/return", "newAccounts": "create"}

  def refused(fields: dict, reason: str) -> str:
    answer = admin.post(address, data=fields, headers=origin)
    page = text(answer)
    assert answer.status_code == 400 and shown(reason) in page, page
    assert formWith(page, "name") == fields
    assert operator.providers() == []
    return page

  refused(fields, english.text("web.administration.form.needsValue", field="clientID"))
  fields["clientID"] = "openfurrow"
  refused(fields, "issuer: Value error, 'http://login.example.org' must be an https address")
  fields["issuer"] = "https://login.example.org"
  refused(fields, "name: Value error, 'Campus Login' is not a provider name")
  fields |= {"name": "campus", "signedOutURL": f"{server}/"}
  refused(fields, "signedOutURL is where the provider sends the person after signing out everywhere")
  fields["signedOutURL"] = ""
  assert admin.post(address, data=fields, headers=origin).status_code == 302
  duplicate = admin.post(address, data=fields, headers=origin)
  assert duplicate.status_code == 400 and shown("identity provider 'campus' already exists") in text(duplicate)
  assert [provider.name for provider in operator.providers()] == ["campus"]


def testAProvisioningTokenIsShownOnceAndAProviderIsDisabledAndEnabled(location):
  operator = Workspace.open(location)
  operator.addProvider(Provider.of("campus", "scim", {"baseURL": f"{server}/scim/campus/v2"}))
  operator.addProvider(Provider.of("idp", "saml", samlSettings))
  admin = signedIn(location, "admin")
  provisioning = createApp(location).test_client()

  def issue() -> str:
    issued = admin.post("/administration/providers/campus", data={"action": "token"}, headers=origin)
    page = text(issued)
    assert issued.status_code == 200 and issued.headers["Cache-Control"] == "no-store"
    assert "Location" not in issued.headers and shown(english.text("web.administration.provider.tokenShownOnce")) in page
    [token] = re.findall(r'<code class="code secret" dir="ltr">([^<]+)</code>', page)
    return token

  def accepted(token: str) -> int:
    return provisioning.get("/scim/campus/v2/Users", headers={"Authorization": f"Bearer {token}"}).status_code

  first = issue()
  assert accepted(first) == 200 and accepted("not the token") == 401
  for address in ("/administration/providers/campus", "/administration/providers", "/administration/audit"):
    assert first not in text(admin.get(address))
  second = issue()
  assert second != first and accepted(second) == 200 and accepted(first) == 401
  assert [(who, detail) for who, _, detail in audited(operator, "provider.token")] == [("admin", {"provider": "campus"})] * 2
  notSCIM = admin.post("/administration/providers/idp", data={"action": "token"}, headers=origin)
  assert notSCIM.status_code == 400 and "only a SCIM provider takes a provisioning token" in text(notSCIM)
  assert 'name="action" value="token"' not in text(admin.get("/administration/providers/idp"))

  def enabled(name: str) -> bool:
    return next(provider.enabled for provider in operator.providers() if provider.name == name)

  assert admin.post("/administration/providers/campus", data={"action": "disable"}, headers=origin).status_code == 302
  assert enabled("campus") is False and accepted(second) == 404
  assert admin.post("/administration/providers/campus", data={"action": "enable"}, headers=origin).status_code == 302
  assert enabled("campus") is True and accepted(second) == 200
  assert [detail for _, _, detail in audited(operator, "provider.enable")] == [
    {"provider": "campus", "enabled": True}, {"provider": "campus", "enabled": False}]


def testAProvidersPageSaysWhatToRegisterAtTheProviderAndShowsEverySetting(location):
  operator = Workspace.open(location)
  operator.addProvider(Provider.of("idp", "saml", samlSettings))
  operator.addProvider(Provider.of("login", "openIDConnect", {
    "issuer": "https://login.example.org", "clientID": "openfurrow", "clientSecretVariable": "OPENFURROW_CLIENT_SECRET",
    "returnURL": f"{server}/signin/with/login/return"}))
  admin = signedIn(location, "admin")
  page = text(admin.get("/administration/providers/idp"))
  metadata = "http://localhost/signin/with/idp/metadata"
  for fact, value in (("entityID", samlSettings["entityID"]), ("signInAddress", samlSettings["returnURL"]),
                      ("signOutAddress", samlSettings["singleLogoutURL"])):
    assert f'<dt>{shown(english.text("web.administration.provider.register." + fact))}</dt>' in page
    assert f'<span class="code" dir="ltr">{value}</span>' in page
  assert f'<a class="code" dir="ltr" href="{metadata}">{metadata}</a>' in page
  for name in settingsModels[ProviderKind.saml].model_fields:
    assert f'<dt class="code">{name}</dt>' in page
  assert '<dt class="code">keyFile</dt><dd><span dir="auto">/srv/keys/signing.key</span></dd>' in page

  operator.setProviderEnabled("idp", False)
  disabled = text(admin.get("/administration/providers/idp"))
  assert f'href="{metadata}"' not in disabled and f'<span class="code" dir="ltr">{metadata}</span>' in disabled
  login = text(admin.get("/administration/providers/login"))
  assert f'<span class="code" dir="ltr">{server}/signin/with/login/return</span>' in login
  assert '<span class="code" dir="ltr">http://localhost/signin/with/login/backchannel-logout</span>' in login


# ---- trusted workload rules ---------------------------------------------------------

def testWorkloadRulesAreAddedSwitchedGivenRolesAndRemovedAfterAConfirmationPage(location):
  operator = Workspace.open(location)
  admin = signedIn(location, "admin")
  typed = {"name": "nightly-weather", "issuer": "githubActions", "claims": "repository_id=734251980\r\nref=refs/heads/main",
           "certificateAuthority": ""}
  early = admin.post("/administration/workloads", data=typed, headers=origin)
  earlyPage = text(early)
  assert early.status_code == 400 and "set the server setting identity.workloadAudience before adding a workload rule" in earlyPage
  assert formWith(earlyPage, "issuer") == typed
  assert shown(english.text("web.administration.workloads.noAudience")) in earlyPage and operator.workloadRules() == []

  operator.setSetting("server", "identity.workloadAudience", server)
  assert english.text("web.administration.workloads.audience", audience=server) in text(admin.get("/administration/workloads"))
  unowned = admin.post("/administration/workloads", data=typed | {"claims": "repository=station/weather"}, headers=origin)
  assert unowned.status_code == 400 and "requires the claim repository_id" in text(unowned)
  malformed = admin.post("/administration/workloads", data=typed | {"claims": "repository_id 734251980"}, headers=origin)
  assert malformed.status_code == 400 and shown("'repository_id 734251980' is not a required claim") in text(malformed)
  assert formWith(text(malformed), "issuer")["claims"] == "repository_id 734251980"
  assert operator.workloadRules() == []

  added = admin.post("/administration/workloads", data=typed, headers=origin)
  assert added.status_code == 302 and added.headers["Location"] == "/administration/workloads/nightly-weather?done=added"
  rule, given = operator.workloadRule("nightly-weather")
  assert (rule.issuer, rule.claims, rule.enabled, rule.certificateAuthority, given) == (
    "https://token.actions.githubusercontent.com", {"repository_id": "734251980", "ref": "refs/heads/main"}, True, None, [])
  assert audited(operator, "workload.")[0] == ("admin", "workload.add", {
    "rule": "nightly-weather", "issuer": rule.issuer, "claims": rule.claims, "certificateAuthority": None})
  page = text(admin.get("/administration/workloads/nightly-weather"))
  assert "repository_id=734251980" in page and rule.issuer in page

  def post(**data):
    return admin.post("/administration/workloads/nightly-weather", data=data, headers=origin)

  assert post(action="disable").status_code == 302 and operator.workloadRule("nightly-weather")[0].enabled is False
  assert post(action="enable").status_code == 302 and operator.workloadRule("nightly-weather")[0].enabled is True
  assert post(action="give", roleCode="analyst", scope=f"trial:{trialCode}").status_code == 302
  assert ("analyst", f"trial:{trialCode}", None, None, "nightly-weather") in held(operator)
  assert post(action="give", roleCode="viewer", scope="server").status_code == 302
  assert post(action="takeBack", roleCode="viewer", scope="server").status_code == 302
  assert [given[:2] for given in held(operator) if given[4] == "nightly-weather"] == [("analyst", f"trial:{trialCode}")]

  confirm = admin.get("/administration/workloads/nightly-weather/remove")
  confirmPage = text(confirm)
  assert confirm.status_code == 200 and shown(english.text("web.administration.confirm.workload.warning")) in confirmPage
  assert english.text("web.administration.role.analyst") in confirmPage and english.text("web.administration.scope.named.trial", name=trialCode) in confirmPage
  assert [rule.name for rule in operator.workloadRules()] == ["nightly-weather"]
  assert admin.post("/administration/workloads/nightly-weather/remove", headers=origin).status_code == 302
  assert operator.workloadRules() == [] and [given for given in held(operator) if given[4] is not None] == []
  assert audited(operator, "workload.remove") == [("admin", "workload.remove", {
    "rule": "nightly-weather", "roles": [{"roleCode": "analyst", "scope": f"trial:{trialCode}"}]})]
  assert admin.get("/administration/workloads/nightly-weather").status_code == 404
