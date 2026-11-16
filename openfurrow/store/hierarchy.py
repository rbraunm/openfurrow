# SPDX-License-Identifier: Apache-2.0
"""The hierarchy in the store: its levels, its places, and where each trial lives (decision 0034)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from openfurrow.schema.hierarchy import HierarchyLevel, Place, checkPlaceCode, splitPath
from openfurrow.store.database import (
  HierarchyLevelRow,
  NotFoundError,
  PlaceRow,
  RoleAssignmentRow,
  SettingValueRow,
  StoreError,
  TrialRow,
)


class ScopeError(ValueError):
  """A scope that is not written as one."""


def loadLevels(session: Session) -> list[HierarchyLevel]:
  rows = session.execute(select(HierarchyLevelRow).order_by(HierarchyLevelRow.ordinal)).scalars().all()
  return [HierarchyLevel(levelCode=row.levelCode, name=row.name) for row in rows]


def replaceLevels(session: Session, levels: list[HierarchyLevel]) -> None:
  """Set the levels, top first. Only while the store has no places and no trials."""
  codes = [level.levelCode for level in levels]
  if len(set(codes)) != len(codes):
    raise StoreError(f"hierarchy levels repeat a code: {codes}")
  if "trial" in codes:
    raise StoreError("the trial is always the last level; it is not listed among the levels")
  placeCount = session.execute(select(func.count()).select_from(PlaceRow)).scalar_one()
  trialCount = session.execute(select(func.count()).select_from(TrialRow)).scalar_one()
  if placeCount or trialCount:
    raise StoreError(
      f"the hierarchy's levels can change only while the store holds no places and no trials; "
      f"it holds {placeCount} places and {trialCount} trials"
    )
  for row in session.execute(select(HierarchyLevelRow)).scalars().all():
    session.delete(row)
  session.flush()
  session.add_all(
    HierarchyLevelRow(levelCode=level.levelCode, ordinal=ordinal, name=level.name) for ordinal, level in enumerate(levels)
  )
  session.flush()


def _levelCodes(session: Session) -> list[str]:
  return [level.levelCode for level in loadLevels(session)]


def placeRowFor(session: Session, path: str) -> PlaceRow:
  """The place at `path`; raises if there is none."""
  parentID = None
  row = None
  walked = []
  for code in splitPath(path):
    walked.append(code)
    row = session.execute(
      select(PlaceRow).where(PlaceRow.code == code, PlaceRow.parentID.is_(None) if parentID is None
                             else PlaceRow.parentID == parentID)
    ).scalar_one_or_none()
    if row is None:
      raise NotFoundError(f"no place '{'/'.join(walked)}'")
    parentID = row.placeID
  return row


def pathOf(session: Session, placeID: int) -> str:
  codes = []
  current = session.get(PlaceRow, placeID)
  while current is not None:
    codes.append(current.code)
    current = None if current.parentID is None else session.get(PlaceRow, current.parentID)
  return "/".join(reversed(codes))


def addPlace(session: Session, parentPath: str | None, code: str, name: str) -> Place:
  """A new place inside `parentPath` (None for the first level), at the level below the parent's."""
  checkPlaceCode(code)
  if not name.strip():
    raise StoreError("a place needs a name")
  levels = _levelCodes(session)
  if not levels:
    raise StoreError("the store has no hierarchy levels, so it has no places; trials stand on their own")
  if parentPath is None:
    parentID, levelIndex = None, 0
  else:
    parent = placeRowFor(session, parentPath)
    parentID, levelIndex = parent.placeID, levels.index(parent.levelCode) + 1
    if levelIndex == len(levels):
      raise StoreError(f"'{parentPath}' is a {parent.levelCode}, the last level; it holds trials, not places")
  siblings = select(PlaceRow).where(
    PlaceRow.code == code, PlaceRow.parentID.is_(None) if parentID is None else PlaceRow.parentID == parentID,
  )
  path = code if parentPath is None else f"{parentPath}/{code}"
  if session.execute(siblings).scalar_one_or_none() is not None:
    raise StoreError(f"place '{path}' already exists")
  session.add(PlaceRow(levelCode=levels[levelIndex], parentID=parentID, code=code, name=name.strip()))
  session.flush()
  return Place(path=path, levelCode=levels[levelIndex], name=name.strip())


