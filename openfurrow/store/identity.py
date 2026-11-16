# SPDX-License-Identifier: Apache-2.0
"""Accounts, groups, roles, assignments and tokens in the store (decisions 0036, 0037)."""

from __future__ import annotations

import datetime
import hashlib
import json
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from openfurrow.identity.model import (
  Account,
  Actor,
  ActorKind,
  Group,
  IdentityError,
  Permission,
  RoleAssignment,
  RoleDefinition,
  builtInRoles,
  normalizedUserName,
)
from openfurrow.identity.passwords import hashPassword, passwordMatches
from openfurrow.store.database import (
  AccountGroupRow,
  AccountRow,
  AuthTokenRow,
  CustomRoleRow,
  GroupMemberRow,
  RoleAssignmentRow,
)
from openfurrow.store.hierarchy import scopeChain, storedScope, writtenScope

wrongSignIn = "the user name or the password is wrong"


def now() -> datetime.datetime:
  return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def _account(row: AccountRow) -> Account:
  return Account(accountID=row.accountID, userName=row.userName, displayName=row.displayName, email=row.email,
                 locale=row.locale, active=row.active)


def accountRow(session: Session, userName: str) -> AccountRow:
  row = session.execute(select(AccountRow).where(AccountRow.userName == normalizedUserName(userName))).scalar_one_or_none()
  if row is None:
    raise IdentityError(f"no account '{userName}'")
  return row


def createAccount(session: Session, userName: str, displayName: str, email: str | None, password: str | None) -> Account:
  name = normalizedUserName(userName)
  if not displayName.strip():
    raise IdentityError("an account needs a display name")
  if session.execute(select(AccountRow).where(AccountRow.userName == name)).scalar_one_or_none() is not None:
    raise IdentityError(f"account '{name}' already exists")
  row = AccountRow(userName=name, displayName=displayName.strip(), email=email, locale=None, active=True,
                   passwordHash=None if password is None else hashPassword(password), createdAt=now())
  session.add(row)
  session.flush()
  return _account(row)


def listAccounts(session: Session) -> list[Account]:
  return [_account(row) for row in session.execute(select(AccountRow).order_by(AccountRow.userName)).scalars().all()]


def setPassword(session: Session, userName: str, password: str) -> None:
  accountRow(session, userName).passwordHash = hashPassword(password)
  session.flush()


def setActive(session: Session, userName: str, active: bool) -> None:
  row = accountRow(session, userName)
  row.active = active
  if not active:
    session.execute(AuthTokenRow.__table__.delete().where(AuthTokenRow.accountID == row.accountID))
  session.flush()


def setLocale(session: Session, userName: str, locale: str | None) -> None:
  accountRow(session, userName).locale = locale
  session.flush()


def signIn(session: Session, userName: str, password: str) -> Account:
  """The account a user name and password belong to; one message for every refusal, so names are not revealed."""
  try:
    row = accountRow(session, userName)
  except IdentityError:
    raise IdentityError(wrongSignIn) from None
  if row.passwordHash is None or not row.active or not passwordMatches(password, row.passwordHash):
    raise IdentityError(wrongSignIn)
  return _account(row)


def createGroup(session: Session, name: str) -> Group:
  if not name.strip():
    raise IdentityError("a group needs a name")
  if session.execute(select(AccountGroupRow).where(AccountGroupRow.name == name.strip())).scalar_one_or_none():
    raise IdentityError(f"group '{name}' already exists")
  row = AccountGroupRow(name=name.strip())
  session.add(row)
  session.flush()
  return Group(groupID=row.groupID, name=row.name, members=[])


def groupRow(session: Session, name: str) -> AccountGroupRow:
  row = session.execute(select(AccountGroupRow).where(AccountGroupRow.name == name)).scalar_one_or_none()
  if row is None:
    raise IdentityError(f"no group '{name}'")
  return row


def setMembership(session: Session, groupName: str, userName: str, member: bool) -> None:
  group, account = groupRow(session, groupName), accountRow(session, userName)
  existing = session.get(GroupMemberRow, (group.groupID, account.accountID))
  if member and existing is None:
    session.add(GroupMemberRow(groupID=group.groupID, accountID=account.accountID))
  elif not member and existing is not None:
    session.delete(existing)
  session.flush()


def listGroups(session: Session) -> list[Group]:
  groups = []
  for row in session.execute(select(AccountGroupRow).order_by(AccountGroupRow.name)).scalars().all():
    members = session.execute(
      select(AccountRow.userName).join(GroupMemberRow, GroupMemberRow.accountID == AccountRow.accountID)
      .where(GroupMemberRow.groupID == row.groupID).order_by(AccountRow.userName)
    ).scalars().all()
    groups.append(Group(groupID=row.groupID, name=row.name, members=list(members)))
  return groups


def defineRole(session: Session, role: RoleDefinition) -> None:
  if role.roleCode in builtInRoles:
    raise IdentityError(f"'{role.roleCode}' is a built-in role")
  if not role.name:
    raise IdentityError(f"role '{role.roleCode}' needs a name")
  text = json.dumps(sorted(permission.value for permission in role.permissions))
  row = session.get(CustomRoleRow, role.roleCode)
  if row is None:
    session.add(CustomRoleRow(roleCode=role.roleCode, name=role.name, permissionsJSON=text))
  else:
    row.name, row.permissionsJSON = role.name, text
  session.flush()


