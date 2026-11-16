# SPDX-License-Identifier: Apache-2.0
"""Tests for the Markdown trial report.

Checks that the AOV Means Table renders with the expected figures on the Yates
oats RCBD, that a significant trial shows separated letter groups, that the input
hash is stable and sensitive, and that an assessment which cannot be analyzed is
reported with an explicit note rather than dropped.
"""

import csv
from pathlib import Path

import pytest

from openfurrow import schemaVersion
from openfurrow.analysis import AnalysisError
from openfurrow.design import generateRcbdLayout
from openfurrow.reports import buildReport, inputHash
from openfurrow.schema import TrialPackage
from openfurrow.schema.observation import Observation
from openfurrow.version import softwareVersion

fixturesDirectory = Path(__file__).parent / "fixtures"


def loadYatesCells():
  cells = {}
  with (fixturesDirectory / "yatesOatsVariety.csv").open() as handle:
    for row in csv.DictReader(handle):
      cells[(row["treatment"], int(row["block"]))] = float(row["yield"])
  return cells


def yatesPackage(extraRatings=None):
  ratings = [{"ratingCode": "YIELD", "name": "Grain yield", "dataType": "numeric",
                  "unit": "qtr-lb/plot", "minValue": 0}]
  if extraRatings:
    ratings.extend(extraRatings)
  return TrialPackage.model_validate({
    "schemaVersion": schemaVersion,
    "trial": {"trialCode": "YATES-OATS", "title": "Yates oats variety", "crop": "Oats",
              "season": "1935", "site": "Rothamsted", "objective": "Compare oat variety yield"},
    "treatments": [{"treatmentCode": code, "name": code} for code in ["GoldenRain", "Marvellous", "Victory"]],
    "design": {"designType": "rcbd", "replications": 6, "randomizationMethod": "sha256FisherYates1", "randomizationSeed": 1},
    "ratings": ratings,
    "assessments": [{"assessmentCode": rating["ratingCode"], "ratingCode": rating["ratingCode"]} for rating in ratings],
  })


def yatesInputs(extraRatings=None, cells=None):
  package = yatesPackage(extraRatings)
  layout = generateRcbdLayout(package)
  cells = cells if cells is not None else loadYatesCells()
  observations = [
    Observation(plotNumber=plot.plotNumber, assessmentCode="YIELD",
                value=cells.get((plot.treatmentCode, plot.block)))
    for plot in layout.plots
  ]
  return package, layout, observations


syntheticCells = {
  ("A", 1): 106.0, ("A", 2): 99.0, ("A", 3): 95.0,
  ("B", 1): 103.0, ("B", 2): 100.0, ("B", 3): 94.0,
  ("C", 1): 86.0, ("C", 2): 79.0, ("C", 3): 75.0,
  ("D", 1): 83.0, ("D", 2): 80.0, ("D", 3): 74.0,
}


def syntheticInputs():
  package = TrialPackage.model_validate({
    "schemaVersion": schemaVersion,
    "trial": {"trialCode": "SYN", "title": "Synthetic", "crop": "x", "season": "x", "site": "x", "objective": "x"},
    "treatments": [{"treatmentCode": code, "name": code} for code in ["A", "B", "C", "D"]],
    "design": {"designType": "rcbd", "replications": 3, "randomizationMethod": "sha256FisherYates1", "randomizationSeed": 1},
    "ratings": [
      {"ratingCode": "Y", "name": "Yield", "dataType": "numeric"}
    ],
    "assessments": [
      {"assessmentCode": "Y", "ratingCode": "Y"}
    ],
  })
  layout = generateRcbdLayout(package)
  observations = [
    Observation(plotNumber=plot.plotNumber, assessmentCode="Y", value=syntheticCells[(plot.treatmentCode, plot.block)])
    for plot in layout.plots
  ]
  return package, layout, observations


# ---- AOV Means Table rendering -------------------------------------------

