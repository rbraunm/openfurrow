# SPDX-License-Identifier: Apache-2.0
"""Reading and writing trial packages and observations to the canonical store.

These functions map between the Pydantic schema (the interchange boundary) and the
ORM rows (the store). They fail loud: saving a trial that already exists, saving an
observation that collides, or loading a trial that is not present all raise rather
than silently overwriting or returning empty. Replacing a trial is an explicit
delete-then-save, never an implicit overwrite.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from openfurrow.store.database import AssessmentRow, ObservationRow, TreatmentRow, TrialRow
from openfurrow.schema.observation import Observation
from openfurrow.schema.trialPackage import (
  AssessmentDataType,
  AssessmentDefinition,
  DesignSpecification,
  DesignType,
  MeasurementKind,
  Transform,
  Treatment,
  TrialMetadata,
  TrialPackage,
)


class StoreError(RuntimeError):
  """A store operation could not be completed as requested."""


class TrialNotFoundError(StoreError):
  """The named trial is not in the store.

  A distinct type because callers need to tell "you asked for something that is not
  here" apart from "what you asked for conflicts with what is here" -- an HTTP surface
  maps these to 404 and 409 respectively, and sniffing the message text to tell them
  apart would be exactly the kind of fragile guessing this project rejects.
  """


class TrialExistsError(StoreError):
  """The trial (or observation) being written is already present."""


@contextmanager
def sessionScope(engine: Engine) -> Iterator[Session]:
  """A transactional session: commit on success, roll back on error, always close."""
  session = Session(engine)
  try:
    yield session
    session.commit()
  except Exception:
    session.rollback()
    raise
  finally:
    session.close()


def savePackage(session: Session, package: TrialPackage) -> None:
  """Persist a trial package. Raises if the trial code is already present."""
  trialCode = package.trial.trialCode
  if session.get(TrialRow, trialCode) is not None:
    raise TrialExistsError(f"trial '{trialCode}' already exists; delete it first to replace it")

  trial = TrialRow(
    trialCode=trialCode,
    title=package.trial.title,
    crop=package.trial.crop,
    season=package.trial.season,
    site=package.trial.site,
    objective=package.trial.objective,
    investigator=package.trial.investigator,
    organization=package.trial.organization,
    schemaVersion=package.schemaVersion,
    designType=package.design.designType.value,
    replications=package.design.replications,
    randomizationSeed=package.design.randomizationSeed,
  )
  for ordinal, treatment in enumerate(package.treatments):
    trial.treatments.append(TreatmentRow(
      trialCode=trialCode,
      treatmentCode=treatment.treatmentCode,
      ordinal=ordinal,
      name=treatment.name,
      product=treatment.product,
      rate=treatment.rate,
      rateUnit=treatment.rateUnit,
      timing=treatment.timing,
    ))
  for ordinal, assessment in enumerate(package.assessments):
    trial.assessments.append(AssessmentRow(
      trialCode=trialCode,
      assessmentCode=assessment.assessmentCode,
      ordinal=ordinal,
      name=assessment.name,
      dataType=assessment.dataType.value,
      unit=assessment.unit,
      timing=assessment.timing,
      minValue=assessment.minValue,
      maxValue=assessment.maxValue,
      allowedValues=json.dumps(assessment.allowedValues) if assessment.allowedValues is not None else None,
      measurementKind=assessment.measurementKind.value,
      transform=assessment.transform.value,
    ))
  session.add(trial)
  session.flush()


def loadPackage(session: Session, trialCode: str) -> TrialPackage:
  """Reconstruct a trial package. Raises if the trial is not present.

  Treatments and assessments are returned in their stored ordinal order, so the
  regenerated layout and the input hash match the originals exactly.
  """
  trial = session.get(TrialRow, trialCode)
  if trial is None:
    raise TrialNotFoundError(f"trial '{trialCode}' not found")

  treatments = [
    Treatment(
      treatmentCode=row.treatmentCode,
      name=row.name,
      product=row.product,
      rate=row.rate,
      rateUnit=row.rateUnit,
      timing=row.timing,
    )
    for row in sorted(trial.treatments, key=lambda row: row.ordinal)
  ]
  assessments = [
    AssessmentDefinition(
      assessmentCode=row.assessmentCode,
      name=row.name,
      dataType=AssessmentDataType(row.dataType),
      unit=row.unit,
      timing=row.timing,
      minValue=row.minValue,
      maxValue=row.maxValue,
      allowedValues=json.loads(row.allowedValues) if row.allowedValues is not None else None,
      measurementKind=MeasurementKind(row.measurementKind),
      transform=Transform(row.transform),
    )
    for row in sorted(trial.assessments, key=lambda row: row.ordinal)
  ]
  return TrialPackage(
    schemaVersion=trial.schemaVersion,
    trial=TrialMetadata(
      trialCode=trial.trialCode,
      title=trial.title,
      crop=trial.crop,
      season=trial.season,
      site=trial.site,
      objective=trial.objective,
      investigator=trial.investigator,
      organization=trial.organization,
    ),
    design=DesignSpecification(
      designType=DesignType(trial.designType),
      replications=trial.replications,
      randomizationSeed=trial.randomizationSeed,
    ),
    treatments=treatments,
    assessments=assessments,
  )


def saveObservations(session: Session, trialCode: str, observations: list[Observation]) -> None:
  """Persist observations for an existing trial. Raises on a missing trial or a collision."""
  if session.get(TrialRow, trialCode) is None:
    raise TrialNotFoundError(f"trial '{trialCode}' not found; save the package first")
  for observation in observations:
    key = (trialCode, observation.plotNumber, observation.assessmentCode)
    if session.get(ObservationRow, key) is not None:
      raise TrialExistsError(
        f"observation already exists for plot {observation.plotNumber}, "
        f"assessment '{observation.assessmentCode}' in trial '{trialCode}'"
      )
    numericValue, textValue = _splitValue(observation.value)
    session.add(ObservationRow(
      trialCode=trialCode,
      plotNumber=observation.plotNumber,
      assessmentCode=observation.assessmentCode,
      numericValue=numericValue,
      textValue=textValue,
    ))
  session.flush()


def loadObservations(session: Session, trialCode: str) -> list[Observation]:
  """Load observations for a trial, ordered by plot then assessment. Raises if absent."""
  if session.get(TrialRow, trialCode) is None:
    raise TrialNotFoundError(f"trial '{trialCode}' not found")
  rows = session.execute(
    select(ObservationRow)
    .where(ObservationRow.trialCode == trialCode)
    .order_by(ObservationRow.plotNumber, ObservationRow.assessmentCode)
  ).scalars().all()
  return [
    Observation(
      plotNumber=row.plotNumber,
      assessmentCode=row.assessmentCode,
      value=_joinValue(row.numericValue, row.textValue),
    )
    for row in rows
  ]


def listTrials(session: Session) -> list[tuple[str, str]]:
  """Every trial in the store as (trialCode, title), ordered by code."""
  rows = session.execute(
    select(TrialRow.trialCode, TrialRow.title).order_by(TrialRow.trialCode)
  ).all()
  return [(row.trialCode, row.title) for row in rows]


def deleteTrial(session: Session, trialCode: str) -> None:
  """Delete a trial and all its treatments, assessments, and observations."""
  trial = session.get(TrialRow, trialCode)
  if trial is None:
    raise TrialNotFoundError(f"trial '{trialCode}' not found")
  session.delete(trial)
  session.flush()


def _splitValue(value: float | str | None) -> tuple[float | None, str | None]:
  if value is None:
    return None, None
  if isinstance(value, str):
    return None, value
  return float(value), None


def _joinValue(numericValue: float | None, textValue: str | None) -> float | str | None:
  if numericValue is not None:
    return numericValue
  if textValue is not None:
    return textValue
  return None
