# OpenFurrow Project Brief

**Project name:** OpenFurrow  
**Tagline:** Open infrastructure for reproducible agricultural trials.  
**Status:** Seed concept / project definition  
**Mission:** For science.

OpenFurrow is an open-source agricultural trial management platform intended to modernize, consolidate, and preserve field, greenhouse, and efficacy research workflows that are currently trapped in legacy desktop tools, spreadsheets, proprietary databases, and ad hoc reporting pipelines.

This is not intended to be a clone of any existing commercial product. The intent is to build open scientific infrastructure: portable data, reproducible analysis, auditable reports, and standards-based interoperability.

---

## 1. One-sentence thesis

Researchers should not need proprietary legacy desktop software, paid database add-ons, Access-backed repositories, or fragile spreadsheet glue to design, preserve, analyze, and report agricultural trial research.

---

## 2. Background

The immediate inspiration came from a domain user mentioning that they work in a primitive-looking commercial agricultural research application. The broader pattern is familiar: an important scientific workflow depends on legacy desktop software, paid licensing, proprietary data assumptions, and add-on database products.

Publicly available ecosystem research suggests this category includes tools that create protocols, manage trials, analyze data, generate reports, and support crop production/protection workflows. Some incumbent stacks appear to treat shared relational trial storage as an additional licensed product rather than the default foundation.

This creates a clear open-science opportunity: what should be a normal database-backed scientific workflow is instead tied to commercial, legacy-style desktop ecosystems.

---

## 3. Why this is a strong open-source candidate

OpenFurrow is compelling because the target problem is not exotic. It is ordinary business tooling inside a scientifically important workflow.

The project appears to sit in the sweet spot where:

- the domain matters scientifically;
- the current incumbent is commercial and proprietary;
- the UI/architecture appears legacy-oriented;
- data volumes are modest;
- the math is mostly known applied statistics, not frontier theory;
- the open ecosystem has useful pieces but not an obvious complete replacement for the full workflow;
- interoperability and reproducibility are more valuable than novelty;
- a small, disciplined open-source project could create an escape hatch before attempting full replacement.

This makes OpenFurrow very different from a deep-math project like Tetradrome. Tetradrome is heroic, abstract, and mathematically severe. OpenFurrow is boring, practical, and likely much more immediately useful.

---

## 4. Core project identity

OpenFurrow should be framed publicly as:

> An open, reproducible agricultural trial platform for field, greenhouse, and efficacy research.

It should not be framed as:

> A clone of a specific incumbent product.

Internally, legacy proprietary tooling is the motivating example and comparison point. Publicly, the mission should be larger: open scientific workflow infrastructure.

OpenFurrow should support researchers who currently live in some combination of:

- legacy proprietary agricultural trial software;
- Excel;
- Access;
- local files;
- paper field notes;
- Field Book;
- BrAPI-compatible systems;
- custom sponsor templates;
- ad hoc R/Python scripts;
- institution-specific databases.

---

## 5. Design principles

### 5.1 Data first

The database and data model are not premium add-ons. They are the spine of the project.

OpenFurrow should treat trial data as durable scientific records, not as incidental files attached to a desktop application.

### 5.2 Reproducible by default

Every generated report should be traceable to:

- source data snapshot;
- schema version;
- transformation version;
- analysis method;
- analysis package/library version;
- report template version;
- runtime metadata.

### 5.3 Open formats before proprietary compatibility

The first priority should be open schemas and common formats:

- CSV;
- Excel import/export;
- JSON/YAML data packages;
- BrAPI;
- Field Book-compatible paths;
- public schemas and migration tools.

Compatibility with incumbent tools should only use legally accessible exports, user-owned data, and documented/public interfaces. Do not build the project around reverse engineering proprietary internals without explicit legal review.

### 5.4 Boring is good

This project should not chase novelty for its own sake. Agricultural researchers need software that is:

- stable;
- understandable;
- inspectable;
- testable;
- portable;
- easy to back up;
- hard to accidentally corrupt;
- clear about what it did.

### 5.5 Standards-aligned, not silo-forming

OpenFurrow should not become another closed data island. BrAPI should be treated as a first-class interoperability target because it is an open, standardized REST API for plant breeding data, including germplasm, field trials, phenotyping, and genotyping.

### 5.6 Domain fidelity over feature count

