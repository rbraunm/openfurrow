# SPDX-License-Identifier: Apache-2.0
"""Setting values in the store, and their resolution down the hierarchy (decision 0035)."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from openfurrow.settings import EffectiveSetting, SettingError, SettingScope, checkedValue, definitions, jsonValue
from openfurrow.store.database import SettingValueRow
from openfurrow.store.hierarchy import scopeChain, storedScope


def _scopeKind(stored: str) -> SettingScope:
  return SettingScope(stored.split(":", 1)[0])


def setValue(session: Session, scope: str, key: str, value) -> None:
  stored = storedScope(session, scope)
  text = json.dumps(jsonValue(key, checkedValue(key, value, _scopeKind(stored))))
  row = session.get(SettingValueRow, (stored, key))
  if row is None:
    session.add(SettingValueRow(scope=stored, key=key, valueJSON=text))
  else:
    row.valueJSON = text
  session.flush()


def clearValue(session: Session, scope: str, key: str) -> None:
  stored = storedScope(session, scope)
  row = session.get(SettingValueRow, (stored, key))
  if row is None:
    raise SettingError(f"setting '{key}' has no value at {scope}")
  session.delete(row)
  session.flush()


def effectiveSettings(session: Session, scope: str) -> list[EffectiveSetting]:
  """Every setting's value at `scope`, and where it was set."""
  chain = scopeChain(session, scope)
  stored = {
    (row.scope, row.key): row.valueJSON
    for row in session.execute(
      select(SettingValueRow).where(SettingValueRow.scope.in_([entry for entry, _ in chain]))
    ).scalars().all()
  }
  result = []
  for key, definition in sorted(definitions.items()):
    for entry, label in chain:
      if (entry, key) in stored:
        value = definition.adapter.validate_python(json.loads(stored[(entry, key)]))
        result.append(EffectiveSetting(key=key, value=value, source=label))
        break
    else:
      result.append(EffectiveSetting(key=key, value=definition.default, source="default"))
  return result
