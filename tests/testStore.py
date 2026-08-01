# SPDX-License-Identifier: Apache-2.0
"""Tests for the canonical SQLite store.

The load path must reconstruct a package and its observations faithfully enough
that the input hash is unchanged and the regenerated layout is identical -- the
two properties the reproducibility story rests on. Float values must round-trip
exactly, typed values must keep their type, and the fail-loud paths (duplicate
save, missing trial, collision) must raise. Cascade delete and SQLite foreign-key
enforcement are checked directly.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from openfurrow.design import generateRcbdLayout
from openfurrow.reports import inputHash
from openfurrow.schema import TrialPackage
from openfurrow.schema.observation import Observation
from openfurrow.store import (
  StoreError,
  createDatabase,
  deleteTrial,
  listTrials,
  loadObservations,
  loadPackage,
  savePackage,
  saveObservations,
  sessionScope,
)
from openfurrow.store.database import ObservationRow


@pytest.fixture
def engine(tmp_path):
  return createDatabase(str(tmp_path / "trials.db"))


def samplePackage(trialCode="TRIAL-1"):
  return TrialPackage.model_validate({
    "schemaVersion": "0.1.0",
    "trial": {"trialCode": trialCode, "title": "Sample trial", "crop": "Wheat", "season": "2025",
              "site": "Field A", "objective": "Compare fungicides", "investigator": "Dr. X",
              "organization": "Org Y"},
    "treatments": [
      {"treatmentCode": "T1", "name": "Untreated control"},
      {"treatmentCode": "T2", "name": "Fungicide X", "product": "Prod X", "rate": 2.5,
       "rateUnit": "L/ha", "timing": "BBCH 30"},
      {"treatmentCode": "T3", "name": "Fungicide Y", "product": "Prod Y", "rate": 1.0, "rateUnit": "kg/ha"},
    ],
    "design": {"designType": "rcbd", "replications": 4, "randomizationSeed": 42},
    "assessments": [
      {"assessmentCode": "YIELD", "name": "Grain yield", "dataType": "numeric", "unit": "kg/ha", "minValue": 0},
      {"assessmentCode": "LODGE", "name": "Lodging", "dataType": "ordinal",
       "allowedValues": ["none", "slight", "severe"]},
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
    savePackage(session, package)
  with sessionScope(engine) as session:
    assert loadPackage(session, "TRIAL-1") == package


def testSaveLoadPreservesInputHash(engine):
  package = samplePackage()
  _, observations = sampleObservations(package)
  with sessionScope(engine) as session:
    savePackage(session, package)
    saveObservations(session, "TRIAL-1", observations)
  with sessionScope(engine) as session:
    loadedPackage = loadPackage(session, "TRIAL-1")
    loadedObservations = loadObservations(session, "TRIAL-1")
  assert inputHash(loadedPackage, loadedObservations) == inputHash(package, observations)


def testSaveLoadPreservesTreatmentOrderViaLayout(engine):
  # The randomizer permutes treatments in package order, so a load that reordered
  # them would produce a different layout. Regenerate from both and compare.
  package = samplePackage()
  originalLayout = generateRcbdLayout(package)
  with sessionScope(engine) as session:
    savePackage(session, package)
  with sessionScope(engine) as session:
    loadedLayout = generateRcbdLayout(loadPackage(session, "TRIAL-1"))
  originalAssignment = {plot.plotNumber: plot.treatmentCode for plot in originalLayout.plots}
  loadedAssignment = {plot.plotNumber: plot.treatmentCode for plot in loadedLayout.plots}
  assert loadedAssignment == originalAssignment


def testObservationValueTypesRoundTrip(engine):
  package = samplePackage()
  _, observations = sampleObservations(package)
  with sessionScope(engine) as session:
    savePackage(session, package)
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
    savePackage(session, package)
    saveObservations(session, "TRIAL-1", observations)
  with sessionScope(engine) as session:
    loaded = {o.plotNumber: o.value for o in loadObservations(session, "TRIAL-1")}
  for observation in observations:
    assert loaded[observation.plotNumber] == observation.value  # exact, not approximate


# ---- fail loud ------------------------------------------------------------

def testSavePackageDuplicateRejected(engine):
  package = samplePackage()
  with sessionScope(engine) as session:
    savePackage(session, package)
  with pytest.raises(StoreError, match="already exists"):
    with sessionScope(engine) as session:
      savePackage(session, package)


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
    savePackage(session, package)
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
    savePackage(session, samplePackage("TRIAL-B"))
    savePackage(session, samplePackage("TRIAL-A"))
  with sessionScope(engine) as session:
    assert listTrials(session) == [("TRIAL-A", "Sample trial"), ("TRIAL-B", "Sample trial")]


def testDeleteTrialCascades(engine):
  package = samplePackage()
  _, observations = sampleObservations(package)
  with sessionScope(engine) as session:
    savePackage(session, package)
    saveObservations(session, "TRIAL-1", observations)
  with sessionScope(engine) as session:
    deleteTrial(session, "TRIAL-1")
  with sessionScope(engine) as session:
    assert listTrials(session) == []
    remaining = session.execute(
      select(ObservationRow).where(ObservationRow.trialCode == "TRIAL-1")
    ).scalars().all()
    assert remaining == []


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


# ---- regression: transform and measurementKind must persist ---------------

def testAssessmentTransformAndKindSurviveRoundTrip(engine):
  """A declared transform and measurement kind must survive save/load.

  Regression: the assessment row once had no columns for these, so a persisted
  transform silently reverted to none on reload -- meaning a transformed analysis
  would quietly run on the untransformed scale after the trial was stored. The default
  round-trip test missed it because its sample used the defaults on both sides.
  """
  package = TrialPackage.model_validate({
    "schemaVersion": "0.1.0",
    "trial": {"trialCode": "TR-1", "title": "t", "crop": "Barley", "season": "2025",
              "site": "s", "objective": "o"},
    "treatments": [{"treatmentCode": code, "name": code} for code in ["A", "B"]],
    "design": {"designType": "rcbd", "replications": 2, "randomizationSeed": 1},
    "assessments": [{"assessmentCode": "CT", "name": "Insect count", "dataType": "numeric",
                     "unit": "per m2", "minValue": 0, "transform": "sqrt",
                     "measurementKind": "count"}],
  })
  with sessionScope(engine) as session:
    savePackage(session, package)
  with sessionScope(engine) as session:
    loaded = loadPackage(session, "TR-1")
  assessment = loaded.assessments[0]
  assert assessment.transform.value == "sqrt"
  assert assessment.measurementKind.value == "count"
  assert loaded == package