def testReportRendersAovMeansTable():
  report = buildReport(*yatesInputs())

  assert "# Trial Report: Yates oats variety" in report
  assert "- Randomization seed: 1" in report
  assert "- Plots: 18" in report

  # ANOVA table figures (matching the published Yates table)
  assert "| Block | 5 | 3968.8194 | 793.7639 | 5.28 | 0.0124 |" in report
  assert "| Treatment | 2 | 446.5903 | 223.2951 | 1.49 | 0.2724 |" in report
  assert "| Error | 10 | 1503.3264 | 150.3326 | - | - |" in report
  assert "| Total | 17 | 5918.7361 | - | - | - |" in report

  assert "- Grand mean: 103.972 (qtr-lb/plot)" in report
  assert "- Coefficient of variation: 11.79%" in report

  # protected LSD: not significant -> all one letter
  assert "| Marvellous | 109.792 | a |" in report
  assert "| Victory | 97.625 | a |" in report
  assert "- LSD (alpha = 0.05): 15.773" in report
  assert "Treatment effect not significant (P = 0.2724)" in report
  assert "Means were not separated" in report

  # reproducibility block
  assert "Input hash (SHA-256): " in report
  assert "OpenFurrow 0.1.0" in report
  assert "numpy" in report


def testReportNamesTheSoftwareVersion():
  package, layout, observations = yatesInputs()
  report = buildReport(package, layout, observations)
  assert f"- Versions: OpenFurrow {softwareVersion}, numpy " in report


def testReportSeparatesSignificantTrial():
  report = buildReport(*syntheticInputs())
  assert "Treatment effect significant (P < 0.0001)" in report
  assert "| A | 100.000 | a |" in report
  assert "| B | 99.000 | a |" in report
  assert "| C | 80.000 | b |" in report
  assert "| D | 79.000 | b |" in report
  assert "Means were not separated" not in report


def testReportUnprotectedLabel():
  report = buildReport(*syntheticInputs(), protected=False)
  assert "Fisher's LSD (alpha = 0.05)" in report
  assert "Protected" not in report


# ---- the trial as recorded: treatments and applications -------------------

def recordedPackage(change=None):
  """A program trial: a control, a two-product program over two applications, a standard."""
  data = {
    "schemaVersion": schemaVersion,
    "trial": {"trialCode": "REC", "title": "Recorded", "crop": "Barley", "season": "2025",
              "site": "North Field", "objective": "Compare programs"},
    "treatments": [
      {"treatmentCode": "UTC", "name": "Untreated control", "role": "untreatedControl"},
      {"treatmentCode": "T2", "name": "Program A", "role": "test", "lines": [
        {"product": "Fungicide A", "kind": "fungicide", "formulationType": "SC",
         "activeSubstances": [
           {"name": "azoxystrobin", "concentration": {"value": 200, "unit": "g/L"}},
           {"name": "difenoconazole", "concentration": {"value": 125, "unit": "g/L"}},
         ],
         "rate": {"value": 0.125, "unit": "kg/ha"}, "rateBasis": "activeSubstance",
         "applicationCodes": ["A", "B"]},
        {"product": "Wetter W", "kind": "adjuvant", "rate": {"value": 0.5, "unit": "L/ha"},
         "rateBasis": "formulatedProduct", "applicationCodes": ["A"]},
      ]},
      {"treatmentCode": "T3", "name": "Standard", "role": "reference", "lines": [
        {"product": "Fungicide B", "activeSubstances": [{"name": "tebuconazole"}],
         "rate": {"value": 2.0, "unit": "L/ha"}, "rateBasis": "formulatedProduct",
         "applicationCodes": ["B"]},
      ]},
    ],
    "applications": [
      {"applicationCode": "A", "timing": "BBCH 31", "date": "2025-05-02", "time": "09:30",
       "method": "Broadcast spray", "placement": "Foliar", "equipment": "Plot sprayer", "nozzle": "XR 11002",
       "pressure": {"value": 250, "unit": "kPa"}, "sprayQuality": "medium",
       "travelSpeed": {"value": 6, "unit": "km/h"}, "sprayVolume": {"value": 200, "unit": "L/ha"},
       "cropStage": "BBCH 30", "targetStage": "First pustules",
       "airTemperature": {"value": 14.5, "unit": "C"}, "relativeHumidity": 64.5,
       "windSpeed": {"value": 2.1, "unit": "m/s"}, "cloudCover": 30, "soilMoisture": "moist",
       "notes": "Dew | light\nwind"},
      {"applicationCode": "B", "timing": "BBCH 39"},
    ],
    "design": {"designType": "rcbd", "replications": 3, "randomizationMethod": "sha256FisherYates1", "randomizationSeed": 1},
    "ratings": [
      {"ratingCode": "Y", "name": "Yield", "dataType": "numeric"}
    ],
    "assessments": [
      {"assessmentCode": "Y", "ratingCode": "Y"}
    ],
  }
  if change:
    change(data)
  return TrialPackage.model_validate(data)


