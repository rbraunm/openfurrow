# OpenFurrow implementation plan

**Status: living document, firmer than `platform-plan.md`.** This is the build sequence:
the lanes from `platform-plan.md` broken into ordered, independently-committable work units
with their shape, dependencies, and acceptance bar settled in advance. Its purpose is to
end per-session relitigation of *what to do next and in what shape* -- a session opens this
file, picks the next unit whose dependencies are met, and executes against a bar that is
already agreed.

It decides shape and direction. It does not impose timelines, and it does not close the
genuinely open forks -- those are listed explicitly under "Parked forks" with their ADR
home, so an open question is visible rather than silently re-argued. When building teaches
us the shape was wrong, we change the unit and record why in the commit; git holds the
history.

## How a session uses this

1. **Bootstrap the environment first:** `bash scripts/bootstrap.sh && source .venv/bin/activate`.
   The project targets Python 3.13; a fresh sandbox ships 3.12 and cannot install it. See
   `CLAUDE.md`.
2. Read `CLAUDE.md`, then this file. The ADRs and `platform-plan.md` are the layers above;
   this is where they turn into work.
3. Pick the next unit whose **Depends** are all done (see "Build spine" for the intended
   order). Prefer the spine unless told otherwise.
4. Build it to its **Done when** bar. One logical commit to `claude` per unit; a large unit
   commits per checkpoint within it.
5. Check the unit off in this file in the same commit, and note anything the build changed
   about the plan.

## Relationship to the other roadmap docs

| Doc | Role | Firmness |
|-----|------|----------|
| `decisions/` (ADRs) | *Why* -- the settled forks the code keys off | Firmest (locked = extra sign-off) |
| `platform-plan.md` | *What and in what order*, at the layer/lane level | Intent, moves freely |
| **`implementation-plan.md`** (this) | *The units that build each lane*, with acceptance | Firm shape, revisable per build |
| `milestones.md` | *Done / next* checklist of shipped capability | A ledger of state |

This file does not restate ADRs or the plan; it points to them. Lane letters (A-F) and gate
numbers (A1, B3, ...) are `platform-plan.md`'s; unit IDs here reuse them.

---

## Settled shapes (decided now -- do not relitigate)

These are design-level decisions that do not rise to an ADR (no contested fork with a
license/auditability consequence) but must be fixed so every session builds the same shape.

1. **One core facade.** Every non-core surface (CLI, Flask, future apps) reaches the core
   through a single session-scoped facade object plus the stateless analysis functions --
   never by importing store/schema/analysis internals directly. The facade encapsulates the
   repeated "open store -> load package -> regenerate layout -> load observations -> act"
   dance that the CLI open-codes today. The CLI is refactored onto the facade as the first
   proof; Flask is the second. This is unit A1; its exact class/method names are finalized
   when built, but the *shape* (one facade, surfaces never touch internals) is fixed.

2. **Layout stays derived, never stored.** The randomized layout is regenerated from the
   recorded seed on demand (as it is today). It is not persisted and not hashed separately.
   Any surface that needs it calls the facade, which regenerates it.

3. **One content hash, one implementation.** `schema.contentHash` over the `TrialDocument`
   is the single fixity anchor across export, verify, sync, and deposit. No surface computes
   its own hash. Locale and display never touch it (ADR 0007).

4. **Package authoring is JSON-canonical.** The trial package is authored and edited as
   validated JSON (the `add` path). CLI flags and, later, UI forms are convenience surfaces
   over that canonical form, not a second schema. `transform` and `measurementKind` are
   package fields (already), set in the JSON; surfacing them elsewhere never forks the schema.

5. **Web UI is server-rendered Flask (ADR 0012).** No single-page-app baseline, no niche
   front-end framework. Light JS only where an interaction demands it, served locally so the
   UI works offline.

6. **No hardcoded user-facing strings, from the first UI line.** ADR 0007 is "in force now."
   The keyed-catalog + locale-formatting scaffolding (unit L0) lands **before** any surface
   that emits user-facing text (Flask/web), so we never hardcode-then-retrofit. The analyst
   CLI's operator-facing output is exempt as tooling, but report/document text that a
   researcher reads is not.

