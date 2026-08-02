# OpenFurrow

Open, reproducible management for agricultural trials — field, greenhouse, and efficacy research — built as a portable, auditable alternative to the Excel/Access-and-spreadsheet workflows these studies usually run on.

Every result carries its provenance: a trial is described by a package plus its observations, the analysis is computed natively and validated against published tables, and the whole trial hashes to a stable content hash so a report can always be traced back to the exact inputs that produced it. The system of record is a single SQLite file you own and can move; a trial exports losslessly to JSON and CSV.

## Status

The full reproducible loop runs end to end for a randomized complete block design — define, randomize, import, analyze, report, export, and reproduce — from the command line, an HTTP API, or a local web interface. It runs offline, on your own machine, in English (en-US / en-GB). See [`roadmap/milestones.md`](roadmap/milestones.md) for what is done and what is next, [`roadmap/implementation-plan.md`](roadmap/implementation-plan.md) for the build sequence, and [`brief.md`](brief.md) for the full brief.

## Install

Requires Python 3.13. From a clone of this repository:

```bash
pip install .            # the core library and the openfurrow command
pip install ".[service]" # adds the web interface and HTTP API
```

This installs the `openfurrow` command. (To run without installing, use the module
form `python -m openfurrow.cli.main` in place of `openfurrow` below.)

## The loop

```bash
openfurrow init trials.db                        # create the store
openfurrow add trials.db trial.json              # add a validated trial package
openfurrow randomize trials.db MY-TRIAL          # the field plan: plot -> block, treatment
openfurrow import trials.db MY-TRIAL data.csv    # import observations from CSV
openfurrow report trials.db MY-TRIAL             # the AOV Means Table
openfurrow export trials.db MY-TRIAL --json trial.json --csv obs.csv
openfurrow verify trials.db MY-TRIAL             # round-trip reproducibility check
```

Other commands: `list`, `info` (design, transforms, and content hash), `delete`,
`import-json` (import a trial document into the store), and `serve` (below). Analysis settings (significance level, mean-comparison test) come
from a project config file passed with `--config`; the defaults are ARM's
conventional alpha 0.05 and protected LSD.

## The web interface

```bash
openfurrow serve trials.db     # then open http://127.0.0.1:8420
```

The same loop with a face: browse trials, add one from a package, see the randomized
field layout as a plot map, import observations (OpenFurrow CSV or a Field Book export),
read the AOV Means Table in the browser, and run the reproducibility check. Everything is
served locally with no external assets, so it works offline, and the report renders in
either shipped locale. The same process exposes a JSON API under `/api` for scripting.

It binds to loopback by default and **has no authentication yet**, so it is a local
single-user tool: do not put it on a network. HTTPS is available as configuration
(`service.tls`) for when that changes.

## Worked example

[`examples/yatesOats/`](examples/yatesOats/) runs the whole loop on Yates's 1935 oat
variety trial and reproduces its published analysis of variance. Start there.

## What it computes

For a randomized complete block design, the AOV Means Table: the analysis-of-variance
table (block / treatment / error), treatment means, grand mean, coefficient of
variation, and Fisher's Protected LSD with a compact letter display. The F and t
distributions are computed natively (no SciPy at runtime); the results are validated
in the test suite against the Yates oats published table and against statsmodels.

## Reproducibility and ownership

- A trial's **input hash** (over package and observations) makes every report
  traceable to its exact inputs. The layout is regenerated from the recorded seed, so
  it is never a separate source of truth.
- The **store** is one SQLite file (via SQLAlchemy, schema portable to PostgreSQL for a
  future team mode). Numeric values are stored exactly, so hashes are stable.
- **Export** to JSON (validated, deterministic, archival) or CSV (long format,
  annotated with block and treatment). The database and a JSON export agree on the
  content hash — your data is never trapped in the store.

## Development

```bash
bash scripts/bootstrap.sh      # installs Python 3.13, creates .venv, installs everything
source .venv/bin/activate
python -m pytest
```

The bootstrap script is idempotent and is the supported way to get a working environment;
it exists because the project targets Python 3.13 and a bare `pip install -e .` fails on
an older interpreter. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the engineering norms
and the validation oracles.

---

Supported in part by the work of [OneSourceIT](https://onesourceit.us/open-source.html).

## License

Apache-2.0. See [LICENSE](LICENSE).
