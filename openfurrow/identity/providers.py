# SPDX-License-Identifier: Apache-2.0
"""Identity providers and what they say about a person (decision 0040).

A provider is configured with a name, a kind and the settings of that kind. Its secret is
never stored: the settings name an environment variable, read when the secret is needed.
The protocols themselves are Carnelian's; this module builds Carnelian's objects from the
settings and turns each protocol's answer into one ProvidedIdentity.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from carnelian import federation as federationAttributes
from carnelian.cas import CASServer
from carnelian.der import publicKeyFromCertificate
from carnelian.federation import Federation, scopedIdentifier, serviceProviderMetadata
from carnelian.fetching import Fetcher, HTTPFailure, secureContext
from carnelian.ldap import Directory
from carnelian.oidc import RelyingParty, SignInRefused, discover
from carnelian.keys import LocalDecryptionKey, LocalSigningKey
from carnelian.saml import (EncryptionPolicy, ReplayStore, SAMLRefused, ServiceProvider, aes128CBC, aes128GCM, aes256CBC,
                            aes256GCM, identityProviderFromMetadata)
from carnelian.saml import serviceProviderMetadata as plainServiceProviderMetadata
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from openfurrow.identity.model import IdentityError, foldedUserName

providerNamePattern = re.compile(r"^[a-z][a-z0-9-]{1,31}$")


class ProviderKind(str, Enum):
  openIDConnect = "openIDConnect"
  saml = "saml"
  ldap = "ldap"
  scim = "scim"
  samlFederation = "samlFederation"
  cas = "cas"


class NewAccounts(str, Enum):
  """What a sign-in does when the provider's identity is linked to no account yet."""

  refuse = "refuse"
  create = "create"
  linkByUserName = "linkByUserName"


class GroupPolicy(str, Enum):
  ignore = "ignore"
  mirror = "mirror"


def _secureURL(value: str) -> str:
  """https, or plain http on the loopback address only (RFC 8252 section 7.3)."""
  parts = urlsplit(value)
  if parts.scheme == "https" and parts.hostname:
    return value
  if parts.scheme == "http" and parts.hostname in ("127.0.0.1", "::1"):
    return value
  raise ValueError(f"'{value}' must be an https address")


def _httpsURL(value: str | None) -> str | None:
  if value is not None and not (urlsplit(value).scheme == "https" and urlsplit(value).hostname):
    raise ValueError(f"'{value}' must be an https address")
  return value


class _SignInSettings(BaseModel):
  model_config = ConfigDict(extra="forbid")

  newAccounts: NewAccounts = NewAccounts.refuse
  groups: GroupPolicy = GroupPolicy.ignore
  certificateAuthority: str | None = None


class _SignOutSettings(_SignInSettings):
  """Signing out of OpenFurrow ends only its own session, unless signOutEverywhere sends the person on to sign out at
  the provider too, which then sends them to signedOutURL when it is given."""

  signOutEverywhere: bool = False
  signedOutURL: str | None = None

  @field_validator("signedOutURL")
  @classmethod
  def secureSignedOut(cls, value: str | None) -> str | None:
    return _httpsURL(value)

  @model_validator(mode="after")
  def signedOutNeedsEverywhere(self) -> _SignOutSettings:
    if self.signedOutURL is not None and not self.signOutEverywhere:
      raise ValueError("signedOutURL is where the provider sends the person after signing out everywhere; "
                       "set signOutEverywhere too")
    return self


class OpenIDConnectSettings(_SignOutSettings):
  issuer: str
  clientID: str
  clientSecretVariable: str
  returnURL: str

  @field_validator("issuer", "returnURL")
  @classmethod
  def secure(cls, value: str) -> str:
    return _secureURL(value)


class KeyPair(BaseModel):
  """A private key and its certificate, as PEM files on the server; never stored in the database."""

  model_config = ConfigDict(extra="forbid")

  keyFile: str
  certificateFile: str
  passwordVariable: str | None = None


