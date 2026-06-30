# SPDX-License-Identifier: Apache-2.0
"""Shared test fixtures."""

import copy

import pytest

_validPackage = {
  "schemaVersion": "0.1.0",
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
    {"treatmentCode": "T1", "name": "Untreated control"},
    {"treatmentCode": "T2", "name": "Program A", "product": "Fungicide A",
     "rate": 2.5, "rateUnit": "L/ha", "timing": "GS31"},
    {"treatmentCode": "T3", "name": "Program B", "product": "Fungicide B",
     "rate": 1.0, "rateUnit": "L/ha", "timing": "GS39"},
  ],
  "design": {"designType": "rcbd", "replications": 4, "randomizationSeed": 42},
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
