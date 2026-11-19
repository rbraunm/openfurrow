# SPDX-License-Identifier: Apache-2.0
"""Identity providers in the store: their configuration, the links to accounts, the sign-ins
waiting for a provider's answer, the provider sessions behind session tokens, the message
identifiers already used, and the groups a provider mirrors (decision 0040)."""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass

from carnelian.saml import SAMLRefused
from sqlalchemy import delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from openfurrow.identity.model import Account, IdentityError, normalizedUserName
from openfurrow.identity.providers import GroupPolicy, NewAccounts, ProvidedIdentity, Provider, ProviderKind
from openfurrow.store.database import (AccountGroupRow, AccountRow, AuthTokenRow, ExternalIdentityRow, GroupMemberRow,
                                       IdentityProviderRow, PendingSignInRow, ProviderSessionRow, ReplayClaimRow)
from openfurrow.store.identity import _account, _hashed as _tokenHash, accountRow, now

pendingMinutes = 10


def _hashed(value: str) -> str:
  return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _provider(row: IdentityProviderRow) -> Provider:
  return Provider.of(row.providerName, row.kind, json.loads(row.settingsJSON), row.enabled)


def providerRow(session: Session, name: str) -> IdentityProviderRow:
  row = session.get(IdentityProviderRow, name)
  if row is None:
    raise IdentityError(f"no identity provider '{name}'")
  return row


def provider(session: Session, name: str) -> Provider:
  return _provider(providerRow(session, name))


def addProvider(session: Session, configured: Provider) -> None:
  if session.get(IdentityProviderRow, configured.name) is not None:
    raise IdentityError(f"identity provider '{configured.name}' already exists")
  session.add(IdentityProviderRow(providerName=configured.name, kind=configured.kind.value,
                                  settingsJSON=configured.settings.model_dump_json(), enabled=configured.enabled,
                                  tokenHash=None))
  session.flush()


def listProviders(session: Session) -> list[Provider]:
  rows = session.execute(select(IdentityProviderRow).order_by(IdentityProviderRow.providerName)).scalars().all()
  return [_provider(row) for row in rows]


def setProviderEnabled(session: Session, name: str, enabled: bool) -> None:
  providerRow(session, name).enabled = enabled
  session.flush()


def issueProvisioningToken(session: Session, name: str) -> str:
  row = providerRow(session, name)
  if row.kind != ProviderKind.scim.value:
    raise IdentityError(f"'{name}' is a {row.kind} provider; only a SCIM provider takes a provisioning token")
  token = secrets.token_urlsafe(32)
  row.tokenHash = _hashed(token)
  session.flush()
  return token


def provisioningTokenMatches(session: Session, name: str, token: str) -> bool:
  row = providerRow(session, name)
  return row.tokenHash is not None and hmac.compare_digest(row.tokenHash, _hashed(token))


# ---- sign-ins waiting for a provider ------------------------------------------

def startPending(session: Session, name: str, state: dict) -> str:
  """Keep a sign-in's state until the provider answers; the key returned goes to the browser's cookie. Starting one
  sweeps those that expired unanswered: anyone can start a sign-in without signing in, so what they leave behind
  is not kept for any retention rule to decide (decision 0044)."""
  session.execute(PendingSignInRow.__table__.delete().where(PendingSignInRow.expiresAt < now()))
  key = secrets.token_urlsafe(32)
  session.add(PendingSignInRow(keyHash=_hashed(key), providerName=name, stateJSON=json.dumps(state),
                               expiresAt=now() + datetime.timedelta(minutes=pendingMinutes)))
  session.flush()
  return key


def takePending(session: Session, key: str) -> tuple[str, dict]:
  """The provider and state of a waiting sign-in, which is then gone: an answer is used once."""
  row = session.get(PendingSignInRow, _hashed(key))
  if row is None:
    raise IdentityError("this sign-in is not waiting for an answer; start again")
  session.delete(row)
  session.flush()
  if row.expiresAt < now():
    raise IdentityError("the sign-in took too long; start again")
  return row.providerName, json.loads(row.stateJSON)


