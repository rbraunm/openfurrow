# North-star vision: a durable public archive for reproducible studies

**Status:** Long-term north star, not near-term scope. Aspirational and
uncommitted. Nothing here is on the build path; `milestones.md` is. This records
where the project could lead, so near-term choices can point in a consistent
direction and the idea is not lost.

## Two distinct efforts

There are two things here, and they should stay separate.

- **OpenFurrow (the tool).** Makes durable, content-hashed, reproducible trial
  artifacts: one portable file carrying the data, the exact analysis, a fixed
  seed, the method, and a hash of its inputs. This is what the rest of the repo
  builds.
- **The archive (an institution).** Preserves those artifacts for decades, curated
  and moderated, as a public home and discovery layer.

They collaborate across a clean seam -- the tool produces archive-ready artifacts;
the archive ingests, preserves, and serves them -- but they are distinct efforts
with distinct concerns, and neither requires the other to exist. The tool ships
and deposits into existing archives now (see Sequencing); the archive is the
eventual owned home. Keeping them separate is deliberate: the tool is a software
project, the archive is a funded institution, and conflating them would saddle a
working tool with the hardest problem in the space.

## What the archive is, and why

A funded, curated, moderated, long-term public home -- plus discovery layer -- for
reproducible study artifacts. It is the durable public home the reproducibility
literature says universities, journals, and publicly funded programs lack (see
`research/reproducibility-and-data-availability.md`): a place where a study's data
and its exact, re-runnable analysis persist together, past the point where the
student who ran it has moved on and the laptop is gone.

The hard parts of this institution are money, governance, and moderation -- not
storage. Bytes are cheap and get cheaper; people and trust do not. The three
perpetuity problems below are all really about that.

## The three perpetuity problems

### 1. Paying the bill forever

An endowment funds operations from its safe long-run real return. At roughly a 4%
annual draw, every $1/yr of forever-cost needs about $25 of principal. The catch:
the dominant long-term cost is not storage, it is people -- curation, moderation,
development, and format migration.

Precedents worth studying: the dark archives CLOCKSS and Portico (library- and
publisher-funded preservation); Dryad (nonprofit, submission plus membership
fees); Zenodo (host-institution plus grants); arXiv (host university plus a major
foundation plus member institutions). The Internet Archive is the cautionary
case: its funding and legal fragility show exactly what an endowment is meant to
prevent.

### 2. Technical care and feeding

Ongoing labor, not a one-time build: fixity checking, format migration, guarding
against bit-rot, geographic replication, and a dark backup. OpenFurrow's content
hashes already provide fixity for free -- any silent change to an artifact is
detectable. The credibility layer is standards: the OAIS reference model for the
archive's architecture, and trusted-repository certification (CoreTrustSeal as the
de facto badge, ISO 16363 as the heavyweight). That certification is also the
on-ramp into journal and funder workflows.

### 3. Curation and moderation against abuse

The underrated, perpetual cost. The archive must moderate junk and fraudulent
data, personally identifying information, and -- because our artifacts can carry
runnable analysis code -- actual malware and resource abuse. If the archive ever
executes deposited code to reproduce a figure, that is a trust-and-safety and
sandboxing problem, not a storage one. Someone owns scope, quality, and bad
actors, indefinitely.

## The legal and financial wrapper

Not legal or financial advice -- the shape of the options, to be checked with a
lawyer and a CPA:

- The durable pattern is a **nonprofit that holds an endowment**, board-governed,
  with a spending policy that funds operations.
- A **charitable trust** can hold the principal under fiduciary rules, but a bare
  trust is a clumsy vehicle for running a live service and employing people; so
  typically the trust holds the money and a nonprofit runs the thing.
- **Fiscal sponsorship** (operating under an existing nonprofit) lets the effort
  take funds and run before incorporating -- a low-overhead start.
- The most durable option is often **not going solo**: embed in or partner with
  something that already has perpetuity machinery -- a university library, a
  scholarly society, a public agricultural-research consortium such as CGIAR, or an
  existing repository.

The tension to name is **perpetuity versus control**: a trust that guarantees the
money also locks its use, and one can fund a technical role but cannot legislate
competence. So the instrument guarantees funding, while a governance body
guarantees care by being able to hire and fire the operator. Both halves are
required.

## Relationship to OpenFurrow and to agridat

- **The tool.** The archive makes "archive-ready" a concrete design goal for
  OpenFurrow -- standard, harvestable metadata; persistent identifiers (DOIs); and
  a preservation-grade export. That is good roadmap direction whether or not the
  archive is ever built.
- **agridat.** Both a precedent and a possible seed corpus. It is a respected,
  MIT-licensed collection of agricultural datasets curated largely by one
  maintainer -- which proves the value of curated ag data and, at the same time,
  demonstrates the exact bus-factor risk a funded, moderated institution exists to
  remove. A curated core could be seeded by ingesting such collections as
  reproducible packages.
- **The "why."** The archive is OpenFurrow's reason for being: the durable public
  home and discovery layer for the reproducible artifacts the tool produces.

## Sequencing

This is the hardest version of the project -- founding a perpetual institution --
and its failure modes are institutional (the money runs out, the maintainer burns
out), which is precisely what the whole design fights. So it is sequenced, not
started now.

- **Near-term (belongs on the build path):** make OpenFurrow deposit into existing
  endowed archives (for example Dryad or Zenodo) and mint DOIs. This buys
  durability and discovery immediately, for free, and teaches the deposit and
  metadata workflows. Tracked under Interoperability in `milestones.md`.
- **Long-term (this document):** the owned, endowed, moderated archive. Stand it up
  when there is traction, a funder, or an institutional partner -- not before. Do
  not let the cathedral distract from the tool that earns the right to build it.

## Open questions

- Governance model, and solo versus partner or embed (and with whom).
- Whether the archive ever executes deposited code, and if so the sandboxing and
  trust-and-safety design that implies.
- Endowment target and cost model (people-dominated, not storage-dominated).
- The boundary with existing repositories and standards bodies -- complement and
  integrate, or duplicate (complement is the working assumption).
- Moderation policy: scope, quality bar, handling of fraud, PII, and malicious or
  abusive deposits, and who staffs it.
