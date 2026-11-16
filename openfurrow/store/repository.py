# SPDX-License-Identifier: Apache-2.0
"""Reading and writing trials to the canonical store.

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

from openfurrow.store.database import (
  ApplicationRow,
  AssessmentRow,
  CheckPlotRow,
  FactorLevelRow,
  FactorRow,
  RatingRow,
  ObservationRow,
  PlotRow,
  PlantingRow,
  PlotDimensionsRow,
  SiteRow,
  SoilRow,
  StoreError,
  TargetRow,
  TreatmentLineRow,
  TreatmentRow,
  TrialRow,
  WeatherRow,
)
from openfurrow.schema.application import Application, SoilMoisture
from openfurrow.schema.assessment import (
  AssessmentDataType,
  Assessment,
  Efficacy,
  EfficacyMethod,
  Subsamples,
  SubsampleRule,
  UntreatedCheck,
  MeasurementKind,
  Rating,
  Transform,
)
from openfurrow.schema.factor import Factor, FactorLevel
from openfurrow.schema.layout import CheckPlot, PlotAssignment
from openfurrow.schema.observation import Observation
from openfurrow.schema.quantity import Quantity
from openfurrow.schema.site import PlotDimensions, Setting, SiteDetails
from openfurrow.schema.target import Target, TargetKind
from openfurrow.schema.trialConditions import Planting, Soil, WeatherRecord
from openfurrow.schema.treatment import (
  ActiveSubstance,
  ProductKind,
  RateBasis,
  Treatment,
  TreatmentLine,
  TreatmentRole,
)
from openfurrow.schema.trialPackage import (
  CheckArrangement,
  DesignSpecification,
  DesignType,
  RandomizationMethod,
  TrialMetadata,
  TrialPackage,
)


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


def savePackage(
  session: Session, package: TrialPackage, layout: list[PlotAssignment], checkPlots: list[CheckPlot],
) -> None:
  """Persist a trial package with its layout and check plots. Raises if the trial code is already present."""
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
    randomizationMethod=package.design.randomizationMethod.value,
    randomizationSeed=package.design.randomizationSeed,
    firstBlockInTreatmentOrder=package.design.firstBlockInTreatmentOrder,
    checkArrangement=package.design.checkArrangement.value,
    mainPlotFactor=package.design.mainPlotFactor,
    subPlotFactor=package.design.subPlotFactor,
  )
  for ordinal, treatment in enumerate(package.treatments):
    trial.treatments.append(TreatmentRow(
      trialCode=trialCode,
      treatmentCode=treatment.treatmentCode,
      ordinal=ordinal,
      name=treatment.name,
      role=treatment.role.value if treatment.role is not None else None,
      factorLevels=json.dumps(treatment.factorLevels),
    ))
    for lineOrdinal, line in enumerate(treatment.lines):
      trial.treatmentLines.append(TreatmentLineRow(
        trialCode=trialCode,
        treatmentCode=treatment.treatmentCode,
        ordinal=lineOrdinal,
        product=line.product,
        kind=line.kind.value if line.kind is not None else None,
        formulationType=line.formulationType,
        activeSubstances=json.dumps([substance.model_dump(mode="json") for substance in line.activeSubstances]),
        rateValue=line.rate.value,
        rateUnit=line.rate.unit,
        rateBasis=line.rateBasis.value,
        applicationCodes=json.dumps(line.applicationCodes),
      ))
  for ordinal, application in enumerate(package.applications):
    pressureValue, pressureUnit = _valueAndUnit(application.pressure)
    travelSpeedValue, travelSpeedUnit = _valueAndUnit(application.travelSpeed)
    sprayVolumeValue, sprayVolumeUnit = _valueAndUnit(application.sprayVolume)
    airTemperatureValue, airTemperatureUnit = _valueAndUnit(application.airTemperature)
    windSpeedValue, windSpeedUnit = _valueAndUnit(application.windSpeed)
    trial.applications.append(ApplicationRow(
      trialCode=trialCode,
      applicationCode=application.applicationCode,
      ordinal=ordinal,
      timing=application.timing,
      date=application.date,
      time=application.time,
      method=application.method,
      placement=application.placement,
      equipment=application.equipment,
      nozzle=application.nozzle,
      pressureValue=pressureValue,
      pressureUnit=pressureUnit,
      sprayQuality=application.sprayQuality,
      travelSpeedValue=travelSpeedValue,
      travelSpeedUnit=travelSpeedUnit,
      sprayVolumeValue=sprayVolumeValue,
      sprayVolumeUnit=sprayVolumeUnit,
      cropStage=application.cropStage,
      targetStage=application.targetStage,
      airTemperatureValue=airTemperatureValue,
      airTemperatureUnit=airTemperatureUnit,
      relativeHumidity=application.relativeHumidity,
      windSpeedValue=windSpeedValue,
      windSpeedUnit=windSpeedUnit,
      cloudCover=application.cloudCover,
      soilMoisture=application.soilMoisture.value if application.soilMoisture is not None else None,
      notes=application.notes,
    ))
  if package.siteDetails is not None:
    site = package.siteDetails
    trial.siteDetails = SiteRow(
      trialCode=trialCode,
      address=site.address,
      latitude=site.latitude,
      longitude=site.longitude,
      elevationValue=None if site.elevation is None else site.elevation.value,
      elevationUnit=None if site.elevation is None else site.elevation.unit,
      setting=None if site.setting is None else site.setting.value,
      exposure=site.exposure,
      slope=site.slope,
    )
  if package.design.plotDimensions is not None:
    dimensions = package.design.plotDimensions
    trial.plotDimensions = PlotDimensionsRow(
      trialCode=trialCode,
      grossLengthValue=None if dimensions.grossLength is None else dimensions.grossLength.value,
      grossLengthUnit=None if dimensions.grossLength is None else dimensions.grossLength.unit,
      grossWidthValue=None if dimensions.grossWidth is None else dimensions.grossWidth.value,
      grossWidthUnit=None if dimensions.grossWidth is None else dimensions.grossWidth.unit,
      netLengthValue=None if dimensions.netLength is None else dimensions.netLength.value,
      netLengthUnit=None if dimensions.netLength is None else dimensions.netLength.unit,
      netWidthValue=None if dimensions.netWidth is None else dimensions.netWidth.value,
      netWidthUnit=None if dimensions.netWidth is None else dimensions.netWidth.unit,
      alleyWidthValue=None if dimensions.alleyWidth is None else dimensions.alleyWidth.value,
      alleyWidthUnit=None if dimensions.alleyWidth is None else dimensions.alleyWidth.unit,
      notes=dimensions.notes,
    )
  if package.planting is not None:
    planting = package.planting
    trial.planting = PlantingRow(
      trialCode=trialCode,
      cultivar=planting.cultivar,
      cropEPPOCode=planting.cropEPPOCode,
      sowingDate=planting.sowingDate,
      seedingRateValue=None if planting.seedingRate is None else planting.seedingRate.value,
      seedingRateUnit=None if planting.seedingRate is None else planting.seedingRate.unit,
      plantDensityValue=None if planting.plantDensity is None else planting.plantDensity.value,
      plantDensityUnit=None if planting.plantDensity is None else planting.plantDensity.unit,
      rowSpacingValue=None if planting.rowSpacing is None else planting.rowSpacing.value,
      rowSpacingUnit=None if planting.rowSpacing is None else planting.rowSpacing.unit,
      inRowSpacingValue=None if planting.inRowSpacing is None else planting.inRowSpacing.value,
      inRowSpacingUnit=None if planting.inRowSpacing is None else planting.inRowSpacing.unit,
      sowingDepthValue=None if planting.sowingDepth is None else planting.sowingDepth.value,
      sowingDepthUnit=None if planting.sowingDepth is None else planting.sowingDepth.unit,
      emergenceDate=planting.emergenceDate,
      precedingCrop=planting.precedingCrop,
      tillage=planting.tillage,
      trainingSystem=planting.trainingSystem,
      rootstock=planting.rootstock,
      plantedYear=planting.plantedYear,
      notes=planting.notes,
    )
  if package.soil is not None:
    soil = package.soil
    trial.soil = SoilRow(
      trialCode=trialCode,
      soilType=soil.soilType,
      texture=soil.texture,
      pH=soil.pH,
      pHMethod=soil.pHMethod,
      organicMatter=soil.organicMatter,
      seedbedQuality=soil.seedbedQuality,
      fertilizerRegime=soil.fertilizerRegime,
      notes=soil.notes,
    )
  trial.weather.extend(_weatherRows(trialCode, package.weather))
  for ordinal, factor in enumerate(package.factors):
    trial.factors.append(FactorRow(
      trialCode=trialCode, factorCode=factor.factorCode, ordinal=ordinal, name=factor.name,
    ))
    for levelOrdinal, level in enumerate(factor.levels):
      trial.factorLevels.append(FactorLevelRow(
        trialCode=trialCode, factorCode=factor.factorCode, levelCode=level.levelCode,
        ordinal=levelOrdinal, name=level.name,
      ))
  for ordinal, target in enumerate(package.targets):
    trial.targets.append(TargetRow(
      trialCode=trialCode,
      targetCode=target.targetCode,
      ordinal=ordinal,
      name=target.name,
      kind=target.kind.value,
      scientificName=target.scientificName,
      eppoCode=target.eppoCode,
    ))
  for ordinal, rating in enumerate(package.ratings):
    trial.ratings.append(RatingRow(
      trialCode=trialCode,
      ratingCode=rating.ratingCode,
      ordinal=ordinal,
      name=rating.name,
      ratingType=rating.ratingType,
      partRated=rating.partRated,
      method=rating.method,
      targetCode=rating.targetCode,
      dataType=rating.dataType.value,
      unit=rating.unit,
      minValue=rating.minValue,
      maxValue=rating.maxValue,
      allowedValues=json.dumps(rating.allowedValues) if rating.allowedValues is not None else None,
      measurementKind=rating.measurementKind.value,
      transform=rating.transform.value,
      transformOffset=rating.transformOffset,
    ))
  for ordinal, assessment in enumerate(package.assessments):
    sampleSizeValue, sampleSizeUnit = _valueAndUnit(assessment.sampleSize)
    trial.assessments.append(AssessmentRow(
      trialCode=trialCode,
      assessmentCode=assessment.assessmentCode,
      ordinal=ordinal,
      ratingCode=assessment.ratingCode,
      timing=assessment.timing,
      date=assessment.date,
      cropStage=assessment.cropStage,
      targetStage=assessment.targetStage,
      timedFromApplicationCode=assessment.timedFromApplicationCode,
      assessedBy=assessment.assessedBy,
      sampleSizeValue=sampleSizeValue,
      sampleSizeUnit=sampleSizeUnit,
      notes=assessment.notes,
      efficacyMethod=None if assessment.efficacy is None else assessment.efficacy.method.value,
      efficacyBaselineAssessmentCode=None if assessment.efficacy is None else assessment.efficacy.baselineAssessmentCode,
      untreatedCheck=assessment.untreatedCheck.value,
      subsampleCount=None if assessment.subsamples is None else assessment.subsamples.count,
      subsampleRule=None if assessment.subsamples is None else assessment.subsamples.rule.value,
    ))
  for check in checkPlots:
    trial.checkPlots.append(CheckPlotRow(
      trialCode=trialCode, plotNumber=check.plotNumber, block=check.block,
      pairedPlots=json.dumps(check.pairedPlots),
    ))
  for plot in layout:
    trial.plots.append(PlotRow(
      trialCode=trialCode,
      plotNumber=plot.plotNumber,
      block=plot.block,
      positionInBlock=plot.positionInBlock,
      mainPlot=plot.mainPlot,
      treatmentCode=plot.treatmentCode,
    ))
  session.add(trial)
  session.flush()


def loadPackage(session: Session, trialCode: str) -> TrialPackage:
  """Reconstruct a trial package. Raises if the trial is not present.

  Treatments and assessments are returned in their stored ordinal order, so the
  input hash matches the original exactly.
  """
  trial = session.get(TrialRow, trialCode)
  if trial is None:
    raise TrialNotFoundError(f"trial '{trialCode}' not found")

  linesByTreatment: dict[str, list[TreatmentLine]] = {}
  for row in sorted(trial.treatmentLines, key=lambda row: (row.treatmentCode, row.ordinal)):
    linesByTreatment.setdefault(row.treatmentCode, []).append(_lineFrom(row))
  orphaned = sorted(set(linesByTreatment) - {row.treatmentCode for row in trial.treatments})
  if orphaned:
    raise StoreError(
      f"trial '{trial.trialCode}' holds product lines for treatment(s) {orphaned} it does not have"
    )
  treatments = [
    Treatment(
      treatmentCode=row.treatmentCode,
      name=row.name,
      role=TreatmentRole(row.role) if row.role is not None else None,
      factorLevels=json.loads(row.factorLevels),
      lines=linesByTreatment.get(row.treatmentCode, []),
    )
    for row in sorted(trial.treatments, key=lambda row: row.ordinal)
  ]
  applications = [
    _applicationFrom(row) for row in sorted(trial.applications, key=lambda row: row.ordinal)
  ]
  assessments = [
    Assessment(
      assessmentCode=row.assessmentCode,
      ratingCode=row.ratingCode,
      timing=row.timing,
      date=row.date,
      cropStage=row.cropStage,
      targetStage=row.targetStage,
      timedFromApplicationCode=row.timedFromApplicationCode,
      assessedBy=row.assessedBy,
      sampleSize=_quantity(row.sampleSizeValue, row.sampleSizeUnit),
      notes=row.notes,
      efficacy=None if row.efficacyMethod is None else Efficacy(
        method=EfficacyMethod(row.efficacyMethod), baselineAssessmentCode=row.efficacyBaselineAssessmentCode,
      ),
      untreatedCheck=UntreatedCheck(row.untreatedCheck),
      subsamples=None if row.subsampleCount is None else Subsamples(
        count=row.subsampleCount, rule=SubsampleRule(row.subsampleRule),
      ),
    )
    for row in sorted(trial.assessments, key=lambda row: row.ordinal)
  ]
  siteDetails = None
  if trial.siteDetails is not None:
    row = trial.siteDetails
    siteDetails = SiteDetails(
      address=row.address,
      latitude=row.latitude,
      longitude=row.longitude,
      elevation=_quantity(row.elevationValue, row.elevationUnit),
      setting=None if row.setting is None else Setting(row.setting),
      exposure=row.exposure,
      slope=row.slope,
    )
  plotDimensions = None
  if trial.plotDimensions is not None:
    row = trial.plotDimensions
    plotDimensions = PlotDimensions(
      grossLength=_quantity(row.grossLengthValue, row.grossLengthUnit),
      grossWidth=_quantity(row.grossWidthValue, row.grossWidthUnit),
      netLength=_quantity(row.netLengthValue, row.netLengthUnit),
      netWidth=_quantity(row.netWidthValue, row.netWidthUnit),
      alleyWidth=_quantity(row.alleyWidthValue, row.alleyWidthUnit),
      notes=row.notes,
    )
  planting = None
  if trial.planting is not None:
    row = trial.planting
    planting = Planting(
      cultivar=row.cultivar,
      cropEPPOCode=row.cropEPPOCode,
      sowingDate=row.sowingDate,
      seedingRate=_quantity(row.seedingRateValue, row.seedingRateUnit),
      plantDensity=_quantity(row.plantDensityValue, row.plantDensityUnit),
      rowSpacing=_quantity(row.rowSpacingValue, row.rowSpacingUnit),
      inRowSpacing=_quantity(row.inRowSpacingValue, row.inRowSpacingUnit),
      sowingDepth=_quantity(row.sowingDepthValue, row.sowingDepthUnit),
      emergenceDate=row.emergenceDate,
      precedingCrop=row.precedingCrop,
      tillage=row.tillage,
      trainingSystem=row.trainingSystem,
      rootstock=row.rootstock,
      plantedYear=row.plantedYear,
      notes=row.notes,
    )
  soil = None
  if trial.soil is not None:
    row = trial.soil
    soil = Soil(
      soilType=row.soilType,
      texture=row.texture,
      pH=row.pH,
      pHMethod=row.pHMethod,
      organicMatter=row.organicMatter,
      seedbedQuality=row.seedbedQuality,
      fertilizerRegime=row.fertilizerRegime,
      notes=row.notes,
    )
  weather = [
    WeatherRecord(
      date=row.date,
      rainfall=_quantity(row.rainfallValue, row.rainfallUnit),
      irrigation=_quantity(row.irrigationValue, row.irrigationUnit),
      minimumTemperature=_quantity(row.minimumTemperatureValue, row.minimumTemperatureUnit),
      maximumTemperature=_quantity(row.maximumTemperatureValue, row.maximumTemperatureUnit),
      notes=row.notes,
    )
    for row in sorted(trial.weather, key=lambda row: row.date)
  ]
  levelsByFactor: dict[str, list[FactorLevel]] = {}
  for row in sorted(trial.factorLevels, key=lambda row: (row.factorCode, row.ordinal)):
    levelsByFactor.setdefault(row.factorCode, []).append(FactorLevel(levelCode=row.levelCode, name=row.name))
  factors = [
    Factor(factorCode=row.factorCode, name=row.name, levels=levelsByFactor[row.factorCode])
    for row in sorted(trial.factors, key=lambda row: row.ordinal)
  ]
  targets = [
    Target(
      targetCode=row.targetCode,
      name=row.name,
      kind=TargetKind(row.kind),
      scientificName=row.scientificName,
      eppoCode=row.eppoCode,
    )
    for row in sorted(trial.targets, key=lambda row: row.ordinal)
  ]
  ratings = [
    Rating(
      ratingCode=row.ratingCode,
      name=row.name,
      ratingType=row.ratingType,
      partRated=row.partRated,
      method=row.method,
      targetCode=row.targetCode,
      dataType=AssessmentDataType(row.dataType),
      unit=row.unit,
      minValue=row.minValue,
      maxValue=row.maxValue,
      allowedValues=json.loads(row.allowedValues) if row.allowedValues is not None else None,
      measurementKind=MeasurementKind(row.measurementKind),
      transform=Transform(row.transform),
      transformOffset=row.transformOffset,
    )
    for row in sorted(trial.ratings, key=lambda row: row.ordinal)
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
    siteDetails=siteDetails,
    targets=targets,
    factors=factors,
    planting=planting,
    soil=soil,
    weather=weather,
    design=DesignSpecification(
      designType=DesignType(trial.designType),
      replications=trial.replications,
      randomizationMethod=RandomizationMethod(trial.randomizationMethod),
      randomizationSeed=trial.randomizationSeed,
      firstBlockInTreatmentOrder=trial.firstBlockInTreatmentOrder,
      checkArrangement=CheckArrangement(trial.checkArrangement),
      mainPlotFactor=trial.mainPlotFactor,
      subPlotFactor=trial.subPlotFactor,
      plotDimensions=plotDimensions,
    ),
    treatments=treatments,
    applications=applications,
    ratings=ratings,
    assessments=assessments,
  )


def loadLayout(session: Session, trialCode: str) -> list[PlotAssignment]:
  """Load a trial's plots, ordered by plot number. Raises if the trial is not present."""
  if session.get(TrialRow, trialCode) is None:
    raise TrialNotFoundError(f"trial '{trialCode}' not found")
  rows = session.execute(
    select(PlotRow).where(PlotRow.trialCode == trialCode).order_by(PlotRow.plotNumber)
  ).scalars().all()
  return [
    PlotAssignment(
      plotNumber=row.plotNumber,
      block=row.block,
      positionInBlock=row.positionInBlock,
      mainPlot=row.mainPlot,
      treatmentCode=row.treatmentCode,
    )
    for row in rows
  ]


