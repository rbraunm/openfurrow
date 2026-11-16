# SPDX-License-Identifier: Apache-2.0
"""The hierarchy in the store: its levels, its places, and where each trial lives (decision 0034)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from openfurrow.schema.hierarchy import HierarchyLevel, Place, checkPlaceCode, splitPath
from openfurrow.store.database import HierarchyLevelRow, PlaceRow, SettingValueRow, StoreError, TrialRow


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
      raise StoreError(f"no place '{'/'.join(walked)}'")
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


def trialPlace(session: Session, trialCode: str) -> str | None:
  trial = session.get(TrialRow, trialCode)
  if trial is None:
    raise StoreError(f"trial '{trialCode}' not found")
  return None if trial.placeID is None else pathOf(session, trial.placeID)


def moveTrial(session: Session, trialCode: str, placePath: str | None) -> None:
  trial = session.get(TrialRow, trialCode)
  if trial is None:
    raise StoreError(f"trial '{trialCode}' not found")
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
