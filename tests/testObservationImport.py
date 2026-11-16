# SPDX-License-Identifier: Apache-2.0
"""Tests for the observation CSV importer."""

import pytest

from openfurrow.config import ImportProfile
from openfurrow.design import generateRcbdLayout
from openfurrow.importers import ObservationImportError, importObservations
from openfurrow.schema import TrialPackage


@pytest.fixture
def packageAndLayout(validPackageDict):
  package = TrialPackage.model_validate(validPackageDict)
  layout = generateRcbdLayout(package)
  return package, layout


def writeCsv(tmpPath, text):
  path = tmpPath / "observations.csv"
  path.write_text(text.lstrip("\n"), encoding="utf-8")
  return path


# ---- long format ----------------------------------------------------------

def testImportLongFormat(tmp_path, packageAndLayout):
  package, layout = packageAndLayout
  path = writeCsv(tmp_path, """
plotNumber,assessmentCode,value
101,YIELD,4800
101,SEV,low
102,YIELD,5000.5
""")
  result = importObservations(path, package, layout)
  assert len(result.observations) == 3
  assert result.warnings == []
  byKey = {(o.plotNumber, o.assessmentCode): o.value for o in result.observations}
  assert byKey[(101, "YIELD")] == 4800.0
  assert isinstance(byKey[(101, "YIELD")], float)
  assert byKey[(101, "SEV")] == "low"
  assert byKey[(102, "YIELD")] == 5000.5


def testUnknownPlotRejected(tmp_path, packageAndLayout):
  package, layout = packageAndLayout
  path = writeCsv(tmp_path, """
plotNumber,assessmentCode,value
999,YIELD,4800
""")
  with pytest.raises(ObservationImportError, match="plot 999 is not in the trial layout"):
    importObservations(path, package, layout)


def testUnknownAssessmentRejected(tmp_path, packageAndLayout):
  package, layout = packageAndLayout
  path = writeCsv(tmp_path, """
plotNumber,assessmentCode,value
101,BOGUS,4800
""")
  with pytest.raises(ObservationImportError, match="assessment 'BOGUS' is not defined"):
    importObservations(path, package, layout)


def testNonNumericValueForNumericAssessmentRejected(tmp_path, packageAndLayout):
  package, layout = packageAndLayout
  path = writeCsv(tmp_path, """
plotNumber,assessmentCode,value
101,YIELD,heavy
""")
  with pytest.raises(ObservationImportError, match="is not a number"):
    importObservations(path, package, layout)


def testNumericBelowMinimumRejected(tmp_path, packageAndLayout):
  package, layout = packageAndLayout  # YIELD has minValue 0
  path = writeCsv(tmp_path, """
plotNumber,assessmentCode,value
101,YIELD,-5
""")
  with pytest.raises(ObservationImportError, match="below the minimum"):
    importObservations(path, package, layout)


def testCategoricalValueOutsideAllowedRejected(tmp_path, packageAndLayout):
  package, layout = packageAndLayout  # SEV allows none/low/moderate/high
  path = writeCsv(tmp_path, """
plotNumber,assessmentCode,value
101,SEV,catastrophic
""")
  with pytest.raises(ObservationImportError, match="is not one of"):
    importObservations(path, package, layout)


def testDuplicateObservationRejected(tmp_path, packageAndLayout):
  package, layout = packageAndLayout
  path = writeCsv(tmp_path, """
plotNumber,assessmentCode,value
101,YIELD,4800
101,YIELD,4900
""")
  with pytest.raises(ObservationImportError, match="duplicate observation"):
    importObservations(path, package, layout)


def testMissingValueRecordedAsNoneWithWarning(tmp_path, packageAndLayout):
  package, layout = packageAndLayout
  path = writeCsv(tmp_path, """
plotNumber,assessmentCode,value
101,YIELD,NA
102,YIELD,4800
""")
  result = importObservations(path, package, layout)
  missing = [o for o in result.observations if o.plotNumber == 101 and o.assessmentCode == "YIELD"]
  assert missing[0].value is None
  assert len(result.warnings) == 1
  assert result.warnings[0].kind == "missingValue"
  assert result.warnings[0].plotNumber == 101


def testMissingRequiredColumnRejected(tmp_path, packageAndLayout):
  package, layout = packageAndLayout
  path = writeCsv(tmp_path, """
plotNumber,assessmentCode
101,YIELD
""")
  with pytest.raises(ObservationImportError, match="long-format column"):
    importObservations(path, package, layout)


