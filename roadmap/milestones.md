# Milestones

The MVP is the thinnest reproducible loop: define a trial, randomize it, import
observations, analyze, report, and export a portable package that re-imports and
reproduces. CLI-first; web UI and team/Postgres mode are post-MVP.

## Done
- [x] Trial-package schema -- trial metadata, treatments, RCBD design spec, assessment
      definitions, with fail-loud validation.
- [x] RCBD layout generation -- deterministic by recorded seed; complete-block invariants
      enforced.
- [x] Project config and import profile -- YAML, per-study settings, override merge.
- [x] Observation importer -- long and wide CSV, validated against the layout and package,
      missing values recorded as warnings.

## Next
- [ ] Analysis -- the AOV Means Table: RCBD ANOVA (block / treatment / error), treatment
      means, grand mean, CV, and Fisher's Protected LSD. Validated against the Yates oats
      published table and statsmodels.
- [ ] Reporting -- a Markdown report with input summary, method and version provenance,
      the reproducibility block (input hash, seed, versions), and warnings.
- [ ] Canonical store -- SQLite via SQLAlchemy; the trial package as a portable file with
      a manifest (checksums, schema version).
- [ ] CLI -- the loop end to end: validate -> randomize -> import -> analyze -> report ->
      export -> re-import.
- [ ] Portable package and reproduce check -- export, re-import, reproduce deterministically.

## Future (recorded, not built)
- [ ] Factorial, split-plot, and multi-environment designs (see `research/test-data.md`).
- [ ] Unbalanced analysis: least-squares adjusted means for ARM parity; Yates missing-plot.
- [ ] Additional mean-comparison tests (Duncan's MRT, Student-Newman-Keuls, Tukey's,
      Waller-Duncan, Dunnett's).
- [ ] Web UI; team mode on PostgreSQL.
