# OpenFurrow Roadmap

Planning workspace for taking `brief.md` from a definition-phase brief to working code.
This folder holds the research gathered from the field and the existing tools, the design
decisions, and the milestone trail. Nothing in `roadmap/` is load-bearing at runtime.

## How this folder is used

- `milestones.md` -- the MVP build, as a tracked checklist: what is done and what is next.
- `decisions/` -- short decision records (ADRs). `decisions/README.md` defines the process
  and indexes the decisions made so far: storage, the reproducibility policy,
  native-analysis-with-oracles, scope, the missing-data policy, the import model, and the
  field-aligned analysis conventions.
- `research/` -- findings gathered by exercising the field and the tools, not by
  assumption: how ARM, BrAPI, and Field Book actually work, and the test-data registry
  (`research/test-data.md`) of sourced, provenanced datasets and what each validates.

## Build order

```
research + field study -> decisions -> schema -> design -> import -> analysis -> reports -> store -> CLI
```

Each step validates the one before it. No analysis code is written until the oracles it
must agree with are pinned and the known-answer data it validates against is sourced
(`research/test-data.md`). The existing tools (ARM, statsmodels, agricolae) and published
tables are the gold masters until OpenFurrow reproduces them.

## Current state

Done: the trial-package schema, the RCBD layout generator (reproducible by seed), the
project config and import profile, and the observation importer (long and wide). Next: the
analysis layer -- the AOV Means Table (ANOVA, treatment means, Protected LSD, CV) --
validated against the Yates oats published table and statsmodels.

## Graduation

Artifacts mature here, then move to their permanent home: research feeds the code (and the
design brief), schema fixtures live alongside the code that consumes them. The roadmap
keeps the planning trail; the repo keeps the result.
