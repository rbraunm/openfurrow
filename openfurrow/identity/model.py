# SPDX-License-Identifier: Apache-2.0
"""Accounts, groups, roles and the actor every change is recorded under (decisions 0036, 0037).

A permission is held at a scope -- the server, a place, a trial -- through a role given to
an account or to a group the account belongs to, and it holds below where it is given.
Five roles are built in; an organization defines its own from the same permissions. Who
acts is an Actor: a signed-in account, everyone (the open mode, where every permission is
held everywhere), the store's operator (the command line and the library, which reach
the store directly and so hold every permission too), the scheduler running a task
(decision 0041), which acts for the operator and is recorded under the task's name, or a
trusted workload (decision 0042): a job whose platform-signed token one workload rule
accepted, holding the roles given to that rule and recorded under the rule's name.
"""

from __future__ import annotations

import re
import unicodedata
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class IdentityError(ValueError):
  """An account, group, role or sign-in that is refused."""


class Permission(str, Enum):
  view = "view"
  enterValues = "enterValues"
  importValues = "importValues"
  editRecord = "editRecord"
  editDesign = "editDesign"
  manageTrials = "manageTrials"
  changeSettings = "changeSettings"
  manageStructure = "manageStructure"
  manageAccess = "manageAccess"
  manageRetention = "manageRetention"
  viewAudit = "viewAudit"
  manageTasks = "manageTasks"


class SignInMode(str, Enum):
  """How the service knows who is acting (decision 0036)."""

  open = "open"          # no sign-in: everyone holds every permission everywhere
  accounts = "accounts"  # every request belongs to a signed-in account or an API token


class ActorKind(str, Enum):
  account = "account"
  everyone = "everyone"
  operator = "operator"
  scheduler = "scheduler"
  workload = "workload"


class Actor(BaseModel):
  """Who a change is made by, and through which surface."""

  model_config = ConfigDict(extra="forbid", frozen=True)

  kind: ActorKind
  accountID: int | None = None
  userName: str | None = None
  taskName: str | None = None
  ruleName: str | None = None
  run: dict[str, Any] | None = Field(default=None, description="a workload's run, as its token's claims tell it")
  surface: str = Field(description="web, api, cli, library, provisioning or scheduler")

  @classmethod
  def operator(cls, surface: str) -> Actor:
    return cls(kind=ActorKind.operator, surface=surface)

  @classmethod
  def everyone(cls, surface: str) -> Actor:
    return cls(kind=ActorKind.everyone, surface=surface)

  @classmethod
  def scheduler(cls, taskName: str) -> Actor:
    """A scheduled task's run (decision 0041), acting for the store like the operator, recorded under its task."""
    return cls(kind=ActorKind.scheduler, taskName=taskName, surface="scheduler")

  @classmethod
  def workload(cls, ruleName: str, run: dict[str, Any], surface: str) -> Actor:
    """A job whose token the workload rule `ruleName` accepted (decision 0042); `run` goes into every event it writes."""
    return cls(kind=ActorKind.workload, ruleName=ruleName, run=run, surface=surface)

  @property
  def holdsEverything(self) -> bool:
    return self.kind in (ActorKind.everyone, ActorKind.operator, ActorKind.scheduler)

  @property
  def name(self) -> str | None:
    """The account's user name, the task a scheduler run belongs to, or the rule that accepted a workload."""
    return {ActorKind.scheduler: self.taskName, ActorKind.workload: self.ruleName}.get(self.kind, self.userName)

  @property
  def label(self) -> str:
    return self.kind.value if self.kind in (ActorKind.everyone, ActorKind.operator) else self.name


roleCodePattern = re.compile(r"^[a-z][A-Za-z0-9]{1,39}$")
userNamePunctuation = frozenset("._@-")
# Scripts written together in one language count as one, so a Japanese or Korean name is not "mixed".
_scriptFamilies = {"HIRAGANA": "JAPANESE", "KATAKANA": "JAPANESE", "KATAKANA-HIRAGANA": "JAPANESE", "HANGUL": "KOREAN"}


def foldedUserName(text: str) -> str:
  """A user name as compared: compatibility-normalized (NFKC) and case-folded, the same however it was typed."""
  return unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", text.strip()).casefold())


def _script(character: str) -> str:
  word = unicodedata.name(character, "UNKNOWN").split()[0]
  return _scriptFamilies.get(word, word)


def normalizedUserName(userName: str) -> str:
  """The canonical user name, or IdentityError: letters of any script, combining marks, digits and '._@-'."""
  name = foldedUserName(userName)
  rule = ("2 to 64 of letters, digits, '.', '_', '@' and '-', starting with a letter or digit, "
          "the part before any '@' in one script")
  if not 2 <= len(name) <= 64 or unicodedata.category(name[0])[0] not in "LN":
    raise IdentityError(f"'{userName}' is not a user name: {rule}")
  for character in name:
    category = unicodedata.category(character)
    if not (category[0] in "LM" or category == "Nd" or character in userNamePunctuation):
      raise IdentityError(f"'{userName}' is not a user name: {character!r} is not allowed; {rule}")
  scripts = {_script(character) for character in name.partition("@")[0] if unicodedata.category(character)[0] == "L"}
  if len(scripts) > 1 and scripts not in ({"CJK", "JAPANESE"}, {"CJK", "KOREAN"}):
    raise IdentityError(f"'{userName}' is not a user name: it mixes the scripts {', '.join(sorted(scripts))}; {rule}")
  return name


class Account(BaseModel):
  model_config = ConfigDict(extra="forbid")

  accountID: int
  userName: str
  displayName: str
  email: str | None = None
  locale: str | None = None
  active: bool


class Group(BaseModel):
  model_config = ConfigDict(extra="forbid")

  groupID: int
  name: str
  members: list[str]


class RoleDefinition(BaseModel):
  """A named set of permissions; the built-in ones are named by the message catalog."""

  model_config = ConfigDict(extra="forbid")

  roleCode: str
  name: str | None = None
  permissions: frozenset[Permission]
  builtIn: bool = False

  @field_validator("roleCode")
  @classmethod
  def codeIsACode(cls, roleCode: str) -> str:
    if not roleCodePattern.match(roleCode):
      raise ValueError(f"'{roleCode}' is not a role code: a letter, then letters and digits")
    return roleCode


_viewer = frozenset({Permission.view})
_collector = _viewer | {Permission.enterValues}
_analyst = _collector | {Permission.importValues}
_manager = _analyst | {Permission.editRecord, Permission.editDesign, Permission.manageTrials, Permission.changeSettings}

builtInRoles: dict[str, RoleDefinition] = {
  role.roleCode: role for role in (
    RoleDefinition(roleCode="viewer", permissions=_viewer, builtIn=True),
    RoleDefinition(roleCode="dataCollector", permissions=_collector, builtIn=True),
    RoleDefinition(roleCode="analyst", permissions=_analyst, builtIn=True),
    RoleDefinition(roleCode="trialManager", permissions=_manager, builtIn=True),
    RoleDefinition(roleCode="administrator", permissions=frozenset(Permission), builtIn=True),
  )
}


class RoleAssignment(BaseModel):
  """A role given to exactly one of an account, a group or a workload rule, at a scope ('server', 'place:<path>',
  'trial:<code>')."""

  model_config = ConfigDict(extra="forbid")

  roleCode: str
  scope: str
  userName: str | None = None
  groupName: str | None = None
  ruleName: str | None = None
