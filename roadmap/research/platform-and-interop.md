# Platform and interoperability: grounding for the field-to-analysis plan

Purpose: ground the platform master plan (`../platform-plan.md`) with cited fact about
the field-collection interop targets, the interoperability standards, and the
self-host deployment vehicles the plan leans on, so its phases rest on evidence rather
than assumption. This is an evidence file; sequencing lives in the plan and decisions
live in `../decisions/`.

## Field-collection interop: Field Book

- A free, open-source Android app (PhenoApps; University of Florida / IFAS, with
  USDA-ARS support). Historically funded in part by USAID -- now closed, see
  `global-south-audience.md` -- along with the McKnight Foundation's CCRP, the NSF, and
  USDA-NIFA. The funding history is noted only for context; the app itself is
  unaffected as an interop target.
- Imports an experiment (a "field") from a file (CSV/XLS/XLSX), from cloud storage, or
  from a BrAPI server, or created from scratch. Each row is an entry (a plot or plant)
  requiring a unique identifier plus a primary and a secondary identifier. Traits (what
  to measure) are user-defined and importable from a file or from BrAPI.
- Collects at plot level (sub-plot data via file), and exports either to a file
  (CSV/XLS) or to a BrAPI server. Key constraint: **only fields imported via BrAPI can
  be exported back to BrAPI.**
- BrAPI mapping: a Field Book "field" is a BrAPI *study*; a trait is a BrAPI
  *observationVariable*; collected data are BrAPI *observations*.
- Android only, distributed through Google Play -- so **iOS is a genuine gap** a
  first-party app would fill.

This yields two interop rungs, which the plan sequences:

1. **File-based (first).** OpenFurrow exports a Field Book-compatible layout file
   (entry ids plus the plot map) and a trait file; the user collects in the field;
   OpenFurrow ingests the exported CSV back into the trial. Fully offline, no server,
   matches the local-first floor.
2. **BrAPI (next).** OpenFurrow runs a BrAPI server that Field Book imports fields and
   traits from and pushes observations back to, eliminating manual file transfer. Live
   sync; pairs with the self-hostable collaboration server.

Adjacent target: GridScore, a web-based BrAPI phenotyping tool, reaches iOS through the
browser and is a secondary interop option to keep in view.

## The interoperability standard: BrAPI

- The Breeding API, version 2 (stable since 2022; v2.1 is the current minor). A RESTful
  JSON specification.
- Its modules are organizational only, and an implementer provides only the endpoints
  it needs: Core (Programs, Trials, Studies, Locations, Lists, People), Phenotyping
  (Observation Units, Observations, Observation Variables, Traits, Scales, Methods,
  Images), Germplasm, and Genotyping.
- V2 added create and update operations (v1 was read-only phenotype data), so a server
  can accept posted observations.
- It is aligned with the MIAPPE metadata standard and with GA4GH, and is explicitly
  software-agnostic and intended for breeding, phenotyping, germplasm, genotyping, and
  **agronomy** data management -- so OpenFurrow's agronomy, efficacy, and
  variety-evaluation trials fit within its scope.
- It is backed by a large community with a CGIAR and breeding-modernization lineage and
  dozens of participating institutions.

Implication: OpenFurrow's BrAPI lane is a **scoped server subset** -- Core (studies,
trials, programs, locations) plus Phenotyping (observationVariables, observationUnits,
observations) -- not the whole specification. Field Book interop in particular needs
only the study endpoints plus Traits, Variables, and Observations.

## Metadata: MIAPPE

- The Minimum Information About a Plant Phenotyping Experiment, version 1.1: a checklist
  of the metadata needed to describe and reproduce a field or phenotyping experiment --
  investigation and study, environment, experimental design, observation units,
  variables, and samples.
- Aligned with BrAPI (which can carry MIAPPE-conformant metadata) and with the ISA
  model.

Implication: MIAPPE is the target vocabulary for archive-ready export and for
structuring what OpenFurrow records about a trial. It rides along with the BrAPI and
deposit/DOI interoperability work rather than being a separate build.

## Self-host deployment vehicles: CloudFormation and AWS Marketplace

The self-hostable, user-owned collaboration server (the optional team path above the
local-first floor) can be delivered two ways, which layer:

- **CloudFormation template (first).** A plain template the user launches in their own
  AWS account, standing up the core with the collaboration, hosting, and security
  features. No seller registration, no listing review, and no ongoing listing
  obligation; squarely in the owner's AWS wheelhouse. The data stays in the user's
  account. Lowest friction to ship.
- **AWS Marketplace free AMI (later).** A listed, discoverable, roughly one-click image.
  A free listing is low-burden on paperwork -- offering only free products requires no
  banking or tax information -- but it carries real obligations: the software must be
  publicly available, full-feature, and production-ready; there must be a defined
  customer-support process; the software must be kept updated and free of known
  vulnerabilities; the listing goes through a manual review (about 7-10 business days
  for the first version); and the AMI must meet security requirements -- key-pair access
  only, no password authentication, no embedded credentials, a currently-supported OS,
  an image under two years old, built in us-east-1, IMDSv2, IAM roles rather than
  embedded keys, and a passing security scan. Repackaged open-source AMIs are explicitly
  supported, and delivery is via a "Launch from Website" experience or AMI-with-
  CloudFormation.

Both keep the data in the user's own account (owned data). The Marketplace security
requirements -- no passwords, IAM roles, encryption, scanning -- are good hygiene we
would want regardless, and they align with the configurable-privacy and security aims of
decision 0005.

Implication: **CloudFormation-first, Marketplace-AMI-later.** The plan's storage and sync
lane sequences them this way, and the Marketplace-vs-CloudFormation choice for any given
release is settled when that lane is built.

## What this grounds in the plan

- **Mobile lane:** file-based Field Book interop first, a scoped BrAPI server next, and
  first-party iOS/Android apps as the committed north-star build (iOS being uncovered by
  Field Book).
- **Interoperability spine:** a BrAPI v2 subset plus MIAPPE metadata, threaded through
  storage, the service, and the deposit/DOI work.
- **Self-host lane:** CloudFormation-first, Marketplace-AMI-later, user-owned throughout.

## References

Access is marked **[open]** or **[web]** (institutional or documentation pages).

- Field Book -- PhenoApps documentation and the `PhenoApps/Field-Book` repository
  (import/export, BrAPI fields-as-studies, plot-level collection); funding history:
  McKnight Foundation CCRP, NSF, USDA-NIFA, and USAID (historical). **[web]**
- Selby, P., et al. (2019). BrAPI -- an application programming interface for plant
  breeding applications. Bioinformatics 35(20):4147-4155; the BrAPI v2 specification at
  brapi.org (modules, read/write, MIAPPE and GA4GH alignment, agronomy scope). **[open]**
- GridScore -- web-based BrAPI field phenotyping tool. **[web]**
- Papoutsoglou, E. A., et al. (2020). Enabling reusability of plant phenomic datasets
  with MIAPPE 1.1. New Phytologist 227(1):260-273. **[open]**
- AWS Marketplace seller documentation -- free products (no banking/tax information),
  AMI-based product delivery, and AMI product policies (security requirements, review
  process, repackaged open-source support). **[web]**
