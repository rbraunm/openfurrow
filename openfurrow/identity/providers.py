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
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit

from carnelian.fetching import Fetcher, HTTPFailure, secureContext
from carnelian.ldap import Directory
from carnelian.oidc import RelyingParty, SignInRefused, discover
from carnelian.saml import SAMLRefused, ServiceProvider, identityProviderFromMetadata
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from openfurrow.identity.model import IdentityError

providerNamePattern = re.compile(r"^[a-z][a-z0-9-]{1,31}$")


class ProviderKind(str, Enum):
  openIDConnect = "openIDConnect"
  saml = "saml"
  ldap = "ldap"
  scim = "scim"


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


class _SignInSettings(BaseModel):
  model_config = ConfigDict(extra="forbid")

  newAccounts: NewAccounts = NewAccounts.refuse
  groups: GroupPolicy = GroupPolicy.ignore
  certificateAuthority: str | None = None


class OpenIDConnectSettings(_SignInSettings):
  issuer: str
  clientID: str
  clientSecretVariable: str
  returnURL: str

  @field_validator("issuer", "returnURL")
  @classmethod
  def secure(cls, value: str) -> str:
    return _secureURL(value)


class SAMLSettings(_SignInSettings):
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
}


class Provider(BaseModel):
  model_config = ConfigDict(extra="forbid")

  name: str
  kind: ProviderKind
  enabled: bool = True
  settings: OpenIDConnectSettings | SAMLSettings | LDAPSettings | SCIMSettings

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
  """What a provider vouches for: its stable subject for the person, and what it says about them."""

  subject: str
  userName: str | None
  displayName: str | None
  email: str | None
  groups: tuple[str, ...]


class ProviderFailure(IdentityError):
  """A provider's answer refused by Carnelian, or a provider that cannot be reached."""


# ---- Carnelian's side --------------------------------------------------------

def _context(settings: _SignInSettings):
  return secureContext(settings.certificateAuthority)


def relyingParty(settings: OpenIDConnectSettings):
  fetcher = Fetcher(_context(settings))
  try:
    provider = discover(settings.issuer, fetcher)
  except (HTTPFailure, SignInRefused) as error:
    raise ProviderFailure(f"the provider at {settings.issuer} cannot be used: {error}") from None
  return RelyingParty(provider, settings.clientID, secret(settings.clientSecretVariable), settings.returnURL, fetcher)


def serviceProvider(settings: SAMLSettings):
  try:
    metadata = Fetcher(_context(settings)).getBytes(settings.metadataURL, "application/samlmetadata+xml, application/xml;q=0.9")
    identityProvider = identityProviderFromMetadata(metadata, settings.identityProviderEntityID)
  except (HTTPFailure, SAMLRefused) as error:
    raise ProviderFailure(f"the metadata at {settings.metadataURL} cannot be used: {error}") from None
  return ServiceProvider(settings.entityID, settings.returnURL, identityProvider)


def directory(settings: LDAPSettings):
  return Directory(settings.host, _context(settings), settings.baseDN, settings.serviceName,
                   secret(settings.servicePasswordVariable), port=settings.port, startTLS=settings.startTLS,
                   userAttribute=settings.userAttribute)


def fromOpenIDConnect(identity) -> ProvidedIdentity:
  return ProvidedIdentity(subject=identity.subject, userName=identity.userName, displayName=identity.displayName,
                          email=identity.email, groups=identity.groups)


def fromSAML(settings: SAMLSettings, identity) -> ProvidedIdentity:
  if identity.nameIDFormat == "urn:oasis:names:tc:SAML:2.0:nameid-format:transient":
    raise ProviderFailure("the provider names people by a transient NameID, which changes at every sign-in; "
                          "configure it to send a persistent one")

  def one(attribute: str | None) -> str | None:
    if attribute is None:
      return None
    values = identity.attributes.get(attribute, ())
    if len(values) > 1:
      raise ProviderFailure(f"the provider sent {len(values)} values of {attribute}")
    return values[0] if values else None

  return ProvidedIdentity(
    subject=identity.nameID, userName=one(settings.userNameAttribute) or identity.nameID,
    displayName=one(settings.displayNameAttribute), email=one(settings.emailAttribute),
    groups=tuple(identity.attributes.get(settings.groupsAttribute, ())) if settings.groupsAttribute else (),
  )


def fromDirectory(identity) -> ProvidedIdentity:
  return ProvidedIdentity(subject=identity.userName.lower(), userName=identity.userName,
                          displayName=identity.displayName, email=identity.email, groups=identity.groups)
