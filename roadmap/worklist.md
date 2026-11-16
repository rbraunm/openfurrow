# OpenFurrow worklist

Findings, defects, checks and owner calls that the plans do not carry.
`implementation-plan.md` holds the ordered build units and `milestones.md` what exists.

Status tags: `fix` (a defect to correct), `build` (work to add), `check` (a suspicion to
measure), `owner` (the owner's call), `done`.

**Counts.** fix 4, build 19, check 0, owner 3, done 18; 44 in all.

## Owner decisions

- **Development environment (2026-11-15):** on the Windows development machine the project
  runs in its own virtual environment inside the clone, on the Python already installed
  there (3.14), unless that turns out complicated or large on disk.
- **Validation (2026-11-15):** development builds are made on Windows. A GitHub Actions
  workflow written for this project tests the full product on Linux and on Windows; it is
  where a change is validated before it is released publicly, and it is a required check
  for pull requests into `main`.
- **Order of work (2026-11-15):** the fixes first; then `main` by pull request; then what a
  first user needs; the written server phase last.
- **Pull request into `main` (2026-11-15):** once the fixes pass the workflow, the pull
  request is opened and merged without asking again. No tag for now.
- **Layout (2026-11-15):** left to what the field does at large, to be researched rather
  than guessed. Result: the layout is recorded data (decision 0015,
  `research/layoutPractice.md`).
- **First real trial (2026-11-15):** the domain contact is available to run a real trial,
  but only once the owner is convinced the tool is ready. That case has not been made
  (USR-6). The proposed bar was to be put to a second opinion; the amended bar is under
  USR-6.
- **Oracles (2026-11-15):** finished trials that are openly available, from different
  sources and fields, are the yardstick; a private trial is not needed to start.
  Candidates are in `research/test-data.md`.

## Reproducibility (REP)

- **REP-1** `done` **The field layout depended on numpy's shuffle.** The plot-to-treatment
  map was regenerated from the seed with numpy's `Generator.permutation` and stored
  nowhere: not in the database, not in the JSON export, not in the content hash. numpy
  allows `Generator` methods to change their output in a feature release, so an existing
  trial's plots could have come to map to other treatments with no error, the content
  hash and `verify` still passing. Built as decision 0015 says. The plot map is recorded
  data: a `plot` table, a `layout` in the trial document, covered by the content hash. A
  generated layout comes from the project's own procedure, `sha256FisherYates1`, specified
  in `openfurrow/design/randomization.py` and pinned in the tests against SHA-256 itself.
  A document whose layout is not what its method and seed produce is rejected. A layout
  made elsewhere is `imported`, has no seed, and is kept as supplied. The schema is 0.2.0,
  and the store carries a version, so a database of an earlier build is refused by name.
  Every existing trial hash changed; the worked example's is now `8bb10a52...e725`.
- **REP-2** `done` **Library versions were not pinned.** Dependencies carry lower bounds
  only, so every install took the newest releases and a validation run could not be
  repeated. One install had already taken a pre-release: formulaic (pulled in by
  statsmodels) requires `wrapt>=1.17.0rc1` on Python 3.13 and newer, a pre-release in a
  specifier makes pip accept pre-releases, and wrapt 2.6.0.dev1 was installed over the
  stable 2.5.2. `constraints.txt` now pins every dependency of the test and service extras
  and the build backend, at the versions that passed on Linux and Windows with Python 3.13
  and 3.14, wrapt at its stable release. The bootstrap script, the workflow and the
  product smoke install with it; `CONTRIBUTING.md` ("Pinned versions") says how to move
  the pins.
- **REP-3** `done` **Exported JSON took the platform's line endings.** On Windows all 152
  lines of the worked example's export ended in CRLF, so the file was not byte-identical
  across platforms although the content hash was. `exportJson` and the report's
  `--output` now write UTF-8 with LF everywhere, and tests check both
  (`tests/testExchange.py`, `tests/testCli.py`).
- **REP-4** `done` **The report named the schema version as the software version.** It
  printed "OpenFurrow 0.1.0" from `schemaVersion` while the installed distribution was
  0.1.0.dev0. The software version now lives in `openfurrow/version.py`; `pyproject.toml`
  takes the distribution's version from it and the report prints it. The product smoke
  checks that the report in every locale names the version of the installed wheel.

## Platforms (PLT)

- **PLT-1** `done` **First run on Windows and on Python 3.14.** Nothing in the repository
  showed the suite running anywhere but Linux with Python 3.13. Run on Windows 11 with
  Python 3.14.8 in a virtual environment inside the clone (382 MB), installed with the
  test and service extras: 357 tests passed in 94 seconds. The worked example through the
  installed `openfurrow` command reproduced the published table and its input hash,
  before and after export and re-import. The web interface was walked
  in Chromium: a trial added through the form, observations uploaded, both reports read,
  the reproducibility check passed, and the Arabic view rendered right to left with its
  draft notice; no console errors, no failed requests, no request to another host.
- **PLT-2** `build` **Setup on Windows.** `scripts/bootstrap.sh` is Ubuntu-only (apt and
  the deadsnakes PPA), and `CLAUDE.md` and `CONTRIBUTING.md` tell every session to run it
  first. Windows needs its own path: a PowerShell 5.1 script, or the commands documented.
- **PLT-3** `done` **Line endings.** The repository had no `.gitattributes`: a Windows
  checkout with Git's default settings got CRLF in every file, and two fixtures were
  committed with CRLF. Measured cost: a wheel built from such a checkout carried CRLF data
  files (613 carriage returns in the en-US catalog alone), so it differed from one built
  on Linux. Git for Windows' own bash tolerated the CRLF in `scripts/bootstrap.sh`; a
  Linux bash given the same file would not. `.gitattributes` now makes text LF in the
  repository and in every checkout, PowerShell scripts excepted, and the two fixtures are
  renormalized.
- **PLT-4** `done` **A non-English report printed to redirected output on Windows.**
  Measured with code page 1252 and no `PYTHONIOENCODING`: `--locale ar` ended in an
  unhandled `UnicodeEncodeError` with an empty file, and `--locale fr` came out in cp1252.
  The command now writes UTF-8 to its output streams on every platform, and a test runs
  it as a process of its own for both locales (`tests/testCli.py`). Redirected output
  keeps the platform's line endings; `--output` is the byte-stable path.
- **PLT-5** `done` **The database file stays open.** Measured on Windows: while a
  `Workspace` is alive its database file can be copied but not renamed or deleted
  (sharing violation); both work once the object is dropped. Ownership by copying the
  file holds. A `Workspace` has no explicit way to release the file; nothing needed one.
- **PLT-6** `fix` **The stated Python target.** `pyproject.toml` requires 3.13 or newer;
  `CLAUDE.md`, `CONTRIBUTING.md`, the README and the bootstrap script say the project
  targets 3.13. Development moves to 3.14 and the workflow tests both. Say "3.13 or newer"
  consistently.

## Validation and release (VAL)

- **VAL-1** `done` **The validation workflow.** `.github/workflows/validate.yml` runs on
  every push to `claude` and every pull request into `main`: the test suite, then
  `scripts/productSmoke.py`, on Linux and Windows with Python 3.13 and 3.14.
  `CONTRIBUTING.md` ("Validation") describes it. The smoke covers what the suite does not
  reach: it builds the source distribution and the wheel from it, installs the wheel with
  the service extra into a clean environment, runs the worked example through the
  installed command in every shipped locale, and reads the served pages. Checked against a
  copy with the templates removed from the packaging: the smoke fails there, at the first
  page. First run, on the commit that added it: all four jobs passed, 357 tests each
  (7 to 10 seconds on Linux, 23 to 25 on Windows), and the worked example's hash was the
  same on both systems and both Python versions.
- **VAL-2** `done` **The workflow gates `main`.** The ruleset "main validation" requires
  the workflow's final check, `validated`, on the default branch and has no bypass, so an
  administrator's merge cannot skip it; "main protections" still requires the pull
  request. Read back from GitHub's list of rules in force on `main`. No pull request has
  met the rule yet (VAL-3).
- **VAL-3** `build` **`main` has none of the code.** It holds `README.md`, `LICENSE` and
  `brief.md`, and its README says the project is in its definition phase. No
  release or tag exists. Merge by pull request once the workflow passes. That pull request
  is also the first to meet the gate: a merge attempted before `validated` has passed must
  be refused. Whether the merge is tagged 0.1.0 is the owner's call.
- **VAL-4** `build` **A run against the newest libraries.** With the versions pinned
  (REP-2), nothing reports that a new release of a dependency breaks the project until
  someone moves the pins. A scheduled run of the workflow that installs without
  `constraints.txt` would.

## Plan and documents (DOC)

- **DOC-1** `fix` **Documents that describe an older state.** `roadmap/platform-plan.md`
  ("Current state") says the service, the web interface and field collection are still to
  be built. `roadmap/README.md` ("Current state") stops at the CLI, and its description of
  `decisions/` names five records of fourteen. `README.md` says the report renders "in
  either shipped locale"; five ship.
- **DOC-2** `fix` **The test-data registry lists more than the suite uses.**
  `roadmap/research/test-data.md` names the Minnesota barley subset as an active fixture;
  no fixture or test uses it. It describes the missing-data cases as copies of
  stirret.borers; the reject tests (`tests/testAnovaRcbd.py`) remove cells from the Yates
  data. `CONTRIBUTING.md` requires the registry to match what the suite validates against.
  Add the fixture and tests, or correct the registry.
- **DOC-3** `fix` **The implementation plan's unit list.** It says adopting a CLDR-backed
  formatting library "is now due as its own unit", and lists no such unit. D3 is unchecked
  although catalogs, direction handling and three draft locales shipped. A3 and C1 are
  standing stances written as checkboxes that can never be ticked. No unit covers a trial
  design form or charts (USR-1, USR-2).
- **DOC-4** `owner` **What follows Phase 1.** The written next phase (own server, sync,
  logins, cloud templates, BrAPI) rests on decision 0005 (still Proposed), an open sync
  mechanism (0011) and an audience that decision 0008 itself gates on a partner's
  confirmation. To be settled at the reassessment (Owner decisions, "Order of work").

## First real user (USR)

- **USR-1** `build` **A trial design form.** In the web interface a trial is created by
  pasting or uploading package JSON (`openfurrow/service/web.py`); a researcher who does
  not write JSON cannot start.
- **USR-2** `build` **Charts.** None exist; `milestones.md` lists means with letters and
  error bars as future work.
- **USR-3** `build` **Analysis breadth.** One design (single-factor RCBD) and one
  comparison method (Fisher's LSD, protected or not). Which designs and tests come first
  depends on what the first user's trials need. The second opinion's ranking for a first
  efficacy trial: the right design and experimental unit; an explicit policy for the
  untreated check (in the analysis or only in the report, never dropped silently); each
  assessment date analysed on its own; the transformation the reference used, offsets
  included; Tukey for all pairs or Dunnett against a check before Duncan and SNK; percent
  control (Abbott, Henderson-Tilton) when the endpoint calls for it; missing plots when
  the trial has them. EPPO PP 1/152 names the completely randomized design beside the
  RCBD as the two principal designs; the tool has only the second.
- **USR-4** `build` **Data entry.** Observations arrive by CSV or a Field Book export. No
  Excel import (the brief lists it second after CSV) and no entry by hand.
- **USR-5** `build` **A printable report.** The report is Markdown, rendered to HTML in
  the browser; the brief names HTML and PDF output.
- **USR-6** `owner` **The readiness case.** Before the domain contact runs a real trial,
  the owner has to be convinced the tool is ready (Owner decisions, "First real trial").
  The bar, as amended by the second opinion, which found the first proposal right for
  unsupervised use and asked for an agreed scope and a traceable analysis on top:
  - *Scope agreed first.* One finished trial; its assessments, transformation, comparison
    test, significance level and check handling named before any number is compared. What
    the tool does not support is refused with a clear message, never approximated.
  - *Set up without JSON.* Treatments entered, and the existing plot, block and treatment
    allocation brought in exactly as planted. A full design form can wait.
  - *Their data from their files.* The export they actually have, with a preview, an
    explicit column mapping, and every observation reconciled (counts, duplicates, units,
    dates).
  - *The numbers match.* Same observations and degrees of freedom; treatment means, the
    ANOVA table, CV, and the LSD or HSD; the same pairwise decisions rather than the same
    letter names. Against a printed report, agreement to its printed precision, and called
    that; against full-precision output, a relative tolerance of one in a million.
  - *A report they can print.* Printing from the browser is enough if tables, notes and
    page breaks survive.
  - *It installs on their Windows PC* from a documented procedure, without a developer.
  - *Safe to use.* Save and reopen; the original data kept as received; the analysis
    settings recorded with the result.
  - *A bounded pilot.* A supervised session, and their established analysis stays the
    analysis of record.
  Showing all of this on open, finished trials (Owner decisions, "Oracles") is the case to
  make to the owner. The parts of a trial record the specialist named (REC) belong to the
  bar as far as the pilot trial uses them.
- **USR-7** `build` **Trials laid out elsewhere.** A layout is always generated from the
  seed. A trial randomized by another tool, or already in the ground, cannot be entered
  with its own plot numbers and its own plot-to-treatment map; its observations could
  only be re-keyed onto a generated layout that does not match the field. A first real
  trial will most likely be one of these. Since REP-1 such a trial can be held: it comes in
  as a trial document whose package says `imported` and whose layout lists the plots
  (`import-json`, or the API). The path through the interface remains to build.
- **USR-8** `build` **What happened to a plot.** A lost plot, a misapplied treatment or a
  difference between the plan and what was planted has no record. EPPO PP 1/181 asks for
  deviations to be noted and reported (decision 0015, "Consequences").

## Trial record (REC)

A research specialist who runs such trials looked at screenshots of a trial page, a
report and the Arabic view (2026-11-15). The verdict: the basic idea is there, but a
trial has to hold much more than its design and its numbers. The points named are, almost
one for one, the sections of the trial report in EPPO PP 1/181's Appendix 1, so the plan
is to build the record to that standard's shape (`research/trialRecord.md`). Each item
below says what the tool holds today and what the plan adds.

Each part is built as data first -- the trial document, the store and the report -- and
then gets its form. Order: REC-7 rests on REP-1, which is under way. REC-3, REC-4 and
REC-8 change the shape of a trial most and come next. REC-1, REC-2, REC-5 and REC-6 are
sections added beside them. REC-9 needs data entry in the tool (USR-4).

- **REC-1** `build` **Planting details.** Today: a crop, a season and a site as free text.
  Plan, after section 1.2 of the standard: crop and cultivar (with an EPPO code where
  known), sowing or planting date, seeding rate with its unit, plant density, row and
  in-row spacing, emergence date, the preceding crop, and tillage, fertilizer and
  irrigation as notes.
- **REC-2** `build` **Pest information.** Today: nothing. Plan, after section 1.1: the
  trial's targets, each with a name, a scientific name or EPPO code and a kind (weed,
  disease, insect, other). A target's stage and level are recorded where they occur: at
  each application (REC-4) and at each assessment (REC-8).
- **REC-3** `build` **Treatment information.** Today: a code, a name, one product, one
  rate with its unit and a free-text timing. Plan, after sections 2.1 and 2.2: a treatment
  has a role (test product, reference product, untreated check) and one or more lines. A
  line is a product (its formulated name, active substances, formulation concentration
  and type) at a rate with its unit, tied by code to the applications it goes on at.
- **REC-4** `build` **Application information.** Today: nothing. Plan, after section 2.2:
  applications as events, each with a code, a date and time, the method, equipment,
  nozzle, pressure and spray volume, the crop's growth stage (BBCH), the target's stage,
  and the conditions at the time (air temperature, humidity, wind, cloud, soil moisture).
  A difference from the planned dose is recorded as a deviation (USR-8).
- **REC-5** `build` **Soil information.** Today: nothing. Plan, after section 3.1.2: soil
  type or texture, pH, organic matter, seed-bed quality and the fertilizer regime; soil
  moisture at application sits with the application (REC-4). Sand, silt and clay
  fractions and soil layers can wait.
- **REC-6** `build` **Weather information.** Today: nothing. Plan, after section 3.1.1:
  the conditions on the day of each application (with REC-4), a dated log of rain,
  irrigation and temperature for the trial, and notes on extremes. Entered by hand or
  from a file; automatic feeds can wait.
- **REC-7** `build` **Special randomizations.** Today: one design, the RCBD, with every
  block shuffled independently. Plan: REP-1 (decision 0015) makes any layout a record,
  so an arrangement made by hand or in another tool is held with its own plot numbers.
  Then, after section 1.3: the arrangement of the untreated control (included,
  imbricated, excluded), plot sizes and the zones between plots, and further designs in
  the order the specialist's trials need them (completely randomized, Latin square,
  split-plot, strip-plot). Which special arrangements are meant is a question for the
  specialist.