class _SAMLKeys(_SignOutSettings):
  """The service's own SAML keys: one that signs its requests and logout messages, and those that decrypt assertions
  (the first is current; the others are kept while a provider still encrypts to them); and this service's address
  for logout messages."""

  signingKey: KeyPair | None = None
  decryptionKeys: list[KeyPair] = []
  allowCBC: bool = False
  singleLogoutURL: str | None = None

  @field_validator("singleLogoutURL")
  @classmethod
  def secureLogout(cls, value: str | None) -> str | None:
    return _httpsURL(value)

  @model_validator(mode="after")
  def keysMakeSense(self) -> _SAMLKeys:
    if self.allowCBC and not self.decryptionKeys:
      raise ValueError("allowCBC is a setting for decrypting assertions; name decryptionKeys too")
    if self.signOutEverywhere and self.singleLogoutURL is None:
      raise ValueError("signOutEverywhere needs singleLogoutURL, the address the identity provider answers at")
    if self.singleLogoutURL is not None and self.signingKey is None:
      raise ValueError("single logout needs signingKey: every logout message is signed")
    files = [pair.keyFile for pair in self.decryptionKeys] + ([self.signingKey.keyFile] if self.signingKey else [])
    if len(set(files)) != len(files):
      raise ValueError("each key is named once: the signing key and every decryption key are different keys")
    return self


class SAMLSettings(_SAMLKeys):
  metadataURL: str
  identityProviderEntityID: str | None = None
  entityID: str
  returnURL: str
  userNameAttribute: str | None = None
  displayNameAttribute: str | None = None
  emailAttribute: str | None = None
  groupsAttribute: str | None = None

  @field_validator("metadataURL", "returnURL")
  @classmethod
  def secure(cls, value: str) -> str:
    return _secureURL(value)


class SubjectAttribute(str, Enum):
  """Which scoped identifier names a person (the SAML Subject Identifier profile, or eduPersonPrincipalName)."""

  subjectID = "subjectID"
  pairwiseID = "pairwiseID"
  eduPersonPrincipalName = "eduPersonPrincipalName"


subjectAttributeNames = {SubjectAttribute.subjectID: federationAttributes.subjectID,
                         SubjectAttribute.pairwiseID: federationAttributes.pairwiseID,
                         SubjectAttribute.eduPersonPrincipalName: federationAttributes.eduPersonPrincipalName}


class FederationSettings(_SAMLKeys):
  """A research and education federation (decision 0040): its MDQ service and key, and the institutions offered."""

  mdqURL: str
  signingCertificate: str
  institutions: list[str]
  entityID: str
  returnURL: str
  subjectAttribute: SubjectAttribute
  userNameAttribute: str = federationAttributes.eduPersonPrincipalName
  displayNameAttribute: str = federationAttributes.displayName
  emailAttribute: str = federationAttributes.mail
  groupsAttribute: str | None = None
  organizationName: str
  informationURL: str
  privacyStatementURL: str
  technicalContact: str
  securityContact: str | None = None

  @field_validator("mdqURL", "returnURL", "informationURL", "privacyStatementURL")
  @classmethod
  def secure(cls, value: str) -> str:
    return _secureURL(value)

  @field_validator("institutions")
  @classmethod
  def someInstitution(cls, institutions: list[str]) -> list[str]:
    if not institutions or len(set(institutions)) != len(institutions):
      raise ValueError("name one or more institutions (their entity IDs), each once")
    return institutions

  @field_validator("signingCertificate")
  @classmethod
  def aCertificate(cls, certificate: str) -> str:
    try:
      publicKeyFromCertificate(certificate)
    except ValueError as error:
      raise ValueError(f"signingCertificate is not a PEM certificate Carnelian can read: {error}") from None
    return certificate


class CASSettings(_SignOutSettings):
  """An Apereo CAS server (protocol 3.0); the attributes are those the server releases to this service."""

  serverURL: str
  returnURL: str
  displayNameAttribute: str | None = "displayName"
  emailAttribute: str | None = "mail"
  groupsAttribute: str | None = None

  @field_validator("serverURL", "returnURL")
  @classmethod
  def secure(cls, value: str) -> str:
    return _secureURL(value)


class LDAPSettings(_SignInSettings):
  host: str
  port: int = 636
  startTLS: bool = False
  baseDN: str
  serviceName: str
  servicePasswordVariable: str
  userAttribute: str = "sAMAccountName"


