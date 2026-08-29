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


# ---- p-values are comparisons, and comparisons obey the locale --------------
#
# Regression: the below-threshold p-value used to be one catalog literal, "<0.0001",
# dropped into a sentence that already supplied its own operator. That produced the
# mathematically malformed "P = <0.0001", and because the literal carried its own
# digits it was the one number in the whole report that ignored the locale -- a French
# report read "alpha = 0,05" and "P = <0.0001" on the same line. The operator now comes
# from the catalog and the number from the formatter, so both faults are structural
# impossibilities rather than strings to keep an eye on.

def testNoLocaleEmitsADoubledComparisonOperator(workspace):
  """No report may pair an equals sign with a second comparison operator."""
  for locale in availableLocales():
    report = workspace.buildReport("L10N-1", locale=locale)
    for malformed in ("= <", "= >", "=<", "=>"):
      assert malformed not in report, f"{locale} report emitted '{malformed}'"


def testBelowThresholdProbabilityUsesTheLocaleDecimalSeparator(workspace):
  """The censored p-value is formatted like every other number, not preformatted.

  The L10N-1 fixture's treatment effect is far below the printed precision, so every
  locale renders the below-threshold form here.
  """
  assert "P < 0.0001" in workspace.buildReport("L10N-1", locale="en-US")
  for locale in ("es", "fr"):
    report = workspace.buildReport("L10N-1", locale=locale)
    assert "P < 0,0001" in report, f"{locale} did not localize the threshold decimal"
    assert "0.0001" not in report, f"{locale} left a dot-decimal threshold in place"


def testOrdinaryAndThresholdProbabilitiesShareOneDecimalPolicy(workspace):
  """A locale cannot format ordinary p-values one way and the threshold another."""
  for locale, separator in (("en-US", "."), ("es", ","), ("fr", ",")):
    report = workspace.buildReport("L10N-1", locale=locale)
    assert f"P = 0{separator}9878" in report      # an ordinary diagnostic p-value
    assert f"P < 0{separator}0001" in report      # the censored treatment p-value


def testAnovaColumnCarriesNoRedundantEqualsSign(workspace):
  """The P column is headed P, so ordinary cells are bare; only the censored one is not."""
  report = workspace.buildReport("L10N-1", locale="en-US")
  # The means table also has a Treatment column; the ANOVA row is the six-cell one.
  anovaRows = [
    line for line in report.splitlines()
    if line.startswith("| Treatment |") and len(line.strip("| ").split(" | ")) == 6
  ]
  assert len(anovaRows) == 1
  assert anovaRows[0].endswith("| < 0.0001 |")
  assert "= " not in anovaRows[0]


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


_reviewedLocales = {"en-US", "en-GB"}
_draftLocales = {"es", "fr", "ar"}


def testReviewedLocalesAreAuthoritative():
  """The English locales are fully reviewed: every string is source or human-approved."""
  for locale in sorted(_reviewedLocales):
    assert loadCatalog(locale).isAuthoritative is True, f"{locale} carries unreviewed drafts"


def testDraftLocalesAreMarkedAsDrafts():
  """A machine-draft locale must say so, string by string (decision 0007).

  Shipping a draft is allowed; shipping it *quietly* is not. Every string in a draft
  locale is machineDraft (a mixed catalog would mean someone approved strings without a
  review pass), the catalog reports itself non-authoritative, and the shipped set is
  exactly the reviewed plus the draft locales -- a new locale must be classified here.
  """
  for locale in sorted(_draftLocales):
    catalog = loadCatalog(locale)
    assert catalog.isAuthoritative is False, f"{locale} claims to be reviewed"
    summary = catalog.statusSummary()
    assert summary[MessageStatus.machineDraft] == len(catalog.keys), (
      f"{locale} has strings not marked machineDraft"
    )
  assert set(availableLocales()) == _reviewedLocales | _draftLocales


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


# ---- the analysis layer emits keys, not prose -----------------------------

def testDiagnosticsCarryKeysNotSentences(workspace):
  """The analysis layer must hand back message keys and numbers, never English.

  Regression: the diagnostics once built their own sentences ("No evidence of unequal
  variance"), which the report printed verbatim -- so a non-English report still read in
  English. Keys keep the wording in the display layer where decision 0007 puts it.
  """
  assumptions = workspace.assessAssumptions("L10N-1", "YIELD")
  for outcome in (assumptions.equalVariance, assumptions.nonAdditivity, assumptions.normality):
    assert outcome.nameKey.startswith("diagnostic.")
    key = outcome.readingKey if outcome.computed else outcome.notComputedKey
    assert key is not None and key.startswith("diagnostic.")
    # No field carries a rendered sentence.
    assert " " not in outcome.nameKey and " " not in key


