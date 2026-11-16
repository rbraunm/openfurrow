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
from openfurrow.schema.assessment import AssessmentDataType, Assessment, Rating, UntreatedCheck
from openfurrow.schema.factor import Factor
from openfurrow.schema.site import PlotDimensions, SiteDetails
from openfurrow.schema.target import Target
from openfurrow.schema.trialConditions import Planting, Soil, WeatherRecord
from openfurrow.schema.treatment import Treatment, TreatmentRole
from openfurrow.version import schemaVersion as currentSchemaVersion


class DesignType(str, Enum):
  """Experimental design used to lay out treatments into plots."""

  rcbd = "rcbd"  # randomized complete block design
  crd = "crd"  # completely randomized design: no blocks
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


class CheckArrangement(str, Enum):
  """How untreated checks sit beside the treated plots (decision 0022).

  `imbricated`: untreated strips between plots, compared with but left out of the analysis
  (EPPO PP 1/152). `adjacent`: each plot halved, one half left untreated, the halves
  analysed together. `paired`: each treated plot has its own untreated partner.
  """

  none = "none"
  imbricated = "imbricated"
  adjacent = "adjacent"
  paired = "paired"


class RandomizationMethod(str, Enum):
  """How a trial's layout came to be (decision 0015).

  A generated layout names the procedure that produced it from the seed, so it can be
  regenerated and checked. A layout made elsewhere -- by hand, by another tool, or
  already in the ground -- is `imported` and has no seed.
  """

  sha256FisherYates1 = "sha256FisherYates1"
  sha256SpatialBalance1 = "sha256SpatialBalance1"
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
  replications: int = Field(ge=2, description="Complete blocks, or for a CRD the plots of each treatment; at least 2.")
  randomizationMethod: RandomizationMethod = Field(description="The procedure that made the layout, or 'imported'.")
  randomizationSeed: int | None = Field(
    default=None, ge=0, description="The seed of a generated layout; absent for an imported one.",
  )
  mainPlotFactor: str | None = Field(default=None, min_length=1, description="Split plot: the factor on main plots.")
  subPlotFactor: str | None = Field(default=None, min_length=1, description="Split plot: the factor on subplots.")
  plotDimensions: PlotDimensions | None = None
  checkArrangement: CheckArrangement = Field(
    default=CheckArrangement.none, description="Untreated checks beside the treated plots, and how.",
  )
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
    if self.designType is DesignType.crd:
      if self.checkArrangement is not CheckArrangement.none:
        raise ValueError("untreated checks beside plots apply to an RCBD, not to a completely randomized design yet")
      if self.firstBlockInTreatmentOrder:
        raise ValueError("a completely randomized design has no blocks, so no first block to keep in order")
      if self.randomizationMethod is RandomizationMethod.sha256SpatialBalance1:
        raise ValueError("spatial balance arranges blocks; a completely randomized design has none")
    if splitPlot and self.checkArrangement is not CheckArrangement.none:
      raise ValueError("untreated checks beside plots apply to an RCBD, not to a split plot yet")
    if self.randomizationMethod is RandomizationMethod.sha256SpatialBalance1 and splitPlot:
      raise ValueError("spatial balance applies to an RCBD's blocks, not to a split plot")
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
  siteDetails: SiteDetails | None = None
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
    """A two-factor trial's treatments are every combination of its factors, each once (decisions 0020, 0025)."""
    design = self.design
    codes = [factor.factorCode for factor in self.factors]
    if design.designType is DesignType.splitPlot:
      if sorted(codes) != sorted([design.mainPlotFactor, design.subPlotFactor]):
        raise ValueError(
          f"a split plot declares exactly its two factors {[design.mainPlotFactor, design.subPlotFactor]}, "
          f"got {codes}"
        )
      first, second = design.mainPlotFactor, design.subPlotFactor
    elif design.designType is DesignType.crd and self.factors:
      raise ValueError("factors are not used by a completely randomized design yet")
    elif not self.factors:
      if any(treatment.factorLevels for treatment in self.treatments):
        raise ValueError("a treatment states factor levels, but the trial declares no factors")
      return self
    elif len(codes) != 2:
      raise ValueError(f"a factorial {design.designType.value} has two factors so far, got {codes}")
    else:
      first, second = codes
    if len(set(codes)) != len(codes):
      raise ValueError(f"factor codes used more than once: {codes}")
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
      combinations.append((treatment.factorLevels[first], treatment.factorLevels[second]))
    expected = [(one, two) for one in levels[first] for two in levels[second]]
    if sorted(combinations) != sorted(expected):
      repeated = sorted({combination for combination in combinations if combinations.count(combination) > 1})
      absent = sorted(set(expected) - set(combinations))
      raise ValueError(
        f"the treatments of a two-factor trial are every combination of its factors once; "
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
      if assessment.efficacy is not None:
        self._checkEfficacy(assessment)
      if assessment.subsamples is not None:
        rating = next(rating for rating in self.ratings if rating.ratingCode == assessment.ratingCode)
        if rating.dataType is not AssessmentDataType.numeric:
          raise ValueError(
            f"assessment '{assessment.assessmentCode}': subsamples give a plot value by a mean or a sum, "
            f"so they need a numeric rating, not {rating.dataType.value}"
          )
      if assessment.untreatedCheck is UntreatedCheck.excluded:
        controls = [t.treatmentCode for t in self.treatments if t.role is TreatmentRole.untreatedControl]
        if len(controls) != 1:
          raise ValueError(
            f"assessment '{assessment.assessmentCode}': leaving the untreated check out needs exactly one "
            f"treatment whose role is untreatedControl, got {controls}"
          )
        if self.factors:
          raise ValueError(
            f"assessment '{assessment.assessmentCode}': a two-factor trial keeps every combination in its "
            f"analysis; the untreated check cannot be left out"
          )
      timedFrom = assessment.timedFromApplicationCode
      if timedFrom is not None and timedFrom not in applicationCodes:
        raise ValueError(
          f"assessment '{assessment.assessmentCode}': application '{timedFrom}' is not declared in the package"
        )
    return self

  def _checkEfficacy(self, assessment: Assessment) -> None:
    code = assessment.assessmentCode
    if self.design.checkArrangement is CheckArrangement.none:
      raise ValueError(f"assessment '{code}': percent control needs untreated checks (design.checkArrangement)")
    ratings = {rating.ratingCode: rating for rating in self.ratings}
    if ratings[assessment.ratingCode].dataType is not AssessmentDataType.numeric:
      raise ValueError(f"assessment '{code}': percent control needs a numeric rating")
    baseline = assessment.efficacy.baselineAssessmentCode
    if baseline is None:
      return
    if baseline == code:
      raise ValueError(f"assessment '{code}': the baseline is another assessment, taken before application")
    occasions = {other.assessmentCode: other for other in self.assessments}
    if baseline not in occasions:
      raise ValueError(f"assessment '{code}': baseline assessment '{baseline}' is not declared in the package")
    if ratings[occasions[baseline].ratingCode].dataType is not AssessmentDataType.numeric:
      raise ValueError(f"assessment '{code}': baseline assessment '{baseline}' is not numeric")

  def analysedTreatmentCodes(self, assessmentCode: str) -> list[str]:
    """The treatments an assessment's analysis takes in, in package order (decision 0030)."""
    excluded = self.assessmentFor(assessmentCode).untreatedCheck is UntreatedCheck.excluded
    return [
      t.treatmentCode for t in self.treatments
      if not (excluded and t.role is TreatmentRole.untreatedControl)
    ]

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
