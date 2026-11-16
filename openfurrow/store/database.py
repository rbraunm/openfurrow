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
- Treatments, ratings and assessments carry an explicit `ordinal`. Their order is
  significant -- the randomizer permutes treatments in package order, and the input
  hash preserves list order -- so it must survive a round trip, which SQL row order
  does not guarantee without an ordering column.
- A quantity (a rate, a pressure) is two columns, its value and its unit. A treatment's
  product lines and a trial's applications are tables of their own (decision 0016); the
  short lists inside a line -- its active substances, the applications it names -- are
  JSON text, as `allowedValues` is.
- An observation value is float | str | None. It is stored in two nullable columns,
  `numericValue` (REAL) and `textValue`, with the assessment's data type selecting
  which is populated and both NULL meaning missing. Native REAL keeps floats exact
  across a round trip, which keeps the hash stable; a single text column would
  stringify them.
- The store carries a version. A database written under another version of this
  schema is refused when it is opened, instead of failing later on a missing column.
"""

from __future__ import annotations

import datetime

from sqlalchemy import ForeignKey, Text, event, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

storeVersion = 14


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
  firstBlockInTreatmentOrder: Mapped[bool]
  checkArrangement: Mapped[str]
  mainPlotFactor: Mapped[str | None]
  subPlotFactor: Mapped[str | None]

  siteDetails: Mapped[SiteRow | None] = relationship(
    back_populates="trial", cascade="all, delete-orphan"
  )
  plotDimensions: Mapped[PlotDimensionsRow | None] = relationship(
    back_populates="trial", cascade="all, delete-orphan"
  )
  planting: Mapped[PlantingRow | None] = relationship(
    back_populates="trial", cascade="all, delete-orphan"
  )
  soil: Mapped[SoilRow | None] = relationship(
    back_populates="trial", cascade="all, delete-orphan"
  )
  weather: Mapped[list[WeatherRow]] = relationship(
    back_populates="trial", cascade="all, delete-orphan"
  )
  factors: Mapped[list[FactorRow]] = relationship(
    back_populates="trial", cascade="all, delete-orphan"
  )
  factorLevels: Mapped[list[FactorLevelRow]] = relationship(
    back_populates="trial", cascade="all, delete-orphan"
  )
  targets: Mapped[list[TargetRow]] = relationship(
    back_populates="trial", cascade="all, delete-orphan"
  )
  treatments: Mapped[list[TreatmentRow]] = relationship(
    back_populates="trial", cascade="all, delete-orphan"
  )
  treatmentLines: Mapped[list[TreatmentLineRow]] = relationship(
    back_populates="trial", cascade="all, delete-orphan"
  )
  applications: Mapped[list[ApplicationRow]] = relationship(
    back_populates="trial", cascade="all, delete-orphan"
  )
  ratings: Mapped[list[RatingRow]] = relationship(
    back_populates="trial", cascade="all, delete-orphan"
  )
  assessments: Mapped[list[AssessmentRow]] = relationship(
    back_populates="trial", cascade="all, delete-orphan"
  )
  checkPlots: Mapped[list[CheckPlotRow]] = relationship(
    back_populates="trial", cascade="all, delete-orphan"
  )
  plots: Mapped[list[PlotRow]] = relationship(
    back_populates="trial", cascade="all, delete-orphan"
  )
  observations: Mapped[list[ObservationRow]] = relationship(
    back_populates="trial", cascade="all, delete-orphan"
  )


class SiteRow(Base):
  """The site's address, position and character; at most one row per trial."""

  __tablename__ = "site"

  trialCode: Mapped[str] = mapped_column(
    ForeignKey("trial.trialCode", ondelete="CASCADE"), primary_key=True
  )
  address: Mapped[str | None]
  latitude: Mapped[float | None]
  longitude: Mapped[float | None]
  elevationValue: Mapped[float | None]
  elevationUnit: Mapped[str | None]
  setting: Mapped[str | None]
  exposure: Mapped[str | None]
  slope: Mapped[str | None]

  trial: Mapped[TrialRow] = relationship(back_populates="siteDetails")


