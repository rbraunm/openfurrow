# 0007 - Localization-ready architecture, and LLM-assisted localization

**Status:** Accepted. The readiness constraints below are in force now for all code;
actual localization is deferred and produced by an LLM-assisted, human-reviewed
pipeline. Direction adopted, not locked. Reversible.

## Context

The long-term vision (`vision.md`) and the reproducibility evidence
(`research/reproducibility-and-data-availability.md`) point toward
resource-constrained, largely public-sector research -- on-farm and
consortium-aligned work, much of it in the global South -- as a candidate primary
audience, where free, open, offline-capable, low-spec, and owned matters and where
adoption within a community benefits from interfaces in the language it actually
uses. That audience is not yet validated with a real partner. **This record does not
commit the project to that audience**; the readiness and the method below are
audience-independent, and the audience call is separate.

Three things shape the decision:

- **Agricultural localization is domain adaptation, not string substitution.** A
  video-game term list is largely context-free; agricultural research is not. It has
  terms of art with fixed, non-literal renderings a general translator gets wrong
  ("randomized complete block," "split-plot," "least significant difference,"
  "coefficient of variation" each have an established form in a given language's
  biometry literature that must be matched, not invented); regional agronomic
  vocabulary where one concept has different local words, sometimes within a single
  language; and genuine conceptual mismatches across research traditions. This is why
  the glossary is the real deliverable and why domain review is mandatory.
- **The unit of localization is a locale, not a language.** A locale is a BCP-47 code
  (for example `en-US`, `en-GB`, `fr`, `pt-BR`, `es-419`) that bundles translated
  strings with locale formatting rules for dates and numbers, taken from the Unicode
  CLDR data rather than hand-rolled. US and UK English make the point: they share
  almost all strings but differ in date order (US MM/DD/YYYY vs UK DD/MM/YYYY), which
  is a data-integrity hazard, not a cosmetic difference.
- **The cost asymmetry, and what changed.** Retrofitting internationalization across
  many locales is far more expensive than designing for it up front. Separately,
  modern LLMs have changed the economics of the first translation pass: unlike the
  old phrase-substitution machine translation, an LLM given a glossary, per-string
  context, and the domain produces a credible draft for high-resource languages --
  but it is fluent even when wrong, so for a tool whose value is precise, auditable
  output that could be cited in journals, human domain review is non-negotiable.

## Decision

### A. Localization-ready architecture (in force now, for all code)

- **No hardcoded user-facing strings.** All user-facing text is externalized into
  keyed message catalogs, so a locale is purely additive.
- **Locale-aware formatting** via BCP-47 locale codes plus Unicode CLDR data; decimal
  separators, thousands separators, and date formats are never hand-rolled in
  user-facing output.
- **Translatable report templates** -- report structure separated from its strings.
- **Analyst core kept separable from community-facing surfaces**, so field-facing
  surfaces can be localized first without translating the whole application.
- **Display-only canonical guardrail (the load-bearing rule).** Locale affects
  display only. The stored data, the JSON/CSV exchange, and the content hash stay
  locale-independent: ISO 8601 dates (YYYY-MM-DD), dot-decimal, no thousands
  grouping. Two reasons this is not optional: otherwise the same trial hashes
  differently for a US and a Brazilian operator, silently breaking reproducibility;
  and a locale-dependent CSV export would round-trip corrupted numbers for
  comma-decimal locales (French and Brazilian write "1.234,56" or "1 234,56") -- the
  same class of bug as the pandas "None" NA-sentinel trap already caught in testing.
  Canonical stays neutral; formatting is a display layer on top.

### B. Candidate locales

- **Committable now, no translation** (formatting plus a spelling overlay only):
  `en-US` and `en-GB`.
- **Translation efforts, pulled** (each needs a maintained agronomic glossary and
  human review): `fr`; `pt-BR` (Brazil is the flagship -- Embrapa, ESALQ -- and
  Brazilian Portuguese differs from European; a tidy tie to the Brazilian
  agronomic-provenance paper in the reproducibility note); and `es-419` (Latin
  America, for the consortium centers CIMMYT, CIP, and CIAT). Priority order: French
  first, then `pt-BR` and `es-419`. `es-419` is chosen over `es-ES` for the Latin
  American research centers; revisit if Spain becomes the target.