def loadCheckPlots(session: Session, trialCode: str) -> list[CheckPlot]:
  """The stored check plots of a trial, by plot number. Raises if the trial is not stored."""
  trial = session.get(TrialRow, trialCode)
  if trial is None:
    raise TrialNotFoundError(f"trial '{trialCode}' not found")
  return [
    CheckPlot(plotNumber=row.plotNumber, block=row.block, pairedPlots=json.loads(row.pairedPlots))
    for row in sorted(trial.checkPlots, key=lambda row: row.plotNumber)
  ]


def saveObservations(session: Session, trialCode: str, observations: list[Observation]) -> None:
  """Persist observations for an existing trial. Raises on a missing trial or a collision."""
  if session.get(TrialRow, trialCode) is None:
    raise TrialNotFoundError(f"trial '{trialCode}' not found; save the package first")
  for observation in observations:
    key = (trialCode, observation.plotNumber, observation.assessmentCode, observation.subsample or 0)
    if session.get(ObservationRow, key) is not None:
      raise TrialExistsError(
        f"observation already exists for plot {observation.plotNumber}, "
        f"assessment '{observation.assessmentCode}' subsample {observation.subsample} in trial '{trialCode}'"
      )
    numericValue, textValue = _splitValue(observation.value)
    session.add(ObservationRow(
      trialCode=trialCode,
      plotNumber=observation.plotNumber,
      assessmentCode=observation.assessmentCode,
      subsample=observation.subsample or 0,
      numericValue=numericValue,
      textValue=textValue,
      outOfRangeConfirmed=observation.outOfRangeConfirmed,
    ))
  session.flush()