class PlotDimensionsRow(Base):
  """The size of the plots and the zones between them; at most one row per trial."""

  __tablename__ = "plotDimensions"

  trialCode: Mapped[str] = mapped_column(
    ForeignKey("trial.trialCode", ondelete="CASCADE"), primary_key=True
  )
  grossLengthValue: Mapped[float | None]
  grossLengthUnit: Mapped[str | None]
  grossWidthValue: Mapped[float | None]
  grossWidthUnit: Mapped[str | None]
  netLengthValue: Mapped[float | None]
  netLengthUnit: Mapped[str | None]
  netWidthValue: Mapped[float | None]
  netWidthUnit: Mapped[str | None]
  alleyWidthValue: Mapped[float | None]
  alleyWidthUnit: Mapped[str | None]
  notes: Mapped[str | None]

  trial: Mapped[TrialRow] = relationship(back_populates="plotDimensions")


class PlantingRow(Base):
  """How the crop was established; at most one row per trial."""

  __tablename__ = "planting"

  trialCode: Mapped[str] = mapped_column(
    ForeignKey("trial.trialCode", ondelete="CASCADE"), primary_key=True
  )
  cultivar: Mapped[str | None]
  cropEPPOCode: Mapped[str | None]
  sowingDate: Mapped[datetime.date | None]
  seedingRateValue: Mapped[float | None]
  seedingRateUnit: Mapped[str | None]
  plantDensityValue: Mapped[float | None]
  plantDensityUnit: Mapped[str | None]
  rowSpacingValue: Mapped[float | None]
  rowSpacingUnit: Mapped[str | None]
  inRowSpacingValue: Mapped[float | None]
  inRowSpacingUnit: Mapped[str | None]
  sowingDepthValue: Mapped[float | None]
  sowingDepthUnit: Mapped[str | None]
  emergenceDate: Mapped[datetime.date | None]
  precedingCrop: Mapped[str | None]
  tillage: Mapped[str | None]
  trainingSystem: Mapped[str | None]
  rootstock: Mapped[str | None]
  plantedYear: Mapped[int | None]
  notes: Mapped[str | None]

  trial: Mapped[TrialRow] = relationship(back_populates="planting")


class SoilRow(Base):
  """The soil of the site; at most one row per trial."""

  __tablename__ = "soil"

  trialCode: Mapped[str] = mapped_column(
    ForeignKey("trial.trialCode", ondelete="CASCADE"), primary_key=True
  )
  soilType: Mapped[str | None]
  texture: Mapped[str | None]
  pH: Mapped[float | None]
  pHMethod: Mapped[str | None]
  organicMatter: Mapped[float | None]
  seedbedQuality: Mapped[str | None]
  fertilizerRegime: Mapped[str | None]
  notes: Mapped[str | None]

  trial: Mapped[TrialRow] = relationship(back_populates="soil")


class WeatherRow(Base):
  """One day of the weather log."""

  __tablename__ = "weather"

  trialCode: Mapped[str] = mapped_column(
    ForeignKey("trial.trialCode", ondelete="CASCADE"), primary_key=True
  )
  date: Mapped[datetime.date] = mapped_column(primary_key=True)
  rainfallValue: Mapped[float | None]
  rainfallUnit: Mapped[str | None]
  irrigationValue: Mapped[float | None]
  irrigationUnit: Mapped[str | None]
  minimumTemperatureValue: Mapped[float | None]
  minimumTemperatureUnit: Mapped[str | None]
  maximumTemperatureValue: Mapped[float | None]
  maximumTemperatureUnit: Mapped[str | None]
  notes: Mapped[str | None]

  trial: Mapped[TrialRow] = relationship(back_populates="weather")