def recordedReport(change=None, locale="en-US"):
  package = recordedPackage(change)
  return buildReport(package, generateRcbdLayout(package), [], locale=locale)


def testReportListsEachProductLineOfATreatment():
  report = recordedReport()
  assert (
    "| Code | Name | Role | Product | Type | Active substance | Formulation | Rate | Applications |\n"
    "|---|---|---|---|---|---|---|---|---|\n"
    "| UTC | Untreated control | Untreated control | - | - | - | - | - | - |\n"
    "| T2 | Program A | Test | Fungicide A | Fungicide | azoxystrobin 200 g/L + difenoconazole 125 g/L "
    "| SC | 0.125 kg/ha of active substance | A, B |\n"
    "| T2 |  |  | Wetter W | Adjuvant | - | - | 0.5 L/ha of product | A |\n"
    "| T3 | Standard | Reference | Fungicide B | - | tebuconazole | - | 2 L/ha of product | B |\n"
  ) in report


def testReportOfAVarietyTrialListsCodesAndNamesOnly():
  # Nothing is recorded of roles, products or applications, so no column or section is made for them.
  report = buildReport(*yatesInputs())
  assert "## Treatments\n\n| Code | Name |\n|---|---|\n| GoldenRain | GoldenRain |\n" in report
  assert "## Applications" not in report


def testReportLeavesOutATreatmentColumnNothingIsRecordedIn():
  def dropKindsAndFormulations(data):
    for treatment in data["treatments"]:
      for line in treatment.get("lines", []):
        line.pop("kind", None)
        line.pop("formulationType", None)
  report = recordedReport(dropKindsAndFormulations)
  assert "| Code | Name | Role | Product | Active substance | Rate | Applications |\n|---|---|---|---|---|---|---|\n" in report
  assert "| T2 |  |  | Wetter W | - | 0.5 L/ha of product | A |" in report


@pytest.mark.parametrize("entered, shown", [
  (0.125, "0.125"), (2.0, "2"), (2.5, "2.5"), (1500.0, "1500"), (0.00001, "0.00001"), (1 / 3, "0.3333333333333333"),
])
def testReportShowsARateAsItWasEntered(entered, shown):
  # Neither padded (2.50) nor rounded (0.13): the number in the report is the number in the record.
  def setRate(data):
    data["treatments"][2]["lines"][0]["rate"]["value"] = entered
  assert f"| {shown} L/ha of product | B |" in recordedReport(setRate)


def testReportTabulatesWhatIsRecordedOfEachApplication():
  report = recordedReport()
  assert (
    "## Applications\n\n"
    "| Application | A | B |\n"
    "|---|---|---|\n"
    "| Timing | BBCH 31 | BBCH 39 |\n"
    "| Date | 05/02/2025 | - |\n"
    "| Time | 09:30 | - |\n"
    "| Method | Broadcast spray | - |\n"
    "| Placement | Foliar | - |\n"
    "| Equipment | Plot sprayer | - |\n"
    "| Nozzle | XR 11002 | - |\n"
    "| Pressure | 250 kPa | - |\n"
    "| Spray quality | medium | - |\n"
    "| Travel speed | 6 km/h | - |\n"
    "| Spray volume | 200 L/ha | - |\n"
    "| Crop stage | BBCH 30 | - |\n"
    "| Target stage | First pustules | - |\n"
    "| Air temperature | 14.5 C | - |\n"
    "| Relative humidity | 64.5% | - |\n"
    "| Wind speed | 2.1 m/s | - |\n"
    "| Cloud cover | 30% | - |\n"
    "| Soil moisture | Moist | - |\n"
    "| Notes | Dew \\| light wind | - |\n"
    "\n## Ratings"
  ) in report


