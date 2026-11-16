# SPDX-License-Identifier: Apache-2.0
"""Setting values in the store, and their resolution down the hierarchy (decision 0035)."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from openfurrow.settings import EffectiveSetting, SettingError, SettingScope, checkedValue, definitions, jsonValue
from openfurrow.store.database import PlaceRow, SettingValueRow, StoreError, TrialRow
from openfurrow.store.hierarchy import pathOf, placeRowFor


def storedScope(session: Session, scope: str) -> tuple[SettingScope, str]:
  """A scope as written ('server', 'place:<path>', 'trial:<code>') and its key in the store."""
  if scope == "server":
    return SettingScope.server, "server"
  kind, _, name = scope.partition(":")
  if kind == "place" and name:
    return SettingScope.place, f"place:{placeRowFor(session, name).placeID}"
  if kind == "trial" and name:
    if session.get(TrialRow, name) is None:
      raise StoreError(f"trial '{name}' not found")
    return SettingScope.trial, f"trial:{name}"
  raise SettingError(f"'{scope}' is not a scope: 'server', 'place:<path>' or 'trial:<code>'")


def setValue(session: Session, scope: str, key: str, value) -> None:
  kind, stored = storedScope(session, scope)
  text = json.dumps(jsonValue(key, checkedValue(key, value, kind)))
  row = session.get(SettingValueRow, (stored, key))
  if row is None:
    session.add(SettingValueRow(scope=stored, key=key, valueJSON=text))
  else:
    row.valueJSON = text
  session.flush()


def clearValue(session: Session, scope: str, key: str) -> None:
  _, stored = storedScope(session, scope)
  row = session.get(SettingValueRow, (stored, key))
  if row is None:
    raise SettingError(f"setting '{key}' has no value at {scope}")
  session.delete(row)
  session.flush()


def _chain(session: Session, scope: str) -> list[tuple[str, str]]:
  """The stored scopes a value is looked for in, nearest first, each with its source label."""
  kind, stored = storedScope(session, scope)
  chain = []
  placeID = None
  if kind is SettingScope.trial:
    chain.append((stored, scope))
    placeID = session.get(TrialRow, stored.split(":", 1)[1]).placeID
  elif kind is SettingScope.place:
    placeID = int(stored.split(":", 1)[1])
  while placeID is not None:
    chain.append((f"place:{placeID}", f"place:{pathOf(session, placeID)}"))
    placeID = session.get(PlaceRow, placeID).parentID
  chain.append(("server", "server"))
  return chain


def effectiveSettings(session: Session, scope: str) -> list[EffectiveSetting]:
  """Every setting's value at `scope`, and where it was set."""
  chain = _chain(session, scope)
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
