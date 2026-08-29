# SPDX-License-Identifier: Apache-2.0
"""Markdown trial report.

Renders the deliverable an ARM user recognizes: for each numeric assessment, the
AOV Means Table -- the analysis-of-variance table, the lettered treatment means,
the grand mean, the coefficient of variation, and the LSD -- followed by a
reproducibility block (decision 0004): the method, the randomization seed, a
stable hash of the inputs, and the library versions.

The report orchestrates the analysis. A per-assessment analysis that cannot be
performed (a missing cell, a non-numeric assessment) is reported as an explicit
note in that assessment's section rather than silently skipped or failing the
whole report -- the reason is surfaced, never hidden.

Localization (decision 0007): the report is a template, not a wall of text. The
Markdown structure -- headings, pipes, alignment rows -- lives here; every string a
researcher reads comes from the keyed catalog through a `Translator`, and every number
is formatted by it. There are no user-facing literals in this module. Locale is a
display choice and touches nothing canonical: the input hash is computed over the
trial document, so the same trial hashes identically no matter which locale rendered
the report.
"""

from __future__ import annotations

import platform

import numpy

from openfurrow.analysis import (
  AnalysisError,
  analyzeRcbd,
  assessAssumptions,
  methodKeyFor,
  separateMeans,
)
from openfurrow.analysis.transforms import backTransformMean
from openfurrow.i18n import Translator, sourceLocale, translatorFor
from openfurrow.schema.document import TrialDocument, contentHash
from openfurrow.schema.layout import TrialLayout
from openfurrow.schema.observation import Observation
from openfurrow.schema.trialPackage import AssessmentDataType, Transform, TrialPackage
from openfurrow.version import schemaVersion

# The precision p-values print at, and the value below which one rounds to zero at that
# precision. Derived, not written twice: change the decimals and the threshold follows.
_probabilityDecimals = 4
_probabilityThreshold = 10.0 ** -_probabilityDecimals

_scaleKeys = {
  Transform.sqrt: "report.scale.sqrt",
  Transform.log: "report.scale.log",
  Transform.arcsinSqrt: "report.scale.arcsinSqrt",
  Transform.logit: "report.scale.logit",
}


def buildReport(
  package: TrialPackage,
  layout: TrialLayout,
  observations: list[Observation],
  significanceLevel: float = 0.05,
  protected: bool = True,
  locale: str = sourceLocale,
) -> str:
  """Build the full Markdown trial report, rendered in `locale`."""
  if layout.trialCode != package.trial.trialCode:
    raise AnalysisError(
      f"layout trialCode '{layout.trialCode}' does not match package trial '{package.trial.trialCode}'"
    )
  translator = translatorFor(locale)
  lines: list[str] = []
  lines += _metadataSection(package, translator)
  lines += _designSection(package, translator)
  lines += _treatmentsSection(package, translator)
  for assessment in package.assessments:
    lines += _assessmentSection(
      assessment, package, layout, observations, significanceLevel, protected, translator
    )
  lines += _reproducibilitySection(package, observations, significanceLevel, protected, translator)
  return "\n".join(lines).rstrip() + "\n"


def inputHash(package: TrialPackage, observations: list[Observation]) -> str:
  """A stable SHA-256 over the canonical inputs (package and observations).

  Delegates to the shared trial-document content hash so hashing here and export
  elsewhere cannot drift. The layout is regenerable from the package's seed and is
  not hashed separately; observations are sorted so ordering does not affect it.
  Locale never enters: this is canonical data, not display.
  """
  return contentHash(TrialDocument(package=package, observations=list(observations)))


def _field(translator: Translator, key: str, value: object) -> str:
  return f"- {translator.text(key)}: {value}"


