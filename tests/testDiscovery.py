# SPDX-License-Identifier: Apache-2.0
"""Every institution of a federation (decision 0040): a signed aggregate made here and served over HTTPS on the
loopback address, read by the federationRefresh task in a real run; the stored list, its search and the sign-in page
built on it; a refresh that fails; and, with --live, eduGAIN's own aggregate."""

import base64
import datetime
import re
import ssl
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree
from pydantic import ValidationError
from signxml import XMLSigner

from openIDConnectStandIn import loopbackCertificates
from openfurrow import Workspace
from openfurrow.identity import RoleAssignment
from openfurrow.identity.providers import Provider
from openfurrow.service import createApp
from openfurrow.tasks.model import RunState
from openfurrow.tasks.scheduler import Scheduler

password = "correct horse battery"
taskName = "federationRefresh-fed"


def certificate(key, name):
  subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
  start = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1)
  return (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(start)
          .not_valid_after(start + datetime.timedelta(days=30)).sign(key, hashes.SHA256()))


federationKey = rsa.generate_private_key(public_exponent=65537, key_size=2048)
federationCertificate = certificate(federationKey, "test federation signing").public_bytes(
  serialization.Encoding.PEM).decode("ascii")
identityProviderCertificate = base64.b64encode(certificate(
  rsa.generate_private_key(public_exponent=65537, key_size=2048), "idp").public_bytes(serialization.Encoding.DER)).decode()

namespaces = ('xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" xmlns:ds="http://www.w3.org/2000/09/xmldsig#" '
              'xmlns:shibmd="urn:mace:shibboleth:metadata:1.0" xmlns:mdui="urn:oasis:names:tc:SAML:metadata:ui" '
              'xmlns:mdrpi="urn:oasis:names:tc:SAML:metadata:rpi" xmlns:mdattr="urn:oasis:names:tc:SAML:metadata:attribute" '
              'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"')


