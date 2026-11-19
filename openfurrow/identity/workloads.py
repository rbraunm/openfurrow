# SPDX-License-Identifier: Apache-2.0
"""Trusted workloads (decision 0042): CI and cloud jobs that prove what they are with their platform's token.

A workload rule names an issuer and the claims a token must carry, each with the exact value required. A job that
presents its platform's OpenID Connect token as its bearer token acts as the one enabled rule that accepts it, with the
roles given to that rule. The checks of a token are Carnelian's: the issuer's signature with the keys its discovery
document names, the times, the server's audience and every required claim. This module checks a rule when it is made,
keeps Carnelian's verifiers, and says which rule accepts a token and which run the token came from.
"""

from __future__ import annotations

import datetime
import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from carnelian.fetching import Fetcher, secureContext
from carnelian.jose import JOSEError, base64urlDecode, readJSON
from carnelian.workload import (WorkloadIdentity, WorkloadIssuer, WorkloadRefused, WorkloadVerifier, discoverIssuer,
                                githubActions)
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from openfurrow.identity.model import IdentityError
from openfurrow.identity.providers import providerNamePattern

gitlab = "https://gitlab.com"
namedIssuers = {"githubActions": githubActions, "gitlab": gitlab}
checkedForEveryToken = ("iss", "aud", "exp", "iat", "nbf")
discoveryRetrySeconds = 60


class WorkloadTokenRefused(IdentityError):
  """A workload token that no rule accepts, or more than one, with why."""


@dataclass(frozen=True)
class Platform:
  """What is known of a named issuer's tokens: the claim that stays with a job's owner, the claim that only names that
  owner, and the claims that tell which run a token came from."""

  ownerClaim: str
  ownerName: str
  runClaims: tuple[str, ...]


platforms = {
  githubActions: Platform("repository_id", "repository",
                          ("repository", "ref", "workflow_ref", "run_id", "run_attempt", "sha")),
  gitlab: Platform("project_id", "project_path", ("project_path", "ref", "pipeline_id", "job_id", "sha")),
}


def _isIssuerAddress(issuer: str) -> bool:
  try:
    parts = urlsplit(issuer)
    return (parts.scheme == "https" and bool(parts.hostname) and parts.port != 0 and parts.username is None
            and not parts.query and not parts.fragment and "?" not in issuer and "#" not in issuer)
  except ValueError:
    return False


class WorkloadRule(BaseModel):
  model_config = ConfigDict(extra="forbid")

  name: str
  issuer: str
  claims: dict[str, str]
  enabled: bool = True
  certificateAuthority: str | None = None
  createdAt: datetime.datetime

  @field_validator("name")
  @classmethod
  def nameIsAName(cls, name: str) -> str:
    if not providerNamePattern.match(name):
      raise ValueError(f"'{name}' is not a workload rule name: a lower-case letter, then 1 to 31 letters, digits or '-'")
    return name

  @field_validator("issuer", mode="before")
  @classmethod
  def issuerByName(cls, issuer: Any) -> Any:
    return namedIssuers.get(issuer, issuer) if isinstance(issuer, str) else issuer

  @field_validator("issuer")
  @classmethod
  def issuerIsAnAddress(cls, issuer: str) -> str:
    if not _isIssuerAddress(issuer):
      raise ValueError(f"'{issuer}' is not an issuer: {' or '.join(namedIssuers)}, or the https address of an OpenID "
                       "Connect issuer exactly as its tokens name it")
    return issuer

  @field_validator("claims", mode="before")
  @classmethod
  def claimsAreExactText(cls, claims: Any) -> Any:
    if not isinstance(claims, dict) or not claims:
      raise ValueError("a rule requires at least one claim; without one, a token from any job at the issuer would pass")
    for name, value in claims.items():
      if not isinstance(name, str) or not name or not isinstance(value, str) or not value:
        raise ValueError(f"the claim {name!r} cannot require {value!r}: a claim and its required value are text, "
                         "compared exactly with what the token carries")
      if name in checkedForEveryToken:
        raise ValueError(f"'{name}' is checked for every token; it is not a claim a rule requires")
    return claims

  @model_validator(mode="after")
  def ownerStaysTheOwner(self) -> WorkloadRule:
    platform = platforms.get(self.issuer)
    if platform is not None and platform.ownerClaim not in self.claims:
      raise ValueError(f"a rule for {self.issuer} requires the claim {platform.ownerClaim}, the number that stays with "
                       f"its owner: {platform.ownerName} is a name, and a name given up can be registered again by "
                       "someone else")
    return self


def claimsGiven(pairs: list[str]) -> dict[str, str]:
  """The claims a rule requires, from the way a person writes them: each once, as CLAIM=VALUE."""
  claims: dict[str, str] = {}
  for pair in pairs:
    name, separator, value = pair.partition("=")
    if not separator or name in claims:
      raise IdentityError(f"'{pair}' is not a required claim: write each claim once, as CLAIM=VALUE")
    claims[name] = value
  return claims


_tokenForm = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


def isWorkloadToken(token: str) -> bool:
  """Whether a bearer token has the form of a JSON Web Token, three base64url parts; an API token has no dot."""
  return _tokenForm.fullmatch(token) is not None


