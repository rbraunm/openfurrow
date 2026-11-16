# SPDX-License-Identifier: Apache-2.0
"""Tests for the canonical SQLite store.

The load path must reconstruct a package, its layout and its observations
faithfully enough that the input hash is unchanged -- the property the
reproducibility story rests on. Float values must round-trip exactly, typed values
must keep their type, and the fail-loud paths (duplicate save, missing trial,
collision, a database written under another store version) must raise. Cascade
delete and SQLite foreign-key enforcement are checked directly.
"""

import sqlite3

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from openfurrow import schemaVersion
from openfurrow.design import generateRcbdLayout
from openfurrow.reports import inputHash
from openfurrow.schema import TrialLayout, TrialPackage
from openfurrow.schema.observation import Observation
from openfurrow.store import (
  StoreError,
  createDatabase,
  deleteTrial,
  listTrials,
  loadLayout,
  loadObservations,
  loadPackage,
  savePackage,
  saveObservations,
  sessionScope,
  storeVersion,
)
from openfurrow.store.database import (
  ApplicationRow,
  ObservationRow,
  PlotRow,
  TreatmentLineRow,
  TreatmentRow,
)


@pytest.fixture
def engine(tmp_path):
  return createDatabase(str(tmp_path / "trials.db"))


def samplePackage(trialCode="TRIAL-1"):
  return TrialPackage.model_validate({
    "schemaVersion": schemaVersion,
    "trial": {"trialCode": trialCode, "title": "Sample trial", "crop": "Wheat", "season": "2025",
              "site": "Field A", "objective": "Compare fungicides", "investigator": "Dr. X",
              "organization": "Org Y"},
    "treatments": [
      {"treatmentCode": "T1", "name": "Untreated control", "role": "untreatedControl"},
      {"treatmentCode": "T2", "name": "Fungicide X", "role": "test", "lines": [
        {"product": "Prod X", "rate": {"value": 2.5, "unit": "L/ha"}, "rateBasis": "formulatedProduct",
         "applicationCodes": ["A"]},
      ]},
      {"treatmentCode": "T3", "name": "Fungicide Y", "role": "reference", "lines": [
        {"product": "Prod Y", "rate": {"value": 1.0, "unit": "kg/ha"}, "rateBasis": "formulatedProduct",
         "applicationCodes": ["A"]},
      ]},
    ],
    "applications": [{"applicationCode": "A", "timing": "BBCH 30"}],
    "design": {"designType": "rcbd", "replications": 4, "randomizationMethod": "sha256FisherYates1", "randomizationSeed": 42},
    "ratings": [
      {"ratingCode": "YIELD", "name": "Grain yield", "dataType": "numeric", "unit": "kg/ha", "minValue": 0},
      {"ratingCode": "LODGE", "name": "Lodging", "dataType": "ordinal", "allowedValues": ["none", "slight", "severe"]}
    ],
    "assessments": [
      {"assessmentCode": "YIELD", "ratingCode": "YIELD"},
      {"assessmentCode": "LODGE", "ratingCode": "LODGE"}
    ],
  })


def sampleObservations(package):
  layout = generateRcbdLayout(package)
  observations = []
  for index, plot in enumerate(layout.plots):
    observations.append(Observation(plotNumber=plot.plotNumber, assessmentCode="YIELD", value=100.0 + index * 1.25))
    observations.append(Observation(plotNumber=plot.plotNumber, assessmentCode="LODGE", value="none"))
  # one explicitly missing numeric value
  observations[0] = Observation(plotNumber=observations[0].plotNumber, assessmentCode="YIELD", value=None)
  return layout, observations


# ---- round trip -----------------------------------------------------------

def testSaveLoadPackageRoundTrip(engine):
  package = samplePackage()
  with sessionScope(engine) as session:
    savePackage(session, package, generateRcbdLayout(package).plots)
  with sessionScope(engine) as session:
    assert loadPackage(session, "TRIAL-1") == package