A smaller set of workflows that match real field trial practice is better than a large generic app that fails at domain-specific details.

---

## 6. Initial product scope

The first useful version should focus on agricultural trial management and reproducible reporting, not genomics-heavy breeding workflows.

### 6.1 In scope for early OpenFurrow

- Projects / studies / trials
- Locations / sites / fields
- Crop and season metadata
- Protocol templates
- Treatments
- Products / materials
- Rates and units
- Application events
- Plot layouts
- Randomization
- Blocks / replications
- Assessment definitions
- Field observations
- Import/export
- Basic validated statistics
- Reproducible reports
- Audit trail
- Attachments by reference/hash
- Local-first or single-user mode
- Team database mode later

### 6.2 Later or optional scope

- Advanced spatial field models
- Multi-location / multi-year trial summaries
- BrAPI server mode
- Full Field Book integration
- Breedbase/BMS interoperability
- GLP/GEP-oriented workflows
- Sponsor-specific report templates
- Mobile/offline sync
- QR/barcode workflows
- GIS/map layers
- Drone/UAV phenotyping integration
- Genotype/phenotype/breeding modules
- Genomic selection or GxE analysis

### 6.3 Explicitly not first

- Full incumbent replacement from day one
- Proprietary format reverse engineering
- Cloud-only architecture
- Enterprise permission labyrinth
- Heavy genomics platform
- Drone imagery processing platform
- Marketplace/commercial SaaS model

---

## 7. MVP proposal

The MVP should prove that OpenFurrow can preserve and reproduce a simple but real agricultural trial workflow end-to-end.

### 7.1 MVP name

**OpenFurrow v0.1: Reproducible Trial Package**

### 7.2 MVP capabilities

1. Create a trial record
   - crop
   - season
   - site
   - study objective
   - investigator/organization fields using generic labels

2. Define treatments
   - treatment name/code
   - product/material
   - rate
   - unit
   - timing
   - application metadata

3. Generate a simple layout
   - randomized complete block design first
   - treatments x replications
   - plot identifiers
   - exportable plot map/table

4. Define assessments
   - trait/measurement name
   - unit
   - assessment date or growth stage
   - allowed values/ranges where applicable

5. Import observations
   - CSV first
   - Excel second
   - manual entry later, unless needed for testing

6. Run basic analysis
   - descriptive statistics
   - ANOVA for supported designs
   - treatment means
   - simple pairwise/comparison output where statistically appropriate

7. Generate a report
   - Markdown/HTML/PDF eventually
   - includes input data summary
   - includes method metadata
   - includes warnings and validation notes
   - generated from versioned template

8. Export a portable project package
   - data files
   - metadata
   - report artifacts
   - checksums
   - manifest

### 7.3 MVP definition of done

The MVP is done when a small sample trial can be created, randomized, populated with observations, analyzed, reported, exported, re-imported, and reproduced bit-for-bit or with explicitly documented tolerances.

---

## 8. Data model sketch

This is a preliminary conceptual model, not a final schema.

### 8.1 Core entities

- Organization
- User / actor
- Project
- Study
- Trial
- Site
- Field
- Season
- Crop
- Protocol
- Treatment
- Product / material
- Application event
- Plot
- Block
- Replication
- Assessment
- Observation
- Unit
- Attachment
- Report
- Analysis run
- Audit event

### 8.2 Important relationships

- A project has many studies.
- A study has many trials.
- A trial occurs at a site/field/season.
- A trial uses a protocol.
- A protocol defines treatments and assessments.
- A trial has a randomized layout of plots.
- Plots receive treatments.
- Assessments define what observations are collected.
- Observations belong to plot x assessment x time/event.
- Analysis runs consume immutable trial snapshots.
- Reports are generated from analysis runs and templates.
- Audit events record meaningful changes.

### 8.3 Attachment posture

Do not store large files directly in the relational database by default.

Use:

- file/object storage for attachments;
- content hashes;
- size and MIME metadata;
- original filename metadata;
- attachment purpose/category;
- references from trial/report/application entities.

---

## 9. Storage and deployment posture

The core data volumes appear to be normal business-app scale, likely on the low end. Public documentation for a legacy trial database add-on indicates that an Access-backed repository can hold thousands of trials within a small file-size ceiling, which implies that basic structured trial data is not inherently huge.

### 9.1 Suggested storage modes

#### Local/single-user mode

