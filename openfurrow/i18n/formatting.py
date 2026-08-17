# SPDX-License-Identifier: Apache-2.0
"""Locale-aware formatting of numbers and dates for display (decision 0007).

**The load-bearing rule: locale affects display only.** The stored data, the JSON/CSV
exchange, and the content hash stay locale-independent -- ISO 8601 dates, dot-decimal,
no thousands grouping. Nothing here is ever used to produce canonical data. If it were,
the same trial would hash differently for a US and a Brazilian operator (silently
breaking reproducibility), and a comma-decimal CSV would round-trip corrupted numbers.
Canonical stays neutral; this module is the display layer on top of it. The test suite
asserts the hash is identical across locales.

Its second job is to exist at all: it gives every user-facing surface one place to
format a number or a date, so no code path reaches for `str(value)` or an f-string and
bakes in US conventions by accident.

**On CLDR.** Decision 0007 requires locale rules to come from Unicode CLDR rather than
being hand-rolled, but it also defers the i18n library/mechanism to the GUI-stack
choice, so this module does not pick one. The table below is a deliberately small
interim stand-in covering exactly the locales in play, and `LocaleFormat` is the seam a
CLDR-backed implementation (Babel or ICU) drops into when that decision is made -- at
which point the table goes away and callers do not change. It is not a claim to be CLDR
and must not grow into a hand-rolled reimplementation of it: adding locales here beyond
the ones actually shipped is the signal that the real mechanism is overdue.
"""

from __future__ import annotations

from datetime import date


class LocaleFormat:
  """How one locale renders numbers and dates for display."""

  def __init__(
    self,
    decimalSeparator: str,
    groupSeparator: str,
    dateOrder: str,
  ) -> None:
    self.decimalSeparator = decimalSeparator
    self.groupSeparator = groupSeparator
    self.dateOrder = dateOrder            # "MDY", "DMY", or "YMD"


class FormattingError(Exception):
  """A locale has no formatting rules, or a value cannot be formatted."""


# The locales actually in play. en-US and en-GB are the reviewed English locales; es, fr,
# and ar carry machine-draft catalogs (decision 0007's LLM-assisted first pass) and their
# formatting rows here follow CLDR conventions for each locale. Draft convention decision
# for ar, pending native review: Western (ASCII) digits with dot decimal, as is common in
# Arabic scientific writing, rather than CLDR's default Arabic-Indic digits -- this
# formatter only swaps separators and cannot produce digit-shape substitution anyway.
#
# This table has now grown to the size the L0 note warned about: per the implementation
# plan, adopting the real CLDR mechanism (Babel) is due as its own unit, at which point
# this table is deleted and `LocaleFormat` remains the seam.
_localeFormats: dict[str, LocaleFormat] = {
  "en-US": LocaleFormat(decimalSeparator=".", groupSeparator=",", dateOrder="MDY"),
  "en-GB": LocaleFormat(decimalSeparator=".", groupSeparator=",", dateOrder="DMY"),
  "es": LocaleFormat(decimalSeparator=",", groupSeparator=".", dateOrder="DMY"),
  "fr": LocaleFormat(decimalSeparator=",", groupSeparator=" ", dateOrder="DMY"),
  "ar": LocaleFormat(decimalSeparator=".", groupSeparator=",", dateOrder="DMY"),
}


def formatFor(locale: str) -> LocaleFormat:
  """The formatting rules for `locale`; raises if there are none."""
  if locale not in _localeFormats:
    raise FormattingError(
      f"no formatting rules for locale '{locale}'; known: {', '.join(sorted(_localeFormats))}"
    )
  return _localeFormats[locale]


def formatNumber(
  value: float | None,
  locale: str,
  decimals: int,
  useGrouping: bool = False,
  absent: str = "-",
) -> str:
  """Render a number for display in `locale` to a fixed number of decimals.

  `absent` is what a missing value shows as. Grouping is off by default: it is right
  for prose and wrong for a dense results table, so the caller decides.
  """
  if value is None:
    return absent
  rules = formatFor(locale)
  rendered = f"{value:,.{decimals}f}" if useGrouping else f"{value:.{decimals}f}"

  # Python formats with US conventions; swap in the locale's separators. The temporary
  # placeholder avoids clobbering a locale whose group separator is the US decimal point.
  rendered = rendered.replace(",", "\x00").replace(".", rules.decimalSeparator)
  return rendered.replace("\x00", rules.groupSeparator if useGrouping else "")


def formatInteger(value: int, locale: str, useGrouping: bool = False) -> str:
  """Render an integer for display in `locale`."""
  rules = formatFor(locale)
  if not useGrouping:
    return str(value)
  return f"{value:,}".replace(",", rules.groupSeparator)


def formatDate(value: date, locale: str) -> str:
  """Render a date for display in `locale`.

  US and UK English differ here (MM/DD/YYYY vs DD/MM/YYYY), which is the whole reason
  the locale, not the language, is the unit of localization. Canonical dates stay ISO
  8601 and never pass through this function.
  """
  rules = formatFor(locale)
  day, month, year = f"{value.day:02d}", f"{value.month:02d}", f"{value.year:04d}"
  if rules.dateOrder == "MDY":
    return f"{month}/{day}/{year}"
  if rules.dateOrder == "DMY":
    return f"{day}/{month}/{year}"
  if rules.dateOrder == "YMD":
    return f"{year}-{month}-{day}"
  raise FormattingError(f"locale '{locale}' has an unknown date order '{rules.dateOrder}'")


# Scripts that read right-to-left. Decision 0007 requires the UI to mirror its layout,
# not just its glyphs, for these -- so direction is derived from the locale's language
# subtag and set on the document, structurally, from the first UI code. None of these
# locales ships yet; the mechanism is here so RTL is designed in, not retrofitted.
_rightToLeftLanguages = {"ar", "fa", "ur", "he", "ps", "sd", "ug", "yi"}


def textDirection(locale: str) -> str:
  """The base text direction for `locale`: 'rtl' for right-to-left scripts, else 'ltr'."""
  language = locale.replace("_", "-").split("-")[0].lower()
  return "rtl" if language in _rightToLeftLanguages else "ltr"