def testNonIntegerPlotNumberRejected(tmp_path, packageAndLayout):
  package, layout = packageAndLayout
  path = writeCsv(tmp_path, """
plotNumber,assessmentCode,value
10A,YIELD,4800
""")
  with pytest.raises(ObservationImportError, match="is not an integer"):
    importObservations(path, package, layout)


# ---- wide format ----------------------------------------------------------

def testImportWideFormatInferredColumns(tmp_path, packageAndLayout):
  package, layout = packageAndLayout
  profile = ImportProfile().withOverrides(format="wide")
  path = writeCsv(tmp_path, """
plotNumber,YIELD,SEV
101,4800,low
102,5000,none
""")
  result = importObservations(path, package, layout, profile)
  assert len(result.observations) == 4
  byKey = {(o.plotNumber, o.assessmentCode): o.value for o in result.observations}
  assert byKey[(101, "YIELD")] == 4800.0
  assert byKey[(101, "SEV")] == "low"
  assert byKey[(102, "SEV")] == "none"


def testWideExplicitAssessmentColumnsSelectsSubset(tmp_path, packageAndLayout):
  package, layout = packageAndLayout
  profile = ImportProfile().withOverrides(format="wide", wide={"assessmentColumns": ["YIELD"]})
  path = writeCsv(tmp_path, """
plotNumber,YIELD,SEV
101,4800,low
""")
  result = importObservations(path, package, layout, profile)
  # Only YIELD selected; the SEV column is ignored.
  assert {o.assessmentCode for o in result.observations} == {"YIELD"}


def testWideInferredUnknownColumnRejected(tmp_path, packageAndLayout):
  package, layout = packageAndLayout
  profile = ImportProfile().withOverrides(format="wide")
  path = writeCsv(tmp_path, """
plotNumber,YIELD,BOGUS
101,4800,7
""")
  with pytest.raises(ObservationImportError, match="not defined in the trial package"):
    importObservations(path, package, layout, profile)


def testWideInferredIgnoreColumnSkipped(tmp_path, packageAndLayout):
  package, layout = packageAndLayout
  profile = ImportProfile().withOverrides(format="wide", wide={"ignoreColumns": ["Entry"]})
  path = writeCsv(tmp_path, """
plotNumber,Entry,YIELD,SEV
101,17,4800,low
""")
  result = importObservations(path, package, layout, profile)
  assert {o.assessmentCode for o in result.observations} == {"YIELD", "SEV"}


def testWidePlotColumnMissingRejected(tmp_path, packageAndLayout):
  package, layout = packageAndLayout
  profile = ImportProfile().withOverrides(format="wide")
  path = writeCsv(tmp_path, """
YIELD,SEV
4800,low
""")
  with pytest.raises(ObservationImportError, match="wide-format plot column"):
    importObservations(path, package, layout, profile)


# ---- parsing + overrides --------------------------------------------------

def testCommaDecimalSeparatorParsing(tmp_path, packageAndLayout):
  package, layout = packageAndLayout
  profile = ImportProfile().withOverrides(parsing={"decimalSeparator": ",", "naTokens": ["", "NA"]})
  path = writeCsv(tmp_path, """
plotNumber,assessmentCode,value
101,YIELD,"4800,5"
""")
  result = importObservations(path, package, layout, profile)
  assert result.observations[0].value == 4800.5


def testProfileColumnOverrideAppliedAtImport(tmp_path, packageAndLayout):
  package, layout = packageAndLayout
  profile = ImportProfile().withOverrides(long={"value": "reading"})
  path = writeCsv(tmp_path, """
plotNumber,assessmentCode,reading
101,YIELD,4800
""")
  result = importObservations(path, package, layout, profile)
  assert result.observations[0].value == 4800.0


def testLayoutPackageMismatchRejected(tmp_path, validPackageDict):
  package = TrialPackage.model_validate(validPackageDict)
  layout = generateRcbdLayout(package)
  otherDict = dict(validPackageDict)
  otherDict["trial"] = dict(validPackageDict["trial"], trialCode="OTHER-2025")
  otherPackage = TrialPackage.model_validate(otherDict)
  path = writeCsv(tmp_path, """
plotNumber,assessmentCode,value
101,YIELD,4800
""")
  # Layout built from ESV trial, package says OTHER -> mismatch.
  with pytest.raises(ObservationImportError, match="does not match package trial"):
    importObservations(path, otherPackage, layout)