def _metadataSection(package: TrialPackage, translator: Translator) -> list[str]:
  trial = package.trial
  lines = [f"# {translator.text('report.heading.trialReport', title=trial.title)}", ""]
  if not translator.isAuthoritative:
    # Decision 0007: a surface showing a non-authoritative locale must say so. The
    # notice is display text like everything else here; the data and hash are untouched.
    lines.append(f"_{translator.text('report.draftNotice')}_")
    lines.append("")
  lines.append(_field(translator, "report.field.trialCode", trial.trialCode))
  lines.append(_field(translator, "report.field.crop", trial.crop))
  lines.append(_field(translator, "report.field.season", trial.season))
  lines.append(_field(translator, "report.field.site", trial.site))
  lines.append(_field(translator, "report.field.objective", trial.objective))
  if trial.investigator:
    lines.append(_field(translator, "report.field.investigator", trial.investigator))
  if trial.organization:
    lines.append(_field(translator, "report.field.organization", trial.organization))
  lines.append("")
  return lines


def _designSection(package: TrialPackage, translator: Translator) -> list[str]:
  return [
    f"## {translator.text('report.heading.design')}",
    "",
    _field(translator, "report.design.design", translator.text("report.design.rcbd")),
    _field(translator, "report.design.treatments", translator.integer(len(package.treatments))),
    _field(translator, "report.design.blocks", translator.integer(package.design.replications)),
    _field(translator, "report.design.plots", translator.integer(package.plotCount)),
    _field(translator, "report.design.seed", translator.integer(package.design.randomizationSeed)),
    "",
  ]


def _treatmentsSection(package: TrialPackage, translator: Translator) -> list[str]:
  absent = translator.text("report.value.absent")
  header = " | ".join(
    translator.text(key)
    for key in (
      "report.treatments.column.code",
      "report.treatments.column.name",
      "report.treatments.column.product",
      "report.treatments.column.rate",
      "report.treatments.column.timing",
    )
  )
  lines = [f"## {translator.text('report.heading.treatments')}", "", f"| {header} |", "|---|---|---|---|---|"]
  for treatment in package.treatments:
    product = treatment.product or translator.text("report.treatments.untreatedControl")
    if treatment.rate is None:
      rate = absent
    else:
      rate = f"{translator.number(treatment.rate, decimals=_significantDecimals(treatment.rate))} {treatment.rateUnit}"
    timing = treatment.timing or absent
    lines.append(f"| {treatment.treatmentCode} | {treatment.name} | {product} | {rate} | {timing} |")
  lines.append("")
  return lines