class SCIMSettings(BaseModel):
  model_config = ConfigDict(extra="forbid")

  baseURL: str
  groups: GroupPolicy = GroupPolicy.ignore

  @field_validator("baseURL")
  @classmethod
  def secure(cls, value: str) -> str:
    if not value.startswith("https://") or value.endswith("/"):
      raise ValueError("baseURL must be the https address the provider reaches, without a trailing slash")
    return value


settingsModels: dict[ProviderKind, type[BaseModel]] = {
  ProviderKind.openIDConnect: OpenIDConnectSettings,
  ProviderKind.saml: SAMLSettings,
  ProviderKind.ldap: LDAPSettings,
  ProviderKind.scim: SCIMSettings,
  ProviderKind.samlFederation: FederationSettings,
  ProviderKind.cas: CASSettings,
}


class Provider(BaseModel):
  model_config = ConfigDict(extra="forbid")

  name: str
  kind: ProviderKind
  enabled: bool = True
  settings: OpenIDConnectSettings | SAMLSettings | LDAPSettings | SCIMSettings | FederationSettings | CASSettings

  @field_validator("name")
  @classmethod
  def nameIsAName(cls, name: str) -> str:
    if not providerNamePattern.match(name):
      raise ValueError(f"'{name}' is not a provider name: a lower-case letter, then 1 to 31 letters, digits or '-'")
    return name

  @model_validator(mode="after")
  def settingsFitTheKind(self) -> Provider:
    if not isinstance(self.settings, settingsModels[self.kind]):
      raise ValueError(f"a {self.kind.value} provider needs {settingsModels[self.kind].__name__}")
    return self

  @classmethod
  def of(cls, name: str, kind: ProviderKind | str, settings: dict, enabled: bool = True) -> Provider:
    kind = ProviderKind(kind)
    return cls(name=name, kind=kind, enabled=enabled, settings=settingsModels[kind].model_validate(settings))


def secret(variable: str) -> str:
  value = os.environ.get(variable)
  if not value:
    raise IdentityError(f"the environment variable {variable}, which holds a provider's secret, is not set")
  return value


@dataclass(frozen=True)
class ProvidedIdentity:
  """What a provider vouches for: its stable subject for the person and what it says about them; and the provider's
  session, by the provider's own identifier for it (an OpenID Connect sid, a SAML SessionIndex, a CAS service
  ticket), with what signing out of it needs."""

  subject: str
  userName: str | None
  displayName: str | None
  email: str | None
  groups: tuple[str, ...]
  sessionID: str | None = None
  signOutDetail: dict[str, str | None] = field(default_factory=dict)


class ProviderFailure(IdentityError):
  """A provider's answer refused by Carnelian, or a provider that cannot be reached."""


# ---- Carnelian's side --------------------------------------------------------

def _context(settings: _SignInSettings):
  return secureContext(settings.certificateAuthority)


providerRefreshSeconds = 60 * 60


class _ProviderCache:
  """What each provider's settings make (its discovery, metadata, keys), kept by purpose, built once and rebuilt after
  providerRefreshSeconds; a failed build is never kept, so the next sign-in tries again."""

  def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
    self._clock = clock
    self._lock = threading.Lock()
    self._built: dict[tuple[str, str, str], tuple[float, Any]] = {}

  def get(self, purpose: str, settings: BaseModel, build: Callable[[], Any]) -> Any:
    key = (purpose, type(settings).__name__, settings.model_dump_json())
    with self._lock:
      found = self._built.get(key)
      if found is not None and self._clock() - found[0] < providerRefreshSeconds:
        return found[1]
    value = build()
    with self._lock:
      self._built[key] = (self._clock(), value)
    return value


_providers = _ProviderCache()


def relyingParty(settings: OpenIDConnectSettings):
  def build():
    fetcher = Fetcher(_context(settings))
    try:
      provider = discover(settings.issuer, fetcher)
    except SignInRefused as error:
      raise ProviderFailure(f"the provider at {settings.issuer} cannot be used: {error}") from None
    return RelyingParty(provider, settings.clientID, secret(settings.clientSecretVariable), settings.returnURL, fetcher)

  return _providers.get("relyingParty", settings, build)


