# SPDX-License-Identifier: Apache-2.0
"""Shared test fixtures."""

import copy

import pytest

from openfurrow import schemaVersion

_validPackage = {
  "schemaVersion": schemaVersion,
  "trial": {
    "trialCode": "ESV-2025-01",
    "title": "Fungicide efficacy on winter wheat",
    "crop": "Wheat",
    "season": "2025 Spring",
    "site": "North Field",
    "objective": "Compare grain yield across fungicide programs",
    "investigator": "Field Lead",
    "organization": "Research Station",
  },
  "treatments": [
    {"treatmentCode": "T1", "name": "Untreated control", "role": "untreatedControl"},
    {"treatmentCode": "T2", "name": "Program A", "role": "test", "lines": [
      {"product": "Fungicide A", "rate": {"value": 2.5, "unit": "L/ha"},
       "rateBasis": "formulatedProduct", "applicationCodes": ["GS31"]},
    ]},
    {"treatmentCode": "T3", "name": "Program B", "role": "reference", "lines": [
      {"product": "Fungicide B", "rate": {"value": 1.0, "unit": "L/ha"},
       "rateBasis": "formulatedProduct", "applicationCodes": ["GS39"]},
    ]},
  ],
  "applications": [
    {"applicationCode": "GS31", "timing": "BBCH 31"},
    {"applicationCode": "GS39", "timing": "BBCH 39"},
  ],
  "design": {"designType": "rcbd", "replications": 4, "randomizationMethod": "sha256FisherYates1", "randomizationSeed": 42},
  "assessments": [
    {"assessmentCode": "YIELD", "name": "Grain yield", "dataType": "numeric",
     "unit": "kg/ha", "minValue": 0.0},
    {"assessmentCode": "SEV", "name": "Disease severity", "dataType": "ordinal",
     "allowedValues": ["none", "low", "moderate", "high"]},
  ],
}


@pytest.fixture
def validPackageDict():
  """A complete, valid trial package as a plain dict.

  Returns a deep copy so a test can mutate it freely without affecting others.
  """
  return copy.deepcopy(_validPackage)
