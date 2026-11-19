# SPDX-License-Identifier: Apache-2.0
"""A stand-in OpenID Connect provider on the loopback address, over HTTPS with a certificate authority of its own:
discovery, a JWK set, an authorization endpoint that signs the next person in without a form, a token endpoint,
back-channel logout tokens and workload tokens signed with its key. It stands at the network boundary for back-channel
logout, which a provider in another network cannot deliver to a test, and for the CI platforms whose tokens only
their own running jobs can ask for."""

from __future__ import annotations

import base64
import datetime
import ipaddress
import json
import secrets
import ssl
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

clientID = "openfurrow"
keyID = "stand-in-1"


def _encoded(data: bytes) -> str:
  return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _number(value: int) -> str:
  return _encoded(value.to_bytes((value.bit_length() + 7) // 8, "big"))


def loopbackCertificates(directory: Path) -> tuple[Path, Path, Path]:
  start = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=5)
  authorityKey = rsa.generate_private_key(public_exponent=65537, key_size=2048)
  authorityName = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "stand-in authority")])
  authority = (x509.CertificateBuilder().subject_name(authorityName).issuer_name(authorityName)
               .public_key(authorityKey.public_key()).serial_number(x509.random_serial_number())
               .not_valid_before(start).not_valid_after(start + datetime.timedelta(days=1))
               .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
               .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
                                            data_encipherment=False, key_agreement=False, key_cert_sign=True,
                                            crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
               .add_extension(x509.SubjectKeyIdentifier.from_public_key(authorityKey.public_key()), critical=False)
               .sign(authorityKey, hashes.SHA256()))
  serverKey = rsa.generate_private_key(public_exponent=65537, key_size=2048)
  server = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")]))
            .issuer_name(authorityName).public_key(serverKey.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(start).not_valid_after(start + datetime.timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(authorityKey.public_key()), critical=False)
            .sign(authorityKey, hashes.SHA256()))
  paths = directory / "authority.crt", directory / "server.crt", directory / "server.key"
  paths[0].write_bytes(authority.public_bytes(serialization.Encoding.PEM))
  paths[1].write_bytes(server.public_bytes(serialization.Encoding.PEM))
  paths[2].write_bytes(serverKey.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
  return paths


class StandInIssuer:
  """Issuers at https://127.0.0.1:<port>/<realm>; the realm 'noLogout' names no end_session_endpoint, the
  discovery document of the realm 'misnamed' names another issuer, and the realm 'slashed' is named with a slash
  at its end, as Entra ID's and Auth0's issuers are. `fetched` lists the paths asked for."""

  def __init__(self, directory: Path) -> None:
    self.certificateAuthority, certificate, key = loopbackCertificates(directory)
    self._signingKey = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    self._codes: dict[str, dict] = {}
    self.nextPerson: dict = {}
    self.fetched: list[str] = []
    issuer = self

    class Handler(BaseHTTPRequestHandler):
      def log_message(self, *arguments):
        pass

      def _json(self, document: dict) -> None:
        body = json.dumps(document).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

      def do_GET(self):
        parts = urllib.parse.urlsplit(self.path)
        realm, _, rest = parts.path.lstrip("/").partition("/")
        issuer.fetched.append(parts.path)
        if rest == ".well-known/openid-configuration":
          self._json(issuer.discovery(realm))
        elif rest == "jwks":
          self._json(issuer.keySet())
        elif rest == "authorize":
          query = dict(urllib.parse.parse_qsl(parts.query))
          code = secrets.token_urlsafe(16)
          issuer._codes[code] = {"realm": realm, "nonce": query["nonce"], **issuer.nextPerson}
          back = f"{query['redirect_uri']}?{urllib.parse.urlencode({'code': code, 'state': query['state']})}"
          self.send_response(302)
          self.send_header("Location", back)
          self.send_header("Content-Length", "0")
          self.end_headers()
        else:
          self.send_error(404)

      def do_POST(self):
        realm, _, rest = urllib.parse.urlsplit(self.path).path.lstrip("/").partition("/")
        fields = dict(urllib.parse.parse_qsl(self.rfile.read(int(self.headers["Content-Length"])).decode("ascii")))
        if rest != "token" or fields.get("code") not in issuer._codes:
          self.send_error(400)
          return
        granted = issuer._codes.pop(fields["code"])
        now = int(time.time())
        claims = {"iss": issuer.issuer(granted.pop("realm")), "aud": clientID, "iat": now, "exp": now + 300,
                  "nonce": granted.pop("nonce"), **granted}
        self._json({"id_token": issuer.signed(claims, "JWT"), "access_token": "unused", "token_type": "Bearer"})

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, key)
    self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    self._server.socket = context.wrap_socket(self._server.socket, server_side=True)
    self.port = self._server.server_address[1]
    self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
    self._thread.start()

  def issuer(self, realm: str) -> str:
    return f"https://127.0.0.1:{self.port}/{realm}" + ("/" if realm == "slashed" else "")

  def discovery(self, realm: str) -> dict:
    base = self.issuer(realm).removesuffix("/")
    named = self.issuer("another") if realm == "misnamed" else self.issuer(realm)
    document = {"issuer": named, "authorization_endpoint": f"{base}/authorize", "token_endpoint": f"{base}/token",
                "jwks_uri": f"{base}/jwks", "id_token_signing_alg_values_supported": ["RS256"],
                "backchannel_logout_supported": True, "backchannel_logout_session_supported": True}
    if realm != "noLogout":
      document["end_session_endpoint"] = f"{base}/logout"
    return document

  def keySet(self) -> dict:
    numbers = self._signingKey.public_key().public_numbers()
    return {"keys": [{"kty": "RSA", "kid": keyID, "use": "sig", "alg": "RS256", "n": _number(numbers.n),
                      "e": _number(numbers.e)}]}

  def signed(self, claims: dict, kind: str) -> str:
    header = _encoded(json.dumps({"alg": "RS256", "kid": keyID, "typ": kind}).encode())
    payload = _encoded(json.dumps(claims).encode())
    signature = self._signingKey.sign(f"{header}.{payload}".encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{payload}.{_encoded(signature)}"

  def logoutToken(self, realm: str, subject: str | None = None, sessionID: str | None = None,
                  audience: str = clientID) -> str:
    now = int(time.time())
    claims = {"iss": self.issuer(realm), "aud": audience, "iat": now, "exp": now + 120, "jti": secrets.token_urlsafe(16),
              "events": {"http://schemas.openid.net/event/backchannel-logout": {}}}
    if subject is not None:
      claims["sub"] = subject
    if sessionID is not None:
      claims["sid"] = sessionID
    return self.signed(claims, "logout+jwt")

  def workloadToken(self, realm: str, audience: str, claims: dict, age: int = 0, lifetime: int = 300,
                    validIn: int | None = None) -> str:
    """A token as a CI platform hands a running job: for the audience the job asked for, issued `age` seconds ago,
    good for `lifetime` seconds from then, and with `validIn` not to be used before that many seconds from now."""
    now = int(time.time())
    body = {"iss": self.issuer(realm), "aud": audience, "iat": now - age, "exp": now - age + lifetime,
            "jti": secrets.token_urlsafe(16), **claims}
    if validIn is not None:
      body["nbf"] = now + validIn
    return self.signed(body, "JWT")

  def close(self) -> None:
    self._server.shutdown()
    self._server.server_close()
