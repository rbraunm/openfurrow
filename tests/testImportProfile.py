# SPDX-License-Identifier: Apache-2.0
"""Tests for the import profile config schema and YAML loader."""

import pytest
from pydantic import ValidationError

from openfurrow.config import (
  ImportFormat,
  ImportProfile,
  LongColumns,
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
