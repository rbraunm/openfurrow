# SPDX-License-Identifier: Apache-2.0
"""Tests for the import profile config schema and YAML loader."""

import pytest
from pydantic import ValidationError

from openfurrow.config import (
  ImportFormat,
  ImportProfile,
  LongColumns,
  MeanComparison,
  OpenFurrowConfig,
  ValueParsing,
  WideColumns,
  defaultConfig,
  loadConfig,
)


# ---- defaults -----------------------------------------------------------

def testDefaultProfileIsLong():
  profile = ImportProfile()
  assert profile.format is ImportFormat.long
  assert profile.long.plotNumber == "plotNumber"
  assert profile.long.assessmentCode == "assessmentCode"
  assert profile.long.value == "value"


def testDefaultParsingTreatsBlankAndNaAsMissing():
  parsing = ValueParsing()
  assert parsing.decimalSeparator == "."
  assert "" in parsing.naTokens
  assert "NA" in parsing.naTokens


def testDefaultConfigHelperIsAllDefaults():
  config = defaultConfig()
  assert config.importProfile.format is ImportFormat.long


# ---- long-format validation ---------------------------------------------

def testLongColumnsMustBeDistinct():
  with pytest.raises(ValidationError, match="distinct columns"):
    LongColumns(plotNumber="col", assessmentCode="col", value="value")


# ---- wide-format validation ----------------------------------------------

def testWideAssessmentColumnsRejectDuplicates():
  with pytest.raises(ValidationError, match="assessmentColumns contains duplicates"):
    WideColumns(plotNumber="Plot", assessmentColumns=["YIELD", "YIELD"])


def testWidePlotColumnCannotBeAssessmentColumn():
  with pytest.raises(ValidationError, match="also an assessment column"):
    WideColumns(plotNumber="Plot", assessmentColumns=["Plot", "YIELD"])


def testWidePlotColumnCannotBeIgnored():
  with pytest.raises(ValidationError, match="also listed in ignoreColumns"):
    WideColumns(plotNumber="Plot", ignoreColumns=["Plot"])


def testWideAssessmentAndIgnoreCannotOverlap():
  with pytest.raises(ValidationError, match="both assessed and ignored"):
    WideColumns(plotNumber="Plot", assessmentColumns=["YIELD"], ignoreColumns=["YIELD"])


def testWideAssessmentColumnsInferredByDefault():
  # None means infer at import time; this is the valid default, not an error.
  assert WideColumns(plotNumber="Plot").assessmentColumns is None


# ---- value parsing validation --------------------------------------------

def testDecimalSeparatorRestrictedToDotOrComma():
  with pytest.raises(ValidationError, match="must be '.' or ','"):
    ValueParsing(decimalSeparator=";")


def testDecimalSeparatorCannotAlsoBeNaToken():
  with pytest.raises(ValidationError, match="cannot also be an NA token"):
    ValueParsing(decimalSeparator=".", naTokens=["", "."])


def testCommaDecimalSeparatorAccepted():
  parsing = ValueParsing(decimalSeparator=",", naTokens=["", "NA"])
  assert parsing.decimalSeparator == ","


# ---- loader ---------------------------------------------------------------

def writeConfig(tmpPath, text):
  path = tmpPath / "openfurrow.yaml"
  path.write_text(text, encoding="utf-8")
  return path


def testLoadConfigParsesImportSection(tmp_path):
  path = writeConfig(tmp_path, """
import:
  format: wide
  wide:
    plotNumber: Plot
    assessmentColumns:
      - Yield
      - Severity
    ignoreColumns:
      - Entry
  parsing:
    decimalSeparator: ","
    naTokens: ["", "NA", "-"]
""")
  config = loadConfig(path)
  assert config.importProfile.format is ImportFormat.wide
  assert config.importProfile.wide.plotNumber == "Plot"
  assert config.importProfile.wide.assessmentColumns == ["Yield", "Severity"]
  assert config.importProfile.wide.ignoreColumns == ["Entry"]
  assert config.importProfile.parsing.decimalSeparator == ","


def testLoadConfigEmptyFileUsesDefaults(tmp_path):
  path = writeConfig(tmp_path, "")
  config = loadConfig(path)
  assert config.importProfile.format is ImportFormat.long


def testLoadConfigRejectsUnknownSection(tmp_path):
  path = writeConfig(tmp_path, "bogusSection:\n  key: value\n")
  with pytest.raises(ValidationError) as excInfo:
    loadConfig(path)
  assert any(error["type"] == "extra_forbidden" for error in excInfo.value.errors())


def testLoadConfigRejectsNonMappingRoot(tmp_path):
  path = writeConfig(tmp_path, "- just\n- a\n- list\n")
  with pytest.raises(ValueError, match="config root must be a mapping"):
    loadConfig(path)


def testLoadConfigRejectsContradictoryParsing(tmp_path):
  path = writeConfig(tmp_path, """
import:
  parsing:
    decimalSeparator: "."
    naTokens: ["", "."]
""")
  with pytest.raises(ValidationError, match="cannot also be an NA token"):
    loadConfig(path)


# ---- overrides ------------------------------------------------------------

def testOverrideFormat():
  profile = ImportProfile().withOverrides(format="wide")
  assert profile.format is ImportFormat.wide


def testOverrideFormatAcceptsEnum():
  profile = ImportProfile().withOverrides(format=ImportFormat.wide)
  assert profile.format is ImportFormat.wide


def testOverrideLongColumnLeavesOthersUnchanged():
  profile = ImportProfile().withOverrides(long={"value": "Yield"})
  assert profile.long.value == "Yield"
  assert profile.long.plotNumber == "plotNumber"
  assert profile.long.assessmentCode == "assessmentCode"


def testOverrideParsingNaTokens():
  profile = ImportProfile().withOverrides(parsing={"naTokens": ["", "-"]})
  assert profile.parsing.naTokens == ["", "-"]


def testOverrideIsRevalidated():
  # Overriding the value column onto the plot column violates distinctness.
  with pytest.raises(ValidationError, match="distinct columns"):
    ImportProfile().withOverrides(long={"value": "plotNumber"})


def testNoOverridesPreservesValues():
  original = ImportProfile()
  unchanged = original.withOverrides()
  assert unchanged.model_dump() == original.model_dump()


# ---- analysis settings (decision 0009) ----------------------------------

def testDefaultAnalysisSettings():
  config = OpenFurrowConfig()
  assert config.analysis.significanceLevel == 0.05
  assert config.analysis.meanComparison is MeanComparison.protectedLSD


def testAnalysisSettingsFromYaml(tmp_path):
  path = tmp_path / "openfurrow.yaml"
  path.write_text("analysis:\n  significanceLevel: 0.01\n  meanComparison: lsd\n", encoding="utf-8")
  config = loadConfig(path)
  assert config.analysis.significanceLevel == 0.01
  assert config.analysis.meanComparison is MeanComparison.lsd


def testAnalysisSignificanceLevelOutOfRangeRejected():
  with pytest.raises(ValidationError):
    OpenFurrowConfig.model_validate({"analysis": {"significanceLevel": 1.0}})
  with pytest.raises(ValidationError):
    OpenFurrowConfig.model_validate({"analysis": {"significanceLevel": 0.0}})


def testUnknownMeanComparisonRejected():
  with pytest.raises(ValidationError):
    OpenFurrowConfig.model_validate({"analysis": {"meanComparison": "tukey"}})


def testUnknownAnalysisSettingRejected():
  with pytest.raises(ValidationError):
    OpenFurrowConfig.model_validate({"analysis": {"alpha": 0.05}})