- SQLite database
- project folder layout
- local attachments
- manifest/checksums
- simple backups

#### Team/institution mode

- PostgreSQL
- filesystem or object storage attachments
- role-based permissions
- audit/event log
- API server

### 9.2 Avoid by default

- treating Access as a core backend;
- putting all attachments into database blobs;
- cloud-only operation;
- requiring Docker for basic development or use;
- making database-backed storage a premium feature.

---

## 10. Analytics and statistics posture

The mathematics here should be treated as applied statistics and reproducible analysis, not frontier math.

Early methods should be conservative and validated:

- descriptive statistics;
- randomized complete block design analysis;
- ANOVA for supported designs;
- treatment means;
- confidence intervals;
- multiple comparison support only where clearly specified;
- missing-value handling with explicit warnings;
- reportable assumptions and diagnostics.

Later methods may include:

- mixed models;
- split plot / strip plot designs;
- repeated measures;
- spatial field effects;
- multi-location / multi-year models;
- dose-response models;
- genotype-by-environment analysis if the project expands into breeding/genomics.

The analytics layer should prioritize correctness, transparency, and reproducibility over breadth.

---

## 11. Validation strategy

OpenFurrow should be validation-driven from the beginning.

### 11.1 Validation sources

Potential validation sources include:

- textbook examples;
- peer-reviewed agricultural statistics examples;
- public datasets;
- R package examples and vignettes;
- known output from legacy tools supplied by users from their own data, if legally usable;
- synthetic trials with analytically predictable results;
- BrAPI sample datasets;
- Field Book sample/export fixtures.

### 11.2 Validation rules

Every statistical method should have:

- known-answer tests;
- tolerance definitions;
- input validation tests;
- missing-data tests;
- bad-unit tests;
- report snapshot tests;
- cross-tool comparisons where possible.

### 11.3 Reproducibility artifacts

Each analysis run should be able to emit:

- input data hash;
- normalized data hash;
- analysis configuration;
- software versions;
- random seed where applicable;
- output hash;
- warning list.

---

## 12. Interoperability landscape

OpenFurrow should integrate with the existing open ecosystem rather than pretending it is the only tool.

### 12.1 BrAPI

BrAPI is a free/open standard interface for plant phenotype/genotype databases and covers data such as germplasm management, field trials, and genotyping. It is the obvious long-term interoperability target.

### 12.2 Field Book

Field Book is an open-source Android app for collecting data on field research plots. It replaces paper field books and reduces transcription errors. OpenFurrow should support Field Book import/export or integration paths.

### 12.3 Breedbase / BMS / BIMS / BreedersDB / AgroFIMS

Existing tools cover important parts of the broader breeding and agricultural data ecosystem:

- Breedbase supports field layouts, phenotyping, genotyping, genomic selection, and BrAPI.
- BMS is an open-source information management system for plant breeding programs.
- BIMS is a free online breeding management system for storing, managing, archiving, and analyzing breeding data.
- BreedersDB presents itself as a 100% open-source plant breeding management platform.
- AgroFIMS supports standards-compliant FAIR fieldbook/metadata generation for agronomic data.

The likely gap is not that nothing exists. The likely gap is that existing open tools are fragmented and often breeding-centric, while the target workflows appear focused on crop production/protection efficacy trials, trial reports, and desktop-style study management.

---

## 13. Incumbent comparison notes

This section is for project context only. It should not be used for marketing language without careful review.

### 13.1 What incumbent tools appear to provide

- Protocol creation
- Trial creation/management
- Agriculture research experiment workflow
- Analysis
- Required reports
- Crop production/protection standard workflows
- Desktop application
- Licensed distribution
- Add-ins/sponsor customizations
- Trial database product/add-on

### 13.2 Signals that make this category a candidate

- Commercial licensing and annual maintenance
- Desktop-first posture
- Update/install flow tied to license credentials
- Relational database as a separate product
- Access-backed database option
- Normal/low-end data scale
- Domain users describe the GUI as primitive
- No obvious complete open-source replacement for the full workflow found yet

### 13.3 What not to do

- Do not copy incumbent UI.
- Do not copy incumbent proprietary code.
- Do not reverse engineer private formats casually.
- Do not make compatibility promises before seeing real user-owned export files.
- Do not publicly position the project as an attack on one vendor.

### 13.4 What to do instead