7. **Field interop is file-first, then BrAPI (ADR 0013).** The file-based Field Book
   round-trip (E1) ships before any BrAPI server (E2).

8. **Every unit is independently committable with real tests.** No unit lands without
   assertions that could fail, oracle-validated where it produces a number, content hash
   verified where it round-trips. Fail loud, no silent fallbacks. ASCII in code and output.

---

## The build spine

The critical path -- the order that unblocks the most, and the default a session follows
absent other direction. Units off the spine (analysis breadth, later-phase lanes) can run
whenever their dependencies are met.

```
A1 facade  ->  A2 package  ->  L0 localization scaffold  ->  B1 Flask API  ->  B3 serve
   |                                                              |
   +--> E1 Field Book round-trip (parallel; core-only)           +--> D1/D2 web UI  -->  D4
```

**Near-term order (Phase 1):**

1. **A1** -- core facade; refactor the CLI onto it. The keystone; everything above waits on it.
2. **E1** -- file-based Field Book round-trip. Parallelizable (core-only), delivers the first
   field capability, and is the second real consumer that pressure-tests A1's shape.
3. **A2** -- package the core for reuse (stable public import surface).
4. **L0** -- localization scaffolding (gates all user-facing surfaces).
5. **B1** -- Flask app wrapping the facade as the one HTTP API.
6. **B3 + D1/D2** -- serve locally; the analyst web UI for the core workflow.
7. **D4**, CLI polish (transform/measurementKind visibility), E1 hardening.

**Phase 2:** C2/C3/C4 (sync + self-hostable server + CloudFormation), E2 (BrAPI subset),
D3 (localization/RTL delivery), E3 (MIAPPE), B4 (service install), B5 (auth).

**Phase 3:** C5 (Marketplace AMI), E4 (deposit + DOI), F (first-party apps).

---

## Work units

Each unit: **Goal / Deliverable / Touches / Depends / Decisions / Done when.** Check the box
when the Done-when bar is met.

### Foundation

- [x] **L0 -- Localization scaffolding** (done)
  - **Goal:** honor ADR 0007 before any user-facing surface exists, so strings are never
    hardcoded then retrofitted.
  - **Deliverable:** `openfurrow/i18n/` -- keyed JSON message catalogs (UTF-8, per locale,
    each string carrying a `source` / `machineDraft` / `humanApproved` status), a `Translator`
    that resolves text and formats numbers/dates, and a locale formatting boundary. Shipped
    locales: `en-US` (source) and `en-GB` (spelling overlay, human-approved). `report.py` is
    fully routed: Markdown structure stays in code, every researcher-facing string comes from
    the catalog, every number through the translator. `--locale` on the CLI `report` command;
    `locale` on `Workspace.buildReport`. Catalogs ship as package data.
  - **Decisions:** *settled at build* -- **no new runtime dependency.** ADR 0007 requires
    CLDR-backed formatting but explicitly defers the i18n library to the GUI-stack choice, so
    L0 does not pick one: `LocaleFormat` is the seam a CLDR-backed implementation (Babel/ICU)
    drops into, behind a deliberately small interim locale table. Everything fails loud --
    unknown locale, missing key, placeholder mismatch -- with **no fallback to English**, since
    a half-translated locale quietly rendering the source language is exactly the invisible
    wrongness the project refuses. A locale is complete or it is not shipped.
  - **Done when:** met -- 267 tests. The canonical guardrail is asserted directly: the content
    hash (and the hash printed inside the report) is identical across locales, and the CSV/JSON
    exchange stays dot-decimal and locale-neutral even after a comma-decimal locale formats
    display. Catalog completeness and cross-locale placeholder parity are enforced, every
    shipped locale is authoritative, and the wheel actually carries the catalogs (it did not at
    first -- a source checkout passed while an installed OpenFurrow would have built no report
    at all).
  - **Remaining (follow-on, not blocking):** the analysis layer still emits diagnostic `name`
    and `interpretation` sentences as English literals; `report.py` formats the numbers around
    them but passes the prose through. Routing generated analysis sentences through the catalog
    is its own unit. The interim locale table must not grow -- adding locales beyond those
    shipped is the signal the real CLDR mechanism is overdue.

### Lane A -- Core and packaging