def loadObservations(session: Session, trialCode: str) -> list[Observation]:
  """Load observations for a trial, ordered by plot then assessment. Raises if absent."""
  if session.get(TrialRow, trialCode) is None:
    raise TrialNotFoundError(f"trial '{trialCode}' not found")
  rows = session.execute(
    select(ObservationRow)
    .where(ObservationRow.trialCode == trialCode)
    .order_by(ObservationRow.plotNumber, ObservationRow.assessmentCode, ObservationRow.subsample)
  ).scalars().all()
  return [
    Observation(
      plotNumber=row.plotNumber,
      assessmentCode=row.assessmentCode,
      value=_joinValue(row.numericValue, row.textValue),
      subsample=row.subsample or None,
      outOfRangeConfirmed=row.outOfRangeConfirmed,
    )
    for row in rows
  ]


def replaceAssessmentObservations(
  session: Session, trialCode: str, assessmentCode: str, observations: list[Observation],
) -> None:
  """Replace every stored value of one assessment with `observations`, all of that assessment."""
  if any(observation.assessmentCode != assessmentCode for observation in observations):
    raise StoreError(f"observations for other assessments were given to replace '{assessmentCode}'")
  if session.get(TrialRow, trialCode) is None:
    raise TrialNotFoundError(f"trial '{trialCode}' not found")
  for row in session.execute(
    select(ObservationRow).where(
      ObservationRow.trialCode == trialCode, ObservationRow.assessmentCode == assessmentCode,
    )
  ).scalars().all():
    session.delete(row)
  session.flush()
  saveObservations(session, trialCode, observations)


