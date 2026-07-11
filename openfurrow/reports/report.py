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

Output is ASCII Markdown so it is portable and renders the same everywhere.
"""

from __future__ import annotations

import platform

import numpy

from openfurrow.version import schemaVersion
from openfurrow.analysis import AnalysisError, analyzeRcbd, assessAssumptions, separateMeans
from openfurrow.analysis.transforms import backTransformMean
from openfurrow.schema.document import TrialDocument, contentHash
from openfurrow.schema.layout import TrialLayout
from openfurrow.schema.observation import Observation
from openfurrow.schema.trialPackage import AssessmentDataType, Transform, TrialPackage


def buildReport(
  package: TrialPackage,
  layout: TrialLayout,
  observations: list[Observation],
  significanceLevel: float = 0.05,
  protected: bool = True,
) -> str:
  """Build the full Markdown trial report."""
  if layout.trialCode != package.trial.trialCode:
    raise AnalysisError(
      f"layout trialCode '{layout.trialCode}' does not match package trial '{package.trial.trialCode}'"
    )
  lines: list[str] = []
  lines += _metadataSection(package)
  lines += _designSection(package)
  lines += _treatmentsSection(package)
  for assessment in package.assessments:
    lines += _assessmentSection(assessment, package, layout, observations, significanceLevel, protected)
  lines += _reproducibilitySection(package, observations, significanceLevel, protected)
  return "\n".join(lines).rstrip() + "\n"


def inputHash(package: TrialPackage, observations: list[Observation]) -> str:
  """A stable SHA-256 over the canonical inputs (package and observations).

  Delegates to the shared trial-document content hash so hashing here and export
  elsewhere cannot drift. The layout is regenerable from the package's seed and is
  not hashed separately; observations are sorted so ordering does not affect it.
  """
  return contentHash(TrialDocument(package=package, observations=list(observations)))


def _metadataSection(package: TrialPackage) -> list[str]:
  trial = package.trial
  lines = [f"# Trial Report: {trial.title}", ""]
  lines.append(f"- Trial code: {trial.trialCode}")
  lines.append(f"- Crop: {trial.crop}")
  lines.append(f"- Season: {trial.season}")
  lines.append(f"- Site: {trial.site}")
  lines.append(f"- Objective: {trial.objective}")
  if trial.investigator:
    lines.append(f"- Investigator: {trial.investigator}")
  if trial.organization:
    lines.append(f"- Organization: {trial.organization}")
  lines.append("")
  return lines


def _designSection(package: TrialPackage) -> list[str]:
  return [
    "## Design",
    "",
    "- Design: Randomized complete block design",
    f"- Treatments: {len(package.treatments)}",
    f"- Blocks (replications): {package.design.replications}",
    f"- Plots: {package.plotCount}",
    f"- Randomization seed: {package.design.randomizationSeed}",
    "",
  ]


def _treatmentsSection(package: TrialPackage) -> list[str]:
  lines = ["## Treatments", "", "| Code | Name | Product | Rate | Timing |", "|---|---|---|---|---|"]
  for treatment in package.treatments:
    product = treatment.product or "(untreated control)"
    rate = f"{treatment.rate:g} {treatment.rateUnit}" if treatment.rate is not None else "-"
    timing = treatment.timing or "-"
    lines.append(f"| {treatment.treatmentCode} | {treatment.name} | {product} | {rate} | {timing} |")
  lines.append("")
  return lines


def _assessmentSection(assessment, package, layout, observations, significanceLevel, protected) -> list[str]:
  lines = [f"## Assessment: {assessment.name} ({assessment.assessmentCode})", ""]
  if assessment.dataType is not AssessmentDataType.numeric:
    lines.append(f"Not analyzed: AOV requires a numeric assessment (this assessment is {assessment.dataType.value}).")
    lines.append("")
    return lines
  try:
    result = analyzeRcbd(assessment.assessmentCode, package, layout, observations)
  except AnalysisError as error:
    lines.append(f"Not analyzed: {error}")
    lines.append("")
    return lines

  separation = separateMeans(result, significanceLevel=significanceLevel, protected=protected)
  unit = f" ({assessment.unit})" if assessment.unit else ""

  lines.append("### Analysis of variance")
  lines.append("")
  if result.transform is not Transform.none:
    lines.append(
      f"Analyzed on the {_scaleName(result.transform)} scale; the table, grand mean, and CV "
      f"below are on that scale."
    )
    lines.append("")
  lines.append("| Source | df | SS | MS | F | P |")
  lines.append("|---|---:|---:|---:|---:|---:|")
  for row in result.table:
    lines.append(
      f"| {row.source.capitalize()} | {row.degreesOfFreedom} | {_number(row.sumOfSquares, 4)} | "
      f"{_number(row.meanSquare, 4)} | {_number(row.fStatistic, 2)} | {_probability(row.pValue)} |"
    )
  lines.append("")
  lines.append(f"- Grand mean: {_number(result.grandMean, 3)}{unit}")
  lines.append(f"- Coefficient of variation: {_number(result.coefficientOfVariation, 2)}%")
  lines.append("")

  treatmentRow = next(row for row in result.table if row.source == "treatment")
  significance = "significant" if separation.treatmentSignificant else "not significant"
  lines.append("### Treatment means")
  lines.append("")
  lines.append(
    f"Mean separation: {separation.method} (alpha = {_number(significanceLevel, 2)}). "
    f"Treatment effect {significance} (P = {_probability(treatmentRow.pValue)})."
  )
  lines.append("")
  meanHeader = f"Mean (original scale){unit}" if result.transform is not Transform.none else f"Mean{unit}"
  lines.append(f"| Treatment | {meanHeader} | Group |")
  lines.append("|---|---:|:--:|")
  for group in separation.groups:
    displayedMean = backTransformMean(result.transform, group.mean)
    lines.append(f"| {group.treatmentCode} | {_number(displayedMean, 3)} | {group.group} |")
  lines.append("")
  if result.transform is not Transform.none:
    lines.append(
      "Means are back-transformed to the original scale as point estimates (not symmetric "
      f"intervals); the analysis of variance and mean separation were computed on the "
      f"{_scaleName(result.transform)} scale."
    )
    lines.append("")
  lines.append(f"- LSD (alpha = {_number(significanceLevel, 2)}): {_number(separation.leastSignificantDifference, 3)}")
  if protected and not separation.treatmentSignificant:
    lines.append("- Means were not separated: the treatment effect was not significant (protected LSD).")
  lines.append("")

  lines += _assumptionsSubsection(assessment.assessmentCode, package, layout, observations, significanceLevel)
  return lines


def _assumptionsSubsection(assessmentCode, package, layout, observations, significanceLevel) -> list[str]:
  assumptions = assessAssumptions(assessmentCode, package, layout, observations, significanceLevel)
  lines = [
    "### Assumption checks",
    "",
    f"Reported only; these do not change the analysis above (significance level alpha = {_number(significanceLevel, 2)}).",
    "",
    _diagnosticLine(assumptions.equalVariance),
    _diagnosticLine(assumptions.nonAdditivity),
    _diagnosticLine(assumptions.normality),
    "",
    "Residuals are from the additive block-and-treatment model and are constrained "
    "(they sum to zero within each block and each treatment), so the normality test is approximate.",
    "",
  ]
  if assumptions.recommendation:
    lines.append(f"Recommendation: {assumptions.recommendation}")
    lines.append("")
  return lines


def _diagnosticLine(outcome) -> str:
  if not outcome.computed:
    return f"- {outcome.name}: {outcome.interpretation}"
  if outcome.statisticName == "F":
    statistic = (
      f"F({outcome.numeratorDegreesOfFreedom}, {outcome.denominatorDegreesOfFreedom}) "
      f"= {outcome.statistic:.2f}"
    )
  else:
    statistic = f"{outcome.statisticName} = {outcome.statistic:.4f}"
  return f"- {outcome.name}: {statistic}. {outcome.interpretation}"


def _reproducibilitySection(package, observations, significanceLevel, protected) -> list[str]:
  test = "Fisher's Protected LSD" if protected else "Fisher's LSD"
  method = f"RCBD ANOVA; {test} (alpha = {_number(significanceLevel, 2)})"
  lines = [
    "## Reproducibility",
    "",
    f"- Method: {method}",
    f"- Randomization seed: {package.design.randomizationSeed}",
  ]
  transformed = [
    f"{assessment.assessmentCode} = {assessment.transform.value}"
    for assessment in package.assessments
    if assessment.transform is not Transform.none
  ]
  if transformed:
    lines.append(f"- Transforms: {', '.join(transformed)}")
  lines.append(f"- Input hash (SHA-256): {inputHash(package, observations)}")
  lines.append(
    f"- Versions: OpenFurrow {schemaVersion}, numpy {numpy.__version__}, Python {platform.python_version()}"
  )
  lines.append("")
  return lines


def _scaleName(transform) -> str:
  return {
    Transform.sqrt: "square-root",
    Transform.log: "natural-log",
    Transform.arcsinSqrt: "arcsine-square-root",
    Transform.logit: "logit",
  }.get(transform, transform.value)


def _number(value, decimals: int) -> str:
  if value is None:
    return "-"
  return f"{value:.{decimals}f}"


def _probability(value) -> str:
  if value is None:
    return "-"
  if value < 0.0001:
    return "<0.0001"
  return f"{value:.4f}"