def testReportHasARowForEveryFactAnApplicationCanHold():
  """A field added to the application and not to the report would be recorded and never shown."""
  package = recordedPackage()
  facts = set(type(package.applications[0]).model_fields) - {"applicationCode"}
  assert all(getattr(package.applications[0], fact) is not None for fact in facts)
  report = recordedReport()
  section = report[report.index("## Applications"):report.index("## Ratings")]
  assert len(section.strip().splitlines()) == 4 + len(facts)


def testReportLeavesOutAnApplicationRowNothingIsRecordedIn():
  def keepTimingsOnly(data):
    data["applications"] = [{"applicationCode": "A", "timing": "BBCH 31"}, {"applicationCode": "B"}]
  report = recordedReport(keepTimingsOnly)
  assert "## Applications\n\n| Application | A | B |\n|---|---|---|\n| Timing | BBCH 31 | - |\n\n" in report


def testReportShowsSecondsOfATimeOnlyWhenRecorded():
  def recordSeconds(data):
    data["applications"][0]["time"] = "09:30:15"
  assert "| Time | 09:30:15 | - |" in recordedReport(recordSeconds)
  assert "| Time | 09:30 | - |" in recordedReport()


def testRecordedTrialRendersInTheReadersLocale():
  spanish = recordedReport(locale="es")
  assert (
    "| T2 | Program A | En ensayo | Fungicide A | Fungicida | azoxystrobin 200 g/L + difenoconazole 125 g/L "
    "| SC | 0,125 kg/ha de sustancia activa | A, B |"
  ) in spanish
  assert "| Humedad relativa | 64,5% | - |" in spanish
  assert "| Humedad del suelo | H\u00famedo | - |" in spanish
  # Day first in British English, month first in American.
  assert "| Date | 02/05/2025 | - |" in recordedReport(locale="en-GB")


def testRecordedTrialRendersInEveryShippedLocale():
  for locale in ("en-US", "en-GB", "es", "fr", "ar"):
    report = recordedReport(locale=locale)
    assert report.count("| T2 |") == 2, locale


# ---- ratings and assessment occasions (decision 0017) ---------------------

def occasionsPackage():
  """One rating taken twice, timed from an application, and a categorical rating."""
  def addOccasions(data):
    data["ratings"] = [
      {"ratingCode": "SEV", "name": "Septoria severity", "ratingType": "disease severity",
       "partRated": "flag leaf", "method": "Visual, 10 leaves", "dataType": "numeric", "unit": "%",
       "minValue": 0, "maxValue": 100, "measurementKind": "proportion", "transform": "arcsinSqrt"},
      {"ratingCode": "LODGE", "name": "Lodging", "dataType": "ordinal", "allowedValues": ["none", "slight", "severe"]},
    ]
    data["assessments"] = [
      {"assessmentCode": "SEV0", "ratingCode": "SEV", "date": "2025-05-01", "timedFromApplicationCode": "A"},
      {"assessmentCode": "SEV14", "ratingCode": "SEV", "timing": "14 DA-A", "date": "2025-05-16",
       "cropStage": "BBCH 39", "targetStage": "Lesions on F-2", "timedFromApplicationCode": "A",
       "assessedBy": "Field team", "sampleSize": {"value": 10, "unit": "leaves"}},
      {"assessmentCode": "LODGE", "ratingCode": "LODGE"},
    ]
  return recordedPackage(addOccasions)


def occasionsReport(locale="en-US"):
  package = occasionsPackage()
  return buildReport(package, generateRcbdLayout(package), [], locale=locale)