- Build an open trial workflow platform.
- Ingest public/open/user-owned formats.
- Support common exports.
- Provide migration helpers where legally safe.
- Make the data model and reports better than the legacy workflow.

---

## 14. Suggested technical architecture

This is a starting point, not a mandate.

### 14.1 Backend

- Python backend is attractive because the scientific/statistical ecosystem is strong.
- FastAPI is a reasonable API candidate.
- SQLAlchemy or SQLModel could support SQLite and PostgreSQL.
- Alembic-style migrations are likely useful.
- Pydantic-style schemas are useful for import/export validation.

### 14.2 Frontend

- Web UI preferred over desktop-only UI.
- React/Vite or similar is acceptable.
- Keep UI boring, fast, and form-focused.
- Prioritize data-entry correctness over visual flash.

### 14.3 Analysis engine

Options:

- Python stats stack for early methods.
- R interop for established agricultural statistics packages where needed.
- Store analysis specifications as data, not only code.
- Version analysis runners and report templates.

### 14.4 CLI

A CLI should exist early for reproducibility and automation:

- create project
- validate data
- import observations
- run analysis
- generate report
- export package

### 14.5 API

The API should be designed with BrAPI alignment in mind, even if BrAPI server mode comes later.

---

## 15. Repository structure proposal

```text
openfurrow/
  README.md
  LICENSE
  docs/
    project-brief.md
    architecture.md
    schema.md
    validation.md
    interoperability.md
  openfurrow/
    api/
    cli/
    core/
    data_model/
    importers/
    exporters/
    analysis/
    reports/
    validation/
  tests/
    fixtures/
    known_answers/
    import_export/
    reports/
  examples/
    simple_rcbd_trial/
    csv_import/
    report_generation/
  schemas/
    json/
    sql/
  templates/
    reports/
```

---

## 16. Roadmap

### Phase 0: Domain discovery

- Interview the domain user.
- Collect screenshots if available.
- Identify daily pain points in the incumbent workflow.
- Identify actual exports available from incumbent tools.
- Identify report formats they must produce.
- Identify statistics they use in practice.
- Identify whether they use Access, SQL Server, Excel, EDE, local project files, or other export/database paths.
- Identify whether Field Book, BrAPI, Breedbase, BMS, or BIMS matter in their environment.

### Phase 1: Data package and schema

- Define the minimal OpenFurrow Trial Package.
- Create JSON schema or equivalent.
- Create example trial fixtures.
- Implement validation.
- Implement CSV import/export.

### Phase 2: Trial design and layout

- Implement randomized complete block design.
- Generate plot IDs.
- Export layout tables.
- Create known-answer layout tests with deterministic seeds.

### Phase 3: Observations and analysis

- Define assessment model.
- Import observation CSV.
- Validate units/types/ranges.
- Run basic analysis.
- Emit analysis metadata.

### Phase 4: Reporting

- Generate Markdown/HTML reports.
- Add template versioning.
- Add report snapshot tests.
- Add warning/assumption sections.

### Phase 5: Interoperability

- Add Field Book import/export path.
- Begin BrAPI mapping.
- Add example connectors/adapters.

### Phase 6: Team mode

- PostgreSQL backend.
- User roles.
- Audit event storage.
- Attachment management.
- API server.

---

## 17. Questions for the domain oracle

Ask the agricultural/genetics contact the following:

1. What exact trial-management product/version are you using?
2. Are you using only the core application, or also database, mobile, summary, or sponsor add-ins?
3. What is the most painful daily workflow?
4. What takes the most time: trial setup, data entry, reporting, analysis, exports, collaboration, or corrections?
5. What does the incumbent tool produce that must be accepted by someone else?
6. What export formats can you get from the incumbent tool today?
7. Do you have direct access to Access, SQL Server, Excel exports, EDE, local project files, or other data paths?
8. What statistical analyses do you actually run?
9. Do you need GLP/GEP-style audit support?
10. Are trials mostly crop protection, crop production, breeding, genetics, or something else?
11. Do you use Field Book or any mobile collection app?
12. Do you use BrAPI, Breedbase, BMS, BIMS, AgroFIMS, or internal databases?
13. How many trials per year?
14. How many sites/locations?
15. How many treatments, reps, plots, and assessments are typical?
16. Do attachments/photos/maps matter?
17. What does collaboration look like?
18. What is the smallest useful open tool that would make your life better immediately?