# ---- provider sessions ------------------------------------------------------------

@dataclass(frozen=True)
class ProviderSession:
  providerName: str
  subject: str
  sessionID: str | None
  detail: dict


def recordProviderSession(session: Session, token: str, providerName: str, identity: ProvidedIdentity) -> None:
  session.add(ProviderSessionRow(tokenHash=_tokenHash(token), providerName=providerName, subject=identity.subject,
                                 sessionID=identity.sessionID, detailJSON=json.dumps(identity.signOutDetail)))
  session.flush()


def providerSessionOf(session: Session, token: str) -> ProviderSession | None:
  row = session.get(ProviderSessionRow, _tokenHash(token))
  if row is None:
    return None
  return ProviderSession(row.providerName, row.subject, row.sessionID, json.loads(row.detailJSON))


def endProviderSessions(session: Session, providerName: str, subject: str | None = None,
                        sessionIDs: tuple[str, ...] | None = None, detail: dict[str, str] | None = None) -> int:
  """End the sessions here that came from a provider's sessions: those of a subject, those with given session IDs,
  those whose sign-out detail holds every given value (a federation's institution and NameID), or a combination; how
  many ended. The tokens themselves are deleted, and their provider sessions with them."""
  if subject is None and not sessionIDs and not detail:
    raise IdentityError("ending a provider's sessions needs a subject, session IDs or sign-out detail")
  query = select(ProviderSessionRow.tokenHash, ProviderSessionRow.detailJSON).where(
    ProviderSessionRow.providerName == providerName)
  if subject is not None:
    query = query.where(ProviderSessionRow.subject == subject)
  if sessionIDs:
    query = query.where(ProviderSessionRow.sessionID.in_(sessionIDs))
  hashes = [tokenHash for tokenHash, detailJSON in session.execute(query).all()
            if not detail or all(json.loads(detailJSON).get(key) == value for key, value in detail.items())]
  if hashes:
    session.execute(delete(AuthTokenRow).where(AuthTokenRow.tokenHash.in_(hashes)))
    session.flush()
  return len(hashes)


# ---- message identifiers used once ---------------------------------------------------

def _stored(instant: float) -> datetime.datetime:
  return datetime.datetime.fromtimestamp(instant, datetime.UTC).replace(tzinfo=None)


def claimOnce(engine: Engine, scope: str, identifier: str, until: float, at: float) -> bool:
  """Claim an identifier in its scope until `until` (seconds since the epoch), in a transaction of its own so that
  nothing after it can undo it: True for the one claim that is new, False while an earlier claim holds. Every claim
  that has expired goes with it, whoever made it: an expired claim protects nothing, and claims are made by whoever
  sends a message, so they must not gather."""
  with Session(engine) as session:
    session.execute(delete(ReplayClaimRow).where(ReplayClaimRow.expiresAt <= _stored(at)))
    session.add(ReplayClaimRow(scope=scope, identifier=identifier, expiresAt=_stored(until)))
    try:
      session.commit()
    except IntegrityError:
      session.rollback()
      return False
  return True


class StoredReplays:
  """Carnelian's ReplayStore over the store, so every process serving one database refuses a SAML message used once."""

  def __init__(self, engine: Engine) -> None:
    self._engine = engine

  def admit(self, issuer: str, assertionID: str, until: float, now: float) -> None:
    if not claimOnce(self._engine, json.dumps(["saml", issuer]), assertionID, until, now):
      raise SAMLRefused(f"message {assertionID!r} from {issuer} was already used")


# ---- what a provider vouches for ------------------------------------------------

def completeSignIn(session: Session, configured: Provider, identity: ProvidedIdentity) -> Account:
  """The account a provider's identity belongs to, linked or made as the provider's settings say."""
  link = session.get(ExternalIdentityRow, (configured.name, identity.subject))
  if link is not None:
    account = session.get(AccountRow, link.accountID)
  else:
    account = _newLink(session, configured, identity)
  if not account.active:
    raise IdentityError("this account is deactivated")
  if configured.settings.groups is GroupPolicy.mirror:
    mirrorMembership(session, configured.name, account.accountID, identity.groups)
  return _account(account)


