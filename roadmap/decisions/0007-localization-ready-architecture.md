# 0007 - Localization-ready architecture (localize later, partner-pulled)

**Status:** Accepted. The readiness constraints below are in force now for all code;
actual localization is deferred. Direction adopted, not locked. Reversible.

## Context

The long-term vision (`vision.md`) and the reproducibility evidence
(`research/reproducibility-and-data-availability.md`) point toward
resource-constrained, largely public-sector research -- on-farm and
consortium-aligned work, much of it in the global South -- as a candidate primary
audience: a setting where free, open, offline-capable, low-spec, and owned matters,
and where adoption within a community benefits from interfaces in the language that
community actually uses. That audience is not yet validated with a real partner.
**This record does not commit the project to that audience**; the audience call is
separate and should be grounded in field intel and a partner, not assumed.

What is decided now is narrower and audience-independent: whichever audience we
serve, the tool should be built so that localization is cheap to add later rather
than a painful retrofit. Two points from the design discussion shape this:

- **The payoff tracks how community-facing a surface is.** The analyst core --
  importing data, configuring an analysis, reading a report -- is used by
  professionals generally comfortable in English or French, so localized menus there
  are a nicety. The community-facing surfaces -- field data collection, participatory
  (mother-baby) trials, anything shown to extension agents and farmer-cooperators --
  are where native-language interfaces are a real adoption lever, not just
  comprehension.
- **Localization is many languages, not one.** Community adoption argues for local
  languages (for example French for francophone regions, and field languages such as
  Swahili, Amharic, or Hausa for community-facing surfaces) -- an open-ended,
  partner-specific set. Scientific and agronomic terms frequently lack standardized
  equivalents in these languages, so localization entails building and maintaining a
  glossary. That stewardship is a burden a partner community must own; we do not
  gatekeep it.

The crux is the cost asymmetry: retrofitting internationalization across many
languages is far more expensive than designing for it from the start.

## Decision

Adopt **localization-ready architecture now; defer actual localization.**

Readiness constraints, in force for all code from now on:

- **No hardcoded user-facing strings.** All user-facing text is externalized into
  keyed message catalogs, so a language pack is purely additive.
- **Locale-aware formatting** for user-facing numbers and dates -- decimal and
  thousands separators and date formats are not hardwired into user-facing output.
- **Translatable report templates** -- report structure is separated from its
  strings; no user-facing text is baked into report-generation logic.
- **Keep the analyst core and the community-facing surfaces separable**, so
  community-facing surfaces can be localized first without translating the whole
  application.

Deferred, and explicitly not decided here:

- Actual language packs, the first target language, and the i18n library/mechanism
  (a GUI-era choice; the CLI has few menus to translate). Any such dependency must
  respect the dependency rule -- no single-maintainer or niche libraries.
- The audience commitment itself, pending a real partner and the developing-world
  ag-software and funder landscape research.

## Consequences

- A small, ongoing discipline now (string externalization, locale-aware formatting,
  template/string separation) buys a large future saving when localization arrives.
- The CLI benefits little from this directly (few strings), but it sets the pattern
  the Web UI will need, where the payoff lands.
- **A tension to manage with the ASCII-only house rule.** The cross-language ASCII
  requirement (and the PowerShell 5.1 / Windows-1252 encoding constraint) governs
  source code and today's ASCII Markdown reports. Rendering non-Latin scripts
  (Amharic, and so on) is a Web-UI / UTF-8-era concern that arrives *with* actual
  localization. Baking in message catalogs now does not mean emitting non-ASCII
  output today; the readiness is structural, the non-ASCII rendering comes later.
- Localization, when it comes, is **partner-pulled and demand-driven**, and carries a
  glossary-stewardship burden the partner owns -- the same stewardship problem the
  archive vision wrestles with.
- Interacts with decision 0005 (configurable privacy) and with data-sovereignty
  concerns around community and farmer data ownership, which this audience makes
  live.

## Open questions

- First localization target language (likely French), and the first community
  language(s) for field-facing surfaces.
- The i18n mechanism, deferred to the GUI stack choice.
- Glossary format and the stewardship model with a partner.
- Whether and when to validate the candidate audience with an institutional partner
  -- separate from this readiness-only decision.
