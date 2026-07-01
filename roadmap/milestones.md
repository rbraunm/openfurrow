# Milestones

The MVP is the thinnest reproducible loop: define a trial, randomize it, import
observations, analyze, report, and export a portable package that re-imports and
reproduces. CLI-first; web UI and team/Postgres mode are post-MVP.

## Done
- [x] Trial-package schema -- trial metadata, treatments, RCBD design spec, assessment
      definitions, with fail-loud validation.
- [x] RCBD layout generation -- deterministic by recorded seed; complete-block invariants
      enforced.
- [x] Project config and import profile -- YAML, per-study settings, override merge; the
      analysis section (significance level, mean-comparison test) per decision 0009.
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

## Next
- [ ] Packaging polish -- installable console script verified end to end; a worked example
      project (design JSON + observations CSV) under `examples/`.

## Future (recorded, not built)
- [ ] Factorial, split-plot, and multi-environment designs (see `research/test-data.md`).
- [ ] Unbalanced analysis: least-squares adjusted means for ARM parity; Yates missing-plot.
- [ ] Additional mean-comparison tests (Duncan's MRT, Student-Newman-Keuls, Tukey's,
      Waller-Duncan, Dunnett's).
- [ ] Web UI; team mode on PostgreSQL.
