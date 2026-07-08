# 0012 - Web UI stack

**Status:** Accepted. Direction adopted, not locked. Reversible.

## Context

The analyst web UI (platform plan Lane D) is where researchers design trials, randomize,
import data, run analysis, and read reports, and it is where localization and
right-to-left support (ADR 0007) land. It is served by the Flask application (ADR 0009).
The stack question is server-rendered (Flask with server-side templates) versus a
separate client-side single-page application consuming the API. The audience (ADR 0008)
is on modest hardware and flaky connectivity, which weighs on the choice.

## Decision

- **Served by the same Flask application** (ADR 0009), consuming the one HTTP API; the
  same API backs web, mobile, and the server.
- **Server-rendered first.** Flask with server-side templates, progressively enhanced
  with light client-side JavaScript only where an interaction needs it, rather than a
  heavy single-page-application front end. The rationale, for this audience: fewer moving
  parts, working on modest hardware and intermittent connectivity, no separate front-end
  build or toolchain, and a small, auditable surface. A richer client-side layer can be
  added where a specific interaction demands it, without adopting a full SPA framework up
  front.
- **Localization and RTL are first-class** (ADR 0007): externalized strings via message
  catalogs, locale-aware number and date formatting (CLDR), and bidirectional layout for
  right-to-left locales. The display-only canonical guardrail holds -- locale never
  touches stored data, the exchange, or the content hash.
- **No heavy or niche front-end framework as a baseline.** Dependencies follow the
  engineering standards (avoid niche or single-maintainer libraries). Any client-side
  libraries are deliberate, minimal, and served locally so the UI works offline, not
  required for core function.

## Consequences

- One codebase (the Flask app) serves both the API and the UI; shipping the analyst tool
  needs no separate front-end build pipeline.
- The offline and low-spec posture is preserved: the UI degrades gracefully and does not
  depend on externally hosted frameworks or heavy client runtimes.
- Localization and RTL are designed in from the first UI code (ADR 0007), not retrofitted.
- If a future surface genuinely needs a rich client application, the API-first boundary
  (ADR 0009) already supports it without rewriting the server.

## Open questions

- How much client-side interactivity the design-a-trial and results surfaces actually
  need (which determines whether and where a client library enters).
- The figure and chart rendering approach (offline, reproducible).
- The template and asset structure for localizable, RTL-capable layouts.
