# 0008 - Primary early audience: global-South public-sector agronomy-trial research

**Status:** Accepted. Adopted as a design lens and a positioning commitment now;
scoped to the analysis and agronomy-trial wedge, and gated on partner validation
before heavy build. Direction adopted, not locked. Reversible.

## Context

Grounded by `research/global-south-audience.md` (with the reproducibility evidence
in `research/reproducibility-and-data-availability.md`, the market structure in
`research/landscape.md`, and the archive north star in `vision.md`). The audience is
resource-constrained, largely public-sector agricultural research in the global
South -- national agricultural research systems (NARS), universities, and regional
centres -- running agronomy, efficacy, variety-evaluation, and on-farm trials.

The evidence for the fit:

- A free, purpose-built statistics tool for exactly this audience -- GenStat's
  Discovery Edition, free for developing-world researchers, adopted across roughly 89
  countries from 2003 -- was discontinued around 2020, reopening a gap. The remaining
  free options are the R ecosystem (a steeper learning curve) or spreadsheets.
- The rationale given at that tool's launch is almost verbatim OpenFurrow's thesis:
  high-quality statistics software is unaffordable for many institutes and
  universities; research goes unpublished because the analysis was incorrect or
  inappropriate; and results suffer from non-visibility. Free, correct, auditable,
  reproducible analysis plus visibility is the tool's core value.
- The reproducibility literature is heavily global-South; the mission fit (free,
  open, offline-capable, owned) is direct; and the space is fundable through the
  open-data, FAIR, and reproducibility mandates and the research-capacity-building
  lines -- distinct from the breeding-pipeline and farmer-advisory funding streams.

The scope boundary is the real fork. The plant-breeding pipeline -- germplasm,
pedigree, crossing records, marker and genomic selection, multi-generation tracking
-- is occupied by well-funded platforms (the Breeding Management System, BreedBase,
the Enterprise Breeding System). OpenFurrow is not that and should not become that.
It is the trial-design-and-analysis tool for agronomy, efficacy, and
variety-evaluation trials (the ARM lineage), which shares the statistical core with
breeding yield trials but not the pipeline-management scope, and which interoperates
with BrAPI, MIAPPE, and ICASA rather than competing with the pipeline managers.

## Decision

- **Name resource-constrained global-South public-sector agronomy, efficacy,
  variety-evaluation, and on-farm trial research a primary early audience.**
- **Scope:** the analysis-and-trial-management wedge only -- explicitly not
  breeding-pipeline or germplasm management.
- **Gate:** this is a design lens and positioning commitment now, not a build
  mandate. Heavy, audience-specific build waits on validation with a real partner --
  a NARS, a university research-capacity network (for example RUFORUM), or a CGIAR
  center -- both to reach users and to avoid guessing at workflows. The project's
  discipline is empirical; the audience is not confirmed until a partner is engaged.
- **Localization via a high-value LLM-assisted first pass -- not a shortcut.**
  Reaching this audience implies localization (decision 0007). The LLM-assisted,
  human-and-partner-reviewed pipeline is adopted deliberately as a **high-value first
  pass, not a low-effort corner-cut.** Given the curated agronomic glossary,
  per-string context, and the domain, a modern LLM produces a credible draft that a
  domain reviewer corrects -- categorically better than the old phrase-substitution
  machine translation, and it turns a blank page into a reviewable draft whose
  quality compounds as corrections feed the glossary. It accelerates expert review;
  it does not replace domain sign-off, and no locale is authoritative until human- or
  partner-reviewed (the provenance rule in decision 0007). This is what lets a
  credible locale be produced proactively, without waiting for a partner to begin,
  while the review gate preserves the precision the journal and citation goal depends
  on.
- **Design responsibilities that follow from this audience** (already decided;
  reaffirmed here as audience-driven):
  - Offline-first, low-spec, owned, and free -- the connectivity, infrastructure, and
    cost constraints of the setting.
  - Localization-readiness including right-to-left languages and complex scripts,
    with a bidirectional, mirrored GUI (decision 0007). Recorded in `CLAUDE.md` and
    `CONTRIBUTING.md` so it is enforced when the UI is built.
  - Data sovereignty: the CARE principles (people-centric) complement FAIR
    (machine-centric) on community-facing and on-farm surfaces; the
    configurable-privacy layer (decision 0005) is both the differentiator and the
    responsibility.

## Consequences

- Wording sharpens across the project: the audience-facing framing is "agronomy,
  efficacy, and variety-evaluation trial analysis," not "breeding."
- This confirms, and does not change, the readiness decisions (0005, 0007) and the
  offline and low-spec posture as the right near-term investments; the audience is a
  lens for those, not new build scope on its own.
- Heavy, audience-specific build (partner workflows, field-facing surfaces, specific
  locales) is deferred until a partner validates it.
- Risks, carried openly: the institutional space is crowded and well funded; the
  dominant funding streams target CGIAR platforms and farmer advisory rather than
  researcher analysis tooling; and adoption depends on a partner.

## Open questions

- Which partner to validate with first (a NARS, a RUFORUM-type network, or a CGIAR
  center), and when.
- How the wedge coexists with the bridge strategy (`landscape.md`) and the archive
  north star (`vision.md`) -- expected to be complementary, not competing.
- What minimal agronomy-trial design breadth the audience needs first (ties to the
  analysis-breadth track in `milestones.md`).