def serviceProvider(settings: SAMLSettings, replays: ReplayStore) -> ServiceProvider:
  """A service provider for one use: the identity provider's metadata and the keys are reused, while the replay store
  is the caller's, since it belongs to the database and not to the process."""
  def build():
    try:
      metadata = Fetcher(_context(settings)).getBytes(settings.metadataURL,
                                                      "application/samlmetadata+xml, application/xml;q=0.9")
      return identityProviderFromMetadata(metadata, settings.identityProviderEntityID)
    except (HTTPFailure, SAMLRefused) as error:
      raise ProviderFailure(f"the metadata at {settings.metadataURL} cannot be used: {error}") from None

  return _keyedServiceProvider(settings, _providers.get("identityProvider", settings, build), replays)


def _pem(path: str, what: str) -> bytes:
  try:
    return Path(path).read_bytes()
  except OSError as error:
    raise IdentityError(f"the {what} file {path} cannot be read: {error.strerror}") from None


def _keyArguments(pair: KeyPair) -> tuple[bytes, bytes, bytes | None]:
  password = secret(pair.passwordVariable).encode("utf-8") if pair.passwordVariable else None
  return _pem(pair.keyFile, "private key"), _pem(pair.certificateFile, "certificate"), password


def _loadedKeys(settings: _SAMLKeys) -> tuple[LocalSigningKey | None, tuple[LocalDecryptionKey, ...]]:
  return _providers.get("keys", settings, lambda: (_signingKey(settings), _decryptionKeys(settings)))


def _signingKey(settings: _SAMLKeys) -> LocalSigningKey | None:
  if settings.signingKey is None:
    return None
  privateKey, certificate, password = _keyArguments(settings.signingKey)
  try:
    return LocalSigningKey(privateKey, certificate, password=password)
  except ValueError as error:
    raise IdentityError(f"the signing key {settings.signingKey.keyFile} cannot be used: {error}") from None


def _decryptionKeys(settings: _SAMLKeys) -> tuple[LocalDecryptionKey, ...]:
  keys = []
  for pair in settings.decryptionKeys:
    privateKey, certificate, password = _keyArguments(pair)
    try:
      keys.append(LocalDecryptionKey(privateKey, certificate, password=password))
    except ValueError as error:
      raise IdentityError(f"the decryption key {pair.keyFile} cannot be used: {error}") from None
  return tuple(keys)


def _encryptionPolicy(settings: _SAMLKeys) -> EncryptionPolicy:
  if not settings.allowCBC:
    return EncryptionPolicy()
  return EncryptionPolicy(contentAlgorithms=frozenset({aes128GCM, aes256GCM, aes128CBC, aes256CBC}))


def _keyedServiceProvider(settings: SAMLSettings | FederationSettings, identityProvider,
                          replays: ReplayStore) -> ServiceProvider:
  signing, decryption = _loadedKeys(settings)
  return ServiceProvider(settings.entityID, settings.returnURL, identityProvider, replayCache=replays, signingKey=signing,
                         decryptionKeys=decryption, encryptionPolicy=_encryptionPolicy(settings),
                         singleLogoutURL=settings.singleLogoutURL)


def _metadataKeys(settings: _SAMLKeys) -> dict[str, Any]:
  signing, decryption = _loadedKeys(settings)
  return {"signingCertificate": signing.certificate if signing else None,
          "encryptionCertificates": tuple(key.certificate for key in decryption),
          "encryptionPolicy": _encryptionPolicy(settings), "singleLogoutURL": settings.singleLogoutURL}


def samlMetadata(settings: SAMLSettings) -> bytes:
  """What the identity provider registers for this service: its entity ID, return and logout addresses, and keys."""
  return plainServiceProviderMetadata(settings.entityID, settings.returnURL, **_metadataKeys(settings))


def directory(settings: LDAPSettings):
  return Directory(settings.host, _context(settings), settings.baseDN, settings.serviceName,
                   secret(settings.servicePasswordVariable), port=settings.port, startTLS=settings.startTLS,
                   userAttribute=settings.userAttribute)


def fromOpenIDConnect(identity) -> ProvidedIdentity:
  sessionID = identity.claims.get("sid")
  if sessionID is not None and (not isinstance(sessionID, str) or not sessionID):
    raise ProviderFailure("the ID token's sid is not text")
  return ProvidedIdentity(subject=identity.subject, userName=identity.userName, displayName=identity.displayName,
                          email=identity.email if identity.emailVerified else None, groups=identity.groups,
                          sessionID=sessionID, signOutDetail={"idToken": identity.idToken})