def _newLink(session: Session, configured: Provider, identity: ProvidedIdentity) -> AccountRow:
  policy = configured.settings.newAccounts
  if policy is NewAccounts.refuse:
    raise IdentityError(f"no account here is linked to this {configured.name} identity; ask an administrator")
  if not identity.userName:
    raise IdentityError(f"{configured.name} sent no user name, so no account can be found or made")
  userName = normalizedUserName(identity.userName)
  existing = session.execute(select(AccountRow).where(AccountRow.userName == userName)).scalar_one_or_none()
  if policy is NewAccounts.linkByUserName:
    if existing is None:
      raise IdentityError(f"no account '{userName}' here to link this {configured.name} identity to")
    account = existing
  else:
    if existing is not None:
      raise IdentityError(f"an account '{userName}' exists but is not linked to {configured.name}; "
                          "an administrator can link it")
    account = AccountRow(userName=userName, displayName=(identity.displayName or userName).strip(), email=identity.email,
                         locale=None, active=True, passwordHash=None, createdAt=now())
    session.add(account)
    session.flush()
  linked = session.execute(select(ExternalIdentityRow).where(
    ExternalIdentityRow.providerName == configured.name, ExternalIdentityRow.accountID == account.accountID)).first()
  if linked is not None:
    raise IdentityError(f"account '{userName}' is already linked to another {configured.name} identity")
  session.add(ExternalIdentityRow(providerName=configured.name, subject=identity.subject, accountID=account.accountID))
  session.flush()
  return account


def linkIdentity(session: Session, name: str, subject: str, userName: str) -> None:
  providerRow(session, name)
  account = accountRow(session, userName)
  if session.get(ExternalIdentityRow, (name, subject)) is not None:
    raise IdentityError(f"that {name} identity is already linked")
  session.add(ExternalIdentityRow(providerName=name, subject=subject, accountID=account.accountID))
  session.flush()


@dataclass(frozen=True)
class LinkedIdentity:
  """A provider's identity an account is linked to: the provider, and its own subject for the person."""

  providerName: str
  subject: str


def identitiesOf(session: Session, userName: str) -> list[LinkedIdentity]:
  account = accountRow(session, userName)
  rows = session.execute(select(ExternalIdentityRow).where(ExternalIdentityRow.accountID == account.accountID)
                         .order_by(ExternalIdentityRow.providerName, ExternalIdentityRow.subject)).scalars().all()
  return [LinkedIdentity(row.providerName, row.subject) for row in rows]


def mirroredGroupName(providerName: str, groupName: str) -> str:
  return f"{providerName}/{groupName.strip().strip('/')}"


def mirroredGroup(session: Session, providerName: str, groupName: str) -> AccountGroupRow:
  name = mirroredGroupName(providerName, groupName)
  row = session.execute(select(AccountGroupRow).where(AccountGroupRow.name == name)).scalar_one_or_none()
  if row is None:
    row = AccountGroupRow(name=name, providerName=providerName)
    session.add(row)
    session.flush()
  elif row.providerName != providerName:
    raise IdentityError(f"group '{name}' exists and is not {providerName}'s")
  return row


def mirrorMembership(session: Session, providerName: str, accountID: int, groupNames: tuple[str, ...]) -> None:
  """The account is in exactly the provider's groups it named, and no other group of that provider."""
  wanted = {mirroredGroup(session, providerName, name).groupID for name in groupNames}
  owned = session.execute(select(AccountGroupRow.groupID).where(AccountGroupRow.providerName == providerName)).scalars().all()
  for groupID in owned:
    member = session.get(GroupMemberRow, (groupID, accountID))
    if groupID in wanted and member is None:
      session.add(GroupMemberRow(groupID=groupID, accountID=accountID))
    elif groupID not in wanted and member is not None:
      session.delete(member)
  session.flush()