def listPlaces(session: Session) -> list[Place]:
  """Every place, ordered by path."""
  rows = session.execute(select(PlaceRow)).scalars().all()
  places = [Place(path=pathOf(session, row.placeID), levelCode=row.levelCode, name=row.name) for row in rows]
  return sorted(places, key=lambda place: place.path.split("/"))


def deletePlace(session: Session, path: str) -> None:
  """Delete an empty place: no places inside it and no trials in it."""
  row = placeRowFor(session, path)
  children = session.execute(select(func.count()).select_from(PlaceRow).where(PlaceRow.parentID == row.placeID)).scalar_one()
  trials = session.execute(select(func.count()).select_from(TrialRow).where(TrialRow.placeID == row.placeID)).scalar_one()
  if children or trials:
    raise StoreError(f"place '{path}' holds {children} places and {trials} trials; only an empty place is deleted")
  session.execute(SettingValueRow.__table__.delete().where(SettingValueRow.scope == f"place:{row.placeID}"))
  session.execute(RoleAssignmentRow.__table__.delete().where(RoleAssignmentRow.scope == f"place:{row.placeID}"))
  session.delete(row)
  session.flush()


def trialPlaceID(session: Session, placePath: str | None) -> int | None:
  """The place a new trial goes in: a place of the last level, or none when the store has no levels."""
  levels = _levelCodes(session)
  if not levels:
    if placePath is not None:
      raise StoreError("the store has no hierarchy levels, so a trial goes in no place")
    return None
  if placePath is None:
    raise StoreError(f"a trial goes in a place of the last level, a {levels[-1]}; name its path")
  row = placeRowFor(session, placePath)
  if row.levelCode != levels[-1]:
    raise StoreError(f"'{placePath}' is a {row.levelCode}; a trial goes in a {levels[-1]}")
  return row.placeID


def storedScope(session: Session, scope: str) -> str:
  """A scope as written ('server', 'place:<path>', 'trial:<code>') as the store keeps it."""
  if scope == "server":
    return "server"
  kind, _, name = scope.partition(":")
  if kind == "place" and name:
    return f"place:{placeRowFor(session, name).placeID}"
  if kind == "trial" and name:
    if session.get(TrialRow, name) is None:
      raise NotFoundError(f"trial '{name}' not found")
    return f"trial:{name}"
  raise ScopeError(f"'{scope}' is not a scope: 'server', 'place:<path>' or 'trial:<code>'")


def writtenScope(session: Session, stored: str) -> str:
  """A stored scope as written."""
  if stored.startswith("place:"):
    return f"place:{pathOf(session, int(stored.split(':', 1)[1]))}"
  return stored


def scopeChain(session: Session, scope: str) -> list[tuple[str, str]]:
  """The stored scopes that hold for `scope`, nearest first, each with its written form."""
  stored = storedScope(session, scope)
  chain = []
  placeID = None
  if stored.startswith("trial:"):
    chain.append((stored, scope))
    placeID = session.get(TrialRow, stored.split(":", 1)[1]).placeID
  elif stored.startswith("place:"):
    placeID = int(stored.split(":", 1)[1])
  while placeID is not None:
    chain.append((f"place:{placeID}", f"place:{pathOf(session, placeID)}"))
    placeID = session.get(PlaceRow, placeID).parentID
  chain.append(("server", "server"))
  return chain


def trialPlace(session: Session, trialCode: str) -> str | None:
  trial = session.get(TrialRow, trialCode)
  if trial is None:
    raise NotFoundError(f"trial '{trialCode}' not found")
  return None if trial.placeID is None else pathOf(session, trial.placeID)


def moveTrial(session: Session, trialCode: str, placePath: str | None) -> None:
  trial = session.get(TrialRow, trialCode)
  if trial is None:
    raise NotFoundError(f"trial '{trialCode}' not found")
  trial.placeID = trialPlaceID(session, placePath)
  session.flush()


def trialsIn(session: Session, placePath: str) -> list[tuple[str, str]]:
  """The trials anywhere inside a place, as (trialCode, title), ordered by code."""
  root = placeRowFor(session, placePath)
  inside = {root.placeID}
  frontier = [root.placeID]
  while frontier:
    children = session.execute(select(PlaceRow.placeID).where(PlaceRow.parentID.in_(frontier))).scalars().all()
    inside |= set(children)
    frontier = children
  rows = session.execute(
    select(TrialRow.trialCode, TrialRow.title).where(TrialRow.placeID.in_(inside)).order_by(TrialRow.trialCode)
  ).all()
  return [(row.trialCode, row.title) for row in rows]
