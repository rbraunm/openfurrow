# SPDX-License-Identifier: Apache-2.0
"""The store Carnelian's SCIM service keeps a provider's users and groups in (decision 0040).

Each SCIM resource is kept whole as its document, and each is also what it means here: a
user is an account (user name, display name, primary e-mail, active), and a group of a
provider that mirrors groups is that provider's group, its members the accounts it holds,
directly or through its nested groups. Deleting a user deactivates its account rather than
removing it, so the audit log keeps naming it.
"""

from __future__ import annotations

import json

from carnelian.scim import SCIMRefused, matches, resourceTypes
from sqlalchemy import select
from sqlalchemy.orm import Session

from openfurrow.identity.model import IdentityError, normalizedUserName
from openfurrow.identity.providers import GroupPolicy, Provider
from openfurrow.store.database import AccountGroupRow, AccountRow, AuthTokenRow, GroupMemberRow, ProvisionedResourceRow
from openfurrow.store.identity import now
from openfurrow.store.providers import mirroredGroupName


def _userName(document: dict) -> str:
  try:
    return normalizedUserName(document["userName"])
  except IdentityError as error:
    raise SCIMRefused(400, str(error), "invalidValue") from None


def _displayName(document: dict, userName: str) -> str:
  name = document.get("name", {})
  joined = " ".join(part for part in (name.get("givenName"), name.get("familyName")) if part)
  return (document.get("displayName") or name.get("formatted") or joined or userName).strip()


def _email(document: dict) -> str | None:
  emails = document.get("emails", [])
  primary = [email["value"] for email in emails if email.get("primary") is True and "value" in email]
  others = [email["value"] for email in emails if "value" in email]
  return (primary or others or [None])[0]


class ProvisioningStore:
  """Carnelian's Store, for one provider, inside the caller's transaction."""

  def __init__(self, session: Session, provider: Provider):
    self.session, self.provider = session, provider

  def _row(self, resourceType: str, resourceID: str) -> ProvisionedResourceRow | None:
    return self.session.get(ProvisionedResourceRow, (self.provider.name, resourceType, resourceID))

  def _rows(self, resourceType: str) -> list[ProvisionedResourceRow]:
    return self.session.execute(select(ProvisionedResourceRow).where(
      ProvisionedResourceRow.providerName == self.provider.name,
      ProvisionedResourceRow.resourceType == resourceType)).scalars().all()

  @property
  def _mirrors(self) -> bool:
    return self.provider.settings.groups is GroupPolicy.mirror

  def create(self, resourceType: str, resource: dict) -> None:
    row = ProvisionedResourceRow(providerName=self.provider.name, resourceType=resourceType, resourceID=resource["id"],
                                 accountID=None, groupID=None, documentJSON=json.dumps(resource))
    if resourceType == "User":
      userName = _userName(resource)
      if self.session.execute(select(AccountRow).where(AccountRow.userName == userName)).scalar_one_or_none():
        raise SCIMRefused(409, f"an account '{userName}' already exists here", "uniqueness")
      account = AccountRow(userName=userName, displayName=_displayName(resource, userName), email=_email(resource),
                           locale=None, active=resource.get("active", True), passwordHash=None, createdAt=now())
      self.session.add(account)
      self.session.flush()
      row.accountID = account.accountID
    elif self._mirrors:
      name = mirroredGroupName(self.provider.name, resource["displayName"])
      if self.session.execute(select(AccountGroupRow).where(AccountGroupRow.name == name)).scalar_one_or_none():
        raise SCIMRefused(409, f"a group '{name}' already exists here", "uniqueness")
      group = AccountGroupRow(name=name, providerName=self.provider.name)
      self.session.add(group)
      self.session.flush()
      row.groupID = group.groupID
    self.session.add(row)
    self.session.flush()
    self._syncMembership()

  def get(self, resourceType: str, resourceID: str) -> dict | None:
    row = self._row(resourceType, resourceID)
    return None if row is None else json.loads(row.documentJSON)

  def replace(self, resourceType: str, resource: dict) -> None:
    row = self._row(resourceType, resource["id"])
    row.documentJSON = json.dumps(resource)
    if row.accountID is not None:
      account = self.session.get(AccountRow, row.accountID)
      userName = _userName(resource)
      if userName != account.userName:
        if self.session.execute(select(AccountRow).where(AccountRow.userName == userName)).scalar_one_or_none():
          raise SCIMRefused(409, f"an account '{userName}' already exists here", "uniqueness")
        account.userName = userName
      account.displayName = _displayName(resource, userName)
      account.email = _email(resource)
      self._setActive(account, resource.get("active", True))
    if row.groupID is not None:
      group = self.session.get(AccountGroupRow, row.groupID)
      name = mirroredGroupName(self.provider.name, resource["displayName"])
      if name != group.name:
        if self.session.execute(select(AccountGroupRow).where(AccountGroupRow.name == name)).scalar_one_or_none():
          raise SCIMRefused(409, f"a group '{name}' already exists here", "uniqueness")
        group.name = name
    self.session.flush()
    self._syncMembership()

  def delete(self, resourceType: str, resourceID: str) -> None:
    row = self._row(resourceType, resourceID)
    if row.accountID is not None:
      self._setActive(self.session.get(AccountRow, row.accountID), False)
    if row.groupID is not None:
      self.session.delete(self.session.get(AccountGroupRow, row.groupID))
    self.session.delete(row)
    self.session.flush()
    self._syncMembership()

  def search(self, resourceType: str, query) -> list[dict]:
    documents = [json.loads(row.documentJSON) for row in self._rows(resourceType)]
    return [document for document in documents
            if query is None or matches(resourceTypes[resourceType], query, document)]

  def _setActive(self, account: AccountRow, active: bool) -> None:
    account.active = active
    if not active:
      self.session.execute(AuthTokenRow.__table__.delete().where(AuthTokenRow.accountID == account.accountID))

  def _syncMembership(self) -> None:
    """Every mirrored group of this provider holds exactly the accounts its SCIM group reaches."""
    if not self._mirrors:
      return
    groups = {row.resourceID: row for row in self._rows("Group")}
    accounts = {row.resourceID: row.accountID for row in self._rows("User")}

    def reached(resourceID: str, seen: frozenset) -> set[int]:
      found = set()
      for member in json.loads(groups[resourceID].documentJSON).get("members", []):
        if member["value"] in accounts:
          found.add(accounts[member["value"]])
        elif member["value"] in groups and member["value"] not in seen:
          found |= reached(member["value"], seen | {member["value"]})
      return found

    for resourceID, row in groups.items():
      wanted = reached(resourceID, frozenset({resourceID}))
      present = set(self.session.execute(select(GroupMemberRow.accountID).where(
        GroupMemberRow.groupID == row.groupID)).scalars().all())
      for accountID in wanted - present:
        self.session.add(GroupMemberRow(groupID=row.groupID, accountID=accountID))
      for accountID in present - wanted:
        self.session.delete(self.session.get(GroupMemberRow, (row.groupID, accountID)))
    self.session.flush()
