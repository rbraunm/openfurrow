# SPDX-License-Identifier: Apache-2.0
"""Workload rules in the store (decision 0042). The roles given to a rule are role assignments like any other
(`store/identity.py`), and go with the rule when it is removed."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from openfurrow.identity.model import IdentityError
from openfurrow.identity.workloads import WorkloadRule
from openfurrow.store.database import WorkloadRuleRow


def _rule(row: WorkloadRuleRow) -> WorkloadRule:
  return WorkloadRule(name=row.ruleName, issuer=row.issuer, claims=json.loads(row.claimsJSON), enabled=row.enabled,
                      certificateAuthority=row.certificateAuthority, createdAt=row.createdAt)


def ruleRow(session: Session, name: str) -> WorkloadRuleRow:
  row = session.get(WorkloadRuleRow, name)
  if row is None:
    raise IdentityError(f"no workload rule '{name}'")
  return row


def rule(session: Session, name: str) -> WorkloadRule:
  return _rule(ruleRow(session, name))


def addRule(session: Session, added: WorkloadRule) -> None:
  if session.get(WorkloadRuleRow, added.name) is not None:
    raise IdentityError(f"workload rule '{added.name}' already exists")
  session.add(WorkloadRuleRow(ruleName=added.name, issuer=added.issuer, claimsJSON=json.dumps(added.claims, sort_keys=True),
                              enabled=added.enabled, certificateAuthority=added.certificateAuthority,
                              createdAt=added.createdAt))
  session.flush()


def listRules(session: Session) -> list[WorkloadRule]:
  rows = session.execute(select(WorkloadRuleRow).order_by(WorkloadRuleRow.ruleName)).scalars().all()
  return [_rule(row) for row in rows]


def enabledRulesOf(session: Session, issuer: str) -> list[WorkloadRule]:
  """The rules a token naming `issuer` is checked against, by name."""
  rows = session.execute(select(WorkloadRuleRow).where(WorkloadRuleRow.issuer == issuer, WorkloadRuleRow.enabled.is_(True))
                         .order_by(WorkloadRuleRow.ruleName)).scalars().all()
  return [_rule(row) for row in rows]


def setRuleEnabled(session: Session, name: str, enabled: bool) -> None:
  ruleRow(session, name).enabled = enabled
  session.flush()


def removeRule(session: Session, name: str) -> None:
  session.delete(ruleRow(session, name))
  session.flush()