def instant(seconds):
  return (datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def identityProvider(entityID, names, scopes, hidden=False):
  category = ('<mdattr:EntityAttributes><saml:Attribute Name="http://macedir.org/entity-category" '
              'NameFormat="urn:oasis:names:tc:SAML:2.0:attrname-format:uri"><saml:AttributeValue>'
              'http://refeds.org/category/hide-from-discovery</saml:AttributeValue></saml:Attribute>'
              '</mdattr:EntityAttributes>') if hidden else ""
  displayNames = "".join(f'<mdui:DisplayName xml:lang="{language}">{text}</mdui:DisplayName>'
                         for language, text in names.items())
  scopeElements = "".join(f'<shibmd:Scope regexp="false">{scope}</shibmd:Scope>' for scope in scopes)
  return (f'<md:EntityDescriptor entityID="{entityID}"><md:Extensions>'
          f'<mdrpi:RegistrationInfo registrationAuthority="https://federation.example.org"/>{category}</md:Extensions>'
          '<md:IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">'
          f'<md:Extensions>{scopeElements}<mdui:UIInfo>{displayNames}</mdui:UIInfo></md:Extensions>'
          '<md:KeyDescriptor use="signing"><ds:KeyInfo><ds:X509Data><ds:X509Certificate>'
          f'{identityProviderCertificate}</ds:X509Certificate></ds:X509Data></ds:KeyInfo></md:KeyDescriptor>'
          '<md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect" '
          f'Location="{entityID}/sso"/></md:IDPSSODescriptor></md:EntityDescriptor>')


geneva = "https://idp.unige.ch/idp/shibboleth"
cairo = "https://idp.cu.edu.eg/idp"
hidden = "https://hidden.example.edu/idp"
broken = "https://broken.example.edu/idp"
members = [
  identityProvider(geneva, {"fr": "Universit\u00e9 de Gen\u00e8ve", "en": "University of Geneva"}, ["unige.ch"]),
  identityProvider(cairo, {"en": "Cairo University", "ar": "\u062c\u0627\u0645\u0639\u0629 \u0627\u0644\u0642\u0627\u0647\u0631\u0629"}, ["cu.edu.eg"]),
  identityProvider(hidden, {"en": "Hidden University"}, ["hidden.example.edu"], hidden=True),
  identityProvider(broken, {"en": "Broken University"}, []),
  *(identityProvider(f"https://idp.station{number:02d}.example.org/idp", {"en": f"Research Station {number:02d}"},
                     [f"station{number:02d}.example.org"]) for number in range(55)),
  ('<md:EntityDescriptor entityID="https://sp.example.org/sp"><md:SPSSODescriptor '
   'protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol"><md:AssertionConsumerService '
   'Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" Location="https://sp.example.org/acs" index="0"/>'
   '</md:SPSSODescriptor></md:EntityDescriptor>'),
]


def signedAggregate(entities):
  text = (f'<md:EntitiesDescriptor {namespaces} Name="https://federation.example.org" ID="aggregate" '
          f'validUntil="{instant(14 * 86400)}"><ds:Signature Id="placeholder"/>' + "".join(entities)
          + "</md:EntitiesDescriptor>")
  return etree.tostring(XMLSigner(signature_algorithm="rsa-sha256", digest_algorithm="sha256",
                                  c14n_algorithm="http://www.w3.org/2001/10/xml-exc-c14n#").sign(
    etree.fromstring(text.encode("utf-8")), key=federationKey, reference_uri="#aggregate", always_add_key_value=False))


class AggregateServer:
  """The federation's aggregate at https://127.0.0.1:<port>/aggregate.xml, signed by a certificate authority of the
  test's own; `document` is what it serves."""

  def __init__(self, directory, document):
    self.certificateAuthority, serverCertificate, serverKey = loopbackCertificates(directory)
    self.document = document
    server = self

    class Handler(BaseHTTPRequestHandler):
      def log_message(self, *arguments):
        pass

      def do_GET(self):
        if self.path != "/aggregate.xml":
          self.send_error(404)
          return
        self.send_response(200)
        self.send_header("Content-Type", "application/samlmetadata+xml")
        self.send_header("Content-Length", str(len(server.document)))
        self.end_headers()
        self.wfile.write(server.document)

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(serverCertificate, serverKey)
    self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    self._server.socket = context.wrap_socket(self._server.socket, server_side=True)
    self.url = f"https://127.0.0.1:{self._server.server_address[1]}/aggregate.xml"
    threading.Thread(target=self._server.serve_forever, daemon=True).start()

  def close(self):
    self._server.shutdown()
    self._server.server_close()


@pytest.fixture(scope="module")
def aggregate():
  return signedAggregate(members)


@pytest.fixture
def server(tmp_path, aggregate):
  served = AggregateServer(tmp_path, aggregate)
  yield served
  served.close()


def federationSettings(server, **overrides):
  return {"mdqURL": "https://mdq.federation.example.org", "signingCertificate": federationCertificate,
          "discoveryAggregate": {"url": server.url, "signingCertificate": federationCertificate},
          "entityID": "https://openfurrow.example.org/saml", "returnURL": "https://openfurrow.example.org/signin/with/fed/return",
          "subjectAttribute": "subjectID", "organizationName": "Example Station",
          "informationURL": "https://openfurrow.example.org/about",
          "privacyStatementURL": "https://openfurrow.example.org/privacy", "technicalContact": "it@example.org",
          "certificateAuthority": str(server.certificateAuthority), "newAccounts": "create", **overrides}


@pytest.fixture
def location(newStore, server):
  location = newStore("discovery")
  operator = Workspace.create(location)
  operator.createAccount("admin", "Administrator", None, password)
  operator.assignRole(RoleAssignment(roleCode="administrator", scope="server", userName="admin"))
  operator.addProvider(Provider.of("fed", "samlFederation", federationSettings(server)))
  return location


def refreshed(location, seconds=120):
  operator = Workspace.open(location)
  scheduler = Scheduler(location, pollSeconds=0.1)
  try:
    deadline = datetime.datetime.now() + datetime.timedelta(seconds=seconds)
    while datetime.datetime.now() < deadline:
      scheduler.tick()
      runs = operator.taskRuns(taskName)
      if runs[0].state not in (RunState.requested, RunState.running) and not scheduler.children:
        return runs[0]
      threading.Event().wait(0.1)
  finally:
    scheduler.windDown()
  raise AssertionError(f"the refresh did not finish: {operator.taskRuns(taskName)}")


@pytest.mark.parametrize("change, why", [
  ({"institutions": [geneva]}, "not both"),
  ({"discoveryAggregate": None}, "one or more institutions"),
  ({"discoveryAggregate": {"url": "http://federation.example.org/aggregate.xml",
                           "signingCertificate": federationCertificate}}, "must be an https address"),
  ({"discoveryAggregate": {"url": "https://federation.example.org/aggregate.xml",
                           "signingCertificate": "not a certificate"}}, "discovery aggregate's signingCertificate is not"),
])
def testDiscoverySettingsAreChecked(server, change, why):
  with pytest.raises(ValidationError, match=why):
    Provider.of("fed", "samlFederation", federationSettings(server, **change))


def testAFederationWithAnAggregateGetsItsRefreshTaskAndAFirstRun(location):
  operator = Workspace.open(location)
  [task] = operator.tasks()
  assert (task.name, task.kind, task.parameters, task.schedule, task.timeLimitSeconds, task.ownerProvider) == (
    taskName, "federationRefresh", {"provider": "fed"}, "0 */6 * * *", 900, "fed")
  assert [(run.state, run.requestedBy) for run in operator.taskRuns(taskName)] == [(RunState.requested, "operator")]
  page = createApp(location).test_client().get("/signin/with/fed").get_data(as_text=True)
  assert "has not been loaded yet" in page and 'name="q"' not in page


def testTheRefreshStoresTheOfferedInstitutionsAndSearchFindsThem(location):
  run = refreshed(location)
  assert run.state is RunState.succeeded, run.output
  assert run.summary.startswith("57 institutions offered, 1 hidden from discovery, 1 entities skipped; the aggregate "
                                "holds until ")
  assert f"left out {broken}: " in run.output and "no scope" in run.output
  [event] = [event for event in Workspace.open(location).auditEvents() if event.action == "provider.discovery"]
  assert (event.actorKind, event.actorName, event.surface, event.detail) == (
    "scheduler", taskName, "scheduler", {"provider": "fed", "offered": 57, "hidden": 1, "skipped": 1})

  client = createApp(location).test_client()

  def found(query, locale="en-US"):
    page = client.get("/signin/with/fed", query_string={"q": query, "locale": locale}).get_data(as_text=True)
    offered = [urllib.parse.unquote(value) for value in re.findall(r'institution=([^&"]+)', page)]
    return offered, page

  assert found("geneve")[0] == [geneva]
  assert found("GEN\u00c8VE")[0] == [geneva]
  assert found("unige.ch")[0] == [geneva]
  assert found("cu.edu")[0] == [cairo]
  assert found("\u0627\u0644\u0642\u0627\u0647\u0631\u0629")[0] == [cairo]
  assert found("hidden")[0] == []
  assert "No institution matches" in found("hidden")[1]
  french = found("geneva", "fr")[1]
  assert "Universit\u00e9 de Gen\u00e8ve" in french and "University of Geneva" not in french
  arabic = found("cairo", "ar")[1]
  assert "\u062c\u0627\u0645\u0639\u0629 \u0627\u0644\u0642\u0627\u0647\u0631\u0629" in arabic and 'dir="rtl"' in arabic
  stations = client.get("/signin/with/fed", query_string={"q": "research station"}).get_data(as_text=True)
  assert stations.count("Research Station ") == 50 and "More institutions match than the first 50 shown" in stations
  assert "Research Station 00" in stations and "Research Station 54" not in stations

  refused = client.get("/signin/with/fed", query_string={"institution": hidden})
  assert refused.status_code == 401 and "is not an institution offered here" in refused.get_data(as_text=True)


def testAFailedRefreshKeepsThePreviousList(location, server, aggregate):
  assert refreshed(location).state is RunState.succeeded
  server.document = aggregate.replace("Cairo University".encode(), "Kairo University".encode())
  operator = Workspace.open(location)
  operator.runTaskNow(taskName)
  run = refreshed(location)
  assert run.state is RunState.failed and "aggregate is refused" in run.summary
  assert cairo in [entityID for entityID, _ in operator.federationChoices("fed", "en", "cairo").institutions]
  assert operator.federationChoices("fed", "en", "kairo").institutions == []


eduGAINAggregate = "https://mds.edugain.org/edugain-v2.xml"
eduGAINCertificate = "https://technical.edugain.org/mds-v2.cer"
eduGAINFingerprint = "BD:21:40:48:9A:9B:D7:40:44:DD:68:05:34:F7:78:88:A9:C1:3B:0A:C1:7C:4F:3A:03:6E:0F:EC:6D:89:99:95"


def testEduGAINsWholeAggregateIsRefreshedAndSearched(request, newStore):
  if not request.config.getoption("--live"):
    pytest.skip("live test: run with --live to read eduGAIN's published aggregate")
  with urllib.request.urlopen(eduGAINCertificate, timeout=60) as answer:
    published = answer.read()
  loaded = (x509.load_pem_x509_certificate(published) if b"BEGIN CERTIFICATE" in published
            else x509.load_der_x509_certificate(published))
  assert loaded.fingerprint(hashes.SHA256()).hex(":").upper() == eduGAINFingerprint
  pem = loaded.public_bytes(serialization.Encoding.PEM).decode("ascii")
  location = newStore("edugain")
  operator = Workspace.create(location)
  settings = {"mdqURL": "https://mds.edugain.org", "signingCertificate": pem,
              "discoveryAggregate": {"url": eduGAINAggregate, "signingCertificate": pem},
              "entityID": "https://openfurrow.example.org/saml", "returnURL": "https://openfurrow.example.org/back",
              "subjectAttribute": "subjectID", "organizationName": "Example Station",
              "informationURL": "https://openfurrow.example.org/about",
              "privacyStatementURL": "https://openfurrow.example.org/privacy", "technicalContact": "it@example.org"}
  operator.addProvider(Provider.of("edugain", "samlFederation", settings))
  scheduler = Scheduler(location, pollSeconds=1)
  try:
    deadline = datetime.datetime.now() + datetime.timedelta(minutes=15)
    while datetime.datetime.now() < deadline:
      scheduler.tick()
      run = operator.taskRuns("federationRefresh-edugain")[0]
      if run.state not in (RunState.requested, RunState.running) and not scheduler.children:
        break
      threading.Event().wait(1)
  finally:
    scheduler.windDown()
  assert run.state is RunState.succeeded, run.output
  print(f"\neduGAIN: {run.summary} (started {run.startedAt}, finished {run.finishedAt})")
  offered = int(run.summary.split()[0])
  assert offered > 5000, run.summary
  arizona = operator.federationChoices("edugain", "en", "arizona.edu")
  assert "urn:mace:incommon:arizona.edu" in [entityID for entityID, _ in arizona.institutions]
