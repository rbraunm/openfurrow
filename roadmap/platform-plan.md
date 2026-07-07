# OpenFurrow platform plan

**Status: living document.** This plan exists to drive the work forward and give us a
shared high-level direction, so we stop deriving the next step ad hoc. It is intent and
sequence, not a contract: phases and lanes describe direction and dependency order, not
deadlines or scope limits. When building teaches us something, the plan changes. It sets
direction; it does not impose artificial limits. Same greenfield spirit as `../CLAUDE.md`
-- no premature constraints, and we rebuild the plan when that is the right call. The
decision records in `decisions/` are firmer than this plan by design; this plan can move
freely above that stable-but-not-frozen decision layer, and git holds the history of
both. No timelines or effort estimates appear here on purpose: this maps *what* and *in
what order*, not *how long*.

## Purpose

The engine has a thorough spine -- ADRs 0001 through 0008 -- but the product architecture
from "Python analysis library plus CLI" to "field utility with apps" was never written
down; the layers above the library were only gestured at as "GUI-era." This document is
that architecture and its sequencing.

## End-goal shape

A local-first, reproducible field-to-analysis platform for agronomy, efficacy, and
variety-evaluation trials (the wedge in ADR 0008 -- not breeding-pipeline management).
One bundled application with multiple entry points; you own your data by default
(offline, a local file); optional user-owned collaboration for teams; interoperation with
the existing field-collection ecosystem now, and first-party mobile apps as a committed
goal.

## The five layers

1. **Core** -- the validated engine; the single source of truth for the statistics
   (ADRs 0001-0008). Its packaging shape (importable library, embedded in the service,
   runnable on-device via native Python) is deliberately left open.
2. **Service / API** -- a Flask application that exposes the core over HTTP; the one API
   behind every other surface, so the math is implemented once.
3. **Storage and sync** -- a local file (and SQLite) as the floor, fully offline and
   owned; an optional, user-owned self-hostable server for team collaboration.
4. **Analyst web UI** -- design trials, randomize, import data, run analysis, read
   reports; the surface where localization and right-to-left support (ADR 0007) land.
5. **Field collection** -- offline data entry: interop with Field Book and BrAPI first,
   first-party iOS/Android apps as a committed north-star build.

## Cross-cutting invariants

Threaded through every lane, not owned by any one:

- **Reproducibility** -- deterministic seeds and content-hashed inputs everywhere;
  locale and display never touch the canonical form or the hash (ADR 0007).
- **Localization and RTL** (ADR 0007) -- readiness now; delivery when the UI exists;
  locales produced by an LLM-assisted, human/partner-reviewed pipeline, none authoritative
  until reviewed.
- **Privacy and sovereignty** (ADR 0005) -- configurable privacy; CARE alongside FAIR on
  community-facing surfaces; data owned by the user.
- **Interoperability** -- a BrAPI v2 subset, MIAPPE metadata, deposit and DOIs, and
  Field Book file and BrAPI exchange (see `research/platform-and-interop.md`).

## Current state

The engine exists and is validated: the trial-package schema, RCBD ANOVA, Fisher's
Protected LSD, assumption diagnostics (ADR 0006 Slice 1), variance-stabilizing transforms
(Slice 2), the SQLite store, JSON/CSV exchange, the CLI, and content hashing, all under
ADRs 0001-0008. Everything above the library and CLI -- the service, the web UI, sync and
the server, field collection, and the apps -- is still to be built.

## Lanes

Each lane runs from the current state toward its target. Gates are ordered by dependency,
not by size, and any lane can run ahead of or behind the others.

### Lane A -- Core and packaging
- **Arc:** from an importable Python library to a stable, versioned core API that every
  surface calls, with the deployment shape kept open.
- **Gates:** (A1) settle a stable internal core API -- the operations surfaces will call
  (build and validate a package, generate a layout, import observations, analyze,
  separate means, assess assumptions, build a report, exchange, hash); (A2) package the
  core so other surfaces install and reuse it; (A3) keep the deployment shapes (library,
  service-embedded, on-device) open and choose per surface as needed.
- **Depends on:** nothing new.
- **Governed by:** the core-packaging ADR; invariant from ADR 0002.

### Lane B -- Service and entry points
- **Arc:** from CLI-only to one bundled application with a CLI entry point and a Flask
  web/API entry point, runnable directly or installable as an OS service (a personal
  local GUI or a private server).
- **Gates:** (B1) a Flask app wrapping the core as an HTTP API -- the one API behind web,
  mobile, and the server; (B2) a web-GUI entry point served by or consuming that API,
  bundled with the app but a separate entry point from the CLI; (B3) a run command to
  serve the web app locally; (B4) cross-OS service install and uninstall (a Windows
  service via PowerShell 5.1, a systemd unit on Linux, a launchd agent on macOS) so a
  user can stand up their own local GUI or private server; (B5) authentication and
  session scaffolding, needed once it runs as a service (ties to ADR 0005).
- **Depends on:** Lane A.
- **Governed by:** the service/API ADR (which also covers entry points and service
  install); the web UI stack ADR.

### Lane C -- Storage, sync, and the self-hostable server
- **Arc:** from a single-user local file and SQLite to an optional, user-owned
  collaboration server with hosting, security, and encryption, shippable as a
  CloudFormation template first and a free AWS Marketplace AMI later.
- **Gates:** (C1) local-first stays the floor -- file exchange and SQLite, fully offline;
  (C2) a sync model for how trials and observations move between a device or analyst and a
  server; (C3) the self-hostable server -- the Flask service in server mode, multi-user,
  with the ADR 0005 privacy, access-control, audit, and encryption features; (C4) a
  CloudFormation template a user launches in their own account, keeping data theirs; (C5)
  a free AWS Marketplace AMI later, for discoverability.
