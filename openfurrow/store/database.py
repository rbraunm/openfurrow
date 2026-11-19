# SPDX-License-Identifier: Apache-2.0
"""Canonical store: SQLAlchemy schema and engine.

The store is a SQLite file or a PostgreSQL database (decision 0001), accessed through
SQLAlchemy with one schema for both; which a deployment uses is its choice. The schema
is kept inside the portable intersection of the two engines: generic column types only.
A location is a file path for SQLite or a `postgresql+pg8000://` URL; pg8000 is the
driver because its licence (BSD) and its dependencies' are permissive.

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
import re
from pathlib import Path

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, LargeBinary, Text, case, column, event, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

storeVersion = 21


class StoreError(RuntimeError):
  """A store operation could not be completed as requested."""


class NotFoundError(StoreError):
  """A trial, place or other named thing is not in the store, or not visible to whoever asks."""


class Base(DeclarativeBase):
  """Declarative base for the store's ORM models."""


class StoreVersionRow(Base):
  """The version of this schema the database was written under; exactly one row."""

  __tablename__ = "storeVersion"

  version: Mapped[int] = mapped_column(primary_key=True)


class HierarchyLevelRow(Base):
  """One level of the hierarchy (decision 0034); a built-in level has no name of its own."""

  __tablename__ = "hierarchyLevel"

  levelCode: Mapped[str] = mapped_column(primary_key=True)
  ordinal: Mapped[int] = mapped_column(unique=True)
  name: Mapped[str | None]


class PlaceRow(Base):
  """A place at one level, inside a place of the level above (none for the first level)."""

  __tablename__ = "place"

  placeID: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
  levelCode: Mapped[str] = mapped_column(ForeignKey("hierarchyLevel.levelCode"))
  parentID: Mapped[int | None] = mapped_column(ForeignKey("place.placeID"))
  code: Mapped[str]
  name: Mapped[str]


class SettingValueRow(Base):
  """A setting's value at one scope: 'server', 'place:<placeID>' or 'trial:<trialCode>' (decision 0035)."""

  __tablename__ = "settingValue"

  scope: Mapped[str] = mapped_column(primary_key=True)
  key: Mapped[str] = mapped_column(primary_key=True)
  valueJSON: Mapped[str]


class AccountRow(Base):
  """A person who signs in (decision 0036); the user name is stored lower-case."""

  __tablename__ = "account"

  accountID: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
  userName: Mapped[str] = mapped_column(unique=True)
  displayName: Mapped[str]
  email: Mapped[str | None]
  locale: Mapped[str | None]
  active: Mapped[bool]
  passwordHash: Mapped[str | None]
  createdAt: Mapped[datetime.datetime]


class AccountGroupRow(Base):
  """A named group of accounts; roles given to it hold for its members."""

  __tablename__ = "accountGroup"

  groupID: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
  name: Mapped[str] = mapped_column(unique=True)
  # A mirrored group belongs to its identity provider, which alone sets its members (decision 0040).
  providerName: Mapped[str | None] = mapped_column(ForeignKey("identityProvider.providerName", ondelete="CASCADE"))


class GroupMemberRow(Base):
  __tablename__ = "groupMember"

  groupID: Mapped[int] = mapped_column(ForeignKey("accountGroup.groupID", ondelete="CASCADE"), primary_key=True)
  accountID: Mapped[int] = mapped_column(ForeignKey("account.accountID", ondelete="CASCADE"), primary_key=True)


class CustomRoleRow(Base):
  """A role an organization defined; its permissions are a JSON list (decision 0037)."""

  __tablename__ = "customRole"

  roleCode: Mapped[str] = mapped_column(primary_key=True)
  name: Mapped[str]
  permissionsJSON: Mapped[str]


class WorkloadRuleRow(Base):
  """A trusted workload (decision 0042): the issuer whose tokens it accepts and, as a JSON object, the claims each
  must carry with exactly these values. Nothing of a token is kept."""

  __tablename__ = "workloadRule"

  ruleName: Mapped[str] = mapped_column(primary_key=True)
  issuer: Mapped[str]
  claimsJSON: Mapped[str] = mapped_column(Text)
  enabled: Mapped[bool]
  certificateAuthority: Mapped[str | None]
  createdAt: Mapped[datetime.datetime]


def _named(columnName: str):
  return case((column(columnName).is_(None), 0), else_=1)