---

## 18. Initial risk register

### 18.1 Domain fidelity risk

The project may accidentally model an idealized trial workflow instead of how real users work. Mitigation: domain interviews, real fixtures, iterative testing.

### 18.2 Reporting risk

Reports may be the actual lock-in. Mitigation: prioritize report reproduction and template flexibility early.

### 18.3 Statistical trust risk

Users will not trust analysis unless outputs are validated. Mitigation: known-answer tests, method documentation, transparent warnings.

### 18.4 Interoperability risk

Open standards exist, but real institutional data may be messy. Mitigation: import/export-first design, aggressive validation, explicit mapping docs.

### 18.5 Scope creep into breeding/genomics

Genetics can become a large, difficult domain. Mitigation: start with efficacy/field trial workflows and treat genomics as later modules.

### 18.6 Legal/proprietary compatibility risk

Incumbent-tool compatibility could create legal risk if handled carelessly. Mitigation: support user-owned exports and public standards first.

### 18.7 Maintenance risk

Open science projects can die if too ambitious. Mitigation: small core, clean fixtures, boring stack, strong docs.

---

## 19. Licensing posture

A permissive open-source license is likely appropriate if the goal is broad scientific adoption.

Recommended default:

- **Apache-2.0** for the codebase.

Reasons:

- permissive;
- friendly to academia, government, nonprofits, and companies;
- includes explicit patent license language;
- common for infrastructure projects.

Potential companion licenses:

- CC-BY-4.0 for documentation;
- CC0 or similar for synthetic test datasets where appropriate;
- be careful with real agricultural trial datasets, which may contain proprietary or sensitive information.

---

## 20. What makes OpenFurrow different

OpenFurrow should not merely be a prettier CRUD app.

Its value should come from:

- open data packages;
- reproducible reports;
- standards-based exchange;
- validation-first statistical methods;
- database-backed storage as a default;
- compatibility with real field workflows;
- liberation from legacy desktop/data silos;
- a careful bridge from existing workflows rather than a purity-first rewrite.

---

## 21. Name rationale

**OpenFurrow** works because:

- "Open" clearly signals open source and open science.
- "Furrow" is agricultural, physical, field-native, and grounded.
- It avoids the forced "-drome" precedent.
- It has better collision behavior than OpenAcre based on preliminary search.
- It sounds like infrastructure, not a startup pitch.

The name suggests opening a path through the field: a good metaphor for creating an open route through legacy agricultural research workflows.

---

## 22. Near-term action list

1. Create a repository named `openfurrow`.
2. Add README with mission and non-goals.
3. Add this project brief under `docs/project-brief.md`.
4. Add license.
5. Add sample `simple_rcbd_trial` fixture.
6. Draft initial trial package schema.
7. Build a CLI proof of concept:
   - validate package
   - import observations
   - run basic summary
   - generate report
8. Interview the domain user and update scope based on actual legacy-workflow pain.
9. Collect legally usable sample exports.
10. Decide whether Field Book or BrAPI should be the first interoperability milestone.

---

## 23. Source notes

These sources were used to ground the open-ag ecosystem context. Closed-incumbent research notes were intentionally omitted from this brief so the public project document stays focused on the open-science mission rather than on one vendor. Sources should be revisited before public claims are made.

1. BrAPI official site: https://brapi.org/
2. BrAPI getting started: https://brapi.org/get-started/1
3. BrAPI paper: https://pmc.ncbi.nlm.nih.gov/articles/PMC6792114/
4. Field Book official site: https://fieldbook.phenoapps.org/
5. Field Book GitHub: https://github.com/PhenoApps/Field-Book
6. PhenoApps app overview: https://phenoapps.org/apps/
7. Breedbase overview: https://cupulses.breedbase.org/
8. Breedbase paper: https://pmc.ncbi.nlm.nih.gov/articles/PMC9258556/
9. BMS overview: https://bmspro.io/596
10. BMS API repository: https://github.com/IntegratedBreedingPlatform/BMSAPI
11. BIMS paper: https://academic.oup.com/database/article/doi/10.1093/database/baab054/6355633
12. BreedersDB: https://breedersdb.com/
13. AgroFIMS official site: https://agrofims.org/
14. AgroFIMS paper: https://www.frontiersin.org/journals/sustainable-food-systems/articles/10.3389/fsufs.2021.726646/full