def testSaveLoadPreservesInputHash(engine):
  package = samplePackage()
  layout, observations = sampleObservations(package)
  with sessionScope(engine) as session:
    savePackage(session, package, layout.plots)
    saveObservations(session, "TRIAL-1", observations)
  with sessionScope(engine) as session:
    loadedPackage = loadPackage(session, "TRIAL-1")
    loadedLayout = TrialLayout.forPackage(loadedPackage, loadLayout(session, "TRIAL-1"))
    loadedObservations = loadObservations(session, "TRIAL-1")
  assert inputHash(loadedPackage, loadedLayout, loadedObservations) == inputHash(package, layout, observations)


def testSaveLoadLayoutRoundTrip(engine):
  # The layout is stored, not regenerated: what comes back is what went in, plot for plot.
  package = samplePackage()
  layout = generateRcbdLayout(package)
  with sessionScope(engine) as session:
    savePackage(session, package, layout.plots)
  with sessionScope(engine) as session:
    assert loadLayout(session, "TRIAL-1") == layout.plots


def testLoadLayoutOfUnknownTrialRejected(engine):
  with sessionScope(engine) as session:
    with pytest.raises(StoreError, match="not found"):
      loadLayout(session, "NOPE")


def testObservationValueTypesRoundTrip(engine):
  package = samplePackage()
  _, observations = sampleObservations(package)
  with sessionScope(engine) as session:
    savePackage(session, package, generateRcbdLayout(package).plots)
    saveObservations(session, "TRIAL-1", observations)
  with sessionScope(engine) as session:
    loaded = {(o.plotNumber, o.assessmentCode): o.value for o in loadObservations(session, "TRIAL-1")}
  original = {(o.plotNumber, o.assessmentCode): o.value for o in observations}
  assert loaded == original
  # the missing value stayed None; a categorical stayed a string; a yield stayed a float
  missingKey = (observations[0].plotNumber, "YIELD")
  assert loaded[missingKey] is None
  someLodge = next(value for (plot, code), value in loaded.items() if code == "LODGE")
  assert isinstance(someLodge, str)
  someYield = next(value for (plot, code), value in loaded.items() if code == "YIELD" and value is not None)
  assert isinstance(someYield, float)


def testFloatValuesRoundTripExactly(engine):
  package = samplePackage()
  layout = generateRcbdLayout(package)
  awkward = [133.25, 95.5, 1.0 / 3.0, 0.1 + 0.2, 2.718281828459045]
  observations = [
    Observation(plotNumber=layout.plots[index].plotNumber, assessmentCode="YIELD", value=value)
    for index, value in enumerate(awkward)
  ]
  with sessionScope(engine) as session:
    savePackage(session, package, generateRcbdLayout(package).plots)
    saveObservations(session, "TRIAL-1", observations)
  with sessionScope(engine) as session:
    loaded = {o.plotNumber: o.value for o in loadObservations(session, "TRIAL-1")}
  for observation in observations:
    assert loaded[observation.plotNumber] == observation.value  # exact, not approximate


# ---- fail loud ------------------------------------------------------------

def testSavePackageDuplicateRejected(engine):
  package = samplePackage()
  with sessionScope(engine) as session:
    savePackage(session, package, generateRcbdLayout(package).plots)
  with pytest.raises(StoreError, match="already exists"):
    with sessionScope(engine) as session:
      savePackage(session, package, generateRcbdLayout(package).plots)


def testSaveObservationsMissingTrialRejected(engine):
  observation = Observation(plotNumber=1, assessmentCode="YIELD", value=1.0)
  with pytest.raises(StoreError, match="not found"):
    with sessionScope(engine) as session:
      saveObservations(session, "NOPE", [observation])


def testSaveObservationsDuplicateRejected(engine):
  package = samplePackage()
  layout = generateRcbdLayout(package)
  observation = Observation(plotNumber=layout.plots[0].plotNumber, assessmentCode="YIELD", value=1.0)
  with sessionScope(engine) as session:
    savePackage(session, package, generateRcbdLayout(package).plots)
    saveObservations(session, "TRIAL-1", [observation])
  with pytest.raises(StoreError, match="already exists"):
    with sessionScope(engine) as session:
      saveObservations(session, "TRIAL-1", [observation])


