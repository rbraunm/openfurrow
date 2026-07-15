# SPDX-License-Identifier: Apache-2.0
"""The translator: one object a user-facing surface uses to produce localized text.

A surface asks a `Translator` for text by key and for numbers and dates by value; it
never writes a user-facing literal and never formats a number itself. That is the whole
discipline decision 0007 asks for, and it is cheap to keep and expensive to retrofit.

    translator = translatorFor("en-GB")
    translator.text("report.field.crop")                  -> "Crop"
    translator.text("report.heading.assessment", name="Yield", code="YIELD")
    translator.number(12.3456, decimals=2)                -> "12.35"

Fails loud: an unknown locale, a missing key, or a placeholder mismatch raises rather
than rendering something plausible-looking and wrong.
"""

from __future__ import annotations

from datetime import date

from openfurrow.i18n.catalog import (
  Catalog,
  MessageError,
  MessageStatus,
  loadCatalog,
  placeholdersIn,
)
from openfurrow.i18n.formatting import formatDate, formatInteger, formatNumber, textDirection


class Translator:
  """Resolves keyed messages and formats values for one locale."""

  def __init__(self, catalog: Catalog) -> None:
    self._catalog = catalog

  @property
  def locale(self) -> str:
    return self._catalog.locale

  @property
  def direction(self) -> str:
    """The base text direction for this locale: 'rtl' or 'ltr'."""
    return textDirection(self._catalog.locale)

  @property
  def isAuthoritative(self) -> bool:
    """False if any string in this locale is an unreviewed machine draft.

    A surface showing a non-authoritative locale is required to say so (decision 0007);
    it must not present unreviewed machine output as finished.
    """
    return self._catalog.isAuthoritative

  def statusSummary(self) -> dict[MessageStatus, int]:
    return self._catalog.statusSummary()

  def text(self, key: str, **placeholders: object) -> str:
    """The localized text for `key`, with its placeholders filled in.

    Placeholder names are machinery fenced from translation, so a mismatch between what
    the text expects and what the caller supplies is a bug in one or the other and is
    raised, never papered over.
    """
    template = self._catalog.text(key)
    expected = placeholdersIn(template)
    supplied = set(placeholders)

    if expected - supplied:
      raise MessageError(
        f"message '{key}' ({self.locale}) needs placeholder(s) "
        f"{sorted(expected - supplied)} that were not supplied"
      )
    if supplied - expected:
      raise MessageError(
        f"message '{key}' ({self.locale}) was given placeholder(s) "
        f"{sorted(supplied - expected)} that it does not use"
      )
    return template.format(**placeholders)

  def number(
    self,
    value: float | None,
    decimals: int,
    useGrouping: bool = False,
    absent: str = "-",
  ) -> str:
    """Format a number for display in this locale."""
    return formatNumber(value, self.locale, decimals, useGrouping=useGrouping, absent=absent)

  def integer(self, value: int, useGrouping: bool = False) -> str:
    """Format an integer for display in this locale."""
    return formatInteger(value, self.locale, useGrouping=useGrouping)

  def date(self, value: date) -> str:
    """Format a date for display in this locale."""
    return formatDate(value, self.locale)


def translatorFor(locale: str) -> Translator:
  """Build the translator for `locale`; raises if it has no catalog."""
  return Translator(loadCatalog(locale))