- [x] **A1 -- Core facade** (done)
  - **Goal:** collapse the scattered free-function surface into one facade every surface calls.
  - **Deliverable:** `openfurrow/workspace.py` -- a `Workspace` exposing the trial loop as
    methods: `create`/`open`; `addPackage`; `listTrials`; `loadPackage`/`loadObservations`;
    `layoutFor`; `importObservations`; `analyze`; `separateMeans`; `assessAssumptions`;
    `buildReport`; `contentHashFor`; `exportDocument`/`exportObservationsCsv`;
    `importDocument`; `verifyRoundTrip`; `deleteTrial`. The core error types are re-exported
    from the facade so surfaces catch them there. The CLI now imports only the facade plus the
    public `TrialPackage`/config. Analysis primitives stay stateless, called by the facade.
  - **Touches:** new `openfurrow/workspace.py`; `cli/main.py` (refactored onto it);
    `tests/testWorkspace.py`.
  - **Decisions:** *settled at build* -- facade class is `Workspace`; **engine-held,
    session-per-method** (the engine is the poolable resource a long-running service reuses;
    the session is the per-call transaction, matching one CLI command / one HTTP request);
    path-based methods only where a portable file is moved, `addPackage` takes the domain
    object. Plus the shape-decisions #1/#2/#3.
  - **Done when:** met -- CLI drives the full loop through the facade only; 234 tests green
    (217 prior + 17 facade); facade tests assert each operation end to end and cross-check the
    composite ops against the primitives; no CLI command imports a store/analysis internal.

- [x] **A2 -- Package the core for reuse** (done)
  - **Goal:** a stable, installable public surface other surfaces import.
  - **Deliverable:** `openfurrow/__init__.py` is now the explicit public API and the
    compatibility boundary: the `Workspace` facade, the schema types, the result types
    (`AnovaResult`, `MeanSeparation`, `Assumptions`, `ImportResult`), the config that
    parameterizes import/analysis, and the error types -- 42 names in `__all__`. The store,
    randomizer, exchange writers, report builder, observation importer, Field Book writers,
    and the analysis primitives stay internal, reached only through the facade. A new leaf
    `openfurrow/version.py` holds `schemaVersion` so internals never import the package root.
  - **Touches:** `openfurrow/__init__.py`; new `openfurrow/version.py`; `reports/report.py`
    (imports the version from the leaf); `tests/testPublicApi.py`.
  - **Depends:** A1.
  - **Decisions:** *settled* -- public surface = facade + schema + result types + config +
    errors. Config is public because `Workspace.importObservations` takes an `ImportProfile`.
    Analysis primitives are internal: the numbers a caller sees must come from the one
    validated path. *Open* -- deployment shape stays open per ADR 0010 (A3).
  - **Done when:** met -- `tests/testPublicApi.py` drives the full loop (author, layout,
    import, analyze, separate, assess, report, export, verify, Field Book, delete) importing
    only from `openfurrow`, and pins both what is exported and what is deliberately not.
    Install smoke passes on 3.13: the wheel builds, installs into a clean venv, and imports
    from site-packages outside the source tree with the console script working.

- [ ] **A3 -- Keep deployment shapes open** -- a standing stance (ADR 0010), not a build.
  Honor it: do not hardwire a single packaging/deployment assumption into A1/A2/B1.

### Lane E -- Field interop

