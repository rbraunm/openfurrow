# SPDX-License-Identifier: Apache-2.0
"""How a page says a size and a retention rule (decision 0044): the words the trial's page and the retention pages
of the administration area share."""

from __future__ import annotations

from openfurrow.retention import RetentionRule

_sizeUnits = (("gigabytes", 10 ** 9), ("megabytes", 10 ** 6), ("kilobytes", 10 ** 3))


def sizeText(count: int, translator) -> str:
  for unit, bytesIn in _sizeUnits:
    if count >= bytesIn:
      return translator.text(f"web.size.{unit}", count=translator.number(count / bytesIn, decimals=1))
  return translator.text("web.size.bytes", count=translator.integer(count))


def ruleText(rule: str, translator) -> str:
  """A retention rule in the reader's words."""
  read = RetentionRule.read(rule)
  if read.period is None:
    return translator.text("web.retention.rule.keep")
  unit = read.period.unit.name
  period = (translator.text(f"web.retention.period.one.{unit}") if read.period.count == 1
            else translator.text(f"web.retention.period.{unit}", count=translator.integer(read.period.count)))
  return translator.text(f"web.retention.rule.{read.policy.value}", period=period)