def roles(session: Session) -> dict[str, RoleDefinition]:
  defined = dict(builtInRoles)
  for row in session.execute(select(CustomRoleRow)).scalars().all():
    defined[row.roleCode] = RoleDefinition(
      roleCode=row.roleCode, name=row.name, permissions=frozenset(Permission(p) for p in json.loads(row.permissionsJSON)),
    )
  return defined


def deleteRole(session: Session, roleCode: str) -> None:
  row = session.get(CustomRoleRow, roleCode)
  if row is None:
    raise IdentityError(f"no custom role '{roleCode}'")
  if session.execute(select(RoleAssignmentRow).where(RoleAssignmentRow.roleCode == roleCode)).first():
    raise IdentityError(f"role '{roleCode}' is still given to someone")
  session.delete(row)
  session.flush()


def assignRole(session: Session, assignment: RoleAssignment, given: bool = True) -> None:
  if assignment.roleCode not in roles(session):
    raise IdentityError(f"no role '{assignment.roleCode}'")
  if (assignment.userName is None) == (assignment.groupName is None):
    raise IdentityError("a role is given to one account or one group")
  accountID = None if assignment.userName is None else accountRow(session, assignment.userName).accountID
  groupID = None if assignment.groupName is None else groupRow(session, assignment.groupName).groupID
  stored = storedScope(session, assignment.scope)
  query = select(RoleAssignmentRow).where(
    RoleAssignmentRow.roleCode == assignment.roleCode, RoleAssignmentRow.scope == stored,
    RoleAssignmentRow.accountID.is_(None) if accountID is None else RoleAssignmentRow.accountID == accountID,
    RoleAssignmentRow.groupID.is_(None) if groupID is None else RoleAssignmentRow.groupID == groupID,
  )
  existing = session.execute(query).scalar_one_or_none()
  if given and existing is None:
    session.add(RoleAssignmentRow(roleCode=assignment.roleCode, scope=stored, accountID=accountID, groupID=groupID))
  elif not given:
    if existing is None:
      raise IdentityError(f"role '{assignment.roleCode}' is not given there")
    session.delete(existing)
  session.flush()


def listAssignments(session: Session) -> list[RoleAssignment]:
  result = []
  for row in session.execute(select(RoleAssignmentRow).order_by(RoleAssignmentRow.assignmentID)).scalars().all():
    result.append(RoleAssignment(
      roleCode=row.roleCode, scope=writtenScope(session, row.scope),
      userName=None if row.accountID is None else session.get(AccountRow, row.accountID).userName,
      groupName=None if row.groupID is None else session.get(AccountGroupRow, row.groupID).name,
    ))
  return result


def permissionsAt(session: Session, actor: Actor, scope: str) -> frozenset[Permission]:
  """What an actor may do at a scope: every permission for everyone and the operator, else its roles' union."""
  if actor.holdsEverything:
    return frozenset(Permission)
  account = session.get(AccountRow, actor.accountID)
  if account is None or not account.active:
    return frozenset()
  groupIDs = session.execute(select(GroupMemberRow.groupID).where(GroupMemberRow.accountID == account.accountID)).scalars().all()
  stored = [entry for entry, _ in scopeChain(session, scope)]
  rows = session.execute(select(RoleAssignmentRow).where(RoleAssignmentRow.scope.in_(stored))).scalars().all()
  defined = roles(session)
  held: set[Permission] = set()
  for row in rows:
    if row.accountID == account.accountID or (row.groupID is not None and row.groupID in groupIDs):
      held |= defined[row.roleCode].permissions
  return frozenset(held)


def scopesWithAssignments(session: Session, actor: Actor) -> list[str]:
  """The written scopes where an account holds a role itself or through a group."""
  account = session.get(AccountRow, actor.accountID)
  if account is None:
    return []
  groupIDs = session.execute(select(GroupMemberRow.groupID).where(GroupMemberRow.accountID == account.accountID)).scalars().all()
  rows = session.execute(select(RoleAssignmentRow)).scalars().all()
  return sorted({writtenScope(session, row.scope) for row in rows
                 if row.accountID == account.accountID or (row.groupID is not None and row.groupID in groupIDs)})


def _hashed(token: str) -> str:
  return hashlib.sha256(token.encode("ascii")).hexdigest()


def issueToken(session: Session, userName: str, kind: str, lifetime: datetime.timedelta | None, name: str | None) -> str:
  """A new session or API token for an account; only its hash is kept."""
  if kind not in ("session", "api"):
    raise IdentityError(f"a token is a session or an api token, not '{kind}'")
  account = accountRow(session, userName)
  if not account.active:
    raise IdentityError(f"account '{userName}' is not active")
  token = secrets.token_urlsafe(32)
  issued = now()
  session.add(AuthTokenRow(tokenHash=_hashed(token), accountID=account.accountID, kind=kind, name=name, createdAt=issued,
                           expiresAt=None if lifetime is None else issued + lifetime))
  session.flush()
  return token


def actorForToken(session: Session, token: str, kind: str, surface: str) -> Actor:
  row = session.get(AuthTokenRow, _hashed(token))
  if row is None or row.kind != kind:
    raise IdentityError("the token is not valid")
  if row.expiresAt is not None and row.expiresAt <= now():
    session.delete(row)
    session.flush()
    raise IdentityError("the token has expired")
  account = session.get(AccountRow, row.accountID)
  if not account.active:
    raise IdentityError("the token's account is not active")
  return Actor(kind=ActorKind.account, accountID=account.accountID, userName=account.userName, surface=surface)


def revokeToken(session: Session, token: str) -> None:
  row = session.get(AuthTokenRow, _hashed(token))
  if row is not None:
    session.delete(row)
    session.flush()