def _weatherRows(trialCode: str, weather: list[WeatherRecord]) -> list[WeatherRow]:
  return [
    WeatherRow(
      trialCode=trialCode,
      date=record.date,
      rainfallValue=None if record.rainfall is None else record.rainfall.value,
      rainfallUnit=None if record.rainfall is None else record.rainfall.unit,
      irrigationValue=None if record.irrigation is None else record.irrigation.value,
      irrigationUnit=None if record.irrigation is None else record.irrigation.unit,
      minimumTemperatureValue=None if record.minimumTemperature is None else record.minimumTemperature.value,
      minimumTemperatureUnit=None if record.minimumTemperature is None else record.minimumTemperature.unit,
      maximumTemperatureValue=None if record.maximumTemperature is None else record.maximumTemperature.value,
      maximumTemperatureUnit=None if record.maximumTemperature is None else record.maximumTemperature.unit,
      notes=record.notes,
    )
    for record in weather
  ]


def replaceWeather(session: Session, trialCode: str, weather: list[WeatherRecord]) -> None:
  """Replace a stored trial's weather log; the schema version is the one the trial carries."""
  trial = session.get(TrialRow, trialCode)
  if trial is None:
    raise TrialNotFoundError(f"trial '{trialCode}' not found")
  trial.weather.clear()
  session.flush()
  trial.weather.extend(_weatherRows(trialCode, weather))
  session.flush()