class FactorRow(Base):
  """One factor of a factorial trial. `ordinal` preserves package order."""

  __tablename__ = "factor"

  trialCode: Mapped[str] = mapped_column(
    ForeignKey("trial.trialCode", ondelete="CASCADE"), primary_key=True
  )
  factorCode: Mapped[str] = mapped_column(primary_key=True)
  ordinal: Mapped[int]
  name: Mapped[str]

  trial: Mapped[TrialRow] = relationship(back_populates="factors")


class FactorLevelRow(Base):
  """One level of a factor. `ordinal` preserves the factor's order of levels."""

  __tablename__ = "factorLevel"

  trialCode: Mapped[str] = mapped_column(
    ForeignKey("trial.trialCode", ondelete="CASCADE"), primary_key=True
  )
  factorCode: Mapped[str] = mapped_column(primary_key=True)
  levelCode: Mapped[str] = mapped_column(primary_key=True)
  ordinal: Mapped[int]
  name: Mapped[str]

  trial: Mapped[TrialRow] = relationship(back_populates="factorLevels")


class TargetRow(Base):
  """One target of the trial. `ordinal` preserves package order."""

  __tablename__ = "target"

  trialCode: Mapped[str] = mapped_column(
    ForeignKey("trial.trialCode", ondelete="CASCADE"), primary_key=True
  )
  targetCode: Mapped[str] = mapped_column(primary_key=True)
  ordinal: Mapped[int]
  name: Mapped[str]
  kind: Mapped[str]
  scientificName: Mapped[str | None]
  eppoCode: Mapped[str | None]

  trial: Mapped[TrialRow] = relationship(back_populates="targets")


class TreatmentRow(Base):
  """One treatment under comparison. `ordinal` preserves package order."""

  __tablename__ = "treatment"

  trialCode: Mapped[str] = mapped_column(
    ForeignKey("trial.trialCode", ondelete="CASCADE"), primary_key=True
  )
  treatmentCode: Mapped[str] = mapped_column(primary_key=True)
  ordinal: Mapped[int]
  name: Mapped[str]
  role: Mapped[str | None]
  factorLevels: Mapped[str] = mapped_column(Text)

  trial: Mapped[TrialRow] = relationship(back_populates="treatments")


class TreatmentLineRow(Base):
  """One product line of a treatment. `ordinal` preserves the order of its lines."""

  __tablename__ = "treatmentLine"

  trialCode: Mapped[str] = mapped_column(
    ForeignKey("trial.trialCode", ondelete="CASCADE"), primary_key=True
  )
  treatmentCode: Mapped[str] = mapped_column(primary_key=True)
  ordinal: Mapped[int] = mapped_column(primary_key=True)
  product: Mapped[str]
  kind: Mapped[str | None]
  formulationType: Mapped[str | None]
  activeSubstances: Mapped[str] = mapped_column(Text)
  rateValue: Mapped[float]
  rateUnit: Mapped[str]
  rateBasis: Mapped[str]
  applicationCodes: Mapped[str] = mapped_column(Text)

  trial: Mapped[TrialRow] = relationship(back_populates="treatmentLines")


class ApplicationRow(Base):
  """One application: its plan, and what was done and found when it was made."""

  __tablename__ = "application"

  trialCode: Mapped[str] = mapped_column(
    ForeignKey("trial.trialCode", ondelete="CASCADE"), primary_key=True
  )
  applicationCode: Mapped[str] = mapped_column(primary_key=True)
  ordinal: Mapped[int]
  timing: Mapped[str | None]
  date: Mapped[datetime.date | None]
  time: Mapped[datetime.time | None]
  method: Mapped[str | None]
  placement: Mapped[str | None]
  equipment: Mapped[str | None]
  nozzle: Mapped[str | None]
  pressureValue: Mapped[float | None]
  pressureUnit: Mapped[str | None]
  sprayQuality: Mapped[str | None]
  travelSpeedValue: Mapped[float | None]
  travelSpeedUnit: Mapped[str | None]
  sprayVolumeValue: Mapped[float | None]
  sprayVolumeUnit: Mapped[str | None]
  cropStage: Mapped[str | None]
  targetStage: Mapped[str | None]
  airTemperatureValue: Mapped[float | None]
  airTemperatureUnit: Mapped[str | None]
  relativeHumidity: Mapped[float | None]
  windSpeedValue: Mapped[float | None]
  windSpeedUnit: Mapped[str | None]
  cloudCover: Mapped[float | None]
  soilMoisture: Mapped[str | None]
  notes: Mapped[str | None]

  trial: Mapped[TrialRow] = relationship(back_populates="applications")


