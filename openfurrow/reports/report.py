# SPDX-License-Identifier: Apache-2.0
"""Markdown trial report.

Renders the deliverable an ARM user recognizes: the trial as recorded -- its design,
its treatments with their product lines, its applications (decision 0016), its ratings
and the assessments they are taken on (decision 0017) -- then, for
each numeric assessment, the AOV Means Table -- the analysis-of-variance table, the
lettered treatment means, the grand mean, the coefficient of variation, and the LSD --
followed by a reproducibility block (decision 0004): the method, the randomization
seed, a stable hash of the inputs, and the library versions.

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
from decimal import Decimal

import numpy

from openfurrow.analysis import (
  AnalysisError,
  analyzeCrd,
  analyzeEfficacy,
  analyzeFactorialRcbd,
  factorialInteractionComparisons,
  letterGroups,
  splitPlotInteractionComparisons,
  separateFactorialMeans,
  analyzeHalves,
  analyzeRcbd,
  checkPairs,
  compareWithChecks,
  analyzeSplitPlot,
  separateFactorMeans,
  assessAssumptions,
  methodKeyFor,
  separateMeans,
)
from openfurrow.analysis.transforms import backTransformMean
from openfurrow.i18n import Translator, sourceLocale, translatorFor
from openfurrow.schema.application import Application
from openfurrow.schema.document import TrialDocument, contentHash
from openfurrow.schema.layout import TrialLayout
from openfurrow.schema.observation import Observation
from openfurrow.schema.quantity import Quantity
from openfurrow.schema.treatment import ActiveSubstance, TreatmentLine
from openfurrow.schema.assessment import AssessmentDataType, Rating, Transform
from openfurrow.schema.trialPackage import CheckArrangement, DesignType, RandomizationMethod, TrialPackage
from openfurrow.version import softwareVersion

# The precision p-values print at, and the value below which one rounds to zero at that
# precision. Derived, not written twice: change the decimals and the threshold follows.
_probabilityDecimals = 4
_probabilityThreshold = 10.0 ** -_probabilityDecimals

_scaleKeys = {
  Transform.sqrt: "report.scale.sqrt",
  Transform.log: "report.scale.log",
  Transform.log10: "report.scale.log10",
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
  lines += _siteSection(package, translator)
  lines += _plantingSection(package, translator)
  lines += _designSection(package, translator)
  lines += _targetsSection(package, translator)
  lines += _treatmentsSection(package, translator)
  lines += _applicationsSection(package, translator)
  lines += _soilSection(package, translator)
  lines += _weatherSection(package, translator)
  lines += _ratingsSection(package, translator)
  lines += _assessmentsSection(package, translator)
  for assessment in package.assessments:
    lines += _assessmentSection(
      assessment, package, layout, observations, significanceLevel, protected, translator
    )
  lines += _reproducibilitySection(
    package, layout, observations, significanceLevel, protected, translator
  )
  return "\n".join(lines).rstrip() + "\n"


def inputHash(package: TrialPackage, layout: TrialLayout, observations: list[Observation]) -> str:
  """A stable SHA-256 over the canonical inputs (package, layout and observations).

  Delegates to the shared trial-document content hash so hashing here and export
  elsewhere cannot drift. Plots and observations are sorted, so ordering does not
  affect it. Locale never enters: this is canonical data, not display.
  """
  return contentHash(
    TrialDocument(
      package=package, layout=layout.plots, checkPlots=layout.checkPlots, observations=list(observations),
    )
  )


def _field(translator: Translator, key: str, value: object, /, **labelPlaceholders) -> str:
  label = translator.text(key, **labelPlaceholders)
  return f"- {translator.text('report.labelValue', label=label, value=value)}"


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


def _siteSection(package: TrialPackage, translator: Translator) -> list[str]:
  site = package.siteDetails
  if site is None:
    return []

  def degrees(value: float) -> str:
    return translator.number(value, decimals=_authoredDecimals(value))

  facts = {
    "address": site.address,
    "position": None if site.latitude is None else translator.text(
      "report.site.positionValue", latitude=degrees(site.latitude), longitude=degrees(site.longitude),
    ),
    "elevation": None if site.elevation is None else _quantityText(site.elevation, translator),
    "setting": None if site.setting is None else translator.text(f"report.site.setting.{site.setting.value}"),
    "exposure": site.exposure,
    "slope": site.slope,
  }
  return _factList("report.heading.site", "report.site.", facts, translator)


def _plantingSection(package: TrialPackage, translator: Translator) -> list[str]:
  planting = package.planting
  if planting is None:
    return []

  def amount(quantity: Quantity | None) -> str | None:
    return None if quantity is None else _quantityText(quantity, translator)

  def day(value) -> str | None:
    return None if value is None else translator.date(value)

  facts = {
    "cultivar": planting.cultivar,
    "cropEPPOCode": planting.cropEPPOCode,
    "sowingDate": day(planting.sowingDate),
    "seedingRate": amount(planting.seedingRate),
    "plantDensity": amount(planting.plantDensity),
    "rowSpacing": amount(planting.rowSpacing),
    "inRowSpacing": amount(planting.inRowSpacing),
    "sowingDepth": amount(planting.sowingDepth),
    "emergenceDate": day(planting.emergenceDate),
    "precedingCrop": planting.precedingCrop,
    "tillage": planting.tillage,
    "trainingSystem": planting.trainingSystem,
    "rootstock": planting.rootstock,
    "plantedYear": None if planting.plantedYear is None else str(planting.plantedYear),
    "notes": planting.notes,
  }
  return _factList("report.heading.planting", "report.planting.", facts, translator)


def _soilSection(package: TrialPackage, translator: Translator) -> list[str]:
  soil = package.soil
  if soil is None:
    return []
  facts = {
    "soilType": soil.soilType,
    "texture": soil.texture,
    "pH": None if soil.pH is None else translator.number(soil.pH, decimals=_authoredDecimals(soil.pH)),
    "pHMethod": soil.pHMethod,
    "organicMatter": None if soil.organicMatter is None else translator.text(
      "report.value.percent",
      value=translator.number(soil.organicMatter, decimals=_authoredDecimals(soil.organicMatter)),
    ),
    "seedbedQuality": soil.seedbedQuality,
    "fertilizerRegime": soil.fertilizerRegime,
    "notes": soil.notes,
  }
  return _factList("report.heading.soil", "report.soil.", facts, translator)


def _factList(headingKey: str, labelPrefix: str, facts: dict[str, str | None], translator: Translator) -> list[str]:
  """A heading and one line for each fact that is recorded."""
  return [
    f"## {translator.text(headingKey)}",
    "",
    *(_field(translator, labelPrefix + name, value) for name, value in facts.items() if value is not None),
    "",
  ]


def _weatherSection(package: TrialPackage, translator: Translator) -> list[str]:
  if not package.weather:
    return []
  header = [
    translator.text(f"report.weather.column.{column}")
    for column in ("date", "rainfall", "irrigation", "minimumTemperature", "maximumTemperature", "notes")
  ]

  def amount(quantity: Quantity | None) -> str | None:
    return None if quantity is None else _quantityText(quantity, translator)

  rows = [
    [
      translator.date(record.date),
      amount(record.rainfall),
      amount(record.irrigation),
      amount(record.minimumTemperature),
      amount(record.maximumTemperature),
      record.notes,
    ]
    for record in package.weather
  ]
  return [
    f"## {translator.text('report.heading.weather')}",
    "",
    *_filledTable(header, rows, translator),
    "",
  ]


def _designSection(package: TrialPackage, translator: Translator) -> list[str]:
  design = package.design
  lines = [
    f"## {translator.text('report.heading.design')}",
    "",
    _field(translator, "report.design.design", translator.text(f"report.design.{design.designType.value}")),
    _field(translator, "report.design.treatments", translator.integer(len(package.treatments))),
    _field(translator, "report.design.blocks", translator.integer(design.replications)),
    _field(translator, "report.design.plots", translator.integer(package.plotCount)),
  ]
  if design.plotDimensions is not None:
    dimensions = design.plotDimensions
    for name in ("grossLength", "grossWidth", "netLength", "netWidth", "alleyWidth"):
      quantity = getattr(dimensions, name)
      if quantity is not None:
        lines.append(_field(translator, f"report.plot.{name}", _quantityText(quantity, translator)))
    if dimensions.notes is not None:
      lines.append(_field(translator, "report.plot.notes", dimensions.notes))
  if design.designType is DesignType.splitPlot:
    factors = {factor.factorCode: factor for factor in package.factors}
    lines.append(_field(translator, "report.design.mainPlotFactor", factors[design.mainPlotFactor].name))
    lines.append(_field(translator, "report.design.subPlotFactor", factors[design.subPlotFactor].name))
  if design.randomizationSeed is None:
    lines.append(
      _field(translator, "report.design.layout", translator.text("report.design.layoutSupplied"))
    )
  else:
    lines.append(
      _field(translator, "report.design.seed", translator.integer(design.randomizationSeed))
    )
  if design.randomizationMethod is RandomizationMethod.sha256SpatialBalance1:
    lines.append(
      _field(translator, "report.design.arrangement", translator.text("report.design.spatiallyBalanced"))
    )
  if design.firstBlockInTreatmentOrder:
    lines.append(
      _field(translator, "report.design.firstBlock", translator.text("report.design.firstBlockInOrder"))
    )
  lines.append("")
  return lines


def _treatmentsSection(package: TrialPackage, translator: Translator) -> list[str]:
  """One row for each product line; a treatment without lines has a row of its own.

  A column no treatment has anything in is left out, so a variety trial prints its codes
  and names and a program trial prints its products, rates and applications.
  """
  header = [
    translator.text(f"report.treatments.column.{column}")
    for column in (
      "code", "name", "role", "product", "kind", "activeSubstances", "formulation", "rate",
      "applications",
    )
  ]
  rows: list[list[str | None]] = []
  for treatment in package.treatments:
    role = (
      None if treatment.role is None
      else translator.text(f"report.treatments.role.{treatment.role.value}")
    )
    if not treatment.lines:
      rows.append([treatment.treatmentCode, treatment.name, role, None, None, None, None, None, None])
    for position, line in enumerate(treatment.lines):
      described = [treatment.name, role] if position == 0 else ["", ""]
      rows.append([treatment.treatmentCode, *described, *_lineCells(line, translator)])
  return [
    f"## {translator.text('report.heading.treatments')}",
    "",
    *_filledTable(header, rows, translator),
    "",
  ]


def _lineCells(line: TreatmentLine, translator: Translator) -> list[str | None]:
  kind = None if line.kind is None else translator.text(f"report.treatments.kind.{line.kind.value}")
  substances = " + ".join(
    _substanceText(substance, translator) for substance in line.activeSubstances
  )
  rate = translator.text(
    f"report.treatments.rate.{line.rateBasis.value}", rate=_quantityText(line.rate, translator)
  )
  return [
    line.product,
    kind,
    substances or None,
    line.formulationType,
    rate,
    ", ".join(line.applicationCodes),
  ]


def _substanceText(substance: ActiveSubstance, translator: Translator) -> str:
  if substance.concentration is None:
    return substance.name
  return f"{substance.name} {_quantityText(substance.concentration, translator)}"


def _applicationsSection(package: TrialPackage, translator: Translator) -> list[str]:
  """What is recorded of each application: one column for each, one row for each fact.

  The planned timing is always shown; any other row appears once an application has
  something in it.
  """
  if not package.applications:
    return []
  recorded = [_applicationFacts(application, translator) for application in package.applications]
  header = [
    translator.text("report.applications.column.application"),
    *(application.applicationCode for application in package.applications),
  ]
  rows = [
    [translator.text(f"report.applications.row.{fact}"), *(facts[fact] for facts in recorded)]
    for fact in recorded[0]
    if fact == "timing" or any(facts[fact] for facts in recorded)
  ]
  return [
    f"## {translator.text('report.heading.applications')}",
    "",
    *_table(header, rows, translator),
    "",
  ]


def _targetsSection(package: TrialPackage, translator: Translator) -> list[str]:
  """The organisms the trial is about; left out when it names none."""
  if not package.targets:
    return []
  header = [
    translator.text(f"report.targets.column.{column}")
    for column in ("code", "name", "scientificName", "eppoCode", "kind")
  ]
  rows = [
    [
      target.targetCode,
      target.name,
      target.scientificName,
      target.eppoCode,
      translator.text(f"report.targets.kind.{target.kind.value}"),
    ]
    for target in package.targets
  ]
  return [
    f"## {translator.text('report.heading.targets')}",
    "",
    *_filledTable(header, rows, translator),
    "",
  ]


def _ratingsSection(package: TrialPackage, translator: Translator) -> list[str]:
  """What is rated: one row for each rating, columns nothing is recorded in left out."""
  header = [
    translator.text(f"report.ratings.column.{column}")
    for column in ("code", "name", "type", "target", "partRated", "method", "unit", "values", "transform")
  ]
  rows = [
    [
      rating.ratingCode,
      rating.name,
      rating.ratingType,
      rating.targetCode,
      rating.partRated,
      rating.method,
      rating.unit,
      _valuesText(rating, translator),
      None if rating.transform is Transform.none else _scaleName(rating.transform, rating.transformOffset, translator),
    ]
    for rating in package.ratings
  ]
  return [
    f"## {translator.text('report.heading.ratings')}",
    "",
    *_filledTable(header, rows, translator),
    "",
  ]


def _assessmentsSection(package: TrialPackage, translator: Translator) -> list[str]:
  """Each occasion a rating is taken, with the days after its application worked out."""
  header = [
    translator.text(f"report.assessments.column.{column}")
    for column in (
      "code", "rating", "timing", "date", "cropStage", "targetStage", "daysAfterApplication",
      "assessedBy", "sampleSize", "notes",
    )
  ]
  rows = []
  for assessment in package.assessments:
    days = package.daysAfterApplication(assessment.assessmentCode)
    rows.append([
      assessment.assessmentCode,
      assessment.ratingCode,
      assessment.timing,
      None if assessment.date is None else translator.date(assessment.date),
      assessment.cropStage,
      assessment.targetStage,
      None if days is None else translator.text(
        "report.assessments.daysAfter",
        days=translator.integer(days),
        application=assessment.timedFromApplicationCode,
      ),
      assessment.assessedBy,
      None if assessment.sampleSize is None else _quantityText(assessment.sampleSize, translator),
      assessment.notes,
    ])
  return [
    f"## {translator.text('report.heading.assessments')}",
    "",
    *_filledTable(header, rows, translator),
    "",
  ]


def _valuesText(rating: Rating, translator: Translator) -> str | None:
  """A rating's allowed values: its categories, or the limits of a number."""
  if rating.allowedValues is not None:
    return " / ".join(rating.allowedValues)
  low, high = rating.minValue, rating.maxValue

  def number(value: float) -> str:
    return translator.number(value, decimals=_authoredDecimals(value))

  if low is not None and high is not None:
    return translator.text("report.ratings.range", low=number(low), high=number(high))
  if low is not None:
    return translator.text("report.ratings.atLeast", low=number(low))
  if high is not None:
    return translator.text("report.ratings.atMost", high=number(high))
  return None


