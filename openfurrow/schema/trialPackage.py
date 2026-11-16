# SPDX-License-Identifier: Apache-2.0
"""Trial package schema: the import/export boundary for an OpenFurrow trial design.

A trial package is the design document for a single trial -- its metadata, the
treatments under comparison, the experimental design used to lay them out, and
the assessments that will be collected. Observations are imported separately and
are not part of the design package.

Every model fails loud: invalid state is rejected at construction, not deferred
to analysis time. There are no silent coercions or fallback defaults that paper
over a malformed package.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from openfurrow.schema.application import Application
from openfurrow.schema.assessment import Assessment, Rating
from openfurrow.schema.factor import Factor
from openfurrow.schema.target import Target
from openfurrow.schema.trialConditions import Planting, Soil, WeatherRecord
from openfurrow.schema.treatment import Treatment
from openfurrow.version import schemaVersion as currentSchemaVersion


class DesignType(str, Enum):
  """Experimental design used to lay out treatments into plots."""

  rcbd = "rcbd"  # randomized complete block design
  splitPlot = "splitPlot"  # main plots in complete blocks, subplots within them


class TrialMetadata(BaseModel):
  """Descriptive metadata for a single trial.

  Investigator and organization use generic labels rather than modeling a full
  actor/organization graph -- that belongs to the canonical store, not to the
  design package.
  """

  model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

  trialCode: str = Field(min_length=1, description="Short stable identifier, e.g. 'ESV-2025-01'.")
  title: str = Field(min_length=1)
  crop: str = Field(min_length=1)
  season: str = Field(min_length=1, description="Free-form season label, e.g. '2025 Spring'.")
  site: str = Field(min_length=1)
  objective: str = Field(min_length=1)
  investigator: str | None = None
  organization: str | None = None


class RandomizationMethod(str, Enum):
  """How a trial's layout came to be (decision 0015).

  A generated layout names the procedure that produced it from the seed, so it can be
  regenerated and checked. A layout made elsewhere -- by hand, by another tool, or
  already in the ground -- is `imported` and has no seed.
  """

  sha256FisherYates1 = "sha256FisherYates1"
  imported = "imported"


class DesignSpecification(BaseModel):
  """How treatments are laid out into plots, and where the layout came from.

  Only RCBD is supported. The layout itself is recorded with the trial (decision
  0015); this says how it was made. The method is always stated, never assumed. A
  generated layout needs its seed, which is what lets the record be checked; an
  imported layout has none.
  """

  model_config = ConfigDict(extra="forbid")

  designType: DesignType = DesignType.rcbd
  replications: int = Field(ge=2, description="Number of complete blocks; RCBD requires at least 2.")
  randomizationMethod: RandomizationMethod = Field(description="The procedure that made the layout, or 'imported'.")
  randomizationSeed: int | None = Field(
    default=None, ge=0, description="The seed of a generated layout; absent for an imported one.",
  )
  mainPlotFactor: str | None = Field(default=None, min_length=1, description="Split plot: the factor on main plots.")
  subPlotFactor: str | None = Field(default=None, min_length=1, description="Split plot: the factor on subplots.")
  firstBlockInTreatmentOrder: bool = Field(
    default=False,
    description="A generated layout leaves block 1 in treatment order, e.g. for field walks.",
  )

  @model_validator(mode="after")
  def seedGoesWithAGeneratedLayout(self) -> DesignSpecification:
    generated = self.randomizationMethod is not RandomizationMethod.imported
    if generated and self.randomizationSeed is None:
      raise ValueError(
        f"randomizationMethod '{self.randomizationMethod.value}' needs a randomizationSeed"
      )
    if not generated and self.randomizationSeed is not None:
      raise ValueError("an imported layout has no randomizationSeed")
    splitPlot = self.designType is DesignType.splitPlot
    named = (self.mainPlotFactor, self.subPlotFactor)
    if splitPlot and None in named:
      raise ValueError("a split-plot design names its mainPlotFactor and its subPlotFactor")
    if splitPlot and self.mainPlotFactor == self.subPlotFactor:
      raise ValueError("a split plot's main-plot and subplot factors must differ")
    if not splitPlot and named != (None, None):
      raise ValueError(f"a {self.designType.value} design has no main-plot or subplot factor")
    if not generated and self.firstBlockInTreatmentOrder:
      raise ValueError("an imported layout is recorded as supplied; firstBlockInTreatmentOrder applies to generated ones")
    return self


class TrialPackage(BaseModel):
  """The complete design document for one trial.

  Treatment and assessment codes must each be unique within the package; they
  are the join keys observation import and analysis rely on, so a collision is
  rejected here rather than producing silently merged rows downstream. Application
  codes are the join between treatment lines and applications, and are held to the
  same rule: a line may only name an application the package declares.
  """

  model_config = ConfigDict(extra="forbid")

  schemaVersion: str = Field(description="The schema this package is written in; must be the one this build reads.")
  trial: TrialMetadata
  targets: list[Target] = Field(default_factory=list)
  factors: list[Factor] = Field(default_factory=list)
  planting: Planting | None = None
  soil: Soil | None = None
  weather: list[WeatherRecord] = Field(default_factory=list, description="One record per day.")
  treatments: list[Treatment] = Field(min_length=2, description="At least two treatments to compare.")
  applications: list[Application] = Field(default_factory=list)
  design: DesignSpecification
  ratings: list[Rating] = Field(min_length=1)
  assessments: list[Assessment] = Field(min_length=1)

  @field_validator("schemaVersion")
  @classmethod
  def schemaVersionIsCurrent(cls, declared: str) -> str:
    if declared != currentSchemaVersion:
      raise ValueError(
        f"schemaVersion '{declared}' is not supported; this build reads schema {currentSchemaVersion}"
      )
    return declared

  @field_validator("treatments")
  @classmethod
  def uniqueTreatmentCodes(cls, treatments: list[Treatment]) -> list[Treatment]:
    codes = [t.treatmentCode for t in treatments]
    if len(set(codes)) != len(codes):
      raise ValueError(f"duplicate treatmentCode values: {sorted(_duplicates(codes))}")
    return treatments

  @model_validator(mode="after")
  def treatmentsAreTheFactorCombinations(self) -> TrialPackage:
    """A split plot's treatments are every combination of its two factors, each once."""
    design = self.design
    if design.designType is not DesignType.splitPlot:
      if self.factors or any(treatment.factorLevels for treatment in self.treatments):
        raise ValueError(
          f"factors are only used by a split-plot design so far; a {design.designType.value} "
          f"design has none"
        )
      return self
    codes = [factor.factorCode for factor in self.factors]
    if sorted(codes) != sorted([design.mainPlotFactor, design.subPlotFactor]):
      raise ValueError(
        f"a split plot declares exactly its two factors {[design.mainPlotFactor, design.subPlotFactor]}, "
        f"got {codes}"
      )
    levels = {factor.factorCode: [level.levelCode for level in factor.levels] for factor in self.factors}
    combinations = []
    for treatment in self.treatments:
      if set(treatment.factorLevels) != set(codes):
        raise ValueError(
          f"treatment '{treatment.treatmentCode}' must state its level of each of {sorted(codes)}"
        )
      for factorCode, levelCode in treatment.factorLevels.items():
        if levelCode not in levels[factorCode]:
          raise ValueError(
            f"treatment '{treatment.treatmentCode}': '{levelCode}' is not a level of factor '{factorCode}'"
          )
      combinations.append((treatment.factorLevels[design.mainPlotFactor], treatment.factorLevels[design.subPlotFactor]))
    expected = [(main, sub) for main in levels[design.mainPlotFactor] for sub in levels[design.subPlotFactor]]
    if sorted(combinations) != sorted(expected):
      repeated = sorted({combination for combination in combinations if combinations.count(combination) > 1})
      absent = sorted(set(expected) - set(combinations))
      raise ValueError(
        f"a split plot's treatments are every combination of its factors once; "
        f"repeated {repeated}, absent {absent}"
      )
    return self

  def mainPlotLevelOf(self, treatmentCode: str) -> str:
    """The main-plot level of a split-plot treatment."""
    treatment = next(treatment for treatment in self.treatments if treatment.treatmentCode == treatmentCode)
    return treatment.factorLevels[self.design.mainPlotFactor]

  @field_validator("weather")
  @classmethod
  def oneWeatherRecordPerDayInOrder(cls, weather: list[WeatherRecord]) -> list[WeatherRecord]:
    for earlier, later in zip(weather, weather[1:]):
      if later.date <= earlier.date:
        raise ValueError(
          f"weather records must run one per day in date order; {later.date} follows {earlier.date}"
        )
    return weather

  @field_validator("targets")
  @classmethod
  def uniqueTargetCodes(cls, targets: list[Target]) -> list[Target]:
    codes = [target.targetCode for target in targets]
    if len(set(codes)) != len(codes):
      raise ValueError(f"duplicate targetCode values: {sorted(_duplicates(codes))}")
    return targets

  @model_validator(mode="after")
  def ratingsNameDeclaredTargets(self) -> TrialPackage:
    declared = {target.targetCode for target in self.targets}
    for rating in self.ratings:
      if rating.targetCode is not None and rating.targetCode not in declared:
        raise ValueError(
          f"rating '{rating.ratingCode}': target '{rating.targetCode}' is not declared in the package"
        )
    return self

  @field_validator("ratings")
  @classmethod
  def uniqueRatingCodes(cls, ratings: list[Rating]) -> list[Rating]:
    codes = [rating.ratingCode for rating in ratings]
    if len(set(codes)) != len(codes):
      raise ValueError(f"duplicate ratingCode values: {sorted(_duplicates(codes))}")
    return ratings

  @field_validator("assessments")
  @classmethod
  def uniqueAssessmentCodes(cls, assessments: list[Assessment]) -> list[Assessment]:
    codes = [a.assessmentCode for a in assessments]
    if len(set(codes)) != len(codes):
      raise ValueError(f"duplicate assessmentCode values: {sorted(_duplicates(codes))}")
    return assessments

  @model_validator(mode="after")
  def treatmentLinesNameDeclaredApplications(self) -> TrialPackage:
    codes = [application.applicationCode for application in self.applications]
    if len(set(codes)) != len(codes):
      raise ValueError(f"duplicate applicationCode values: {sorted(_duplicates(codes))}")
    declared = set(codes)
    for treatment in self.treatments:
      for line in treatment.lines:
        unknown = sorted(set(line.applicationCodes) - declared)
        if unknown:
          raise ValueError(
            f"treatment '{treatment.treatmentCode}', product '{line.product}': "
            f"application(s) {unknown} are not declared in the package"
          )
    return self

  @model_validator(mode="after")
  def assessmentsNameDeclaredRatingsAndApplications(self) -> TrialPackage:
    ratingCodes = {rating.ratingCode for rating in self.ratings}
    applicationCodes = {application.applicationCode for application in self.applications}
    for assessment in self.assessments:
      if assessment.ratingCode not in ratingCodes:
        raise ValueError(
          f"assessment '{assessment.assessmentCode}': rating '{assessment.ratingCode}' is not declared in the package"
        )
      timedFrom = assessment.timedFromApplicationCode
      if timedFrom is not None and timedFrom not in applicationCodes:
        raise ValueError(
          f"assessment '{assessment.assessmentCode}': application '{timedFrom}' is not declared in the package"
        )
    return self

  def assessmentFor(self, assessmentCode: str) -> Assessment:
    """The assessment with this code; raises if the package has none."""
    for assessment in self.assessments:
      if assessment.assessmentCode == assessmentCode:
        return assessment
    raise KeyError(f"assessment '{assessmentCode}' is not defined in the trial package")

  def ratingFor(self, assessmentCode: str) -> Rating:
    """The rating an assessment takes, which holds the rules its values obey."""
    ratingCode = self.assessmentFor(assessmentCode).ratingCode
    return next(rating for rating in self.ratings if rating.ratingCode == ratingCode)

  def daysAfterApplication(self, assessmentCode: str) -> int | None:
    """Days from the application an assessment is timed from; None until both have a date."""
    assessment = self.assessmentFor(assessmentCode)
    if assessment.timedFromApplicationCode is None or assessment.date is None:
      return None
    application = next(
      application for application in self.applications
      if application.applicationCode == assessment.timedFromApplicationCode
    )
    if application.date is None:
      return None
    return (assessment.date - application.date).days

  @property
  def plotCount(self) -> int:
    """Total plots the design produces; derived, never stored."""
    return len(self.treatments) * self.design.replications


def _duplicates(values: list[str]) -> set[str]:
  seen: set[str] = set()
  repeated: set[str] = set()
  for value in values:
    if value in seen:
      repeated.add(value)
    seen.add(value)
  return repeated