- [x] **E1 -- File-based Field Book round-trip** (done)
  - **Goal:** first field capability with no server -- export a trial for Field Book, ingest
    what comes back.
  - **Deliverable, shipped in two checkpoints:**
    - **E1a export:** `openfurrow/interop/fieldbook.py` writers -- `writeFieldImport` (field CSV:
      plotNumber/block/positionInBlock/treatment) and `writeTraitFile` (legacy quoted `.trt`,
      trait name = assessment code; numeric -> numeric with unit/bounds, ordinal/categorical ->
      categorical with slash-joined values); forbidden field headers fail loud. Facade:
      `Workspace.exportFieldBook`.
    - **E1b ingest:** `fieldBookImportProfile` + `Workspace.importFieldBook` -- reuses the
      standard long importer with the Field Book mapping (unique-id -> plot, `trait` ->
      assessmentCode, `value` -> value; provenance columns ignored).
  - **Touches:** a new `openfurrow/interop/fieldbook.py` (or similar); reuse
    `importers/observations.py`, `exchange.py`; tests + fixtures.
  - **Depends:** the core (A1 preferred so it rides the facade, but E1 can start against the
    current functions and move onto the facade when A1 lands).
  - **Decisions:** *settled* -- file-first (shape #7), reuse the importer not a parallel path;
    **formats are pinned in `roadmap/research/fieldbook-formats.md`** against Field Book 5.4 /
    current source (field-import CSV; legacy `.trt`; database long export). Ingest the database
    (long) export, map unique-id -> plotNumber, `trait` -> assessmentCode, `value` -> value.
    Field Book is GPL-2.0, so committed fixtures are OpenFurrow-authored files conforming to
    the format, not vendored Field Book samples. *Open* -- whether to emit plot row/column
    geometry now or defer; how to carry the export's provenance columns (timestamp/person/etc.)
    on ingest.
  - **Done when:** met -- a trial exports to Field Book field + `.trt` files (structure
    asserted); a conformant database-format fixture ingests to the exact expected observations;
    and a full round-trip (observations out to a Field Book export and back into a fresh store)
    reproduces the same content hash. Fixture is OpenFurrow-authored, registered in
    `tests/fixtures/README.md`. 246 tests (243 prior + 3 ingest; +9 export landed in E1a).

- [ ] **E2 -- Scoped BrAPI v2 server subset** (Phase 2) -- Core studies/trials/programs/
  locations + Phenotyping variables/units/observations, read+write. Depends: B1, and C for
  live sync. Governed by ADR 0013.
- [ ] **E3 -- MIAPPE 1.1 export** (Phase 2). Depends: the data model being stable.
- [ ] **E4 -- Deposit + DOI** (Phase 3) -- Dryad/Zenodo deposit, content hash as fixity.

### Lane B -- Service and entry points

- [x] **B1 -- Flask app wrapping the facade as the one HTTP API** (done)
  - **Goal:** the single HTTP interface behind every non-CLI surface.
  - **Deliverable:** `openfurrow/service/` -- `createApp(databasePath, config)` returns a Flask
    app whose controllers call one `Workspace` method and serialize the result: trials
    (list/add/get/delete), layout, observations (CSV body, plus a Field Book endpoint),
    analysis/means/assumptions, report (`?locale=`), hash, verify, document export/import,
    health. `runner.py` holds the bind/TLS layer, separate so the app is testable without a
    socket. Flask is an optional `service` extra, not a core dependency (A3).
  - **Decisions:** *settled at build* -- **errors map by exception type, never by message
    text.** That forced a correction in the store: `StoreError` was raised for both "not
    found" and "already exists", so it now has `TrialNotFoundError` (404) and
    `TrialExistsError` (409) subclasses; anything else store-related is 400. **HTTPS is
    optional config** (`service.tls.enabled` + `certificateFile`/`privateKeyFile`), off by
    default because the first target is a local single-user tool on loopback; it fails loud if
    enabled without a usable certificate rather than silently degrading to HTTP. Default bind
    is loopback so a local tool cannot become a network service by accident.
    **Let's Encrypt / ACME is deliberately not implemented** -- it needs a public DNS name,
    inbound reachability, and a renewal daemon, none of which a local or LAN deployment has;
    it belongs with the internet-facing self-hostable server (C3/C4), and this shape does not
    block it, since an ACME-obtained certificate is just a cert/key pair pointed at by the
    same two settings. Auth remains deferred to B5 / ADR 0005: this app must not be exposed to
    a network until then.
  - **Done when:** met -- 284 tests. The full loop runs over HTTP; analysis, means,
    assumptions, and the report are asserted identical to the facade's own output (proving the
    controllers compute nothing); the status mapping is asserted per error type; the report's
    `?locale=` is proven display-only against the content hash; and TLS is proven off by
    default, rejected at construction when enabled without a certificate, and fail-loud when a
    certificate file is missing.

