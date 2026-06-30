# SPDX-License-Identifier: Apache-2.0
"""Canonical store: SQLAlchemy schema and engine.

The canonical store is a single SQLite file (decision 0001), accessed through
SQLAlchemy so the same schema runs on PostgreSQL for a future team mode without a
rewrite. The schema is kept inside the portable intersection of the two engines:
generic column types only, no SQLite-specific features.

Three deliberate modeling choices, recorded in decision 0001:

- The layout is not stored. It is a pure function of the package (the seed plus the
  design and treatment order), so per "derive, don't duplicate" it is regenerated
  on demand rather than persisted -- which also keeps the input hash, computed over
  package and observations, a complete description of the trial.
- Treatments and assessments carry an explicit `ordinal`. Their order is
  significant -- the randomizer permutes treatments in package order, and the input
  hash preserves list order -- so it must survive a round trip, which SQL row order
  does not guarantee without an ordering column.
- An observation value is float | str | None. It is stored in two nullable columns,
  `numericValue` (REAL) and `textValue`, with the assessment's data type selecting
  which is populated and both NULL meaning missing. Native REAL keeps floats exact
  across a round trip, which keeps the hash stable; a single text column would
  stringify them.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Text, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
  """Declarative base for the store's ORM models."""


class TrialRow(Base):
  """A trial: its metadata and design, folded into one row (the relation is 1:1)."""

  __tablename__ = "trial"

  trialCode: Mapped[str] = mapped_column(primary_key=True)
  title: Mapped[str]
  crop: Mapped[str]
  season: Mapped[str]
  site: Mapped[str]
  objective: Mapped[str]
  investigator: Mapped[str | None]
  organization: Mapped[str | None]
  schemaVersion: Mapped[str]
  designType: Mapped[str]
  replications: Mapped[int]
  randomizationSeed: Mapped[int]

  treatments: Mapped[list[TreatmentRow]] = relationship(
    back_populates="trial", cascade="all, delete-orphan"
  )
  assessments: Mapped[list[AssessmentRow]] = relationship(
    back_populates="trial", cascade="all, delete-orphan"
  )
  observations: Mapped[list[ObservationRow]] = relationship(
    back_populates="trial", cascade="all, delete-orphan"
  )


class TreatmentRow(Base):
  """One treatment under comparison. `ordinal` preserves package order."""

  __tablename__ = "treatment"

  trialCode: Mapped[str] = mapped_column(
    ForeignKey("trial.trialCode", ondelete="CASCADE"), primary_key=True
  )
  treatmentCode: Mapped[str] = mapped_column(primary_key=True)
  ordinal: Mapped[int]
  name: Mapped[str]
  product: Mapped[str | None]
  rate: Mapped[float | None]
  rateUnit: Mapped[str | None]
  timing: Mapped[str | None]

  trial: Mapped[TrialRow] = relationship(back_populates="treatments")


class AssessmentRow(Base):
  """One assessment to collect. `allowedValues` is stored as a JSON text column."""

  __tablename__ = "assessment"

  trialCode: Mapped[str] = mapped_column(
    ForeignKey("trial.trialCode", ondelete="CASCADE"), primary_key=True
  )
  assessmentCode: Mapped[str] = mapped_column(primary_key=True)
  ordinal: Mapped[int]
  name: Mapped[str]
  dataType: Mapped[str]
  unit: Mapped[str | None]
  timing: Mapped[str | None]
  minValue: Mapped[float | None]
  maxValue: Mapped[float | None]
  allowedValues: Mapped[str | None] = mapped_column(Text)

  trial: Mapped[TrialRow] = relationship(back_populates="assessments")


class ObservationRow(Base):
  """One recorded value, keyed by plot and assessment. See the value-column note."""

  __tablename__ = "observation"

  trialCode: Mapped[str] = mapped_column(
    ForeignKey("trial.trialCode", ondelete="CASCADE"), primary_key=True
  )
  plotNumber: Mapped[int] = mapped_column(primary_key=True)
  assessmentCode: Mapped[str] = mapped_column(primary_key=True)
  numericValue: Mapped[float | None]
  textValue: Mapped[str | None]

  trial: Mapped[TrialRow] = relationship(back_populates="observations")


def createDatabase(path: str) -> Engine:
  """Open (creating if needed) the SQLite store at `path` and ensure the schema.

  Foreign keys are enforced for SQLite via a per-connection pragma; on PostgreSQL
  they are enforced natively and the pragma is not applied.
  """
  from sqlalchemy import create_engine

  engine = create_engine(f"sqlite:///{path}")
  if engine.dialect.name == "sqlite":
    event.listen(engine, "connect", _enableSqliteForeignKeys)
  Base.metadata.create_all(engine)
  return engine


def _enableSqliteForeignKeys(dbapiConnection, connectionRecord) -> None:
  cursor = dbapiConnection.cursor()
  cursor.execute("PRAGMA foreign_keys=ON")
  cursor.close()