class RoleAssignmentRow(Base):
  """A role given to exactly one of an account, a group or a workload rule, at a stored scope ('server', 'place:<id>',
  'trial:<code>')."""

  __tablename__ = "roleAssignment"
  __table_args__ = (CheckConstraint(_named("accountID") + _named("groupID") + _named("ruleName") == 1,
                                    name="roleAssignmentHasOneHolder"),)

  assignmentID: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
  roleCode: Mapped[str]
  scope: Mapped[str]
  accountID: Mapped[int | None] = mapped_column(ForeignKey("account.accountID", ondelete="CASCADE"))
  groupID: Mapped[int | None] = mapped_column(ForeignKey("accountGroup.groupID", ondelete="CASCADE"))
  ruleName: Mapped[str | None] = mapped_column(ForeignKey("workloadRule.ruleName", ondelete="CASCADE"))


class AuthTokenRow(Base):
  """A session or an API token, kept only as its SHA-256."""

  __tablename__ = "authToken"

  tokenHash: Mapped[str] = mapped_column(primary_key=True)
  accountID: Mapped[int] = mapped_column(ForeignKey("account.accountID", ondelete="CASCADE"))
  kind: Mapped[str]
  name: Mapped[str | None]
  createdAt: Mapped[datetime.datetime]
  expiresAt: Mapped[datetime.datetime | None]


class IdentityProviderRow(Base):
  """A configured identity provider (decision 0040); its settings are JSON, its secrets are not stored."""

  __tablename__ = "identityProvider"

  providerName: Mapped[str] = mapped_column(primary_key=True)
  kind: Mapped[str]
  settingsJSON: Mapped[str] = mapped_column(Text)
  enabled: Mapped[bool]
  tokenHash: Mapped[str | None]


class ExternalIdentityRow(Base):
  """An account's identity at one provider, by the provider's own stable subject."""

  __tablename__ = "externalIdentity"

  providerName: Mapped[str] = mapped_column(ForeignKey("identityProvider.providerName", ondelete="CASCADE"),
                                            primary_key=True)
  subject: Mapped[str] = mapped_column(primary_key=True)
  accountID: Mapped[int] = mapped_column(ForeignKey("account.accountID", ondelete="CASCADE"))


class ProvisionedResourceRow(Base):
  """A user or group a provider keeps here by SCIM: its SCIM document and the account or group it is."""

  __tablename__ = "provisionedResource"

  providerName: Mapped[str] = mapped_column(ForeignKey("identityProvider.providerName", ondelete="CASCADE"),
                                            primary_key=True)
  resourceType: Mapped[str] = mapped_column(primary_key=True)
  resourceID: Mapped[str] = mapped_column(primary_key=True)
  accountID: Mapped[int | None] = mapped_column(ForeignKey("account.accountID", ondelete="CASCADE"))
  groupID: Mapped[int | None] = mapped_column(ForeignKey("accountGroup.groupID", ondelete="CASCADE"))
  documentJSON: Mapped[str] = mapped_column(Text)


class PendingSignInRow(Base):
  """A sign-in sent to a provider and not yet back; found by the SHA-256 of its browser cookie, used once."""

  __tablename__ = "pendingSignIn"

  keyHash: Mapped[str] = mapped_column(primary_key=True)
  providerName: Mapped[str] = mapped_column(ForeignKey("identityProvider.providerName", ondelete="CASCADE"))
  stateJSON: Mapped[str] = mapped_column(Text)
  expiresAt: Mapped[datetime.datetime]


class ProviderSessionRow(Base):
  """The provider session a session token was issued for, kept so a sign-out at either end ends the other."""

  __tablename__ = "providerSession"
  __table_args__ = (Index("providerSessionByID", "providerName", "sessionID"),
                    Index("providerSessionBySubject", "providerName", "subject"))

  tokenHash: Mapped[str] = mapped_column(ForeignKey("authToken.tokenHash", ondelete="CASCADE"), primary_key=True)
  providerName: Mapped[str] = mapped_column(ForeignKey("identityProvider.providerName", ondelete="CASCADE"))
  subject: Mapped[str]
  sessionID: Mapped[str | None]
  detailJSON: Mapped[str] = mapped_column(Text)


class ReplayClaimRow(Base):
  """A message identifier used once (a SAML assertion or LogoutRequest, an OpenID Connect logout token), kept until
  it could no longer be accepted anyway; inserting one is the atomic claim."""

  __tablename__ = "replayClaim"

  scope: Mapped[str] = mapped_column(primary_key=True)
  identifier: Mapped[str] = mapped_column(primary_key=True)
  expiresAt: Mapped[datetime.datetime] = mapped_column(index=True)


class DiscoveryListRow(Base):
  """A federation provider's discovery list (decision 0040): when its aggregate was last read, and until when it held."""

  __tablename__ = "discoveryList"

  providerName: Mapped[str] = mapped_column(ForeignKey("identityProvider.providerName", ondelete="CASCADE"),
                                            primary_key=True)
  fetchedAt: Mapped[datetime.datetime]
  validUntil: Mapped[datetime.datetime]