def claimedIssuer(token: str) -> str:
  """The issuer a token names, read before any check of it and used only to choose the rules whose verifiers check it."""
  if not isWorkloadToken(token):
    raise WorkloadTokenRefused("a workload token is a JSON Web Token: three base64url parts")
  try:
    claims = readJSON(base64urlDecode(token.split(".")[1]), "the token's claims")
  except JOSEError as error:
    raise WorkloadTokenRefused(f"the token is refused: {error}") from None
  issuer = claims.get("iss") if isinstance(claims, dict) else None
  if not isinstance(issuer, str) or not issuer:
    raise WorkloadTokenRefused("the token names no issuer")
  return issuer


class Verifiers:
  """Carnelian's verifiers, one for each issuer, audience and set of required claims, kept for the life of the process:
  a verifier holds its issuer's keys and paces its own fetches of them. An issuer whose discovery document cannot be
  used is asked again only after discoveryRetrySeconds and its tokens are refused meanwhile, so an issuer that is
  down does not make every request carrying one of its tokens wait for it."""

  def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
    self._clock = clock
    self._lock = threading.Lock()
    self._issuers: dict[tuple[str, str | None], tuple[Fetcher, WorkloadIssuer]] = {}
    self._failures: dict[tuple[str, str | None], tuple[float, str]] = {}
    self._verifiers: dict[tuple[str, str | None, str, tuple[tuple[str, str], ...]], WorkloadVerifier] = {}

  def get(self, issuer: str, certificateAuthority: str | None, audience: str, claims: dict[str, str]) -> WorkloadVerifier:
    key = (issuer, certificateAuthority, audience, tuple(sorted(claims.items())))
    found = self._verifiers.get(key)
    if found is not None:
      return found
    with self._lock:
      if key not in self._verifiers:
        fetcher, discovered = self._discovered(issuer, certificateAuthority)
        self._verifiers[key] = WorkloadVerifier(discovered, audience, claims, fetcher)
      return self._verifiers[key]

  def _discovered(self, issuer: str, certificateAuthority: str | None) -> tuple[Fetcher, WorkloadIssuer]:
    key = (issuer, certificateAuthority)
    if key not in self._issuers:
      failedAt, why = self._failures.get(key, (float("-inf"), ""))
      wait = failedAt + discoveryRetrySeconds - self._clock()
      if wait > 0:
        raise WorkloadTokenRefused(f"{why}; it is asked again in {wait:.0f} seconds")
      try:
        self._issuers[key] = _discover(issuer, certificateAuthority)
      except WorkloadTokenRefused as refusal:
        self._failures[key] = self._clock(), str(refusal)
        raise
    return self._issuers[key]


def _discover(issuer: str, certificateAuthority: str | None) -> tuple[Fetcher, WorkloadIssuer]:
  try:
    fetcher = Fetcher(secureContext(certificateAuthority))
  except OSError as error:
    # The file's path is the server's own, so whoever sent the token is not told it.
    raise WorkloadTokenRefused(f"the issuer {issuer} cannot be used: the certificate authority file of its workload "
                               f"rule cannot be read ({type(error).__name__})") from None
  try:
    return fetcher, discoverIssuer(issuer, fetcher)
  except WorkloadRefused as error:
    raise WorkloadTokenRefused(f"the issuer {issuer} cannot be used: {error}") from None


_verifiers = Verifiers()
# No token carries this claim, so a verifier requiring it refuses every token. What it refuses a token for before it
# comes to the claim is what is wrong with the token itself, and says nothing of what any rule requires.
_claimNoTokenCarries = "openfurrow-no-such-claim"
_valueNoTokenCarries = secrets.token_urlsafe(16)


def _faultOf(token: str, rule: WorkloadRule, audience: str, verifiers: Verifiers) -> str | None:
  """What is wrong with a token whatever rule it meets, as a verifier of `rule`'s issuer finds it; None for a token
  that is its issuer's, in time and for this audience."""
  verifier = verifiers.get(rule.issuer, rule.certificateAuthority, audience, {_claimNoTokenCarries: _valueNoTokenCarries})
  try:
    verifier.verify(token)
  except WorkloadRefused as refusal:
    return None if _valueNoTokenCarries in str(refusal) else str(refusal)
  raise RuntimeError(f"a token carries the claim {_claimNoTokenCarries} with this process's own value")


def acceptingRule(token: str, candidates: list[WorkloadRule], audience: str,
                  verifiers: Verifiers = _verifiers) -> tuple[WorkloadRule, WorkloadIdentity]:
  """The one rule among `candidates`, the enabled rules of the issuer the token names, that accepts the token, and
  what the token says. A refusal tells what is wrong with the token, never what a rule requires."""
  if not candidates:
    raise WorkloadTokenRefused("the token's issuer is not one whose workloads are trusted here")
  accepted = []
  for rule in candidates:
    try:
      accepted.append((rule, verifiers.get(rule.issuer, rule.certificateAuthority, audience, rule.claims).verify(token)))
    except WorkloadRefused:
      continue
  if len(accepted) > 1:
    names = ", ".join(f"'{rule.name}'" for rule, _ in accepted)
    raise WorkloadTokenRefused(f"the token is ambiguous: the workload rules {names} all accept it, and a token must "
                               "match exactly one")
  if not accepted:
    raise WorkloadTokenRefused(_faultOf(token, candidates[0], audience, verifiers)
                               or "the token is its issuer's, but its claims match no workload trusted here")
  return accepted[0]


def runOf(identity: WorkloadIdentity) -> dict[str, Any]:
  """The run a token came from, as its platform tells it: the issuer and subject, and the run's claims where the
  issuer is one whose claims are known."""
  platform = platforms.get(identity.issuer)
  told = ("iss", "sub") + (platform.runClaims if platform is not None else ())
  return {name: identity.claims[name] for name in told if name in identity.claims}