def _filledTable(header: list[str], rows: list[list[str | None]], translator: Translator) -> list[str]:
  """A table without the columns no row has anything in."""
  filled = [column for column in range(len(header)) if any(row[column] for row in rows)]
  return _table(
    [header[column] for column in filled],
    [[row[column] for column in filled] for row in rows],
    translator,
  )


def _applicationFacts(application: Application, translator: Translator) -> dict[str, str | None]:
  """An application's facts as display text, in the order the report lists them."""
  def amount(quantity: Quantity | None) -> str | None:
    return None if quantity is None else _quantityText(quantity, translator)

  def percent(value: float | None) -> str | None:
    if value is None:
      return None
    return translator.text(
      "report.value.percent", value=translator.number(value, decimals=_authoredDecimals(value))
    )

  return {
    "timing": application.timing,
    "date": None if application.date is None else translator.date(application.date),
    "time": None if application.time is None else translator.time(application.time),
    "method": application.method,
    "placement": application.placement,
    "equipment": application.equipment,
    "nozzle": application.nozzle,
    "pressure": amount(application.pressure),
    "sprayQuality": application.sprayQuality,
    "travelSpeed": amount(application.travelSpeed),
    "sprayVolume": amount(application.sprayVolume),
    "cropStage": application.cropStage,
    "targetStage": application.targetStage,
    "airTemperature": amount(application.airTemperature),
    "relativeHumidity": percent(application.relativeHumidity),
    "windSpeed": amount(application.windSpeed),
    "cloudCover": percent(application.cloudCover),
    "soilMoisture": (
      None if application.soilMoisture is None
      else translator.text(f"report.applications.soilMoisture.{application.soilMoisture.value}")
    ),
    "notes": application.notes,
  }