class DiscoveredInstitutionRow(Base):
  """An institution a federation's aggregate offers for discovery; its keys are never kept, only what finding it
  needs. `searchText` is its names, entity ID and scopes folded for case- and accent-insensitive search."""

  __tablename__ = "discoveredInstitution"

  providerName: Mapped[str] = mapped_column(ForeignKey("discoveryList.providerName", ondelete="CASCADE"),
                                            primary_key=True)
  entityID: Mapped[str] = mapped_column(primary_key=True)
  displayNamesJSON: Mapped[str] = mapped_column(Text)
  scopesJSON: Mapped[str] = mapped_column(Text)
  registrationAuthority: Mapped[str | None]
  searchText: Mapped[str] = mapped_column(Text)


class ScheduledTaskRow(Base):
  """A configured task of a kind defined in code (decision 0041). `ownerProvider` names the identity provider whose
  feature made it and still needs it, so it is not deleted while that provider uses it; `ownerFeature` names a
  feature of the store itself that made it with the store (retention, decision 0044)."""

  __tablename__ = "scheduledTask"
  __table_args__ = (CheckConstraint(_named("ownerProvider") + _named("ownerFeature") <= 1, name="scheduledTaskHasOneOwner"),)

  name: Mapped[str] = mapped_column(primary_key=True)
  kind: Mapped[str]
  parametersJSON: Mapped[str] = mapped_column(Text)
  schedule: Mapped[str]
  enabled: Mapped[bool]
  timeLimitSeconds: Mapped[int]
  nextRunAt: Mapped[datetime.datetime | None]
  createdAt: Mapped[datetime.datetime]
  ownerProvider: Mapped[str | None] = mapped_column(ForeignKey("identityProvider.providerName"))
  ownerFeature: Mapped[str | None]


class TaskRunRow(Base):
  """One run of a task: requested, then claimed by one scheduler (running), then succeeded, failed or stopped; or
  skipped when its task was still running. `host`, `schedulerProcessID` and `processID` say where a running run is,
  so a run whose scheduler died can be found."""

  __tablename__ = "taskRun"
  __table_args__ = (Index("taskRunByTask", "taskName", "requestedAt"), Index("taskRunByState", "state"))

  runID: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
  taskName: Mapped[str] = mapped_column(ForeignKey("scheduledTask.name", ondelete="CASCADE"))
  requestedBy: Mapped[str]
  requestedAt: Mapped[datetime.datetime]
  startedAt: Mapped[datetime.datetime | None]
  finishedAt: Mapped[datetime.datetime | None]
  state: Mapped[str]
  summary: Mapped[str | None] = mapped_column(Text)
  output: Mapped[str] = mapped_column(Text)
  host: Mapped[str | None]
  schedulerProcessID: Mapped[int | None]
  processID: Mapped[int | None]


class SchedulerHeartbeatRow(Base):
  """When a scheduler last checked in, and which; exactly one row once any scheduler has run."""

  __tablename__ = "schedulerHeartbeat"

  heartbeatID: Mapped[int] = mapped_column(primary_key=True)
  host: Mapped[str]
  processID: Mapped[int]
  lastSeenAt: Mapped[datetime.datetime]


class AuditEventRow(Base):
  """One change, who made it and from where (decision 0038); never updated, and removed only by retention (decision
  0044)."""

  __tablename__ = "auditEvent"

  eventID: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
  at: Mapped[datetime.datetime]
  actorKind: Mapped[str]
  actorName: Mapped[str | None]
  surface: Mapped[str]
  action: Mapped[str]
  scope: Mapped[str]
  detailJSON: Mapped[str]


class TrialRow(Base):
  """A trial: its metadata and design, folded into one row (the relation is 1:1)."""

  __tablename__ = "trial"

  trialCode: Mapped[str] = mapped_column(primary_key=True)
  placeID: Mapped[int | None] = mapped_column(ForeignKey("place.placeID"))
  # Like the place, when a trial was closed is a fact of this store, not of the trial: outside its content hash.
  closedOn: Mapped[datetime.date | None]
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


