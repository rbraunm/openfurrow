# SPDX-License-Identifier: Apache-2.0
"""A federation provider's discovery list: the institutions its aggregate offers, kept for search (decision 0040).

The list is replaced whole, in one transaction, by each refresh that succeeds; a failed
refresh never reaches it. Search runs in the database over each institution's names in
every language, its entity ID and its scopes, folded so that case and accents do not
matter: a query typed without accents finds a name written with them.
"""

from __future__ import annotations

import datetime
import json
import unicodedata
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from openfurrow.identity.providers import Discovery
from openfurrow.store.database import DiscoveredInstitutionRow, DiscoveryListRow


def folded(text: str) -> str:
  """Text as search compares it: compatibility-decomposed, without combining marks, case-folded."""
  decomposed = unicodedata.normalize("NFKD", text)
  return "".join(character for character in decomposed if not unicodedata.combining(character)).casefold()


def displayNameIn(names: dict[str, str], entityID: str, locale: str) -> str:
  """The name in the locale, else in its language, else in English, else the entity ID (as Carnelian chooses)."""
  wanted = (locale.lower(), locale.split("-")[0].lower(), "en")
  byLanguage = {language.lower(): text for language, text in names.items()}
  return next((byLanguage[language] for language in wanted if language in byLanguage), entityID)


@dataclass(frozen=True)
class DiscoveryList:
  fetchedAt: datetime.datetime
  validUntil: datetime.datetime
  count: int


@dataclass(frozen=True)
class FoundInstitutions:
  """Institutions that match a search, as (entity ID, name in the locale), and whether more matched than are shown."""

  institutions: list[tuple[str, str]]
  more: bool


def replaceDiscovery(session: Session, providerName: str, discovery: Discovery, fetchedAt: datetime.datetime) -> None:
  session.execute(delete(DiscoveredInstitutionRow).where(DiscoveredInstitutionRow.providerName == providerName))
  session.execute(delete(DiscoveryListRow).where(DiscoveryListRow.providerName == providerName))
  session.add(DiscoveryListRow(providerName=providerName, fetchedAt=fetchedAt,
                               validUntil=datetime.datetime.fromtimestamp(discovery.validUntil, datetime.UTC)
                               .replace(tzinfo=None)))
  session.flush()
  session.add_all(
    DiscoveredInstitutionRow(
      providerName=providerName, entityID=found.entityID, displayNamesJSON=json.dumps(found.displayNames, sort_keys=True),
      scopesJSON=json.dumps(list(found.scopes)), registrationAuthority=found.registrationAuthority,
      searchText="\n".join(folded(text) for text in (*found.displayNames.values(), found.entityID, *found.scopes)),
    )
    for found in discovery.institutions
  )
  session.flush()


def discoveryList(session: Session, providerName: str) -> DiscoveryList | None:
  row = session.get(DiscoveryListRow, providerName)
  if row is None:
    return None
  count = len(session.execute(select(DiscoveredInstitutionRow.entityID)
                              .where(DiscoveredInstitutionRow.providerName == providerName)).all())
  return DiscoveryList(fetchedAt=row.fetchedAt.replace(tzinfo=datetime.UTC),
                       validUntil=row.validUntil.replace(tzinfo=datetime.UTC), count=count)


def isDiscovered(session: Session, providerName: str, entityID: str) -> bool:
  return session.get(DiscoveredInstitutionRow, (providerName, entityID)) is not None


def _likePattern(text: str) -> str:
  return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def searchDiscovery(session: Session, providerName: str, query: str, locale: str, limit: int) -> FoundInstitutions:
  """The institutions whose names, entity ID or scopes hold every word of the query, those whose name begins with it
  first, then by name in the locale."""
  words = folded(query).split()
  if not words:
    return FoundInstitutions([], False)
  statement = select(DiscoveredInstitutionRow).where(DiscoveredInstitutionRow.providerName == providerName)
  for word in words:
    statement = statement.where(DiscoveredInstitutionRow.searchText.like(_likePattern(word), escape="\\"))
  found = [(row.entityID, displayNameIn(json.loads(row.displayNamesJSON), row.entityID, locale))
           for row in session.execute(statement).scalars().all()]
  start = folded(query).strip()
  found.sort(key=lambda pair: (not folded(pair[1]).startswith(start), folded(pair[1]), pair[0]))
  return FoundInstitutions(found[:limit], len(found) > limit)