def testReportListsTheTargetsAndTheRatingsThatNameThem():
  def addTarget(data):
    data["targets"] = [{"targetCode": "SEPT", "name": "Septoria leaf blotch", "kind": "disease",
                        "eppoCode": "SEPTTR"}]
    data["ratings"] = [{"ratingCode": "SEV", "name": "Septoria severity", "targetCode": "SEPT",
                        "dataType": "numeric"}]
    data["assessments"] = [{"assessmentCode": "SEV", "ratingCode": "SEV"}]
  package = recordedPackage(addTarget)
  report = buildReport(package, generateRcbdLayout(package), [])
  assert (
    "## Targets\n\n| Code | Name | EPPO code | Kind |\n|---|---|---|---|\n"
    "| SEPT | Septoria leaf blotch | SEPTTR | Disease |\n"
  ) in report
  assert "| Code | Name | Target |\n|---|---|---|\n| SEV | Septoria severity | SEPT |\n" in report
  assert "## Targets" not in recordedReport()


def testReportPlacesPlantingSoilAndWeatherWhereTheStandardDoes():
  def addConditions(data):
    data["planting"] = {"cultivar": "Laureate", "sowingDate": "2025-03-20",
                        "seedingRate": {"value": 350, "unit": "seeds/m2"}}
    data["soil"] = {"texture": "silty clay loam", "pH": 6.8, "pHMethod": "water 1:2.5", "organicMatter": 2.4}
    data["weather"] = [
      {"date": "2025-05-01", "rainfall": {"value": 4.2, "unit": "mm"}},
      {"date": "2025-05-02", "minimumTemperature": {"value": -0.5, "unit": "C"}, "notes": "Ground frost"},
    ]
  package = recordedPackage(addConditions)
  report = buildReport(package, generateRcbdLayout(package), [])
  assert (
    "## Planting\n\n- Cultivar: Laureate\n- Sowing date: 03/20/2025\n- Seeding rate: 350 seeds/m2\n\n## Design"
  ) in report
  assert (
    "## Soil\n\n- Texture: silty clay loam\n- pH: 6.8\n- pH method: water 1:2.5\n- Organic matter: 2.4%\n"
  ) in report
  assert (
    "## Weather\n\n| Date | Rainfall | Minimum temperature | Notes |\n|---|---|---|---|\n"
    "| 05/01/2025 | 4.2 mm | - | - |\n| 05/02/2025 | - | -0.5 C | Ground frost |\n"
  ) in report
  order = [report.index(heading) for heading in
           ("## Planting", "## Design", "## Applications", "## Soil", "## Weather", "## Ratings")]
  assert order == sorted(order)
  assert "## Planting" not in recordedReport() and "## Weather" not in recordedReport()


def testReportDescribesTheSiteAndThePlots():
  def addSite(data):
    data["siteDetails"] = {"address": "Station Road", "latitude": 52.1234, "longitude": -0.5678,
                           "elevation": {"value": 85, "unit": "m"}, "setting": "glasshouse"}
    data["design"]["plotDimensions"] = {"grossLength": {"value": 10, "unit": "m"},
                                        "netWidth": {"value": 1.5, "unit": "m"}}
    data["planting"] = {"rootstock": "M9", "plantedYear": 2019}
  package = recordedPackage(addSite)
  report = buildReport(package, generateRcbdLayout(package), [])
  assert (
    "## Site\n\n- Address: Station Road\n- Position: 52.1234, -0.5678\n- Elevation: 85 m\n"
    "- Grown in: a glasshouse\n\n## Planting\n\n- Rootstock: M9\n- Year planted: 2019\n\n## Design"
  ) in report
  assert "- Plot length (gross): 10 m\n- Plot width (net, assessed): 1.5 m\n" in report
  assert "- Posición: 52,1234; -0,5678" in buildReport(package, generateRcbdLayout(package), [], locale="es")


def testReportListsWhatIsRated():
  assert (
    "## Ratings\n\n"
    "| Code | Name | Rating type | Part rated | Method | Unit | Values | Analyzed on |\n"
    "|---|---|---|---|---|---|---|---|\n"
    "| SEV | Septoria severity | disease severity | flag leaf | Visual, 10 leaves | % | 0 to 100 | arcsine-square-root |\n"
    "| LODGE | Lodging | - | - | - | - | none / slight / severe | - |\n"
  ) in occasionsReport()