def listTrials(session: Session) -> list[tuple[str, str]]:
  """Every trial in the store as (trialCode, title), ordered by code."""
  rows = session.execute(
    select(TrialRow.trialCode, TrialRow.title).order_by(TrialRow.trialCode)
  ).all()
  return [(row.trialCode, row.title) for row in rows]


def deleteTrial(session: Session, trialCode: str) -> None:
  """Delete a trial with its treatments, assessments, plots and observations."""
  trial = session.get(TrialRow, trialCode)
  if trial is None:
    raise TrialNotFoundError(f"trial '{trialCode}' not found")
  session.delete(trial)
  session.flush()


def _valueAndUnit(quantity: Quantity | None) -> tuple[float | None, str | None]:
  if quantity is None:
    return None, None
  return quantity.value, quantity.unit


def _quantity(value: float | None, unit: str | None) -> Quantity | None:
  """The quantity two columns hold; half a quantity is a damaged row and is rejected."""
  if value is None and unit is None:
    return None
  return Quantity(value=value, unit=unit)


def _lineFrom(row: TreatmentLineRow) -> TreatmentLine:
  return TreatmentLine(
    product=row.product,
    kind=ProductKind(row.kind) if row.kind is not None else None,
    formulationType=row.formulationType,
    activeSubstances=[ActiveSubstance.model_validate(item) for item in json.loads(row.activeSubstances)],
    rate=Quantity(value=row.rateValue, unit=row.rateUnit),
    rateBasis=RateBasis(row.rateBasis),
    applicationCodes=json.loads(row.applicationCodes),
  )


def _applicationFrom(row: ApplicationRow) -> Application:
  return Application(
    applicationCode=row.applicationCode,
    timing=row.timing,
    date=row.date,
    time=row.time,
    method=row.method,
    placement=row.placement,
    equipment=row.equipment,
    nozzle=row.nozzle,
    pressure=_quantity(row.pressureValue, row.pressureUnit),
    sprayQuality=row.sprayQuality,
    travelSpeed=_quantity(row.travelSpeedValue, row.travelSpeedUnit),
    sprayVolume=_quantity(row.sprayVolumeValue, row.sprayVolumeUnit),
    cropStage=row.cropStage,
    targetStage=row.targetStage,
    airTemperature=_quantity(row.airTemperatureValue, row.airTemperatureUnit),
    relativeHumidity=row.relativeHumidity,
    windSpeed=_quantity(row.windSpeedValue, row.windSpeedUnit),
    cloudCover=row.cloudCover,
    soilMoisture=SoilMoisture(row.soilMoisture) if row.soilMoisture is not None else None,
    notes=row.notes,
  )


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
