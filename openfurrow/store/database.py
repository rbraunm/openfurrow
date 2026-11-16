# SPDX-License-Identifier: Apache-2.0
"""Canonical store: SQLAlchemy schema and engine.

The canonical store is a single SQLite file (decision 0001), accessed through
SQLAlchemy so the same schema runs on PostgreSQL for a future team mode without a
rewrite. The schema is kept inside the portable intersection of the two engines:
generic column types only, no SQLite-specific features.

Modeling choices, recorded in decisions 0001 and 0015:

- The layout is stored, one row per plot (decision 0015). Which treatment stands on
  which plot is a fact about the field; the seed and the method's name on the trial
  row say how a generated layout was made, and are absent or `imported` otherwise.
- Treatments and assessments carry an explicit `ordinal`. Their order is
  significant -- the randomizer permutes treatments in package order, and the input
  hash preserves list order -- so it must survive a round trip, which SQL row order
  does not guarantee without an ordering column.
- An observation value is float | str | None. It is stored in two nullable columns,
  `numericValue` (REAL) and `textValue`, with the assessment's data type selecting
  which is populated and both NULL meaning missing. Native REAL keeps floats exact
  across a round trip, which keeps the hash stable; a single text column would
  stringify them.
- The store carries a version. A database written under another version of this
  schema is refused when it is opened, instead of failing later on a missing column.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Text, event, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

storeVersion = 2


class StoreError(RuntimeError):
  """A store operation could not be completed as requested."""


class Base(DeclarativeBase):
  """Declarative base for the store's ORM models."""


class StoreVersionRow(Base):
  """The version of this schema the database was written under; exactly one row."""

  __tablename__ = "storeVersion"

  version: Mapped[int] = mapped_column(primary_key=True)


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
  randomizationMethod: Mapped[str]
  randomizationSeed: Mapped[int | None]

  treatments: Mapped[list[TreatmentRow]] = relationship(
    back_populates="trial", cascade="all, delete-orphan"
  )
  assessments: Mapped[list[AssessmentRow]] = relationship(
    back_populates="trial", cascade="all, delete-orphan"
  )
  plots: Mapped[list[PlotRow]] = relationship(
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
  measurementKind: Mapped[str]
  transform: Mapped[str]

  trial: Mapped[TrialRow] = relationship(back_populates="assessments")


class PlotRow(Base):
  """One plot of the layout: a treatment at a position within a block."""

  __tablename__ = "plot"

  trialCode: Mapped[str] = mapped_column(
    ForeignKey("trial.trialCode", ondelete="CASCADE"), primary_key=True
  )
  plotNumber: Mapped[int] = mapped_column(primary_key=True)
  block: Mapped[int]
  positionInBlock: Mapped[int]
  treatmentCode: Mapped[str]

  trial: Mapped[TrialRow] = relationship(back_populates="plots")


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
  """Open the SQLite store at `path`, creating it if the file holds no tables yet.

  An existing store must have been written under this schema's version; any other is
  refused here. Foreign keys are enforced for SQLite via a per-connection pragma; on
  PostgreSQL they are enforced natively and the pragma is not applied.
  """
  from sqlalchemy import create_engine

  engine = create_engine(f"sqlite:///{path}")
  if engine.dialect.name == "sqlite":
    event.listen(engine, "connect", _enableSqliteForeignKeys)

  existingTables = set(inspect(engine).get_table_names())
  if not existingTables:
    Base.metadata.create_all(engine)
    with Session(engine) as session:
      session.add(StoreVersionRow(version=storeVersion))
      session.commit()
    return engine

  if StoreVersionRow.__tablename__ not in existingTables:
    raise StoreError(
      f"database '{path}' was written by an earlier build of OpenFurrow, before stores "
      f"carried a version. Export its trials with that build and import them into a new "
      f"database."
    )
  with Session(engine) as session:
    versions = session.execute(select(StoreVersionRow.version)).scalars().all()
  if versions != [storeVersion]:
    raise StoreError(
      f"database '{path}' holds store version {versions}, and this build reads version "
      f"{storeVersion}. Export its trials with the build that wrote it and import them "
      f"into a new database."
    )
  return engine


def _enableSqliteForeignKeys(dbapiConnection, connectionRecord) -> None:
  cursor = dbapiConnection.cursor()
  cursor.execute("PRAGMA foreign_keys=ON")
  cursor.close()
