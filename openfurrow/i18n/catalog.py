# SPDX-License-Identifier: Apache-2.0
"""Keyed message catalogs (decision 0007).

User-facing text lives in static, per-locale JSON catalogs, not in the code, so a
locale is purely additive. A catalog is a mapping of key -> {text, status}, where the
status is `source`, `machineDraft`, or `humanApproved`: the project never presents
unreviewed machine output as authoritative, so the status travels with every string
and a locale is only authoritative when every string in it is human-approved.

Catalogs are read at load time from files on disk. There is no runtime translation
call of any kind (decision 0007 C, and decision 0002): a locale ships as data.

**Everything fails loud.** A missing key, an unknown locale, a placeholder the text
does not use, or a placeholder the caller did not supply all raise. There is no
fallback to the key name and no silent fallback to English -- a half-translated locale
that quietly renders English is exactly the kind of invisible wrongness this project
refuses. Completeness is a property a locale either has or does not, and the test
suite enforces it.

Source is ASCII per the house rule; catalogs are UTF-8 by necessity (accented Latin
now, other scripts later) and are read as explicit UTF-8.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from string import Formatter

# The locale the source strings are authored in. Its catalog defines the key set every
# other locale must cover.
sourceLocale = "en-US"

_localeDirectory = Path(__file__).parent / "locales"


class MessageStatus(Enum):
  """Provenance of a single translated string (decision 0007 C)."""

  source = "source"                    # authored in the source locale
  machineDraft = "machineDraft"        # machine-translated, not yet reviewed
  humanApproved = "humanApproved"      # reviewed and signed off by a domain speaker


class MessageError(Exception):
  """A message could not be resolved: unknown locale, missing key, bad placeholders."""


class Catalog:
  """The messages for one locale, with each string's translation status."""

  def __init__(self, locale: str, messages: dict[str, tuple[str, MessageStatus]]) -> None:
    self.locale = locale
    self._messages = messages

  @property
  def keys(self) -> set[str]:
    return set(self._messages)

  def text(self, key: str) -> str:
    """The raw (unformatted) text for `key`; raises if the locale does not define it."""
    if key not in self._messages:
      raise MessageError(f"locale '{self.locale}' has no message for key '{key}'")
    return self._messages[key][0]

  def status(self, key: str) -> MessageStatus:
    """The translation status of one string."""
    if key not in self._messages:
      raise MessageError(f"locale '{self.locale}' has no message for key '{key}'")
    return self._messages[key][1]

  @property
  def isAuthoritative(self) -> bool:
    """True only when every string is source or human-approved.

    A locale containing any unreviewed machine draft is NOT authoritative, and a
    surface must say so rather than presenting it as finished work.
    """
    return all(
      status is not MessageStatus.machineDraft for _, status in self._messages.values()
    )

  def statusSummary(self) -> dict[MessageStatus, int]:
    """How many strings sit at each status -- the per-locale audit view."""
    summary = {status: 0 for status in MessageStatus}
    for _, status in self._messages.values():
      summary[status] += 1
    return summary


def availableLocales() -> list[str]:
  """Every locale with a catalog on disk."""
  return sorted(path.stem for path in _localeDirectory.glob("*.json"))


def loadCatalog(locale: str) -> Catalog:
  """Load one locale's catalog from disk; raises if it is absent or malformed."""
  path = _localeDirectory / f"{locale}.json"
  if not path.exists():
    raise MessageError(
      f"no catalog for locale '{locale}'; available: {', '.join(availableLocales())}"
    )
  document = json.loads(path.read_text(encoding="utf-8"))
  if document.get("locale") != locale:
    raise MessageError(
      f"catalog '{path.name}' declares locale '{document.get('locale')}', expected '{locale}'"
    )

  messages: dict[str, tuple[str, MessageStatus]] = {}
  for key, entry in document["messages"].items():
    try:
      status = MessageStatus(entry["status"])
    except (KeyError, ValueError) as error:
      raise MessageError(f"message '{key}' in locale '{locale}' has an invalid status") from error
    messages[key] = (entry["text"], status)
  return Catalog(locale, messages)


def placeholdersIn(text: str) -> set[str]:
  """The named placeholders a message text uses, e.g. {'title'} for 'Report: {title}'.

  Placeholders are machinery, not prose: they are fenced from translation (decision
  0007 C) and must match across locales, which the test suite asserts.
  """
  return {name for _, name, _, _ in Formatter().parse(text) if name}