def testLoadUnknownTrialRejected(engine):
  with sessionScope(engine) as session:
    with pytest.raises(StoreError, match="not found"):
      loadPackage(session, "NOPE")
    with pytest.raises(StoreError, match="not found"):
      loadObservations(session, "NOPE")


# ---- list, delete, integrity ---------------------------------------------

def testListTrials(engine):
  with sessionScope(engine) as session:
    for trialCode in ("TRIAL-B", "TRIAL-A"):
      package = samplePackage(trialCode)
      savePackage(session, package, generateRcbdLayout(package).plots)
  with sessionScope(engine) as session:
    assert listTrials(session) == [("TRIAL-A", "Sample trial"), ("TRIAL-B", "Sample trial")]


def testDeleteTrialCascades(engine):
  package = samplePackage()
  _, observations = sampleObservations(package)
  with sessionScope(engine) as session:
    savePackage(session, package, generateRcbdLayout(package).plots)
    saveObservations(session, "TRIAL-1", observations)
  with sessionScope(engine) as session:
    deleteTrial(session, "TRIAL-1")
  with sessionScope(engine) as session:
    assert listTrials(session) == []
    remaining = session.execute(
      select(ObservationRow).where(ObservationRow.trialCode == "TRIAL-1")
    ).scalars().all()
    assert remaining == []
    for table in (PlotRow, TreatmentRow, TreatmentLineRow, ApplicationRow):
      remaining = session.execute(select(table).where(table.trialCode == "TRIAL-1")).scalars().all()
      assert remaining == [], table.__tablename__


def testDeleteUnknownTrialRejected(engine):
  with pytest.raises(StoreError, match="not found"):
    with sessionScope(engine) as session:
      deleteTrial(session, "NOPE")


def testForeignKeyEnforcedForOrphanObservation(engine):
  # Inserting an observation for a non-existent trial must be rejected by the DB
  # itself (SQLite foreign keys enabled via pragma), not just by the repository.
  with pytest.raises(IntegrityError):
    with Session(engine) as session:
      session.add(ObservationRow(trialCode="GHOST", plotNumber=1, assessmentCode="YIELD",
                                 numericValue=1.0, textValue=None))
      session.commit()


# ---- treatment lines and applications (decision 0016) ----------------------

def testTreatmentLinesAndApplicationsAreRowsOfTheirOwn(engine):
  package = samplePackage()
  with sessionScope(engine) as session:
    savePackage(session, package, generateRcbdLayout(package).plots)
  with sessionScope(engine) as session:
    lines = session.execute(
      select(TreatmentLineRow).order_by(TreatmentLineRow.treatmentCode, TreatmentLineRow.ordinal)
    ).scalars().all()
    assert [
      (line.treatmentCode, line.product, line.rateValue, line.rateUnit, line.rateBasis, line.applicationCodes)
      for line in lines
    ] == [
      ("T2", "Prod X", 2.5, "L/ha", "formulatedProduct", '["A"]'),
      ("T3", "Prod Y", 1.0, "kg/ha", "formulatedProduct", '["A"]'),
    ]
    applications = session.execute(select(ApplicationRow)).scalars().all()
    assert [(row.applicationCode, row.timing, row.date) for row in applications] == [("A", "BBCH 30", None)]
    roles = session.execute(select(TreatmentRow.treatmentCode, TreatmentRow.role)).all()
    assert sorted(roles) == [("T1", "untreatedControl"), ("T2", "test"), ("T3", "reference")]


def testRateRoundTripsExactly(engine):
  # A rate is authored data and enters the content hash, so it must come back bit for bit.
  awkward = 0.1 + 0.2
  data = samplePackage().model_dump(mode="json")
  data["treatments"][1]["lines"][0]["rate"]["value"] = awkward
  package = TrialPackage.model_validate(data)
  with sessionScope(engine) as session:
    savePackage(session, package, generateRcbdLayout(package).plots)
  with sessionScope(engine) as session:
    assert loadPackage(session, "TRIAL-1").treatments[1].lines[0].rate.value == awkward


