# SPDX-License-Identifier: Apache-2.0
"""Shared test fixtures."""

import copy
import json
import os
import secrets
from pathlib import Path

import pytest

from openIDConnectStandIn import StandInIssuer
from openfurrow import schemaVersion

postgresVariable = "OPENFURROW_TEST_POSTGRES"


def pytest_addoption(parser):
  parser.addoption(
    "--store", choices=("sqlite", "postgresql"), default="sqlite",
    help=f"the database every store test runs on; postgresql takes its server from {postgresVariable}",
  )
  parser.addoption("--testbed", help="Carnelian's testbed.json (rbraunm/carnelian testbed/prepare.py); "
                                     "the sign-in tests run against its identity providers")
  parser.addoption("--directory", action="store_true", help="the Carnelian testbed's Samba directory is running too")
  parser.addoption("--live", action="store_true", help="also read real federations' published aggregates over the internet")


def pytest_configure(config):
  if config.getoption("--store") == "postgresql" and not os.environ.get(postgresVariable):
    raise pytest.UsageError(
      f"--store postgresql needs {postgresVariable}, a postgresql+pg8000:// URL of a role that may create databases"
    )


@pytest.fixture(scope="session")
def testbed(request):
  path = request.config.getoption("--testbed")
  if path is None:
    pytest.skip("identity provider test: run with --testbed=<Carnelian's testbed.json> against a running testbed")
  return json.loads(Path(path).read_text(encoding="utf-8"))


@pytest.fixture
def standIn(tmp_path):
  """An OpenID Connect issuer on the loopback address, with a certificate authority of its own."""
  issuer = StandInIssuer(tmp_path)
  yield issuer
  issuer.close()


@pytest.fixture
def storeKind(request):
  return request.config.getoption("--store")


@pytest.fixture
def newStore(request, tmp_path, storeKind):
  """Store locations by name for one test: a SQLite file, or a PostgreSQL database dropped afterwards.

  The same name gives the same store within a test, so a test can reopen what it made.
  """
  made: dict[str, str] = {}

  def make(name: str) -> str:
    if name in made:
      return made[name]
    if storeKind == "sqlite":
      made[name] = str(tmp_path / f"{name}.db")
      return made[name]
    from sqlalchemy import create_engine, text
    server = os.environ[postgresVariable]
    database = f"openfurrow_test_{secrets.token_hex(6)}"
    admin = create_engine(server, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
      connection.execute(text(f'CREATE DATABASE "{database}"'))
    admin.dispose()
    made[name] = server.rsplit("/", 1)[0] + f"/{database}"
    return made[name]

  yield make
  if storeKind == "postgresql" and made:
    from sqlalchemy import create_engine, text
    admin = create_engine(os.environ[postgresVariable], isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
      for location in made.values():
        connection.execute(text(f'DROP DATABASE "{location.rsplit("/", 1)[1]}" WITH (FORCE)'))
    admin.dispose()

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
  "ratings": [
    {"ratingCode": "YIELD", "name": "Grain yield", "dataType": "numeric", "unit": "kg/ha", "minValue": 0.0},
    {"ratingCode": "SEV", "name": "Disease severity", "dataType": "ordinal", "allowedValues": ["none", "low", "moderate", "high"]}
  ],
  "assessments": [
    {"assessmentCode": "YIELD", "ratingCode": "YIELD"},
    {"assessmentCode": "SEV", "ratingCode": "SEV"}
  ],
}


@pytest.fixture
def validPackageDict():
  """A complete, valid trial package as a plain dict.

  Returns a deep copy so a test can mutate it freely without affecting others.
  """
  return copy.deepcopy(_validPackage)