class ReceivedFileRow(Base):
  """A file as an import received it (decision 0044): its bytes and their SHA-256, the name it was sent under, the
  sheet read, the columns as they were mapped, who imported it and when, and what the import made of it. Kept beside
  the trial and outside its content hash; the trial's deletion removes it."""

  __tablename__ = "receivedFile"
  __table_args__ = (Index("receivedFileByTrial", "trialCode", "fileID"),)

  fileID: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
  trialCode: Mapped[str] = mapped_column(ForeignKey("trial.trialCode", ondelete="CASCADE"))
  kind: Mapped[str]
  fileName: Mapped[str | None]
  sheetName: Mapped[str | None]
  sha256: Mapped[str]
  sizeBytes: Mapped[int] = mapped_column(BigInteger)
  content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
  mappingJSON: Mapped[str] = mapped_column(Text)
  producedJSON: Mapped[str] = mapped_column(Text)
  importedByKind: Mapped[str]
  importedByName: Mapped[str | None]
  importedAt: Mapped[datetime.datetime]


class RetentionHoldRow(Base):
  """A hold on a trial (decision 0044): while it stands nothing of the trial is pruned, and the trial is not deleted,
  which the foreign key refuses too."""

  __tablename__ = "retentionHold"

  trialCode: Mapped[str] = mapped_column(ForeignKey("trial.trialCode"), primary_key=True)
  reason: Mapped[str] = mapped_column(Text)
  heldByKind: Mapped[str]
  heldByName: Mapped[str | None]
  heldAt: Mapped[datetime.datetime]


postgresqlScheme = "postgresql+pg8000://"


def isDatabaseURL(location: str) -> bool:
  """True for a database URL, False for a SQLite file path; any URL but PostgreSQL's is refused."""
  if "://" not in location:
    return False
  if not location.startswith(postgresqlScheme):
    raise StoreError(f"a store URL starts with '{postgresqlScheme}'; got '{location.split('://')[0]}://'")
  return True


def displayLocation(location: str) -> str:
  """The location without a password, for messages."""
  return re.sub(r"://([^:/@]+):[^@]*@", r"://\1:***@", location)


def openEngine(location: str) -> Engine:
  """An engine on the store's database, foreign keys enforced on both engines."""
  from sqlalchemy import create_engine

  if not isDatabaseURL(location):
    engine = create_engine(f"sqlite:///{location}")
    event.listen(engine, "connect", _enableSqliteForeignKeys)
    return engine
  return create_engine(location, pool_pre_ping=True)


def createDatabase(location: str, create: bool = True) -> Engine:
  """Open the store at `location`, creating its tables in an empty database when `create`.

  An existing store must have been written under this schema's version; any other is
  refused here, and so are a file that does not exist and an empty database when `create`
  is false. Foreign keys are enforced for SQLite via a per-connection pragma; PostgreSQL
  enforces them itself.
  """
  # SQLite makes the file it is asked to open, so a mistyped path would leave an empty one behind.
  if not create and not isDatabaseURL(location) and not Path(location).exists():
    raise StoreError(f"database '{location}' does not exist; create it first")
  engine = openEngine(location)
  existingTables = set(inspect(engine).get_table_names())
  if not existingTables:
    if not create:
      raise StoreError(f"database '{displayLocation(location)}' holds no OpenFurrow store; create it first")
    from openfurrow.schema.hierarchy import defaultLevelCodes
    from openfurrow.store.tasks import createFeatureTasks
    with engine.connect() as connection:
      if engine.dialect.name == "sqlite":
        # Python's SQLite driver opens no transaction for CREATE statements, so each table and index would be written
        # to disk on its own; begun explicitly, the store's creation is one write, and all of it or none.
        connection.exec_driver_sql("BEGIN")
      Base.metadata.create_all(connection)
      with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        session.add(StoreVersionRow(version=storeVersion))
        session.add_all(
          HierarchyLevelRow(levelCode=code, ordinal=ordinal, name=None) for ordinal, code in enumerate(defaultLevelCodes)
        )
        createFeatureTasks(session, datetime.datetime.now(datetime.UTC))
        session.commit()
      connection.commit()
    return engine

  if StoreVersionRow.__tablename__ not in existingTables:
    raise StoreError(
      f"database '{displayLocation(location)}' was written by an earlier build of OpenFurrow, before stores "
      f"carried a version. Export its trials with that build and import them into a new "
      f"database."
    )
  with Session(engine) as session:
    versions = session.execute(select(StoreVersionRow.version)).scalars().all()
  if versions != [storeVersion]:
    raise StoreError(
      f"database '{displayLocation(location)}' holds store version {versions}, and this build reads version "
      f"{storeVersion}. Export its trials with the build that wrote it and import them "
      f"into a new database."
    )
  return engine


def _enableSqliteForeignKeys(dbapiConnection, connectionRecord) -> None:
  cursor = dbapiConnection.cursor()
  cursor.execute("PRAGMA foreign_keys=ON")
  cursor.close()
