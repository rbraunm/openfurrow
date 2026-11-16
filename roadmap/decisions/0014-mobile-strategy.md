# 0014 - Mobile strategy

**Status:** Accepted. Direction adopted, not locked. Reversible.

## Context

The audience (ADR 0008) collects in the field, often offline and on modest devices. Field
Book -- Android only -- is the established open collection app and our first interop path
(ADR 0013), but it leaves iOS uncovered and is not tailored to the agronomy and efficacy
workflow. The platform plan makes first-party iOS and Android apps a committed north-star
lane (Lane F) in the user-interop direction, reached after interop rather than instead of
it.

## Decision

- **Interop first, own apps as a committed lane.** Field capability is delivered first
  through Field Book and BrAPI interop (ADR 0013). First-party iOS and Android
  offline-collection apps are a committed build -- not a parked maybe -- pursued as a
  distinct lane, filling the iOS gap and offering a differentiated agronomy and efficacy
  collection workflow.
- **Collection, not analysis, on the device.** The apps collect observations against a
  trial's plot map and sync; they do not run the ANOVA. Analysis stays in the core (the
  invariant of ADR 0010; ADR 0002). On-device analysis remains an option ADR 0010 keeps
  open, but the mobile apps are collection surfaces.
- **Sync to the user-owned server.** The apps sync to the user's own server (ADR 0011)
  through the API (ADR 0009) or BrAPI (ADR 0013); the data stays owned. Offline-first:
  collect without connectivity, sync when it is available.
- **App-store presence.** Distribution through the Apple App Store and Google Play is
  part of the goal.
- **Framework choice deferred.** Cross-platform (one codebase for both) versus native
  (per platform) is an open decision settled when the lane is built; the API and BrAPI
  sync boundary (ADRs 0009 and 0013) keeps the server independent of that choice.

## Consequences

- The heaviest surface -- native mobile with offline sync and store presence -- is
  reached on top of a stable API and server, and after interop has exercised the field
  workflow.
- iOS coverage, absent from Field Book, is a concrete differentiator the own-apps lane
  delivers.
- The apps depend on ADR 0009 (API), ADR 0011 (server and sync), and the interop patterns
  from ADR 0013.
- Nothing here forecloses continuing to support Field Book interop alongside first-party
  apps; both coexist.

## Open questions

- Cross-platform versus native framework (respecting the dependency rule -- avoid niche
  or unmaintained frameworks).
- The on-device data model and the offline sync mechanism (with the ADR 0011 sync model).
- How much agronomy- and efficacy-specific workflow differentiates the apps from Field
  Book.