- **REC-8** `build` **Assessment definitions.** Today: a code, a name, a data type, a
  unit, a free-text timing, a range or allowed values, a measurement kind and a
  transform; one value per plot. Plan, after section 3.2: a definition (what is rated,
  the rating type, unit and scale, the part rated, the method, limits or categories, the
  transform) kept apart from its occasions (the date, the crop and pest stage, the days
  after a named application, who assessed). A sample size, and subsamples within a plot
  kept as entered, with the plot's value derived from them.
- **REC-9** `build` **Validation rules for data entry.** Today: a value is checked on
  import against the range or allowed values, and one bad value rejects the file; the
  tool has no entry of its own (USR-4). Plan: entry in the tool, with the definition's
  rules applied as a value is typed, in two strengths. What cannot be a value (a wrong
  type, a category that does not exist) is refused. What is unlikely (outside the limits)
  is flagged and kept only with a confirmation that the record keeps. A completeness
  check comes before analysis. Whether a value outside its limits may be kept at all is
  the owner's call: today it is refused, and the incumbent tool flags it and lets the
  user confirm.

## Small finds (SML)

- **SML-1** `done` **Two tests asserted any exception.** `testServeMissingDatabaseFailsLoud`
  (`tests/testServe.py`) and `testIngestRejectsPlotOutsideLayout`
  (`tests/testFieldBookImport.py`) used `pytest.raises(Exception)`. Both now name the
  exception and its message.