def _table(header: list[str], rows: list[list[str | None]], translator: Translator) -> list[str]:
  """A pipe table of text cells. A cell that is None shows as absent; an empty one stays empty."""
  absent = translator.text("report.value.absent")
  lines = [f"| {' | '.join(header)} |", "|" + "---|" * len(header)]
  for row in rows:
    cells = (absent if cell is None else _cell(cell) for cell in row)
    lines.append(f"| {' | '.join(cells)} |")
  return lines


def _cell(text: str) -> str:
  """Authored text as a table cell: a pipe or a line break in it would end the cell."""
  return " ".join(text.split()).replace("|", "\\|")


def _quantityText(quantity: Quantity, translator: Translator) -> str:
  """A value and its unit. In a right-to-left report the pair is isolated (Unicode FSI ... PDI),
  so any viewer keeps "250 kPa" in that order instead of reading it as "kPa 250"."""
  value = translator.number(quantity.value, decimals=_authoredDecimals(quantity.value))
  text = f"{value} {quantity.unit}"
  if translator.direction == "rtl":
    return f"\u2068{text}\u2069"
  return text


def _assessmentSection(
  assessment, package, layout, observations, significanceLevel, protected, translator: Translator
) -> list[str]:
  rating = package.ratingFor(assessment.assessmentCode)
  lines = [
    f"## {translator.text('report.heading.assessment', name=rating.name, code=assessment.assessmentCode)}",
    "",
  ]
  if rating.dataType is not AssessmentDataType.numeric:
    lines.append(translator.text("report.assessment.notNumeric", dataType=rating.dataType.value))
    lines.append("")
    return lines
  if package.design.designType is DesignType.splitPlot:
    return lines + _splitPlotSubsections(
      assessment.assessmentCode, rating, package, layout, observations, significanceLevel, protected, translator,
    )
  try:
    analyze = analyzeCrd if package.design.designType is DesignType.crd else analyzeRcbd
    result = analyze(assessment.assessmentCode, package, layout, observations)
  except AnalysisError as error:
    lines.append(translator.text("report.assessment.notAnalyzed", reason=str(error)))
    lines.append("")
    return lines

  separation = separateMeans(result, significanceLevel=significanceLevel, protected=protected)
  unit = f" ({rating.unit})" if rating.unit else ""
  alpha = translator.number(significanceLevel, decimals=2)

  lines.append(f"### {translator.text('report.heading.anova')}")
  lines.append("")
  if result.transform is not Transform.none:
    lines.append(
      translator.text("report.anova.transformedScale", scale=_scaleName(result.transform, result.transformOffset, translator))
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
      translator.text(
        "report.value.percent", value=translator.number(result.coefficientOfVariation, decimals=2)
      ),
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
    displayedMean = backTransformMean(result.transform, group.mean, result.transformOffset)
    lines.append(
      f"| {group.treatmentCode} | {translator.number(displayedMean, decimals=3)} | {group.group} |"
    )
  lines.append("")
  if result.transform is not Transform.none:
    lines.append(
      translator.text("report.means.backTransformNote", scale=_scaleName(result.transform, result.transformOffset, translator))
    )
    lines.append("")
  lines.append(_field(
    translator,
    "report.means.leastSignificantDifference",
    translator.number(separation.leastSignificantDifference, decimals=3),
    alpha=alpha,
  ))
  if protected and not separation.treatmentSignificant:
    lines.append(f"- {translator.text('report.means.notSeparated')}")
  lines.append("")

  if package.factors:
    lines += _factorialSubsections(
      assessment.assessmentCode, rating, package, layout, observations, significanceLevel, protected, translator,
    )
  if package.design.designType is DesignType.crd:
    lines += [f"### {translator.text('report.heading.assumptions')}", "",
              translator.text("report.crd.assumptionsNotComputed"), ""]
  else:
    lines += _assumptionsSubsection(
      assessment.assessmentCode, package, layout, observations, significanceLevel, translator
    )
  if package.design.checkArrangement is not CheckArrangement.none:
    lines += _checksSubsections(assessment, package, layout, observations, significanceLevel, protected, translator)
  return lines


def _checksSubsections(
  assessment, package, layout, observations, significanceLevel, protected, translator: Translator,
) -> list[str]:
  """The untreated checks beside the plots: their level, and the comparisons the arrangement calls for."""
  code = assessment.assessmentCode
  arrangement = package.design.checkArrangement
  lines = [f"### {translator.text('report.checks.heading')}", ""]
  try:
    pairs = checkPairs(code, package, layout, observations)
  except AnalysisError as error:
    return lines + [translator.text("report.assessment.notAnalyzed", reason=str(error)), ""]
  lines += [
    translator.text(f"report.checks.arrangement.{arrangement.value}"),
    "",
    _field(translator, "report.checks.checkMean", translator.number(
      sum(pair.check for pair in pairs) / len(pairs), decimals=3)),
    _field(translator, "report.checks.treatedMean", translator.number(
      sum(pair.treated for pair in pairs) / len(pairs), decimals=3)),
    "",
  ]
  if arrangement is CheckArrangement.adjacent:
    try:
      halves = analyzeHalves(code, package, layout, observations)
      sourceNames = {
        "block": translator.text("report.anova.source.block"),
        "mainPlot": translator.text("report.anova.source.treatment"),
        "mainPlotError": translator.text("report.splitPlot.source.mainPlotError"),
        "subPlot": translator.text("report.checks.source.half"),
        "interaction": translator.text("report.checks.source.treatmentByHalf"),
        "subPlotError": translator.text("report.splitPlot.source.subPlotError"),
        "total": translator.text("report.anova.source.total"),
      }
      lines += [f"#### {translator.text('report.checks.heading.halves')}", ""]
      lines += _anovaTable(halves.table, sourceNames, translator) + [""]
    except AnalysisError as error:
      lines += [translator.text("report.assessment.notAnalyzed", reason=str(error)), ""]
  if arrangement is CheckArrangement.paired:
    try:
      comparisons = compareWithChecks(code, package, layout, observations)
      header = " | ".join(
        translator.text(f"report.checks.column.{column}")
        for column in ("treatment", "treated", "check", "difference", "t", "degreesOfFreedom", "probability")
      )
      lines += [f"#### {translator.text('report.checks.heading.paired')}", "", f"| {header} |",
                "|---|---:|---:|---:|---:|---:|---:|"]
      for comparison in comparisons:
        lines.append(
          f"| {comparison.treatmentCode} | {translator.number(comparison.treatedMean, decimals=3)} "
          f"| {translator.number(comparison.checkMean, decimals=3)} "
          f"| {translator.number(comparison.meanDifference, decimals=3)} "
          f"| {translator.number(comparison.tStatistic, decimals=2)} "
          f"| {translator.integer(comparison.degreesOfFreedom)} | {_probabilityCell(comparison.pValue, translator)} |"
        )
      lines.append("")
    except AnalysisError as error:
      lines += [translator.text("report.assessment.notAnalyzed", reason=str(error)), ""]
  if assessment.efficacy is not None:
    lines += _efficacySubsection(assessment, package, layout, observations, significanceLevel, protected, translator)
  return lines


def _efficacySubsection(
  assessment, package, layout, observations, significanceLevel, protected, translator: Translator,
) -> list[str]:
  method = translator.text(f"report.checks.efficacyMethod.{assessment.efficacy.method.value}")
  lines = [f"#### {translator.text('report.checks.heading.efficacy', method=method)}", ""]
  try:
    result = analyzeEfficacy(assessment.assessmentCode, package, layout, observations)
  except AnalysisError as error:
    return lines + [translator.text("report.assessment.notAnalyzed", reason=str(error)), ""]
  separation = separateMeans(result, significanceLevel=significanceLevel, protected=protected)
  sourceNames = {
    source: translator.text(f"report.anova.source.{source}") for source in ("block", "treatment", "error", "total")
  }
  alpha = translator.number(significanceLevel, decimals=2)
  treatmentRow = next(row for row in result.table if row.source == "treatment")
  significance = translator.text(
    "report.means.significant" if separation.treatmentSignificant else "report.means.notSignificant"
  )
  lines += _anovaTable(result.table, sourceNames, translator)
  lines += [
    "",
    translator.text(
      "report.means.separation", method=translator.text(separation.methodKey), alpha=alpha,
      significance=significance, probability=_probabilityStatement(treatmentRow.pValue, translator),
    ),
    "",
    f"| {translator.text('report.means.column.treatment')} | {translator.text('report.checks.column.efficacy')} "
    f"| {translator.text('report.means.column.group')} |",
    "|---|---:|:--:|",
    *(
      f"| {group.treatmentCode} | {translator.number(group.mean, decimals=1)} | {group.group} |"
      for group in separation.groups
    ),
    "",
    _field(translator, "report.means.leastSignificantDifference",
           translator.number(separation.leastSignificantDifference, decimals=2), alpha=alpha),
    "",
  ]
  return lines


def _splitPlotSubsections(
  assessmentCode, rating, package, layout, observations, significanceLevel, protected, translator: Translator,
) -> list[str]:
  """The split-plot ANOVA, each factor's separated means, and the cell means (decision 0020)."""
  try:
    result = analyzeSplitPlot(assessmentCode, package, layout, observations)
  except AnalysisError as error:
    return [translator.text("report.assessment.notAnalyzed", reason=str(error)), ""]
  factors = {factor.factorCode: factor for factor in package.factors}
  mainName, subName = factors[result.mainPlotFactor].name, factors[result.subPlotFactor].name
  unit = f" ({rating.unit})" if rating.unit else ""
  alpha = translator.number(significanceLevel, decimals=2)
  sourceNames = {
    "block": translator.text("report.anova.source.block"),
    "mainPlot": mainName,
    "mainPlotError": translator.text("report.splitPlot.source.mainPlotError"),
    "subPlot": subName,
    "interaction": translator.text("report.splitPlot.source.interaction", main=mainName, sub=subName),
    "subPlotError": translator.text("report.splitPlot.source.subPlotError"),
    "total": translator.text("report.anova.source.total"),
  }
  lines = [f"### {translator.text('report.heading.anova')}", ""]
  if result.transform is not Transform.none:
    lines += [translator.text("report.anova.transformedScale", scale=_scaleName(result.transform, result.transformOffset, translator)), ""]
  lines += _anovaTable(result.table, sourceNames, translator)
  lines += [
    "",
    _field(translator, "report.anova.grandMean", f"{translator.number(result.grandMean, decimals=3)}{unit}"),
    _field(translator, "report.splitPlot.cvMain", translator.text(
      "report.value.percent", value=translator.number(result.mainPlotCoefficientOfVariation, decimals=2))),
    _field(translator, "report.splitPlot.cvSub", translator.text(
      "report.value.percent", value=translator.number(result.subPlotCoefficientOfVariation, decimals=2))),
    "",
  ]
  lines += _twoFactorMeans(
    result, package, result.mainPlotFactor, result.subPlotFactor,
    lambda factorCode: separateFactorMeans(result, factorCode, significanceLevel=significanceLevel, protected=protected),
    lambda factorCode: next(
      row for row in result.table if row.source == ("mainPlot" if factorCode == result.mainPlotFactor else "subPlot")
    ),
    splitPlotInteractionComparisons(result, significanceLevel), protected, unit, alpha, translator,
  )
  lines += [
    f"### {translator.text('report.heading.assumptions')}",
    "",
    translator.text("report.splitPlot.assumptionsNotComputed"),
    "",
  ]
  return lines


def _twoFactorMeans(
  result, package, firstFactor, secondFactor, separate, rowFor, comparisons, protected, unit, alpha, translator,
) -> list[str]:
  """Each factor's level means with their letters, then the combination means with theirs.

  The letters in a row compare the second factor's levels at that level of the first, on the
  LSD for that comparison; under the protected rule they are given only when the
  interaction is significant.
  """
  factors = {factor.factorCode: factor for factor in package.factors}
  meanHeaderKey = (
    "report.means.column.mean" if result.transform is Transform.none else "report.means.column.meanOriginalScale"
  )
  lines: list[str] = []
  for factorCode in (firstFactor, secondFactor):
    separation = separate(factorCode)
    significance = translator.text(
      "report.means.significant" if separation.factorSignificant else "report.means.notSignificant"
    )
    levelNames = {level.levelCode: level.name for level in factors[factorCode].levels}
    lines += [
      f"### {translator.text('report.splitPlot.heading.factorMeans', factor=factors[factorCode].name)}",
      "",
      translator.text(
        "report.splitPlot.separation", method=translator.text(separation.methodKey), alpha=alpha,
        significance=significance, probability=_probabilityStatement(rowFor(factorCode).pValue, translator),
      ),
      "",
      f"| {translator.text('report.splitPlot.column.level')} | {translator.text(meanHeaderKey, unit=unit)} "
      f"| {translator.text('report.means.column.group')} |",
      "|---|---:|:--:|",
      *(
        f"| {_cell(levelNames[group.levelCode])} "
        f"| {translator.number(backTransformMean(result.transform, group.mean, result.transformOffset), decimals=3)} | {group.group} |"
        for group in separation.groups
      ),
      "",
      _field(translator, "report.means.leastSignificantDifference",
             translator.number(separation.leastSignificantDifference, decimals=3), alpha=alpha),
      "",
    ]
  cellMeans = {mean.treatmentCode: mean.mean for mean in result.treatmentMeans}
  secondLevels = factors[secondFactor].levels
  lines += [
    f"### {translator.text('report.splitPlot.heading.cellMeans', main=factors[firstFactor].name, sub=factors[secondFactor].name)}",
    "",
    f"| {firstFactor} | " + " | ".join(_cell(level.name) for level in secondLevels) + " |",
    "|---|" + "---:|" * len(secondLevels),
  ]
  treatmentFor = {
    (t.factorLevels[firstFactor], t.factorLevels[secondFactor]): t.treatmentCode for t in package.treatments
  }
  lettered = comparisons.interactionSignificant or not protected
  withinRow = comparisons.secondWithinFirst.leastSignificantDifference
  for firstLevel in factors[firstFactor].levels:
    rowMeans = [cellMeans[treatmentFor[(firstLevel.levelCode, level.levelCode)]] for level in secondLevels]
    ordered = sorted(range(len(rowMeans)), key=lambda index: rowMeans[index], reverse=True)
    letters = [""] * len(rowMeans)
    if lettered:
      for rank, letter in zip(ordered, letterGroups([rowMeans[index] for index in ordered], withinRow)):
        letters[rank] = f" {letter}"
    cells = (
      translator.number(backTransformMean(result.transform, mean, result.transformOffset), decimals=3) + letters[index]
      for index, mean in enumerate(rowMeans)
    )
    lines.append(f"| {_cell(firstLevel.name)} | " + " | ".join(cells) + " |")
  firstName, secondName = factors[firstFactor].name, factors[secondFactor].name
  lines += [
    "",
    translator.text(
      "report.twoFactor.lettersNote" if lettered else "report.twoFactor.noLettersNote",
      first=firstName, second=secondName,
    ),
    "",
    _field(translator, "report.twoFactor.secondWithinFirst", translator.number(withinRow, decimals=3),
           alpha=alpha, first=firstName, second=secondName),
    _field(translator, "report.twoFactor.firstWithinSecond",
           translator.number(comparisons.firstWithinSecond.leastSignificantDifference, decimals=3),
           alpha=alpha, first=firstName, second=secondName),
    "",
  ]
  return lines


def _factorialSubsections(
  assessmentCode, rating, package, layout, observations, significanceLevel, protected, translator: Translator,
) -> list[str]:
  """The treatment line of a two-factor RCBD split into its factors (decision 0025)."""
  try:
    result = analyzeFactorialRcbd(assessmentCode, package, layout, observations)
  except AnalysisError as error:
    return [translator.text("report.assessment.notAnalyzed", reason=str(error)), ""]
  factors = {factor.factorCode: factor for factor in package.factors}
  firstName, secondName = factors[result.firstFactor].name, factors[result.secondFactor].name
  sourceNames = {
    "block": translator.text("report.anova.source.block"),
    "firstFactor": firstName,
    "secondFactor": secondName,
    "interaction": translator.text("report.splitPlot.source.interaction", main=firstName, sub=secondName),
    "error": translator.text("report.anova.source.error"),
    "total": translator.text("report.anova.source.total"),
  }
  unit = f" ({rating.unit})" if rating.unit else ""
  alpha = translator.number(significanceLevel, decimals=2)
  lines = [f"### {translator.text('report.factorial.heading')}", ""]
  lines += _anovaTable(result.table, sourceNames, translator) + [""]
  lines += _twoFactorMeans(
    result, package, result.firstFactor, result.secondFactor,
    lambda factorCode: separateFactorialMeans(result, factorCode, significanceLevel=significanceLevel, protected=protected),
    lambda factorCode: next(
      row for row in result.table if row.source == ("firstFactor" if factorCode == result.firstFactor else "secondFactor")
    ),
    factorialInteractionComparisons(result, significanceLevel), protected, unit, alpha, translator,
  )
  return lines


def _anovaTable(table, sourceNames: dict[str, str], translator: Translator) -> list[str]:
  header = " | ".join(
    translator.text(f"report.anova.column.{column}")
    for column in ("source", "degreesOfFreedom", "sumOfSquares", "meanSquare", "fStatistic", "probability")
  )
  lines = [f"| {header} |", "|---|---:|---:|---:|---:|---:|"]
  for row in table:
    lines.append(
      f"| {_cell(sourceNames[row.source])} "
      f"| {translator.integer(row.degreesOfFreedom)} "
      f"| {translator.number(row.sumOfSquares, decimals=4)} "
      f"| {translator.number(row.meanSquare, decimals=4)} "
      f"| {translator.number(row.fStatistic, decimals=2)} "
      f"| {_probabilityCell(row.pValue, translator)} |"
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
  if not outcome.computed:
    return _field(
      translator, outcome.nameKey,
      translator.text(outcome.notComputedKey, **outcome.notComputedDetail),
    )
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
  line = translator.text(
    "diagnostic.line", name=translator.text(outcome.nameKey), statistic=statistic, reading=reading
  )
  return f"- {line}"


def _reproducibilitySection(
  package, layout, observations, significanceLevel, protected, translator: Translator
) -> list[str]:
  test = translator.text(methodKeyFor(protected))
  methodKey = {
    DesignType.splitPlot: "report.reproducibility.splitPlotMethodValue",
    DesignType.crd: "report.reproducibility.crdMethodValue",
  }.get(package.design.designType, "report.reproducibility.methodValue")
  method = translator.text(
    methodKey,
    test=test,
    alpha=translator.number(significanceLevel, decimals=2),
  )
  design = package.design
  lines = [
    f"## {translator.text('report.heading.reproducibility')}",
    "",
    _field(translator, "report.reproducibility.method", method),
    # The method's name is an identifier, shown as recorded in every locale.
    _field(
      translator, "report.reproducibility.randomizationMethod", design.randomizationMethod.value
    ),
  ]
  if design.randomizationSeed is not None:
    lines.append(
      _field(
        translator, "report.reproducibility.seed", translator.integer(design.randomizationSeed)
      )
    )
  transformed = [
    f"{rating.ratingCode} = {rating.transform.value}" + (f"(x + {rating.transformOffset:g})" if rating.transformOffset else "")
    for rating in package.ratings
    if rating.transform is not Transform.none
  ]
  if transformed:
    lines.append(_field(translator, "report.reproducibility.transforms", ", ".join(transformed)))
  # The input hash is canonical, not display: it is the same in every locale.
  lines.append(
    _field(
      translator, "report.reproducibility.inputHash", inputHash(package, layout, observations)
    )
  )
  lines.append(
    "- "
    + translator.text(
      "report.reproducibility.versions",
      openfurrow=softwareVersion,
      numpy=numpy.__version__,
      python=platform.python_version(),
    )
  )
  lines.append("")
  return lines


def _scaleName(transform, offset: float, translator: Translator) -> str:
  key = _scaleKeys.get(transform)
  if key is None:
    raise AnalysisError(f"no report scale name for transform '{transform.value}'")
  if offset == 0.0:
    return translator.text(key)
  return translator.text(
    "report.scale.withOffset", scale=translator.text(key),
    offset=translator.number(offset, decimals=_authoredDecimals(offset)),
  )


def _authoredDecimals(value: float) -> int:
  """The decimals of a number someone entered, so that it is shown as written.

  The shortest form that reads back as the same number has exactly the decimals that
  were typed: 0.125 keeps three and 2 keeps none, neither padded nor rounded.
  """
  return max(0, -Decimal(repr(float(value))).normalize().as_tuple().exponent)


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