def _assessmentSection(
  assessment, package, layout, observations, significanceLevel, protected, translator: Translator
) -> list[str]:
  lines = [
    f"## {translator.text('report.heading.assessment', name=assessment.name, code=assessment.assessmentCode)}",
    "",
  ]
  if assessment.dataType is not AssessmentDataType.numeric:
    lines.append(translator.text("report.assessment.notNumeric", dataType=assessment.dataType.value))
    lines.append("")
    return lines
  try:
    result = analyzeRcbd(assessment.assessmentCode, package, layout, observations)
  except AnalysisError as error:
    lines.append(translator.text("report.assessment.notAnalyzed", reason=str(error)))
    lines.append("")
    return lines

  separation = separateMeans(result, significanceLevel=significanceLevel, protected=protected)
  unit = f" ({assessment.unit})" if assessment.unit else ""
  alpha = translator.number(significanceLevel, decimals=2)

  lines.append(f"### {translator.text('report.heading.anova')}")
  lines.append("")
  if result.transform is not Transform.none:
    lines.append(
      translator.text("report.anova.transformedScale", scale=_scaleName(result.transform, translator))
    )
    lines.append("")
  anovaHeader = " | ".join(
    translator.text(key)
    for key in (
      "report.anova.column.source",
      "report.anova.column.degreesOfFreedom",
      "report.anova.column.sumOfSquares",
      "report.anova.column.meanSquare",
      "report.anova.column.fStatistic",
      "report.anova.column.probability",
    )
  )
  lines.append(f"| {anovaHeader} |")
  lines.append("|---|---:|---:|---:|---:|---:|")
  for row in result.table:
    lines.append(
      f"| {translator.text(f'report.anova.source.{row.source}')} "
      f"| {translator.integer(row.degreesOfFreedom)} "
      f"| {translator.number(row.sumOfSquares, decimals=4)} "
      f"| {translator.number(row.meanSquare, decimals=4)} "
      f"| {translator.number(row.fStatistic, decimals=2)} "
      f"| {_probabilityCell(row.pValue, translator)} |"
    )
  lines.append("")
  lines.append(
    _field(translator, "report.anova.grandMean", f"{translator.number(result.grandMean, decimals=3)}{unit}")
  )
  lines.append(
    _field(
      translator,
      "report.anova.coefficientOfVariation",
      f"{translator.number(result.coefficientOfVariation, decimals=2)}%",
    )
  )
  lines.append("")

  treatmentRow = next(row for row in result.table if row.source == "treatment")
  significance = translator.text(
    "report.means.significant" if separation.treatmentSignificant else "report.means.notSignificant"
  )
  lines.append(f"### {translator.text('report.heading.treatmentMeans')}")
  lines.append("")
  lines.append(
    translator.text(
      "report.means.separation",
      method=translator.text(separation.methodKey),
      alpha=alpha,
      significance=significance,
      probability=_probabilityStatement(treatmentRow.pValue, translator),
    )
  )
  lines.append("")
  meanHeaderKey = (
    "report.means.column.mean" if result.transform is Transform.none
    else "report.means.column.meanOriginalScale"
  )
  meanHeader = translator.text(meanHeaderKey, unit=unit)
  lines.append(
    f"| {translator.text('report.means.column.treatment')} | {meanHeader} "
    f"| {translator.text('report.means.column.group')} |"
  )
  lines.append("|---|---:|:--:|")
  for group in separation.groups:
    displayedMean = backTransformMean(result.transform, group.mean)
    lines.append(
      f"| {group.treatmentCode} | {translator.number(displayedMean, decimals=3)} | {group.group} |"
    )
  lines.append("")
  if result.transform is not Transform.none:
    lines.append(
      translator.text("report.means.backTransformNote", scale=_scaleName(result.transform, translator))
    )
    lines.append("")
  lines.append(
    f"- {translator.text('report.means.leastSignificantDifference', alpha=alpha)}: "
    f"{translator.number(separation.leastSignificantDifference, decimals=3)}"
  )
  if protected and not separation.treatmentSignificant:
    lines.append(f"- {translator.text('report.means.notSeparated')}")
  lines.append("")

  lines += _assumptionsSubsection(
    assessment.assessmentCode, package, layout, observations, significanceLevel, translator
  )
  return lines


def _assumptionsSubsection(
  assessmentCode, package, layout, observations, significanceLevel, translator: Translator
) -> list[str]:
  assumptions = assessAssumptions(assessmentCode, package, layout, observations, significanceLevel)
  lines = [
    f"### {translator.text('report.heading.assumptions')}",
    "",
    translator.text("report.assumptions.note", alpha=translator.number(significanceLevel, decimals=2)),
    "",
    _diagnosticLine(assumptions.equalVariance, translator),
    _diagnosticLine(assumptions.nonAdditivity, translator),
    _diagnosticLine(assumptions.normality, translator),
    "",
    translator.text("report.assumptions.residualsNote"),
    "",
  ]
  if assumptions.recommendationKey:
    if assumptions.recommendationTransform is not None:
      detail = translator.text(
        assumptions.recommendationKey,
        kind=assumptions.recommendationKind.value,
        transform=assumptions.recommendationTransform.value,
      )
    else:
      detail = translator.text(assumptions.recommendationKey)
    lines.append(translator.text("report.assumptions.recommendation", recommendation=detail))
    lines.append("")
  return lines