- **Depends on:** Lane B; ADR 0005.
- **Governed by:** the storage/sync-and-server ADR; evolves ADR 0001; realizes ADR 0005.

### Lane D -- Analyst web UI
- **Arc:** from no UI to a web interface for the full analyst workflow, localized and
  RTL-capable.
- **Gates:** (D1) design a trial and randomize it; (D2) import observations, run the
  analysis, and read the report; (D3) localization and RTL wiring per ADR 0007 -- message
  catalogs, locale-aware formatting, bidirectional layout, and the reviewed locale packs;
  (D4) browse and manage trials -- list, open, and verify the content hash.
- **Depends on:** Lane B; ADR 0007.
- **Governed by:** the web UI stack ADR; realizes ADR 0007.

### Lane E -- Field interop
- **Arc:** from no field capability to field-capable through the existing ecosystem:
  file-based Field Book exchange first, a scoped BrAPI server next, MIAPPE metadata, and
  deposit with DOIs.
- **Gates:** (E1) a file-based Field Book round-trip -- export a layout file and a trait
  file, ingest the collected CSV -- offline, no server; (E2) a scoped BrAPI server subset
  (Core studies, trials, programs, locations plus Phenotyping observation variables,
  observation units, and observations) so Field Book and other BrAPI tools sync live;
  (E3) MIAPPE-conformant export; (E4) deposit into endowed archives and mint DOIs -- the
  interoperability step toward the archive north star in `vision.md`.
- **Depends on:** Lane B (for the BrAPI server) and Lane C (for live sync); E1 depends
  only on the core.
- **Governed by:** the interoperability ADR; realizes the interoperability track in
  `milestones.md` and the near-term deposit step in `vision.md`.

### Lane F -- First-party apps
- **Arc:** from interop-only to first-party iOS and Android offline-collection apps that
  sync to the user's own server -- filling the iOS gap Field Book leaves and offering a
  differentiated agronomy and efficacy workflow. A committed north-star lane in the
  user-interop direction, not a parked idea.
- **Gates:** (F1) the app strategy and framework decision (cross-platform or native);
  (F2) an offline field-collection app working against a trial's plot map; (F3) sync to
  the user-owned server through the API or BrAPI; (F4) app-store presence on the Apple
  App Store and Google Play; (F5) the agronomy and efficacy workflow that differentiates
  it from Field Book.
- **Depends on:** Lane B, Lane C, and the interop patterns from Lane E.
- **Governed by:** the mobile strategy ADR.

## Phases

Phases are capability bands across the lanes -- a shared sense of the overall arc, not
deadlines. Lanes can run ahead or behind, and reality reorders these as we learn.

- **Phase 0 -- Engine** (done and continuing): the validated core and CLI, ADRs
  0001-0008. Analysis breadth (factorial and other designs) continues here as needed.
- **Phase 1 -- A local analyst tool with a face:** a stable core API (A1-A2), the Flask
  service with web-GUI and CLI entry points and local service install (B1-B4), the
  analyst web UI for the core workflow (D1-D2), and a file-based Field Book round-trip
  (E1). A person can design, collect via Field Book files, analyze, and read a report --
  locally, owning their data, through a GUI. The first field-capable bar, via interop.
- **Phase 2 -- Owned collaboration and live field sync:** the self-hostable user-owned
  server and its CloudFormation template (C2-C4), a scoped BrAPI server (E2),
  localization and RTL in the UI (D3), and MIAPPE export (E3). A small team runs its own
  server, syncs Field Book live, works in its own language, and exports interoperable
  metadata.
- **Phase 3 -- Reach and permanence:** the AWS Marketplace AMI (C5), deposit with DOIs
  (E4), and first-party apps (F). Easy self-host, durable public deposit, and first-party
  mobile collection -- the north-star shape.

## How the existing decisions slot in

- ADR 0001 (SQLite canonical store) -- the Lane C local floor.
- ADR 0002 (own the math; oracles validate) -- the Lane A invariant.
- ADR 0003 (reject missing data) -- core behavior.
- ADR 0004 (registry and hierarchy) -- informs the data model as it grows.
- ADR 0005 (configurable privacy / IAM) -- the Lane C server and team mode.
- ADR 0006 (diagnostics and transforms) -- core analysis.
- ADR 0007 (localization-ready architecture) -- delivered in Lane D.
- ADR 0008 (primary early audience) -- the lens over every lane (the agronomy wedge, the
  global-South audience, partner-gated before heavy build).

## New decisions this plan needs

Written as the next artifact (each a clean, current-state ADR):

- **Service / API and entry points** -- Flask, the one API behind all surfaces, the CLI
  and web-GUI entry points, and cross-OS service install (PowerShell 5.1 on Windows).
- **Core packaging shape** -- library versus service-embedded versus on-device, kept open.
- **Storage, sync, and the self-hostable server** -- local-first floor, the sync model,
  CloudFormation-first then Marketplace-AMI-later, encryption; realizes ADR 0005.
- **Interoperability** -- the BrAPI v2 subset, MIAPPE, Field Book file and BrAPI exchange,
  and deposit with DOIs.
- **Web UI stack** -- how the UI is served and built.
- **Mobile strategy** -- interop-first, first-party apps as the committed lane; framework
  decision.

## Open questions, to settle as we build

- Whether the web UI is served by Flask (server-rendered) or is a separate front end
  consuming the Flask API (settled in the web UI ADR; current lean: one Flask app serving
  an API the UI consumes, so the same API backs web, mobile, and the server).
- The sync mechanism for Lane C.
- The mobile framework for Lane F.
- Marketplace-versus-CloudFormation timing in Lane C.
- When to validate the ADR 0008 audience with a partner.
- The core's packaging and deployment shape (Lane A).
