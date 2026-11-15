# OpenFurrow worklist

Findings, defects, checks and owner calls that the plans do not carry.
`implementation-plan.md` holds the ordered build units and `milestones.md` what exists.

Status tags: `fix` (a defect to correct), `build` (work to add), `check` (a suspicion to
measure), `owner` (the owner's call), `done`.

**Counts.** fix 15, build 9, check 0, owner 3, done 3; 30 in all.

## Owner decisions

- **Development environment (2026-11-15):** on the Windows development machine the project
  runs in its own virtual environment inside the clone, on the Python already installed
  there (3.14), unless that turns out complicated or large on disk.
- **Validation (2026-11-15):** development builds are made on Windows. A GitHub Actions
  workflow written for this project tests the full product on Linux and on Windows; it is
  where a change is validated before it is released publicly, and it is a required check
  for pull requests into `main`.
- **Order of work (2026-11-15):** file every flagged item here first; then the environment,
  the baseline run and the workflow; then reassess the order of everything else.
- **First real trial (2026-11-15):** the domain contact is available to run a real trial,
  but only once the owner is convinced the tool is ready. That case has not been made
  (USR-6).

## Reproducibility (REP)

- **REP-1** `fix` **The field layout depends on numpy's shuffle.**
  `openfurrow/design/randomization.py` regenerates the plot-to-treatment map from the seed
  with `Generator.permutation`, and the map is stored nowhere: not in the database, not in
  the JSON export, not in the content hash. numpy's compatibility policy
  (https://numpy.org/doc/stable/reference/random/compatibility.html) allows `Generator`
  methods to change their output in a feature release; only the bit generators carry a
  version-to-version guarantee. `pyproject.toml` accepts any numpy from 1.26. If the
  shuffle changes, an existing trial's plots map to other treatments and the analysis is
  wrong with no error: the content hash and `verify` still pass. The module's docstring
  says the stream is guaranteed across versions. Two tests pin a known layout
  (`tests/testRcbdLayout.py`), so a developer would see a change; a user would not. Open
  choice: an own shuffle drawn from the bit generator's raw output, a layout fingerprint
  stored with the trial and checked at every regeneration, or both; and whether the
  exported document carries the map. This touches settled shape 2 of
  `implementation-plan.md` (layout derived, never stored).
- **REP-2** `fix` **Library versions are not pinned.** Dependencies carry lower bounds
  only, so every install takes the newest releases. A validation run is then not
  repeatable. The baseline of PLT-1 ran against statsmodels 0.15.0, pandas 3.1.1,
  SQLAlchemy 2.1.8 and numpy 2.5.5 and passed, which says nothing about the next release.
  One case already in the tree: formulaic (pulled in by statsmodels) requires
  `wrapt>=1.17.0rc1` on Python 3.13 and newer, and a pre-release in a specifier makes pip
  accept pre-releases, so the install took wrapt 2.6.0.dev1 over the stable 2.5.2. Pin the
  test environment.
- **REP-3** `fix` **Exported JSON takes the platform's line endings.** `exportJson`
  (`openfurrow/exchange.py`) opens the file in text mode without a newline setting.
  Measured on Windows: all 152 lines of the worked example's export end in CRLF. The
  content hash is computed in memory and is unaffected, but the file is not byte-identical
  across platforms, while the function's own docstring calls it deterministic and decision
  0001 speaks of hashing the file. Write LF on every platform.
- **REP-4** `fix` **The report names the schema version as the software version.** The
  reproducibility block prints "OpenFurrow 0.1.0" from `schemaVersion`
  (`openfurrow/reports/report.py`), while the installed distribution is 0.1.0.dev0. Two
  builds of the software with one schema cannot be told apart in a report's provenance.

## Platforms (PLT)

- **PLT-1** `done` **First run on Windows and on Python 3.14.** Nothing in the repository
  showed the suite running anywhere but Linux with Python 3.13. Run on Windows 11 with
  Python 3.14.8 in a virtual environment inside the clone (382 MB), installed with the
  test and service extras: 357 tests passed in 94 seconds. The worked example through the
  installed `openfurrow` command reproduced the published table and the input hash
  `50fbfb3a...4ded`, before and after export and re-import. The web interface was walked
  in Chromium: a trial added through the form, observations uploaded, both reports read,
  the reproducibility check passed, and the Arabic view rendered right to left with its
  draft notice; no console errors, no failed requests, no request to another host.
- **PLT-2** `build` **Setup on Windows.** `scripts/bootstrap.sh` is Ubuntu-only (apt and
  the deadsnakes PPA), and `CLAUDE.md` and `CONTRIBUTING.md` tell every session to run it
  first. Windows needs its own path: a PowerShell 5.1 script, or the commands documented.
- **PLT-3** `fix` **Line endings.** The repository has no `.gitattributes`. A Windows
  checkout with Git's default settings gets CRLF in every file, which breaks
  `scripts/bootstrap.sh` under bash and puts CRLF data files into a wheel built there. Two
  fixtures are committed with CRLF (`examples/yatesOats/observations.csv`,
  `tests/fixtures/stirretBorers.csv`); the other 122 files are LF.
- **PLT-4** `fix` **A non-English report printed to redirected output on Windows.**
  `openfurrow report` prints the report (`openfurrow/cli/main.py`); when output is
  redirected, Python on Windows encodes it with the ANSI code page. Measured with code
  page 1252 and no `PYTHONIOENCODING`: `--locale ar` ends in an unhandled
  `UnicodeEncodeError` with an empty file, and `--locale fr` writes the report in cp1252,
  not UTF-8. `--output` writes UTF-8 and works for both.
- **PLT-5** `done` **The database file stays open.** Measured on Windows: while a
  `Workspace` is alive its database file can be copied but not renamed or deleted
  (sharing violation); both work once the object is dropped. Ownership by copying the
  file holds. A `Workspace` has no explicit way to release the file; nothing needed one.
- **PLT-6** `fix` **The stated Python target.** `pyproject.toml` requires 3.13 or newer;
  `CLAUDE.md`, `CONTRIBUTING.md`, the README and the bootstrap script say the project
  targets 3.13. Development moves to 3.14 and the workflow tests both. Say "3.13 or newer"
  consistently.

## Validation and release (VAL)

- **VAL-1** `build` **The validation workflow.** No GitHub Actions workflow exists. Owner
  decision: one workflow tests the full product on Linux and on Windows. The full product
  includes what the test suite does not reach: the wheel installed into a clean
  environment and run from there (the install smoke `milestones.md` records was done by
  hand).
- **VAL-2** `build` **The workflow gates `main`.** A required check for pull requests into
  `main`, in a ruleset without a bypass, so that an administrator's merge cannot skip it.
- **VAL-3** `build` **`main` is 65 commits behind `claude`.** It holds `README.md`,
  `LICENSE` and `brief.md`, and its README says the project is in its definition phase. No
  release or tag exists. Merge by pull request once the workflow passes. Whether that
  merge is tagged 0.1.0 is the owner's call.

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
  depends on what the first user's trials need.
- **USR-4** `build` **Data entry.** Observations arrive by CSV or a Field Book export. No
  Excel import (the brief lists it second after CSV) and no entry by hand.
- **USR-5** `build` **A printable report.** The report is Markdown, rendered to HTML in
  the browser; the brief names HTML and PDF output.
- **USR-6** `owner` **The readiness case.** Before the domain contact runs a real trial,
  the owner has to be convinced the tool is ready (Owner decisions, "First real trial").
  What that case must show is not yet defined.

## Small finds (SML)

- **SML-1** `fix` **Two tests assert any exception.** `testServeMissingDatabaseFailsLoud`
  (`tests/testServe.py`) and one test in `tests/testFieldBookImport.py` use
  `pytest.raises(Exception)`, which passes on any failure.
- **SML-2** `fix` **A return annotation.** `buildRcbdMatrix`
  (`openfurrow/analysis/anova.py`) is annotated as returning three values and returns
  four.
- **SML-3** `fix` **Stale comments in code.** `openfurrow/i18n/formatting.py` says no
  right-to-left locale ships yet; `openfurrow/workspace.py` speaks of "the future Flask
  service"; `openfurrow/service/web.py` describes D1 scope only;
  `openfurrow/config/profile.py` says the import profile is the only section.
- **SML-4** `fix` **A test depends on the working directory.**
  `testTemplatesAndStaticArePackaged` (`tests/testWeb.py`) runs `python -m build` without
  naming the project directory, so it passes only when pytest starts in the repository
  root; it also needs network access.
- **SML-5** `owner` **File names.** The owner's cross-project naming rule (camel case,
  files included) is not followed by `scripts/seed-draft-locales.py`,
  `tests/fixtures/fieldbook_database_export.csv` and the hyphenated documents under
  `roadmap/`. Rename, or leave as they are.
- **SML-6** `done` **A pre-release dependency.** A normal install on Python 3.14 takes a
  pre-release of wrapt; the cause and the remedy are in REP-2.
- **SML-7** `fix` **An unknown schema version is accepted.** `TrialPackage.schemaVersion`
  is any non-empty string: a package declaring 99.0 loads without complaint, although the
  code implements 0.1.0 and the field exists for migration.