def testReportListsEachOccasionWithDaysAfterItsApplication():
  # A count before spraying is normal, so a day before the application reads -1.
  assert (
    "## Assessments\n\n"
    "| Code | Rating | Timing | Date | Crop stage | Target stage | Days after application | Assessed by | Sample size |\n"
    "|---|---|---|---|---|---|---|---|---|\n"
    "| SEV0 | SEV | - | 05/01/2025 | - | - | -1 DA-A | - | - |\n"
    "| SEV14 | SEV | 14 DA-A | 05/16/2025 | BBCH 39 | Lesions on F-2 | 14 DA-A | Field team | 10 leaves |\n"
    "| LODGE | LODGE | - | - | - | - | - | - | - |\n"
  ) in occasionsReport()


def testEachOccasionOfARatingIsAnalysedOnItsOwn():
  report = occasionsReport()
  assert "## Assessment: Septoria severity (SEV0)" in report
  assert "## Assessment: Septoria severity (SEV14)" in report
  assert "## Assessment: Lodging (LODGE)" in report
  assert "- Transforms: SEV = arcsinSqrt" in report


def testReportStatesAOneSidedLimit():
  report = buildReport(*yatesInputs())
  assert "| YIELD | Grain yield | qtr-lb/plot | at least 0 |" in report


def testRatingsAndAssessmentsRenderInEveryShippedLocale():
  for locale in ("en-US", "en-GB", "es", "fr", "ar"):
    assert occasionsReport(locale).count("| SEV14 |") == 1, locale
  assert "| SEV14 | SEV | 14 DA-A | 16/05/2025 |" in occasionsReport("en-GB")
  assert "| 0 a 100 |" in occasionsReport("es")


# ---- input hash -----------------------------------------------------------

def testInputHashStable():
  packageA, layoutA, observationsA = yatesInputs()
  packageB, layoutB, observationsB = yatesInputs()
  assert inputHash(packageA, layoutA, observationsA) == inputHash(packageB, layoutB, observationsB)


def testInputHashSensitiveToValueChange():
  package, layout, observations = yatesInputs()
  baseline = inputHash(package, layout, observations)
  perturbed = list(observations)
  perturbed[0] = Observation(
    plotNumber=observations[0].plotNumber,
    assessmentCode=observations[0].assessmentCode,
    value=observations[0].value + 1.0,
  )
  assert inputHash(package, layout, perturbed) != baseline


def testInputHashOrderIndependent():
  package, layout, observations = yatesInputs()
  assert inputHash(package, layout, observations) == inputHash(package, layout, list(reversed(observations)))


# ---- transparent failure --------------------------------------------------

def testReportNotesMissingAssessment():
  cells = loadYatesCells()
  del cells[("GoldenRain", 3)]
  report = buildReport(*yatesInputs(cells=cells))
  # the design still renders, but the assessment is flagged with the reason
  assert "## Design" in report
  assert "## Assessment: Grain yield (YIELD)" in report
  assert "Not analyzed:" in report
  assert "missing values" in report
  # no AOV table for the unanalyzable assessment
  assert "### Analysis of variance" not in report


def testReportNotesNonNumericAssessment():
  report = buildReport(*yatesInputs(extraRatings=[
    {"ratingCode": "LODGE", "name": "Lodging", "dataType": "ordinal",
     "allowedValues": ["none", "slight", "severe"]},
  ]))
  assert "## Assessment: Lodging (LODGE)" in report
  assert "Not analyzed: AOV requires a numeric assessment" in report
  # the numeric assessment is still fully analyzed
  assert "### Analysis of variance" in report


def testReportRejectsLayoutPackageMismatch():
  package, layout, observations = yatesInputs()
  otherPackage = syntheticInputs()[0]
  with pytest.raises(AnalysisError, match="does not match package trial"):
    buildReport(otherPackage, layout, observations)
