# SPDX-License-Identifier: Apache-2.0
"""Tests for the localization scaffolding (L0, decision 0007).

Three things are being defended here.

1. **The canonical guardrail, which is load-bearing.** Locale affects display only. The
   same trial must hash identically no matter which locale rendered its report, and the
   exchange must stay dot-decimal and locale-neutral. If this ever breaks, the same
   trial hashes differently for a US and a Brazilian operator and reproducibility --
   the entire point of the project -- silently dies.

2. **Catalog integrity.** Every locale covers the full key set, placeholders match
   across locales (they are machinery, fenced from translation), and every miss --
   unknown locale, missing key, wrong placeholders -- fails loud rather than rendering
   something plausible and wrong.

3. **Translation-status honesty.** A locale carrying unreviewed machine drafts is not
   authoritative and must report itself as such.
"""

import csv
import json
from datetime import date
from pathlib import Path

import pytest

from openfurrow import TrialPackage, Workspace, contentHash, defaultConfig
from openfurrow.i18n import (
  Catalog,
  FormattingError,
  MessageError,
  MessageStatus,
  availableLocales,
  formatDate,
  formatNumber,
  loadCatalog,
  placeholdersIn,
  sourceLocale,
  translatorFor,
)

_localeDirectory = Path("openfurrow/i18n/locales")

_packageDict = {
  "schemaVersion": "0.1.0",
  "trial": {"trialCode": "L10N-1", "title": "Localization trial", "crop": "Barley",
            "season": "2025", "site": "Field A", "objective": "Compare treatments"},
  "treatments": [{"treatmentCode": code, "name": code} for code in ["A", "B", "C", "D"]],
  "design": {"designType": "rcbd", "replications": 3, "randomizationSeed": 7},
  "assessments": [{"assessmentCode": "YIELD", "name": "Yield", "dataType": "numeric",
                   "unit": "kg/ha", "minValue": 0}],
}
_values = {
  ("A", 1): 106, ("A", 2): 99, ("A", 3): 95, ("B", 1): 103, ("B", 2): 100, ("B", 3): 94,
  ("C", 1): 86, ("C", 2): 79, ("C", 3): 75, ("D", 1): 83, ("D", 2): 80, ("D", 3): 74,
}


@pytest.fixture
def workspace(tmp_path):
  ws = Workspace.create(str(tmp_path / "trials.db"))
  package = TrialPackage.model_validate(_packageDict)
  ws.addPackage(package)
  layout = ws.layoutFor("L10N-1")
  csvPath = tmp_path / "obs.csv"
  with csvPath.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.writer(handle)
    writer.writerow(["plotNumber", "assessmentCode", "value"])
    for plot in sorted(layout.plots, key=lambda plot: plot.plotNumber):
      writer.writerow([plot.plotNumber, "YIELD", _values[(plot.treatmentCode, plot.block)]])
  ws.importObservations("L10N-1", str(csvPath), defaultConfig().importProfile)
  return ws


# ---- 1. the canonical guardrail: locale is display only -------------------

def testContentHashIsIdenticalAcrossLocales(workspace, tmp_path):
  """Rendering a report in another locale must not change the trial's hash."""
  before = workspace.contentHashFor("L10N-1")
  workspace.buildReport("L10N-1", locale="en-US")
  workspace.buildReport("L10N-1", locale="en-GB")
  assert workspace.contentHashFor("L10N-1") == before


def testReportedInputHashIsIdenticalAcrossLocales(workspace):
  """The hash printed *inside* the report is canonical: same in every locale."""
  def hashLine(locale):
    report = workspace.buildReport("L10N-1", locale=locale)
    return next(line for line in report.splitlines() if "SHA-256" in line).split(": ")[-1]

  assert hashLine("en-US") == hashLine("en-GB") == workspace.contentHashFor("L10N-1")


def testExchangeStaysLocaleNeutral(workspace, tmp_path):
  """Canonical export is dot-decimal regardless of any locale used for display."""
  workspace.buildReport("L10N-1", locale="en-GB")
  csvPath = tmp_path / "out.csv"
  workspace.exportObservationsCsv("L10N-1", str(csvPath))
  text = csvPath.read_text(encoding="utf-8")
  assert "106.0" in text                       # dot-decimal, not "106,0"
  assert ";" not in text                       # not a comma-decimal CSV dialect

  jsonPath = tmp_path / "out.json"
  workspace.exportDocument("L10N-1", str(jsonPath))
  document = json.loads(jsonPath.read_text(encoding="utf-8"))
  assert document["observations"][0]["value"] == 106.0   # a JSON number, not a string


