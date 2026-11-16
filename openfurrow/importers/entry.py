# SPDX-License-Identifier: Apache-2.0
"""Values typed by a person, read against their rating (decision 0023).

A typed value is text. It is read in two strengths: what cannot be a value at all (not a
number, a category the rating does not have, a number written with both a point and a
comma) is refused; a number outside the rating's limits is accepted only once the person
confirms it. An empty box is no value. A number may be written with the decimal mark of
the reader's locale or with a point; grouping marks are not read.
"""

from __future__ import annotations

import re

from openfurrow.schema.assessment import AssessmentDataType, Rating

_number = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")


class EntryRefused(ValueError):
  """A typed value that cannot be a value of its rating; `reasonKey` names why for display."""

  def __init__(self, reasonKey: str, **placeholders: str) -> None:
    super().__init__(reasonKey)
    self.reasonKey = reasonKey
    self.placeholders = placeholders


def readEntry(text: str, rating: Rating, decimalSeparator: str) -> float | str | None:
  """The value a typed text stands for; None for an empty box. Raises EntryRefused."""
  text = text.strip()
  if not text:
    return None
  if rating.dataType is not AssessmentDataType.numeric:
    if text not in rating.allowedValues:
      raise EntryRefused("web.entry.refused.notCategory", values=" / ".join(rating.allowedValues))
    return text
  if decimalSeparator != ".":
    if decimalSeparator in text and "." in text:
      raise EntryRefused("web.entry.refused.twoDecimalMarks")
    text = text.replace(decimalSeparator, ".")
  if not _number.match(text):
    raise EntryRefused("web.entry.refused.notNumber")
  return float(text)


def writeEntry(value: float | str | None, decimalSeparator: str) -> str:
  """A stored value as it is shown in an entry box: as entered, in the reader's decimal mark."""
  if value is None:
    return ""
  if isinstance(value, str):
    return value
  written = str(int(value)) if value.is_integer() else repr(value)
  return written.replace(".", decimalSeparator)
