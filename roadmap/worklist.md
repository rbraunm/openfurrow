# OpenFurrow worklist

Findings, defects, checks and owner calls that the plans do not carry.
`implementation-plan.md` holds the ordered build units and `milestones.md` what exists.

Status tags: `fix` (a defect to correct), `build` (work to add), `check` (a suspicion to
measure), `owner` (the owner's call), `done`.

**Counts.** fix 0, build 6, check 0, owner 4, done 48; 58 in all.

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
- **Paired plot (2026-11-15):** the name covers several arrangements; all of them are
  supported rather than one chosen (decision 0022, REC-14).
- **Values outside their limits (2026-11-15):** a typed value outside its allowed range is
  flagged and kept once the user confirms it, and the record keeps the confirmation. It is
  not refused (REC-9).
- **Building the trial record (2026-11-15):** go, starting with treatments, applications
  and assessments, without waiting for the specialist unless the answers would change the
  shape. The questions on special randomizations and on an example of a trial's setup have
  been sent to the specialist.
- **The specialist's answers (2026-11-15):** the special arrangements in use are the first
  replicate left in treatment order, split plots, paired plots and the spatially balanced
  RCBD (REC-7). No example of a trial's setup can be shared: the specialist's trials carry
  a company's confidential details. The suggested route to a first user: a tool that
  also collects data on a phone or tablet could interest a university group to try it
  and publish the result, which could draw industry attention over some years (USR-9).

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
  Every existing trial hash changed.
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
- **PLT-2** `done` **Setup on Windows.** `scripts/bootstrap.sh` is Ubuntu-only (apt and
  the deadsnakes PPA), and `CLAUDE.md` and `CONTRIBUTING.md` told every session to run it
  first. Windows now has its own documented path: three commands in `CONTRIBUTING.md`
  ("Setup"), the ones that produced the Windows baseline (PLT-1). A script wrapping them
  has not been needed.
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
- **PLT-6** `done` **The stated Python target.** `pyproject.toml` requires 3.13 or newer,
  while `CLAUDE.md`, `CONTRIBUTING.md`, the README and the plan said the project targets
  3.13. They now say 3.13 or newer; development runs on 3.14 and the workflow tests both.
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
  request. Read back from GitHub's list of rules in force on `main`. The first pull
  request under the rule was merged after `validated` had passed on it (VAL-3). A merge
  before the check passes has not been attempted, so the refusal itself has not been
  observed.
- **VAL-3** `done` **`main` had none of the code.** It held `README.md`, `LICENSE` and
  `brief.md`, and its README said the project was in its definition phase. Pull request 2
  brought it up to the working tool on 2026-11-15, after the fixes of this worklist and
  after `validated` passed on both of its runs (392 tests on each of four combinations).
  `main` and `claude` are level. No tag was made; that remains the owner's call.
- **VAL-4** `done` **A run against the newest libraries.** The `latest` workflow runs the
  suite every Monday against the newest releases, without `constraints.txt`, on both
  systems and both Python versions; it does not gate `main` (`CONTRIBUTING.md`, "Pinned
  versions"). A manual run waits for the workflow to reach `main`, where GitHub reads
  scheduled workflows from; the same install was measured on Windows with Python 3.14
  before it was committed.

## Plan and documents (DOC)

- **DOC-1** `done` **Documents that described an older state.** `roadmap/platform-plan.md`
  said the service, the web interface and field collection were still to be built;
  `roadmap/README.md` stopped at the CLI and named five decision records of fifteen;
  `README.md` said the report renders "in either shipped locale" when five ship. All three
  now describe what exists.
- **DOC-2** `done` **The test-data registry listed more than the suite used.**
  `roadmap/research/test-data.md` named the Minnesota barley subset as an active fixture
  although nothing uses it, and described the missing-data cases as copies of
  stirret.borers although the reject tests remove cells from the Yates data. The registry
  now says both as they are. Two more published trials were added and are in use
  (`tests/testPublishedOracles.py`): Clewer and Scarisbrick's wheat varieties, entered
  with the layout it was grown in, and Gomez and Gomez's rice seeding rates. Each is
  checked against its printed table and against statsmodels.
- **DOC-3** `done` **The implementation plan's unit list.** It said adopting a CLDR-backed
  formatting library "is now due as its own unit" and listed none; D3 was unchecked
  without saying what had shipped; A3 and C1 were standing stances written as checkboxes;
  no unit covered a trial design form or charts. It now has unit L1 for the formatting
  library, says what of D3 shipped and what remains, drops the two checkboxes, and points
  to this worklist for the first-user work until its units are cut.
- **DOC-4** `owner` **What follows Phase 1.** The written next phase (own server, sync,
  logins, cloud templates, BrAPI) rests on decision 0005 (still Proposed), an open sync
  mechanism (0011) and an audience that decision 0008 itself gates on a partner's
  confirmation. To be settled at the reassessment (Owner decisions, "Order of work").

## First real user (USR)

- **USR-1** `done` **A trial design form.** "Add trial" opens a form: the trial's details,
  treatments with their roles, the number of blocks, and assessments with a unit and
  limits or a list of categories, with buttons for more rows; it works without JavaScript
  and keeps everything typed when something is wrong. The layout is generated from a seed
  (drawn and recorded when left empty) or uploaded as planted (USR-7). Product lines,
  applications, factors, checks and the other parts of the record are still written as
  a trial file; their forms are USR-14.
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
  Built so far: the transformation with its offset and log10 (decision 0026), percent
  control (decision 0022), and the split-plot and factorial RCBD designs (decisions 0020,
  0025), the completely randomized design (decision 0027) and Tukey's HSD for all pairs
  (decision 0028), Dunnett against the untreated check (decision 0029) and an explicit
  policy for the check in each assessment's analysis (decision 0030). Still to come:
  Dunnett with unequal replication, and missing plots (the analysis refuses an incomplete
  table, decision 0003).
- **USR-4** `done` **Data entry.** Built as decision 0031 says: a CSV or an `.xlsx` sheet
  (read natively) is previewed, its columns mapped by the person, imported, and reconciled
  per assessment against the plots; an import never replaces stored values. Typed entry is
  REC-9; keeping the file and the mapping with the trial is REC-16.
- **USR-5** `done` **A printable report.** The report page has a Print button and a print
  stylesheet: the site header, links and footer are left off, headings stay with what
  follows them and tables are not split where they fit on a page. Measured by printing the
  split-plot and paired-check reports to PDF in Chromium, in English and Arabic: four
  pages each, no site chrome, no page starting inside a table. A PDF comes from the
  browser's own "save as PDF"; the tool writes none itself.
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
- **USR-7** `done` **Trials laid out elsewhere.** Built: the trial form takes a CSV of the
  plots as planted (plotNumber, block, positionInBlock, treatmentCode, other columns left
  aside), keeps it exactly, and refuses one that is not complete blocks. Before: A layout is always generated from the
  seed. A trial randomized by another tool, or already in the ground, cannot be entered
  with its own plot numbers and its own plot-to-treatment map; its observations could
  only be re-keyed onto a generated layout that does not match the field. A first real
  trial will most likely be one of these. Since REP-1 such a trial can be held: it comes in
  as a trial document whose package says `imported` and whose layout lists the plots
  (`import-json`, or the API). The path through the interface remains to build.
- **USR-9** `owner` **Field collection for a university pilot.** The specialist's route to a
  first user (Owner decisions, "The specialist's answers") needs data collected on a
  phone or tablet. The owner's direction (2026-11-15): too big to settle now, and a very
  important part of the proof-of-concept deliverable. The bar is ease: most of the time
  someone is sent a link, clicks it, and can do the work they need to do. What that looks
  like is to be discussed once the substrate (the trial record, entry and the analysis)
  is in place. For that discussion: the file-based Field Book path exists today but needs
  an Android app and a file hand-off; decision 0014 plans the project's own apps; a link
  that just works points at a served, phone-ready web interface (decisions 0011, 0012).
- **USR-10** `done` **Factorial RCBD.** Built as decision 0025 says: two factors on an RCBD,
  their combinations the treatments, the factorial table (A, B, A x B on the one error) and
  each factor's means separated, checked against Gomez and Gomez section 3.3 and
  statsmodels. Three or more factors are still refused.
- **USR-11** `done` **Comparisons inside a two-factor interaction.** The table of combination
  means carries letters comparing the second factor's levels within each row, on the LSD for
  that comparison, and states both LSDs. For a split plot two subplot means at one main-plot
  level differ by sqrt(2 Eb / r) and two main-plot means at one subplot level by
  sqrt(2 [(b - 1) Eb + Ea] / rb) on the weighted t (Gomez and Gomez Tables 5.5 and 5.6);
  a factorial RCBD uses its one error for both. Under the protected rule the letters appear
  only when the interaction is significant. Checked against the book's 482.8 kg/ha and LSD
  of 980 (its tabulated t, 2.029, is 2.0281 exactly) and its weighted-t example (2.178).
- **USR-12** `done` **Assumption checks for a split plot and a CRD.** Brown-Forsythe for
  both; Shapiro-Wilk on the CRD's residuals and on each split-plot stratum; Tukey's
  non-additivity stays RCBD-only (decision 0006).
- **USR-13** `done` **The field map of a split plot or a trial with checks.** The map
  outlines each main plot with its main-plot level, and draws each check plot dashed and
  marked untreated, right after the last plot it serves.
- **USR-14** `build` **Forms for the rest of the record.** Product lines, applications,
  targets, planting, soil, weather, factors, checks and percent control are entered in a
  trial file today; the form covers the trial, treatments, blocks, layout and assessments.
- **USR-8** `build` **What happened to a plot, and who changed a value.** A lost plot, a misapplied treatment or a
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

- **REC-1** `done` **Planting details.** Built as decision 0019 says: cultivar, the crop's
  EPPO code, sowing date, seeding rate, plant density, row and in-row spacing, sowing
  depth, emergence date (not before sowing), preceding crop, tillage and notes. Fertilizer
  lives with the soil and irrigation in the weather log, each once.
- **REC-2** `done` **Pest information.** Built as decision 0018 says: a trial lists its
  targets (code, common name, kind, scientific name, EPPO code checked for shape), and a
  rating names the target it rates by code. A target's stage at an application or an
  assessment stays text.
- **REC-3** `done` **Treatment information.** Built as decision 0016 says: a treatment
  may state its role (test, reference, untreated control, other control) and has product
  lines, each a formulated product with its kind, formulation type, active substances and
  their concentrations, and a rate whose basis (product or active substance) must be
  stated, tied by code to its applications. Stored, exported, hashed and printed; the
  report shows one row per line and leaves out a column nothing is recorded in.
- **REC-4** `done` **Application information.** Built as decision 0016 says: each
  application has a code, the planned timing, date and time of day, method, placement,
  equipment, nozzle, pressure, spray quality, travel speed, spray volume, crop and target
  stage, air temperature, relative humidity, wind speed, cloud cover, soil moisture and
  notes; the report tabulates them. Impossible values are refused on entry. A difference
  from the planned dose stays with USR-8; entry by form stays with USR-1.
- **REC-10** `done` **The Markdown report on right-to-left readers.** Measured by showing
  the Arabic report's lines as plain right-to-left text in Chromium: quantities read
  "kPa 250" and "L/ha 0.5". In a right-to-left report every quantity is now wrapped in
  Unicode isolates (FSI, PDI), and the same lines read "250 kPa" and "0.5 L/ha". Other
  locales are unchanged. The order of mixed Latin cells across a whole table row still
  depends on the viewer.
- **REC-5** `done` **Soil information.** Built as decision 0019 says: soil type, texture,
  pH with the method it was measured by, organic matter, seed-bed quality, the fertilizer
  regime and notes. Soil moisture at application sits with the application. Sand, silt
  and clay fractions and soil layers can wait.
- **REC-6** `done` **Weather information.** Built as decision 0019 says: a log of days in
  date order with rainfall, irrigation, minimum and maximum temperature and notes; the
  conditions on application days are with each application (REC-4). Reading a log from a
  file is REC-13.
- **REC-14** `done` **What a paired plot is.** The name covers three arrangements; the
  owner decided to support all of them (decision 0022): imbricated strips, adjacent
  halves and paired partners, with percent control by Abbott or Henderson-Tilton.
- **REC-15** `done` **Plot sizes and the zones between plots.** Built as decision 0024
  says: gross and net length and width and the alleys, on the design, in the report.
- **REC-12** `done` **The site itself.** Built as decision 0024 says: address, latitude and
  longitude, elevation, setting, exposure and slope; and for perennial crops the training
  system, rootstock and year planted beside the spacing planting already had.
- **REC-13** `done` **A weather log from a file.** A CSV of days (a date, then rainfall,
  irrigation, minimum and maximum temperature with the unit in the header, and notes)
  replaces the trial's weather log, from the command line (`import-weather`) or the trial
  page. Rows are put in date order; a day given twice, a column without its unit or a
  value the log refuses is named, and nothing is replaced.
- **REC-7** `done` **Special randomizations.** The arrangements the specialist named are
  built: the first replicate left in treatment order (a design option), the split plot
  (decision 0020), the spatially balanced RCBD (decision 0021) and the paired plot in all
  three of its meanings (decision 0022). Any arrangement laid out elsewhere comes in as an
  imported layout. Plot sizes and the zones between plots are REC-15.
- **REC-8** `done` **Assessment definitions.** Built as decision 0017 says: a rating holds
  what is rated and every rule its values obey (rating type, part rated, method, data
  type, unit, limits or categories, measurement kind, transform); an assessment is one
  occasion it is taken (timing, date, crop and target stage, the application it is timed
  from, who assessed, sample size, notes). Each occasion is analysed on its own, and the
  report shows days after application (14 DA-A), derived from the two dates. Subsamples
  are REC-11; a rating's target came with REC-2.
- **REC-11** `build` **Subsamples within a plot.** Several values taken in one plot on one
  occasion (ten leaves, four quadrats) kept as entered, with the plot's value derived from
  them by a stated rule (mean, sum). Today one value per plot and assessment.
- **REC-16** `build` **The file as received.** The readiness bar asks for "the original data
  kept as received" and the brief for the resolved column mapping to be recorded. An import
  keeps neither: the observations are saved, the file and the mapping are not. To keep: the
  file's bytes and hash, the sheet, the mapping and when it was imported, exported with the
  trial.
- **REC-9** `done` **Validation rules for data entry.** Built as decision 0023 says: an entry
  page per assessment, values checked in two strengths. What cannot be a value is refused
  and nothing saved; a value outside its limits is saved only once ticked, and the
  confirmation is kept with the value, exported and hashed, as the owner decided. The
  same rule checks every trial document. A completeness count shows on the page; the
  analysis still refuses an incomplete table (decision 0003).

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
- **SML-10** `done` **Back arrows in right-to-left pages.** The "back" links wrote a left
  arrow into the text, so on the Arabic pages the arrow pointed away from where it leads.
  The arrow now follows the page direction.