- [x] **B2 -- Web-GUI entry point** (done, with D1) -- the server-rendered UI blueprint
  (`openfurrow/service/web.py`, templates, one local stylesheet) registered by `createApp`, with
  a request-scoped `Translator`, `?locale=` selection, and `lang`/`dir` set from the locale.
- [x] **B3 -- `serve` command** (done) -- `openfurrow serve <db> [--config --host --port]`
  builds the app via `createApp` and binds through `runService`; `--host/--port` override the
  config. The service extra is imported inside the handler so every other command works without
  Flask and `serve` gives a clear "install openfurrow[service]" hint instead of an opaque
  ImportError. `Workspace.open` fails loud on a missing database before binding. Tested with a
  real server started in a thread answering `/health` on an ephemeral port (a genuine bind,
  which a test client cannot show). Depends: B1.
- [ ] **B4 -- Cross-OS service install/uninstall** (Phase 2) -- Windows service via
  PowerShell 5.1, systemd on Linux, launchd on macOS. Depends: B3.
- [ ] **B5 -- Auth + session scaffolding** (Phase 2) -- arrives with service mode; ties ADR 0005.

### Lane D -- Analyst web UI

- [x] **D1 -- Design + randomize** (done) -- server-rendered pages to list trials, add a trial,
  and view the randomized field layout. **Scope call (shape #4):** "author" is submit/upload the
  canonical package JSON (the add form is seeded with an editable example); a field-by-field
  design form is a later unit. The randomized layout renders as a field plot map -- blocks as
  bands, plots as mono-coded cells, treatments as an Okabe-Ito colorblind-safe *redundant* cue
  beside the always-present code, with the seed and content hash shown as provenance. Views are
  thin over the facade (no store/analysis access). Localized through L0 with the display-only
  guardrail asserted (locale never changes the hash); RTL mirroring verified empirically by
  forcing `dir=rtl` (logical-property CSS, ADR 0007). Offline: all assets local, asserted by a
  no-external-reference test; templates and CSS ship as package data. Depends: B1, B2, L0.
- [x] **D2 -- Import + analyze + report** (done) -- the trial page gains an import section
  (CSV upload, OpenFurrow or Field Book format, selected by the facade method) that shows the
  imported count and any warnings and fails loud on bad data without losing the page; the report
  page renders `Workspace.buildReport`'s Markdown to HTML (the `markdown` library, `tables`
  extension, a service extra) so the AOV Means Table is a real HTML table, localized via
  `?locale=`, with a link to download the raw Markdown from the API. The report view is
  display-only -- opening it in any locale leaves the content hash unchanged (asserted). The
  "View report" link appears only once observations exist. Depends: D1.
- [ ] **D3 -- Localization + RTL delivery** (Phase 2) -- message catalogs wired, CLDR
  formatting, bidirectional layout, reviewed locale packs. Depends: D2, L0, ADR 0007.
- [x] **D4 -- Browse + manage trials** (done) -- the index browses trials; the trial page gains
  a manage section with an in-browser reproducibility check (`verifyRoundTrip`, read-only GET,
  shows pass/fail and the hash without changing the trial) and delete. Deletion is safe: the GET
  is a confirmation page and only a POST deletes, so a crawler, prefetch, or accidental
  link-follow cannot destroy data; both fail loud (404) on an unknown trial. Depends: D2.

### Lane C -- Storage, sync, self-hostable server

- [ ] **C1 -- Local-first floor** -- already true (SQLite + file, offline, owned). Honor it;
  do not regress it in any later unit.
- [ ] **C2 -- Sync model** (Phase 2) -- how trials/observations move device/analyst <-> server;
  content hash as the free fixity check. *Open fork:* the sync mechanism (ADR 0011).
- [ ] **C3 -- Self-hostable server** (Phase 2) -- Flask in server mode, multi-user, with the
  ADR 0005 privacy/access/audit/encryption features. Depends: B1, B5, ADR 0005.
- [ ] **C4 -- CloudFormation template** (Phase 2) -- launch in the user's own account, data
  stays theirs. Depends: C3.
- [ ] **C5 -- AWS Marketplace AMI** (Phase 3) -- free, for discoverability; support/patch/scan
  obligations. *Open fork:* Marketplace-vs-CFN timing (ADR 0011).

### Lane F -- First-party apps (Phase 3)

