# Contributing to OpenFurrow

OpenFurrow is open, reproducible management for agricultural trials -- a portable,
auditable alternative to Excel/Access and single-vendor (ARM-style) trial workflows. The
mission shapes the rules below: results must be reproducible and validated, and the data
they are validated against must be honestly sourced.

The authoritative design and engineering rules live in `brief.md` (the design brief),
`CLAUDE.md`, and `roadmap/decisions/`. Read those for the data model, the reproducibility
policy, the no-silent-fallback rule, and the field conventions (ARM's AOV Means Table,
BrAPI/Field Book import). This file covers the norm that is easiest to forget: keeping
validation and its test data honest.

## Setup

OpenFurrow needs Python 3.13 or newer. On Ubuntu, bootstrap the environment before
anything else:

```bash
bash scripts/bootstrap.sh
source .venv/bin/activate
pytest
```

The script installs Python 3.13 if it is missing, creates `.venv`, and installs the project
editable with its test extras. It is idempotent. New system-level dependencies belong in
that script, and new Python dependencies in `pyproject.toml`.

On Windows, with Python 3.13 or newer installed, from the repository root in PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install --constraint constraints.txt --editable ".[test,service]"
.venv\Scripts\python -m pytest
```

### Pinned versions

`pyproject.toml` states what the library accepts, with lower bounds only. `constraints.txt`
states what was tested: the exact version of every dependency of the test and service
extras, and of the build backend. The bootstrap script, the validation workflow and the
product smoke all install with it, so a validation run can be repeated. Outside the
bootstrap script the same install is:

```bash
python -m pip install --constraint constraints.txt --editable ".[test,service]"
```

To move the pins, install without the file, run the suite and `scripts/productSmoke.py`,
write the versions that passed (`python -m pip freeze --exclude-editable`, plus the
setuptools the build used), and let the workflow confirm them on every platform. A
pre-release is never pinned when a release satisfies the requirement.

The `latest` workflow (`.github/workflows/latest.yml`) runs the suite every Monday on Linux
and Windows with Python 3.13 and 3.14 against the newest releases, without
`constraints.txt`, and records what it installed. It does not gate `main`: a red run there
says a new release breaks the project, and is the cue to fix the code or hold the pin.

## Validation: every change is tested on Linux and Windows

Every push to `claude` and every pull request into `main` runs the `validate` workflow
(`.github/workflows/validate.yml`) on Linux and Windows with Python 3.13 and 3.14: the test
suite, then `scripts/productSmoke.py`, which builds the source distribution and the wheel,
installs the wheel into a clean environment, and runs the worked example and the service
from there. `main` accepts a pull request only when the workflow's `validated` check has
passed, and that rule has no bypass. Both parts run locally the same way:

```bash
python -m pytest
python scripts/productSmoke.py
```

### The testbed: PostgreSQL and the other fixtures

The store runs on SQLite and on PostgreSQL, and the suite runs on either: `--store
postgresql` puts every test's store in a fresh database on the server named by
`OPENFURROW_TEST_POSTGRES` (a `postgresql+pg8000://` URL of a role that may create
databases), and fails at once if it is not set. The fixtures are defined once, in
`testbed/compose.yaml`, with every password from the environment:

- **The workflow** starts them for one run and throws them away (the `postgresql` job).
- **For development**, any Debian or Ubuntu host with root keeps them running:
  `sudo sh testbed/setupHost.sh <directory holding compose.yaml>` installs Docker if needed,
  makes the password once (in `testbed.env` beside the file, root only) and starts every
  service; run it again to reprovision, with `--fresh` to throw the data away too.

```bash
OPENFURROW_TEST_POSTGRES=postgresql+pg8000://openfurrow:<password>@<host>:5432/openfurrow python -m pytest --store postgresql
```

## Oracles: every reported number is validated

OpenFurrow never presents an unvalidated statistic as a fact. Each analysis result is
checked against at least one oracle and carries its method, library versions, and
validation status. The oracles, strongest first:

- **Published tables** -- an ANOVA table from the literature, independent of any software,
  and the strongest anchor. The primary anchor is the Yates oats RCBD (see the registry).
- **statsmodels** -- an independent implementation, used as a cross-check oracle and a
  test-only dependency. It validates; it is never part of the runtime analysis path
  (decision 0002).
- **scipy** and **openpyxl** -- test-only cross-checks for the assumption tests and Dunnett's
  distribution (scipy), and for the native `.xlsx` reader (openpyxl, decision 0031).
- **agricolae** (R) -- a reference for mean-separation behavior (Fisher's Protected LSD,
  alpha 0.05), consulted for parity, not vendored.

A result that matches no oracle is not trustworthy: the self-authored computation must
agree with an oracle within a documented tolerance.

## Test data: referenced by provenance, never vendored

`roadmap/research/test-data.md` is the registry of source and test material -- which
datasets we use, what each one is for, how to use it, and its license and citation. The
rule: **track the reference, not the data.** Third-party datasets are not committed into
the repo. Each fixture is transcribed or exported from its cited source with a provenance
header (dataset name, source version, original citation); agridat-derived material cites
both agridat (MIT) and the original publication. Data values are facts; their selection,
provenance, and intended use are what we version here.

When a dataset becomes usable for a new study type, add it to the registry with its
coverage role before wiring tests against it -- the registry should always reflect what
the suite actually validates against.

## Where things live

- **Design:** `brief.md` -- the design brief / specification.
- **Roadmap:** `roadmap/README.md` and `roadmap/milestones.md` -- the planning trail and
  the MVP build state.
- **Decisions (ADRs):** `roadmap/decisions/` -- short Status / Context / Decision /
  Consequences records; `roadmap/decisions/README.md` defines the process and indexes the
  decisions made so far.
- **Research:** `roadmap/research/` -- findings gathered by exercising the field and the
  tools, including the test-data registry.

## Engineering norms

Reproducible by default; fail loud with no silent fallbacks; own the core math (oracles
validate only); open and portable storage; exact-and-auditable before fast-or-convenient. User-facing text is externalized (no
hardcoded strings) with locale-aware number and date formatting, while stored data, the
exchange, and the content hash stay locale-neutral; because the target locales include
right-to-left and non-Latin scripts, the GUI is to be built bidirectional- and
complex-script-capable, with the layout mirrored for RTL, not only the glyphs (decisions
0007 and 0008).
These are stated in `CLAUDE.md` and recorded in `roadmap/decisions/`. One commit per
logical checkpoint; work lands on the `claude` branch and is merged by the owner via PR.