def _diagnosticLine(outcome, translator: Translator) -> str:
  """Render one assumption check in the reader's locale.

  The analysis layer hands back keys and numbers, never sentences, so the wording and
  the number formatting are both resolved here (decision 0007).
  """
  name = translator.text(outcome.nameKey)
  if not outcome.computed:
    return f"- {name}: {translator.text(outcome.notComputedKey, **outcome.notComputedDetail)}"
  if outcome.statisticName == "F":
    statistic = (
      f"F({translator.integer(outcome.numeratorDegreesOfFreedom)}, "
      f"{translator.integer(outcome.denominatorDegreesOfFreedom)}) "
      f"= {translator.number(outcome.statistic, decimals=2)}"
    )
  else:
    statistic = f"{outcome.statisticName} = {translator.number(outcome.statistic, decimals=4)}"
  reading = translator.text(
    "diagnostic.reading",
    verdict=translator.text(outcome.readingKey),
    probability=_probabilityStatement(outcome.pValue, translator),
  )
  return f"- {name}: {statistic}. {reading}"


def _reproducibilitySection(
  package, observations, significanceLevel, protected, translator: Translator
) -> list[str]:
  test = translator.text(methodKeyFor(protected))
  method = translator.text(
    "report.reproducibility.methodValue",
    test=test,
    alpha=translator.number(significanceLevel, decimals=2),
  )
  lines = [
    f"## {translator.text('report.heading.reproducibility')}",
    "",
    _field(translator, "report.reproducibility.method", method),
    _field(
      translator, "report.reproducibility.seed",
      translator.integer(package.design.randomizationSeed),
    ),
  ]
  transformed = [
    f"{assessment.assessmentCode} = {assessment.transform.value}"
    for assessment in package.assessments
    if assessment.transform is not Transform.none
  ]
  if transformed:
    lines.append(_field(translator, "report.reproducibility.transforms", ", ".join(transformed)))
  # The input hash is canonical, not display: it is the same in every locale.
  lines.append(
    _field(translator, "report.reproducibility.inputHash", inputHash(package, observations))
  )
  lines.append(
    "- "
    + translator.text(
      "report.reproducibility.versions",
      openfurrow=schemaVersion,
      numpy=numpy.__version__,
      python=platform.python_version(),
    )
  )
  lines.append("")
  return lines


def _scaleName(transform, translator: Translator) -> str:
  key = _scaleKeys.get(transform)
  if key is None:
    raise AnalysisError(f"no report scale name for transform '{transform.value}'")
  return translator.text(key)


def _significantDecimals(value: float) -> int:
  """Rate is authored data: show it as written, not padded to a fixed width."""
  return 0 if float(value).is_integer() else 2


def _belowProbabilityThreshold(value: float) -> bool:
  """True when a p-value would round to zero at the precision reports print.

  This is a display-precision fact, not a statistical one: nothing in the analysis
  result is censored, and the threshold is derived from the printed precision rather
  than written out a second time.
  """
  return value < _probabilityThreshold


def _probabilityCell(value, translator: Translator) -> str:
  """A p-value as an ANOVA table cell.

  The column is headed P, so an ordinary value carries no operator; only the censored
  case needs one.
  """
  if value is None:
    return translator.text("report.value.absent")
  if _belowProbabilityThreshold(value):
    return translator.text(
      "report.value.lessThan",
      value=translator.number(_probabilityThreshold, decimals=_probabilityDecimals),
    )
  return translator.number(value, decimals=_probabilityDecimals)


def _probabilityStatement(value, translator: Translator) -> str:
  """A p-value as prose: the operator and the number, for a sentence reading `P {...}`.

  The operator is rendered from the catalog rather than written into the sentence, so
  the censored case reads `P < 0.0001` instead of the malformed `P = <0.0001`, and the
  number goes through the locale formatter like every other number in the report.
  """
  if value is None:
    return translator.text("report.value.absent")
  if _belowProbabilityThreshold(value):
    return translator.text(
      "report.value.lessThan",
      value=translator.number(_probabilityThreshold, decimals=_probabilityDecimals),
    )
  return translator.text(
    "report.value.equalTo",
    value=translator.number(value, decimals=_probabilityDecimals),
  )
