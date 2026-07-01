# Market structure and the bridge opportunity

Field intel on how commercial crop-protection trial software is actually used, and
what it means for where OpenFurrow's leverage is. This refines the incumbent notes
in `brief.md` sections 12-13 with input from a working agricultural-research
contact, corroborated by public sources.

## The workflow is split across two tools

In practice the trial workflow is not served by one product but by two, used
together:

1. **A system of record / registry (ARM's current role).** The incumbent desktop
   product (ARM, by Gylling Data Management) is used primarily to hold protocols and
   to associate trials with product IDs and labels, so trials stay **comparable and
   trackable across many trials and many years**. Its across-trial and relational
   features (ARM Summary Across Trials; the ARM Trial Database add-in) are exactly
   this registry role. This is where the durable, cross-season value sits.

2. **A separate analysis and visualization suite (reported as "Bits").** The actual
   statistical analysis and visualization is increasingly done in a **separate,
   cloud-hosted** application, reported by the contact as "Bits". (The product
   identity is not yet confirmed from public sources; treat the name as
   to-confirm. What is confirmed is the *pattern*: analysis and graphing happen
   outside the registry tool.)

Public signal corroborates the split: ARM users report its built-in statistics are
basic and that they move to SAS or R for real analysis, and ask for integrated
graphing that is not there. So the registry tool is strong at tracking and weak at
analysis/visualization, and a second tool fills the analysis gap.

## The gap: neither travels well

Both sides of this workflow are hard to get data out of in the portable, owned form
OpenFurrow targets -- the desktop registry keeps data in a proprietary
desktop/relational form, and the cloud analysis suite keeps it in the cloud. The
data is split across two silos, and neither silo hands the researcher a portable,
self-describing copy of the whole trial.

## The opportunity: be the bridge, and own the data

OpenFurrow's strongest position is not "a better ARM" or "a better analysis tool" in
isolation. It is to be the **one-stop-shop that unifies both layers** -- the
protocol/product/label registry *and* the analysis-and-visualization -- on a single
open, portable, reproducible foundation the researcher owns. The wedge is precisely
the thing neither incumbent offers: a trial is one portable, hash-verifiable
document (SQLite file plus JSON/CSV export), analyzed transparently, with the
cross-year/cross-trial registry that made the desktop tool valuable in the first
place.

Bridging implies interoperability in both directions: **import from** the incumbent
formats (migrate a protocol/product registry in; ingest analysis inputs) so adoption
does not mean re-keying years of trials, and **open export** so the researcher is
never re-locked.

## The privacy caveat

The contact also flagged that companies sometimes need to **restrict** their trial
and product data -- not everything is meant to be shared, even within an
organization. So "you own the file" is necessary but not sufficient; ownership has
to coexist with controlled confidentiality (blinding product identities, restricting
cooperator or site data, role-scoped access). This argues for a **configurable data
privacy / access layer**, which the cloud incumbents provide only inside their walls
and not in a portable way.

## What this changes on the roadmap

- **Registry model** -- reusable protocols, a product/label catalog, and a
  project/study/trial (and season) hierarchy for cross-trial/cross-year tracking.
  See decision 0004.
- **Analysis and visualization** -- charts and cross-trial/across-year summaries, not
  just the tabular AOV Means Table (pairs with the web UI).
- **Interoperability / migrate-in** -- importers for the incumbent registry and
  analysis formats, so the bridge is real (extends `brief.md` section 12).
- **Configurable privacy / IAM** -- policy-driven data restriction, enforced at the
  access boundary, coexisting with the ownership and reproducibility model. See
  decision 0005.

## Provenance

Primary source is direct input from a working agricultural-research contact
(2026). Public corroboration below. The "Bits" product identity and any specific
competitor capability claims are to be confirmed before they are used in any public
positioning.

Sources:

1. ARM by Gylling Data Management -- product page: https://gdmdata.com/products/arm
2. ARM introduction (Summary Across Trials; Trial Database add-in): https://www.gdmdata.com/media/documents/ARM_Introduction.pdf
3. ARM user reviews (basic statistics; export to SAS/R; graphing requests), G2: https://www.g2.com/products/arm-by-gylling-data-management/reviews
