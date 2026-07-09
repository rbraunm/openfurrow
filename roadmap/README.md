# OpenFurrow Roadmap

Planning workspace for taking `brief.md` from a definition-phase brief to working code.
This folder holds the research gathered from the field and the existing tools, the design
decisions, and the milestone trail. Nothing in `roadmap/` is load-bearing at runtime.

## How this folder is used

- `milestones.md` -- the build, as a tracked checklist: what is done and what is next.
- `platform-plan.md` -- the living master plan: the field-to-analysis platform's end-goal
  shape, five layers, and phased lanes (engine, service, storage/sync, web UI, field
  interop, first-party apps). Direction and intent, not a contract.
- `implementation-plan.md` -- the build sequence: each lane broken into ordered,
  independently-committable work units with settled shape, dependencies, and an acceptance
  bar, so a session picks the next unit and executes without relitigating direction. Firmer
  than `platform-plan.md`, revisable per build.
- `decisions/` -- short decision records (ADRs). `decisions/README.md` defines the process
  and holds the records: the SQLite-canonical store, native-analysis-with-oracles, and the
  missing-data policy (accepted), plus the registry/hierarchy and privacy/IAM layer
  (proposed, long-term) -- with a note of the choices recorded elsewhere (scope, the import
  model, the analysis conventions) that were not real forks and so are not ADRs.
- `research/` -- findings gathered by exercising the field and the tools, not by
  assumption: how ARM, BrAPI, and Field Book actually work; the market structure and the
  bridge opportunity (`research/landscape.md`); the reproducibility and data-availability
  evidence base (`research/reproducibility-and-data-availability.md`); the global-South
  audience landscape and where the tool fits (`research/global-south-audience.md`); the
  platform and interoperability grounding (`research/platform-and-interop.md`); and the
  test-data registry (`research/test-data.md`) of sourced, provenanced datasets and
  what each validates; and the Field Book interop format spec
  (`research/fieldbook-formats.md`) pinning the import/trait/export layouts unit E1 targets.
- `vision.md` -- the long-term north star: a funded, curated public archive for
  reproducible studies, a separate institution from the tool. Aspirational, not on the
  build path.

## Build order

```
research + field study -> decisions -> schema -> design -> import -> analysis -> reports -> store -> CLI
```

Each step validates the one before it. No analysis code is written until the oracles it
must agree with are pinned and the known-answer data it validates against is sourced
(`research/test-data.md`). The existing tools (ARM, statsmodels, agricolae) and published
tables are the gold masters until OpenFurrow reproduces them.

## Current state

The v0.1 MVP is complete: schema, RCBD layout, config (with the analysis section), the
observation importer, the analysis layer (the AOV Means Table -- ANOVA, treatment means,
Protected LSD, CV, validated against the Yates oats published table and statsmodels),
reporting, the SQLite canonical store, portable JSON/CSV exchange, and the CLI loop
(`init -> add -> randomize -> import -> report -> export -> import-json -> verify`), with a
worked example under `examples/`. See `milestones.md` for the full checklist.

Direction beyond the MVP is set by `research/landscape.md`: field practice splits the trial
workflow across a registry tool (protocols, product IDs, labels, cross-year tracking) and a
separate cloud analysis/visualization suite, neither easily portable. OpenFurrow's goal is
to bridge both layers on an open, portable, owned foundation, with configurable privacy the
incumbents lack. The future tracks in `milestones.md` -- registry (decision 0004),
visualization, interoperability, and the privacy/IAM layer (decision 0005) -- serve that
goal.

## Graduation

Artifacts mature here, then move to their permanent home: research feeds the code (and the
design brief), schema fixtures live alongside the code that consumes them. The roadmap
keeps the planning trail; the repo keeps the result.