def testMeanSeparationCarriesAKeyNotAMethodName(workspace):
  """The method name is a catalog key, not a display string built in the analysis.

  Regression: separateMeans used to set method="Fisher's Protected LSD", an English
  sentence fragment inside a canonical analysis result. The report printed it verbatim,
  so the one line of every non-English report that names the statistical method was in
  English. testDiagnosticsCarryKeysNotSentences already forbade this for diagnostics;
  mean separation was the gap it did not cover.
  """
  for protected, expected in ((True, "report.method.fisherProtectedLSD"),
                              (False, "report.method.fisherLSD")):
    separation = workspace.separateMeans(
      "L10N-1", "YIELD", significanceLevel=0.05, protected=protected)
    assert separation.methodKey == expected
    assert " " not in separation.methodKey


def testMethodNameIsLocalizedInEveryLocale(workspace):
  """The method name resolves per locale and is not the English string in any of them."""
  for locale in availableLocales():
    report = workspace.buildReport("L10N-1", locale=locale)
    rendered = loadCatalog(locale).text("report.method.fisherProtectedLSD")
    assert rendered in report, f"{locale} did not render its own method name"
  english = loadCatalog("en-US").text("report.method.fisherProtectedLSD")
  for locale in ("es", "fr", "ar"):
    assert english not in workspace.buildReport("L10N-1", locale=locale), (
      f"{locale} report carried the English method name")


def testEveryDiagnosticKeyResolvesInEveryLocale(workspace):
  """Every key the analysis can emit must exist in every shipped catalog.

  A key with no catalog entry raises at render time, so this is what stops a diagnostic
  from breaking a report in one locale but not another.
  """
  assumptions = workspace.assessAssumptions("L10N-1", "YIELD")
  keys = []
  for outcome in (assumptions.equalVariance, assumptions.nonAdditivity, assumptions.normality):
    keys.append(outcome.nameKey)
    keys.append(outcome.readingKey if outcome.computed else outcome.notComputedKey)
  for locale in availableLocales():
    catalog = loadCatalog(locale)
    for key in keys:
      assert key in catalog.keys, f"{locale} is missing {key}"


def testDiagnosticTextFollowsTheLocale(workspace, tmp_path):
  """A report in another locale renders the diagnostics in that locale.

  Uses a temporary catalog with two diagnostic strings overridden, so the assertion is
  about the mechanism (the text follows the catalog) rather than about any shipped
  translation.
  """
  import json

  from openfurrow.i18n.catalog import _localeDirectory

  source = json.loads((_localeDirectory / f"{sourceLocale}.json").read_text(encoding="utf-8"))
  source["locale"] = "fr"                       # fr has formatting rules but no catalog
  for entry in source["messages"].values():
    entry["status"] = "humanApproved"
  source["messages"]["diagnostic.equalVariance.clear"]["text"] = "VERDICT-IN-LOCALE"
  temporary = _localeDirectory / "fr.json"
  # fr ships a real catalog now: save it and put it back, never delete it.
  original = temporary.read_bytes()
  temporary.write_text(json.dumps(source, indent=2, ensure_ascii=False), encoding="utf-8")
  try:
    before = workspace.contentHashFor("L10N-1")
    localized = workspace.buildReport("L10N-1", locale="fr")
    assert "VERDICT-IN-LOCALE" in localized
    assert "No evidence of unequal variance" not in localized
    assert workspace.contentHashFor("L10N-1") == before
  finally:
    temporary.write_bytes(original)


# ---- draft locales surface their status (decision 0007) --------------------

def testReportCarriesDraftNoticeInDraftLocale(workspace):
  """A report in a machine-draft locale says so, right under the title; a reviewed
  locale never shows the notice. Display only: the hash is identical either way."""
  before = workspace.contentHashFor("L10N-1")
  spanish = workspace.buildReport("L10N-1", locale="es")
  english = workspace.buildReport("L10N-1", locale="en-US")
  assert "Traducción preliminar" in spanish
  assert "Draft translation" not in english
  assert workspace.contentHashFor("L10N-1") == before


def testDraftReportIsFullyLocalized(workspace):
  """No English leaks into a draft-locale report body."""
  spanish = workspace.buildReport("L10N-1", locale="es")
  for english in ("Randomization seed", "Analysis of variance", "Grand mean",
                  "No evidence", "Coefficient of variation"):
    assert english not in spanish, f"English '{english}' leaked into the es report"
  assert "Análisis de varianza" in spanish
  assert "Semilla de aleatorización" in spanish
