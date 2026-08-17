# Milestones

The MVP was the thinnest reproducible loop: define a trial, randomize it, import
observations, analyze, report, and export a portable package that re-imports and
reproduces. That loop is now reachable three ways -- the CLI, an HTTP API, and a local
web UI. Team/Postgres mode and a user-owned server remain post-MVP.

Detailed, ordered work units and their acceptance bars live in `implementation-plan.md`;
this file is the coarse "what exists" ledger.

## Done
- [x] Trial-package schema -- trial metadata, treatments, RCBD design spec, assessment
      definitions, with fail-loud validation.
- [x] RCBD layout generation -- deterministic by recorded seed; complete-block invariants
      enforced.
- [x] Project config and import profile -- YAML, per-study settings, override merge; the
      analysis section (significance level, mean-comparison test) per the ARM-aligned
      analysis conventions.
- [x] Observation importer -- long and wide CSV, validated against the layout and package,
      missing values recorded as warnings.
- [x] Analysis -- the AOV Means Table: RCBD ANOVA (block / treatment / error), treatment
      means, grand mean, CV, and Fisher's Protected LSD. F and t distributions are native
      (no scipy runtime). Validated against the Yates oats published table and statsmodels.
- [x] Reporting -- a Markdown report with input summary, method and version provenance,
      the reproducibility block (input hash, seed, versions), and per-assessment notes.
- [x] Canonical store -- SQLite via SQLAlchemy (decision 0001, Accepted); portable to
      PostgreSQL. Layout regenerated not stored; float values exact; foreign keys enforced.
- [x] Portable exchange -- JSON (validated, deterministic, archival) and long-format CSV;
      the database and a JSON export agree on the content hash.
- [x] CLI -- the loop end to end: init -> add -> randomize -> import -> report -> export ->
      import-json -> verify, plus list, info, delete.
- [x] Reproduce check -- `verify` round-trips a trial to the same content hash; a trial
      re-imported into a fresh database is identical.
- [x] Worked example -- `examples/yatesOats/` runs the whole loop on the Yates oat trial
      and reproduces its published ANOVA and a known stable input hash; guarded by a test.
- [x] README quickstart -- install and the loop, replacing the definition-phase stub.
- [x] Install smoke on Python 3.13 -- the wheel builds, installs into a clean venv, and
      imports and runs from site-packages outside the source tree; `scripts/bootstrap.sh`
      provisions the 3.13 environment and is idempotent.
- [x] Core facade -- one `Workspace` that every surface calls; the CLI, the API, and the web
      UI reach the core only through it, so no surface can drift from or re-implement the core.
- [x] Public API surface -- `openfurrow/__init__.py` is the compatibility boundary (facade,
      schema types, result types, config, errors); internals stay internal.
- [x] Localization scaffolding (decision 0007) -- keyed per-locale JSON catalogs with a
      translation-status convention, locale-aware number/date formatting, and RTL-capable
      direction handling. Ships en-US and en-GB. Display only: a trial hashes identically in
      every locale.
- [x] HTTP API -- a Flask service, thin controllers over the facade, fail-loud errors mapped
      to status by exception type, optional HTTPS, bounded request bodies. No auth yet.
- [x] `serve` command -- runs the service and web UI locally.
- [x] Analyst web UI -- browse trials, add a trial, view the randomized field layout as a plot
      map, import observations, read the report, verify reproducibility, and delete. Served
      offline with no external assets; localized; RTL layout mirroring verified.
- [x] Field Book file interop (E1) -- export a trial's field and trait files, ingest a Field
      Book database-format export, round-tripping to the same content hash.

## Next
Nothing outstanding from the MVP loop. The next tracks are analysis breadth (below) and
Phase 2 of `implementation-plan.md` (user-owned server, sync, BrAPI subset, RTL locale
delivery).

## Future (recorded, not built)

The long-term goal is a one-stop-shop that bridges the two-tool workflow -- the
protocol/product/label registry and the analysis-and-visualization -- on an open,
portable, owned foundation, with the data portability and configurable privacy the
incumbents lack. See `research/landscape.md`. The tracks below serve that goal; ARM
feature parity is the long-term target, filtered through it. Beyond these tracks, the
project's long-term north star -- a funded, curated public archive for reproducible
studies, as a separate institution that the tool feeds -- is recorded in `vision.md`.

**Analysis breadth**
- [ ] Factorial, split-plot, and multi-environment designs (see `research/test-data.md`).
- [ ] Unbalanced analysis: least-squares adjusted means for ARM parity; Yates missing-plot
      (the decision-0003 successor).
- [ ] Additional mean-comparison tests (Duncan's MRT, Student-Newman-Keuls, Tukey's,
      Waller-Duncan, Dunnett's).

**Registry and organization (decision 0004)**
- [ ] Reusable protocols, a product/label catalog, and a program/project/study/trial
      (+season) hierarchy, so trials are comparable and trackable across trials and years --
      the registry role the incumbent desktop tool actually fills.
- [ ] Cross-trial and across-year summaries built on the registry.

**Analysis and visualization UI**
- [x] Web UI -- the analyst workflow (see Done).
- [ ] Visualization: means with letters/error bars, interaction plots, MET and across-year
      summaries -- reproducible views over validated results, not a new source of truth.

**Interoperability (the bridge)**
- [ ] Import from the incumbent registry and analysis formats (migrate a protocol/product
      history in without re-keying); open export so data is never re-locked. Extends the
      interoperability landscape in `brief.md` section 12.
- [x] Field Book file round-trip (export field/trait files, ingest the collected export).
- [ ] BrAPI v2 server subset (Core + Phenotyping), and live sync with it.
- [ ] Deposit into existing endowed archives (Dryad, Zenodo) and mint DOIs -- a durable
      public home and discovery now, and the near-term first step toward the archive
      north star (`vision.md`).

**Team mode and privacy (decisions 0001, 0005)**
- [ ] Team mode on PostgreSQL.
- [ ] Configurable data privacy / IAM layer: policy-driven restriction enforced at the
      access boundary, an append-only audit log, and a defined interaction with the
      content-hash model (a redacted export is a different, self-labeled document).

**Competitive**
- [ ] ARM parity gap analysis -- research doc under `research/`: inventory ARM's capability
      surface and tag each have / partial / missing, as the parity backlog. Long-term.