def testProductLinesOfATreatmentTheTrialLacksAreRefused(engine):
  package = samplePackage()
  with sessionScope(engine) as session:
    savePackage(session, package, generateRcbdLayout(package).plots)
    session.add(TreatmentLineRow(
      trialCode="TRIAL-1", treatmentCode="GHOST", ordinal=0, product="Prod Z", kind=None,
      formulationType=None, activeSubstances="[]", rateValue=1.0, rateUnit="L/ha",
      rateBasis="formulatedProduct", applicationCodes='["A"]',
    ))
  with sessionScope(engine) as session:
    with pytest.raises(StoreError, match=r"holds product lines for treatment\(s\) \['GHOST'\] it does not have"):
      loadPackage(session, "TRIAL-1")


def testHalfAQuantityInTheStoreIsRefused(engine):
  # A value without its unit is a damaged row; it is not read as a bare number.
  package = samplePackage()
  with sessionScope(engine) as session:
    savePackage(session, package, generateRcbdLayout(package).plots)
  with sessionScope(engine) as session:
    row = session.execute(select(ApplicationRow)).scalar_one()
    row.pressureValue = 250.0
  with sessionScope(engine) as session:
    with pytest.raises(ValidationError) as excInfo:
      loadPackage(session, "TRIAL-1")
  assert [error["loc"] for error in excInfo.value.errors()] == [("unit",)]


# ---- regression: transform and measurementKind must persist ---------------

def testAssessmentTransformAndKindSurviveRoundTrip(engine):
  """A declared transform and measurement kind must survive save/load.

  Regression: the assessment row once had no columns for these, so a persisted
  transform silently reverted to none on reload -- meaning a transformed analysis
  would quietly run on the untransformed scale after the trial was stored. The default
  round-trip test missed it because its sample used the defaults on both sides.
  """
  package = TrialPackage.model_validate({
    "schemaVersion": schemaVersion,
    "trial": {"trialCode": "TR-1", "title": "t", "crop": "Barley", "season": "2025",
              "site": "s", "objective": "o"},
    "treatments": [{"treatmentCode": code, "name": code} for code in ["A", "B"]],
    "design": {"designType": "rcbd", "replications": 2, "randomizationMethod": "sha256FisherYates1", "randomizationSeed": 1},
    "ratings": [
      {"ratingCode": "CT", "name": "Insect count", "dataType": "numeric", "unit": "per m2", "minValue": 0, "transform": "sqrt", "measurementKind": "count"}
    ],
    "assessments": [
      {"assessmentCode": "CT", "ratingCode": "CT"}
    ],
  })
  with sessionScope(engine) as session:
    savePackage(session, package, generateRcbdLayout(package).plots)
  with sessionScope(engine) as session:
    loaded = loadPackage(session, "TR-1")
  assessment = loaded.ratings[0]
  assert assessment.transform.value == "sqrt"
  assert assessment.measurementKind.value == "count"
  assert loaded == package


# ---- the store carries a version ------------------------------------------

def testReopeningAStoreOfThisVersionSucceeds(tmp_path):
  path = str(tmp_path / "trials.db")
  package = samplePackage()
  with sessionScope(createDatabase(path)) as session:
    savePackage(session, package, generateRcbdLayout(package).plots)
  with sessionScope(createDatabase(path)) as session:
    assert listTrials(session) == [("TRIAL-1", "Sample trial")]


def testStoreWithoutAVersionIsRefused(tmp_path):
  # What an earlier build left behind: its tables, and no record of a version.
  path = tmp_path / "old.db"
  connection = sqlite3.connect(path)
  connection.execute("CREATE TABLE trial (trialCode TEXT PRIMARY KEY, title TEXT)")
  connection.commit()
  connection.close()
  with pytest.raises(StoreError, match="written by an earlier build"):
    createDatabase(str(path))


def testStoreOfAnotherVersionIsRefused(tmp_path):
  path = tmp_path / "other.db"
  createDatabase(str(path)).dispose()
  connection = sqlite3.connect(path)
  connection.execute("UPDATE storeVersion SET version = ?", (storeVersion + 1,))
  connection.commit()
  connection.close()
  with pytest.raises(StoreError, match=rf"holds store version \[{storeVersion + 1}\], and this build reads version {storeVersion}"):
    createDatabase(str(path))
