# How the field treats a randomized layout

Purpose: settle whether a trial's plot map (which treatment is on which plot, in which
block) is something to regenerate from the randomization seed or something to record. This
is an evidence file; the decision is `../decisions/0015-layout-recorded-as-data.md`.

Sources marked **[read]** were opened and read for this note. Sources marked **[reported]**
were found through assisted web research and are cited as reported, not re-read.

## 1. The standards carry the assignment on every plot

- **BrAPI v2.1.** An `ObservationUnit` (typically a plot) has `treatments`, "List of
  treatments applied to an observation unit", each a `factor` and a `modality`, mapped to
  MIAPPE's "Observation Unit factor value". Its `observationUnitPosition` holds the entry
  type, the unit's level, its relationships to higher levels (block, replicate) and its
  position coordinates. The assignment travels as data with each unit. **[read]**
- **MIAPPE 1.1.** Observation units with their factor values and spatial distribution,
  and a map of the experimental design, are part of the minimum description of an
  experiment. **[reported]**; the factor-value mapping is cited in BrAPI's schema
  **[read]**.

## 2. The regulations put the assignment in the trial record

- **EPPO PP 1/181 (5)**, the standard behind good experimental practice for efficacy
  trials. Appendix 1, section 1.3 "Design and layout": the design and layout of the plots
  should be described, "preferably with a plan"; the type of experimental design is
  stated; plots are assigned to treatments and to blocks. Section 3.4: what is recorded
  during a trial is held in the trial notebook, and the trial report contains all relevant
  information from it. Section 3.3.3: any deviation from the protocol is noted and
  reported. **[read]**
- **EPPO PP 1/152 (4)**, section 1.2.2: the arrangement of treatments is randomized
  separately for each block. The same section notes that treatments within a replicate
  "may appear in treatment order" and that this is to be avoided wherever possible -- so
  in practice it happens. **[read]**
- **OECD GLP for field studies and US EPA guidance.** Raw data are the original records
  needed to reconstruct a study; missing critical raw data is a ground for rejecting it.
  **[reported]**

## 3. Tools store or hand over the realized layout

- **Breedbase.** A generated design can be redone ("Redo Randomization") until it is
  confirmed; confirming saves it into the database. An existing trial is uploaded with its
  own layout: plot number and block number are required columns, row and column and
  treatments optional. Layout details can be edited afterwards. **[read]**
- **agricolae (R).** `design.rcbd(trt, r, serie, seed, kinds, first, continue,
  randomization)` returns the parameters, a sketch and the `book`, the fieldbook. The
  `first` argument chooses whether replicate 1 is randomized at all. The fieldbook is what
  the user keeps. **[read]**
- **Field Book.** Imports a field as one row per plot with its identifiers; see
  `fieldbook-formats.md`. **[read]** there.
- **BMS, KDSmart, EBS, SAS PROC PLAN, GenStat, FielDHub.** Import external designs, store
  imported trials, or write the realized assignment to an output dataset or spreadsheet.
  **[reported]**
- **ARM.** The trial map is a document of the trial and appears in published trial
  reports with plot numbers, replicates and treatments; the vendor now also georeferences
  it. **[reported]**

No tool or standard in this survey keeps only a seed and regenerates the layout as its
system of record.

## 4. Why a seed alone is not a record

- **Random number generators change.** NumPy allows the methods of its `Generator`
  (`permutation`, `shuffle`, `integers`) to produce different results in a new feature
  release; only its bit generators carry a version-to-version guarantee. **[read]** R
  changed its default sampler in version 3.6.0, so a design generated from a seed before
  that release is not reproduced by the same seed after it unless the old sampler is
  requested. **[reported]**
- **A layout in the field is not always what the generator produced.** The first
  replicate is often left in treatment order (the agricolae argument and the EPPO wording
  above), a layout may come from another tool, a plan may be adjusted before planting, and
  plots are lost.
- **The failure is silent.** Observations are keyed by plot. If the regenerated map
  differs, every observation is still found, every block still holds every treatment, and
  the analysis runs -- on the wrong treatments.

## 5. What this implies

- The realized layout is data: stored, exported and covered by the content hash.
- The seed and the name of the randomization method are provenance. A layout made
  elsewhere has neither.
- Regenerating the layout from its seed is a check on the record, never its source.
- What happened to a plot after the plan was issued (as planted against as planned, lost
  plots, misapplied treatments) is a further record of its own; EPPO asks for deviations
  to be reported. Not designed here.

## References

- BrAPI v2.1 specification, `BrAPI-Phenotyping/ObservationUnits` schemas
  (github.com/plantbreeding/BrAPI) and the observation-level best practices
  (plant-breeding-api.readthedocs.io). **[read]**
- EPPO PP 1/181 (5), Conduct and reporting of efficacy evaluation trials, including good
  experimental practice; EPPO PP 1/152 (4), Design and analysis of efficacy evaluation
  trials (pp1.eppo.int). **[read]**
- Breedbase user manual, Managing field trials (solgenomics.github.io/sgn). **[read]**
- agricolae reference manual, `design.rcbd` (CRAN). **[read]**
- NumPy, Compatibility policy for `numpy.random` (numpy.org). **[read]**
- R documentation, Random number generation (`sample.kind`, R 3.6.0). **[reported]**
- Papoutsoglou et al. (2020), Enabling reusability of plant phenomic datasets with MIAPPE
  1.1, New Phytologist 227(1):260-273. **[reported]**
- OECD, The application of the GLP principles to field studies; US EPA, GLP study
  rejection guidance. **[reported]**
- Vendor and project documentation for ARM, BMS, KDSmart, EBS, SAS PROC PLAN, GenStat and
  FielDHub. **[reported]**
