# OpenFurrow

Open, reproducible management for agricultural trials — field, greenhouse, and efficacy research — built as a portable, auditable alternative to the Excel/Access-and-spreadsheet workflows these studies usually run on.

Every result carries its provenance: a trial is described by a package plus its observations, the analysis is computed natively and validated against published tables, and the whole trial hashes to a stable content hash so a report can always be traced back to the exact inputs that produced it. The system of record is a single SQLite file you own and can move; a trial exports losslessly to JSON and CSV.

## Status

The full reproducible loop runs end to end for a randomized complete block design — define, randomize, import, analyze, report, export, and reproduce — from the command line, an HTTP API, or a local web interface. It runs offline, on your own machine. English (en-US / en-GB) is fully reviewed; Spanish, French, and Arabic ship as clearly-marked machine drafts pending native review, with the Arabic interface rendered right-to-left. See [`roadmap/milestones.md`](roadmap/milestones.md) for what is done and what is next, [`roadmap/implementation-plan.md`](roadmap/implementation-plan.md) for the build sequence, and [`brief.md`](brief.md) for the full brief.

## Install

Requires Python 3.13 or newer. From a clone of this repository:

```bash
pip install .            # the core library and the openfurrow command
pip install ".[service]" # adds the web interface and HTTP API
```

This installs the `openfurrow` command. (To run without installing, use the module
form `python -m openfurrow.cli.main` in place of `openfurrow` below.) To get exactly the
dependency versions the project is validated with, add `--constraint constraints.txt`.

## The loop

```bash
openfurrow init trials.db                        # create the store
openfurrow place add trials.db station "Research station"           # organization
openfurrow place add trials.db station/fungicides "Fungicides"      # project
openfurrow place add trials.db station/fungicides/wheat "Wheat"     # study
openfurrow add trials.db trial.json --place station/fungicides/wheat  # add a validated trial package
openfurrow randomize trials.db MY-TRIAL          # the field plan: plot -> block, treatment
openfurrow import trials.db MY-TRIAL data.csv    # import observations from CSV
openfurrow report trials.db MY-TRIAL             # the AOV Means Table
openfurrow export trials.db MY-TRIAL --json trial.json --csv obs.csv
openfurrow verify trials.db MY-TRIAL             # round-trip reproducibility check
```

A trial that already has its layout -- made by hand or in another tool, perhaps already
in the ground -- comes in whole with `import-json`: a trial document whose package says
`"randomizationMethod": "imported"` and whose `layout` lists each plot with its block,
position and treatment. Its plot numbers and assignments are kept exactly as supplied.

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
any shipped locale. The same process exposes a JSON API under `/api` for scripting.

It binds to loopback by default and, in its default open mode, **has no authentication**,
so as installed it is a local single-user tool: do not put it on a network. Sign-in by
accounts with roles is switched on by the setting `identity.signInMode` (decisions 0036 and
0037), and HTTPS is configuration (`service.tls`).

### The scheduler

Work on a schedule -- such as reading a research federation's list of institutions every
six hours -- is done by the scheduler, a second process run beside the web server on the
same store:

```bash
openfurrow scheduler trials.db     # Ctrl+C stops it; running tasks finish or are recorded stopped
openfurrow task list trials.db     # the tasks, their schedules, next and last runs
openfurrow task run trials.db federationRefresh-edugain    # run one now
```

Without it nothing scheduled happens; the web interface's Tasks page says when it last
checked in. Schedules are five-field cron expressions read in the setting `tasks.timeZone`
(UTC by default). Installing the web server and the scheduler as services is not built
yet; until it is, start both by hand.

### Calling the API from a GitHub Actions job

With sign-in by accounts (the setting `identity.signInMode`), a script calls the API with
an account's API token. A CI job needs no stored secret: it proves what it is with the
token its platform signs for it, and acts with the roles given to the rule that trusts it
(decision 0042). On the server, once:

```bash
openfurrow setting set trials.db server identity.workloadAudience https://trials.example.org
openfurrow workload add trials.db nightly-weather githubActions repository_id=123456789 ref=refs/heads/main
openfurrow role assign trials.db analyst place:station/fungicides/wheat2025 --workload nightly-weather
```

`repository_id` is the repository's number (`gh api repos/<owner>/<name> --jq .id`), which
stays its own through a rename; a rule that names only the repository's name is refused.
In the workflow, the job asks GitHub for a token for the server's audience and sends it:

```yaml
permissions:
  contents: read
  id-token: write
steps:
  - run: |
      token=$(curl --fail --silent --show-error -H "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" \
        "$ACTIONS_ID_TOKEN_REQUEST_URL&audience=https://trials.example.org" | jq -r .value)
      curl --fail --silent --show-error -H "Authorization: Bearer $token" --data-binary @observations.csv \
        https://trials.example.org/api/trials/WHEAT-2025-01/observations
```

The token lasts minutes and is never stored. `openfurrow audit trials.db` names the rule
and the run behind every change the job makes. Any other OpenID Connect issuer is trusted
the same way, by its https address and the claims its tokens must carry.

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

- A trial's **input hash** (over the package, the field layout and the observations)
  makes every report traceable to its exact inputs. The layout -- which treatment stands
  on which plot -- is recorded with the trial. One the tool generated can be regenerated
  from its seed and checked; one made elsewhere is kept exactly as supplied.
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