- **SML-2** `done` **A return annotation.** `buildRcbdMatrix`
  (`openfurrow/analysis/anova.py`) is annotated with the four values it returns.
- **SML-3** `done` **Stale comments in code.** Corrected in
  `openfurrow/i18n/formatting.py`, `openfurrow/workspace.py`, `openfurrow/service/web.py`
  and `openfurrow/config/profile.py`.
- **SML-4** `done` **A test depended on the working directory.**
  `testTemplatesAndStaticArePackaged` (`tests/testWeb.py`) built a wheel in the source
  tree: it passed only when pytest started in the repository root, it needed the network,
  and a `build/` directory left by an earlier build supplied files the project no longer
  packaged. Measured on a copy with the templates removed from the packaging: the test
  passed while the old `build/` was there and failed once it was deleted. Removed; the
  product smoke proves the same thing from a wheel built from the source distribution.
- **SML-5** `owner` **File names.** The owner's cross-project naming rule (camel case,
  files included) is not followed by `scripts/seed-draft-locales.py`,
  `tests/fixtures/fieldbook_database_export.csv` and the hyphenated documents under
  `roadmap/`. Rename, or leave as they are.
- **SML-6** `done` **A pre-release dependency.** A normal install on Python 3.14 takes a
  pre-release of wrapt; the cause and the remedy are in REP-2.
- **SML-7** `done` **An unknown schema version was accepted.** A package declaring 99.0
  loaded without complaint. A package must now declare the schema this build reads; any
  other value is rejected with both versions named. The web form's example takes its
  version from the same constant.
- **SML-8** `done` **A test rewrote a shipped catalog in place.**
  `testDiagnosticTextFollowsTheLocale` (`tests/testLocalization.py`) overwrote `fr.json`
  in the source tree and put it back afterwards, so an interrupted run would have left the
  shipped French catalog replaced. It now reads from a copy of the catalogs.
- **SML-9** `done` **The API answered a document that is not JSON with a server error.**
  `POST /api/documents` let a JSON parse error escape, and no handler mapped it. Importing
  a document now raises one error type for a file that is not JSON or not a valid trial
  document, which the command line reports and the API answers with 400.