### C. Production method: LLM-assisted, human-reviewed, build-time

- **The glossary is the first-class artifact, not the translations.** A curated,
  version-controlled term base maps each source term of art to an approved target per
  locale, with a definition and a usage note. It is seeded from real domain sources
  (how the R and agricolae documentation, and Portuguese and Spanish biometry texts,
  render these terms), not invented by the model. The LLM consumes it for
  consistency; humans curate it; corrections feed back so quality compounds across
  every future string.
- **The LLM produces the bulk draft; humans sign off.** Approval is sought on early
  passes. The model accelerates review, it does not replace domain sign-off; the
  reviewer is ideally a partner or a native domain speaker.
- **Localization provenance and translation status (auditability and honesty).**
  Every string carries a status -- `source`, `machine-draft` (machine-translated,
  unreviewed), or `human-approved`. The tool never presents unreviewed machine output
  as authoritative and never labels a locale complete or authoritative until it has
  been human-reviewed; a machine-draft locale is surfaced to the user as such. This is
  the same fail-loud honesty the rest of the project holds, and it is essential to the
  goal of being citable in journals: a reproducibility tool must be transparent about
  which of its own outputs are machine-generated versus verified. Status is
  inspectable per locale and per string.
- **Build-time, not runtime.** Reviewed catalogs ship as static files. There is no
  live LLM call -- or any translation-service call -- in the runtime; that would be a
  niche, non-reproducible runtime dependency, contrary to decision 0002.
- **Mechanical guardrails.** The LLM touches display strings only, never canonical
  data, the exchange, or the hash. Placeholders, interpolation, format specifiers, and
  plural rules (for example `{treatmentCode}` and ICU plurals) are fenced from the
  model, so it translates the text around the machinery, not the machinery.

### Deferred, and not decided here

- The audience commitment itself.
- The i18n library or mechanism (a GUI-era choice; it must respect the dependency
  rule -- no single-maintainer or niche libraries).
- Community and field languages (for example isiZulu, isiXhosa, Swahili, Amharic, or
  Hausa) for the community-facing surfaces -- later, and partner-pulled.

## Consequences

- A small, ongoing discipline now (string externalization, locale-aware formatting,
  template and string separation) buys a large saving when localization arrives. The
  CLI benefits little directly, but it sets the pattern the Web UI will need.
- **The partner gate shifts.** Because a credible draft locale can be produced
  proactively, localization no longer needs a partner to *start*; but a locale is not
  authoritative until domain-reviewed. The gate moves from "need a partner to begin"
  to "need review to ship as authoritative."
- **The perpetual cost is curation and stewardship** -- the maintained glossary and
  the review -- the same category as the archive vision's "who maintains this
  forever." The tool ships and runs indefinitely in English; every translation locale
  is optional and deferred. The ceiling rose; the floor did not move.
- **Encoding.** Source code stays ASCII per the house rule. Message catalogs and
  localized output are UTF-8 by necessity -- French, Portuguese, and Spanish all use
  accented Latin characters, and later scripts more so -- and are read and written as
  explicit UTF-8. Localized reports therefore move the report layer from ASCII to
  UTF-8 output; the ASCII rule continues to govern source, not translated data.
- Interacts with decision 0005 (configurable privacy) and with data-sovereignty
  concerns around community and farmer data ownership, which this audience makes live.

## Open questions

- Spanish target: `es-419` (Latin America) unless Spain (`es-ES`) is preferred.
- The i18n mechanism, deferred to the GUI stack choice.
- Glossary format and schema, and the stewardship model with a partner.
- How prominently to surface per-locale translation status in the UI (for example a
  "machine-draft, unreviewed" badge).
- Whether and when to validate the candidate audience with a partner -- separate from
  this readiness and method decision.