class RatingRow(Base):
  """What is rated and its rules. `allowedValues` is stored as a JSON text column."""

  __tablename__ = "rating"

  trialCode: Mapped[str] = mapped_column(
    ForeignKey("trial.trialCode", ondelete="CASCADE"), primary_key=True
  )
  ratingCode: Mapped[str] = mapped_column(primary_key=True)
  ordinal: Mapped[int]
  name: Mapped[str]
  ratingType: Mapped[str | None]
  partRated: Mapped[str | None]
  method: Mapped[str | None]
  targetCode: Mapped[str | None]
  dataType: Mapped[str]
  unit: Mapped[str | None]
  minValue: Mapped[float | None]
  maxValue: Mapped[float | None]
  allowedValues: Mapped[str | None] = mapped_column(Text)
  measurementKind: Mapped[str]
  transform: Mapped[str]
  transformOffset: Mapped[float]

  trial: Mapped[TrialRow] = relationship(back_populates="ratings")


class AssessmentRow(Base):
  """One occasion a rating is taken; observations are keyed by its code."""

  __tablename__ = "assessment"

  trialCode: Mapped[str] = mapped_column(
    ForeignKey("trial.trialCode", ondelete="CASCADE"), primary_key=True
  )
  assessmentCode: Mapped[str] = mapped_column(primary_key=True)
  ordinal: Mapped[int]
  ratingCode: Mapped[str]
  timing: Mapped[str | None]
  date: Mapped[datetime.date | None]
  cropStage: Mapped[str | None]
  targetStage: Mapped[str | None]
  timedFromApplicationCode: Mapped[str | None]
  assessedBy: Mapped[str | None]
  sampleSizeValue: Mapped[float | None]
  sampleSizeUnit: Mapped[str | None]
  notes: Mapped[str | None]
  efficacyMethod: Mapped[str | None]
  efficacyBaselineAssessmentCode: Mapped[str | None]
  untreatedCheck: Mapped[str]
  subsampleCount: Mapped[int | None]
  subsampleRule: Mapped[str | None]

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
  mainPlot: Mapped[int | None]
  treatmentCode: Mapped[str]

  trial: Mapped[TrialRow] = relationship(back_populates="plots")


class CheckPlotRow(Base):
  """An untreated check plot; `pairedPlots` is a JSON list of the plots it serves."""

  __tablename__ = "checkPlot"

  trialCode: Mapped[str] = mapped_column(
    ForeignKey("trial.trialCode", ondelete="CASCADE"), primary_key=True
  )
  plotNumber: Mapped[int] = mapped_column(primary_key=True)
  block: Mapped[int]
  pairedPlots: Mapped[str] = mapped_column(Text)

  trial: Mapped[TrialRow] = relationship(back_populates="checkPlots")


class ObservationRow(Base):
  """One recorded value, keyed by plot and assessment. See the value-column note."""

  __tablename__ = "observation"

  trialCode: Mapped[str] = mapped_column(
    ForeignKey("trial.trialCode", ondelete="CASCADE"), primary_key=True
  )
  plotNumber: Mapped[int] = mapped_column(primary_key=True)
  assessmentCode: Mapped[str] = mapped_column(primary_key=True)
  # 0 is the plot's own value; 1 and up number the subsamples of an assessment that takes them.
  subsample: Mapped[int] = mapped_column(primary_key=True)
  numericValue: Mapped[float | None]
  textValue: Mapped[str | None]
  outOfRangeConfirmed: Mapped[bool]

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