def testCommaDecimalLocaleFormatsDisplayButNotCanonical(workspace, tmp_path):
  """A comma-decimal locale changes display only -- the hash is untouched.

  fr is the case decision 0007 names explicitly: if locale leaked into canonical form,
  a French operator's export would carry "1,5" and round-trip corrupted.
  """
  assert formatNumber(1.5, "fr", decimals=1) == "1,5"
  assert formatNumber(1.5, "en-US", decimals=1) == "1.5"
  before = workspace.contentHashFor("L10N-1")
  workspace.exportDocument("L10N-1", str(tmp_path / "doc.json"))
  assert workspace.contentHashFor("L10N-1") == before


# ---- 2. catalog integrity -------------------------------------------------

def testEveryLocaleCoversTheFullKeySet():
  """A locale is complete or it is not shipped -- no silent English fallback."""
  sourceKeys = loadCatalog(sourceLocale).keys
  assert sourceKeys                                   # the source catalog is not empty
  for locale in availableLocales():
    missing = sourceKeys - loadCatalog(locale).keys
    extra = loadCatalog(locale).keys - sourceKeys
    assert missing == set(), f"{locale} is missing {sorted(missing)}"
    assert extra == set(), f"{locale} defines unknown keys {sorted(extra)}"


def testPlaceholdersMatchAcrossLocales():
  """Placeholders are machinery, fenced from translation: they must not drift."""
  source = loadCatalog(sourceLocale)
  for locale in availableLocales():
    catalog = loadCatalog(locale)
    for key in source.keys:
      assert placeholdersIn(catalog.text(key)) == placeholdersIn(source.text(key)), (
        f"{locale}:{key} placeholders differ from {sourceLocale}"
      )


def testUnknownLocaleFailsLoud():
  with pytest.raises(MessageError):
    translatorFor("xx-XX")


def testMissingKeyFailsLoud():
  with pytest.raises(MessageError):
    translatorFor(sourceLocale).text("report.does.not.exist")


def testMissingPlaceholderFailsLoud():
  with pytest.raises(MessageError):
    translatorFor(sourceLocale).text("report.heading.trialReport")   # needs {title}


def testUnusedPlaceholderFailsLoud():
  with pytest.raises(MessageError):
    translatorFor(sourceLocale).text("report.field.crop", title="unexpected")


def testUnknownFormattingLocaleFailsLoud():
  with pytest.raises(FormattingError):
    formatNumber(1.0, "xx-XX", decimals=2)


# ---- 3. translation-status honesty ---------------------------------------

def testSourceLocaleIsAuthoritative():
  assert translatorFor(sourceLocale).isAuthoritative is True


def testMachineDraftLocaleIsNotAuthoritative():
  """An unreviewed machine draft must report itself as non-authoritative."""
  catalog = Catalog("xx", {
    "a": ("Reviewed", MessageStatus.humanApproved),
    "b": ("Unreviewed", MessageStatus.machineDraft),
  })
  assert catalog.isAuthoritative is False
  assert catalog.statusSummary()[MessageStatus.machineDraft] == 1


def testEveryShippedLocaleIsAuthoritative():
  """Nothing unreviewed ships: every catalog on disk is source or human-approved."""
  for locale in availableLocales():
    assert loadCatalog(locale).isAuthoritative is True, f"{locale} carries unreviewed drafts"


# ---- locale actually changes the display ----------------------------------

def testBritishLocaleUsesBritishSpelling(workspace):
  american = workspace.buildReport("L10N-1", locale="en-US")
  british = workspace.buildReport("L10N-1", locale="en-GB")
  assert "Randomization seed" in american
  assert "Randomisation seed" in british
  assert american != british


def testDateOrderDiffersBetweenEnglishLocales():
  """The US/UK date-order split is the reason a locale, not a language, is the unit."""
  when = date(2025, 6, 1)
  assert formatDate(when, "en-US") == "06/01/2025"
  assert formatDate(when, "en-GB") == "01/06/2025"


def testReportContainsNoUntranslatedSourceLeak(workspace):
  """The en-GB report must not carry the American spellings it overrides."""
  british = workspace.buildReport("L10N-1", locale="en-GB")
  assert "Randomization" not in british