- [ ] **F1 -- App strategy + framework** -- *open fork:* cross-platform vs native (ADR 0014).
- [ ] **F2 -- Offline collection app** against a trial's plot map. Depends: F1.
- [ ] **F3 -- Sync to the user-owned server** via the API or BrAPI. Depends: C3, E2.
- [ ] **F4 -- App-store presence** (Apple App Store, Google Play).
- [ ] **F5 -- Differentiated agronomy/efficacy collection workflow.**

### CLI polish (small, standalone)

- [x] **Surface `transform` / `measurementKind` in the CLI** (done)
  - **Goal:** close the flagged gap that these are only settable/visible by editing trial JSON.
  - **Deliverable:** `info` now prints each assessment on its own line with dataType, unit,
    numeric range, `transform`, and `measurementKind` (shown even at their defaults, so the
    current setting is visible), and allowed values for categorical/ordinal; the `add` help
    documents the fields. They stay package-JSON fields (shape #4); no parallel setter.
  - **Uncovered and fixed a real bug:** the store's `AssessmentRow` had no columns for
    `transform` or `measurementKind`, so both were silently dropped on save and reloaded as
    `none`/`unspecified`. A trial with a declared transform, once persisted (always -- every
    surface persists then reloads), would run its analysis on the untransformed scale
    silently. Added the columns and the save/load mapping; regression-tested at the store
    level (a non-default transform survives a round-trip) and behaviorally (the persisted
    transform reaches `analyze`). The default round-trip test had missed it by using defaults
    on both sides.
  - **Done when:** met -- `info` reports transform and kind for every assessment (tested), and
    the store persists them (tested). 327 tests.
  - **Follow-on guard (done):** `tests/testPersistenceCompleteness.py` prevents the whole class
    -- a *maximal* package (every optional field non-default) must survive the store and the
    JSON exchange exactly, and transform, measurementKind, treatment rate, and numeric bounds
    must each change the content hash. A field not exercised there is a field that can be
    silently lost, so adding a schema field means extending that test.

### Analysis breadth (independent side-track, Phase 0 continuing)

Slot any of these in when useful; they do not compete with the spine and depend only on the
core. Each is oracle-validated against `research/test-data.md`.

- [ ] Factorial designs; then split-plot; then multi-environment.
- [ ] Additional mean-comparison tests (Duncan's, SNK, Tukey's, Waller-Duncan, Dunnett's).
- [ ] Transform offsets slice (log(y+c), empirical logit, the count-denominator question) --
      the deferred part of ADR 0006.
- [ ] Bartlett's test (needs a native incomplete gamma).
- [ ] Unbalanced analysis: least-squares adjusted means (ARM parity) and the Yates
      missing-plot successor to ADR 0003.
- [ ] GLMs (Poisson / negative-binomial / binomial) -- a separate future track (ADR 0006).

---

## Parked forks (open on purpose)

Genuinely open decisions, left open with their home. A session does not resolve these ad hoc;
raise them for a talk-first decision when a unit forces the choice.

| Fork | Home | Forced by |
|------|------|-----------|
| Core deployment/packaging shape (library / embedded / on-device) | ADR 0010, unit A3 | never (kept open) |
| Sync mechanism | ADR 0011, unit C2 | C2 |
| Mobile framework (cross-platform vs native) | ADR 0014, unit F1 | F1 |
| Marketplace-vs-CloudFormation timing | ADR 0011, unit C5 | C5 |
| Partner validation timing for the ADR 0008 audience | ADR 0008 | before heavy audience-specific build |
| Plot geometry (row/column) now vs later; how to carry export provenance columns on ingest | unit E1 | E1 build |
| Auth/session model specifics | ADR 0005, unit B5 | B5 |

---

## Definition of done (every unit)

- Fails loud; no silent fallbacks, no second-strategy paths.
- Tests make real assertions that could fail; oracle-validated where a number is produced;
  no monkeypatching the logic under test.
- Content hash intact and verified where the unit round-trips or exchanges data.
- ASCII in code and generated output; user-facing strings routed through L0 once it exists.
- Layout stays derived; internals stay behind the facade.
- One logical commit to `claude`, human-style message; this file's checkbox updated in the
  same commit.