def _samlSignOutDetail(identity) -> dict[str, str | None]:
  return {"nameID": identity.nameID, "nameIDFormat": identity.nameIDFormat, "sessionIndex": identity.sessionIndex}


def fromSAML(settings: SAMLSettings, identity) -> ProvidedIdentity:
  if identity.nameIDFormat == "urn:oasis:names:tc:SAML:2.0:nameid-format:transient":
    raise ProviderFailure("the provider names people by a transient NameID, which changes at every sign-in; "
                          "configure it to send a persistent one")
  return ProvidedIdentity(
    subject=identity.nameID, userName=_single(identity, settings.userNameAttribute) or identity.nameID,
    displayName=_single(identity, settings.displayNameAttribute), email=_single(identity, settings.emailAttribute),
    groups=tuple(identity.attributes.get(settings.groupsAttribute, ())) if settings.groupsAttribute else (),
    sessionID=identity.sessionIndex, signOutDetail=_samlSignOutDetail(identity),
  )


def fromDirectory(identity) -> ProvidedIdentity:
  return ProvidedIdentity(subject=foldedUserName(identity.userName), userName=identity.userName,
                          displayName=identity.displayName, email=identity.email, groups=identity.groups)


def _single(identity, attribute: str | None) -> str | None:
  if attribute is None:
    return None
  values = identity.attributes.get(attribute, ())
  if len(values) > 1:
    raise ProviderFailure(f"the provider sent {len(values)} values of {attribute}")
  return values[0] if values else None


def institution(settings: FederationSettings, entityID: str):
  """An institution offered here, its metadata fetched from the federation and checked."""
  if entityID not in settings.institutions:
    raise IdentityError(f"'{entityID}' is not an institution offered here")
  federation = _providers.get("federation", settings, lambda: Federation("the federation", settings.mdqURL, settings.signingCertificate,
                                                           Fetcher(_context(settings))))
  try:
    return federation.institution(entityID)
  except SAMLRefused as error:
    raise ProviderFailure(f"the institution {entityID} cannot be used: {error}") from None


def federationServiceProvider(settings: FederationSettings, chosen, replays: ReplayStore) -> ServiceProvider:
  return _keyedServiceProvider(settings, chosen.identityProvider, replays)


def fromFederation(settings: FederationSettings, chosen, identity) -> ProvidedIdentity:
  try:
    subject = scopedIdentifier(identity, chosen, subjectAttributeNames[settings.subjectAttribute])
  except SAMLRefused as error:
    raise ProviderFailure(str(error)) from None
  return ProvidedIdentity(
    subject=subject, userName=_single(identity, settings.userNameAttribute),
    displayName=_single(identity, settings.displayNameAttribute), email=_single(identity, settings.emailAttribute),
    groups=tuple(identity.attributes.get(settings.groupsAttribute, ())) if settings.groupsAttribute else (),
    sessionID=identity.sessionIndex, signOutDetail=_samlSignOutDetail(identity) | {"institution": chosen.entityID},
  )


def federationMetadata(settings: FederationSettings) -> bytes:
  """What the federation registers for this service: its entity ID, return address, names and contacts."""
  return serviceProviderMetadata(settings.entityID, settings.returnURL, {"en": "OpenFurrow"}, settings.informationURL,
                                 settings.privacyStatementURL, settings.organizationName, settings.technicalContact,
                                 settings.securityContact, **_metadataKeys(settings))


def casServer(settings: CASSettings) -> CASServer:
  return CASServer(settings.serverURL, settings.returnURL, Fetcher(_context(settings)))


def fromCAS(settings: CASSettings, identity) -> ProvidedIdentity:
  return ProvidedIdentity(
    subject=foldedUserName(identity.userName), userName=identity.userName,
    displayName=_single(identity, settings.displayNameAttribute), email=_single(identity, settings.emailAttribute),
    groups=identity.attributes.get(settings.groupsAttribute, ()) if settings.groupsAttribute else (),
    sessionID=identity.ticket,
  )
