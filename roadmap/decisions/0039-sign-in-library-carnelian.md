# 0039 - The sign-in library is Carnelian, its own project under MIT

**Status:** Accepted.

## Context

OpenFurrow writes its own sign-in library so that no third-party licence limits where it
can be used (owner, 2026-11-16; `governance-plan.md`). The question was where that library
lives and under which licence. OpenFurrow is Apache-2.0, chosen in the brief for its
explicit patent grant. A small library is the kind of code other projects -- including
GPLv2 ones, which cannot take Apache-2.0 code -- would want to include.

## Decision

- **Its own repository and package, [Carnelian](https://github.com/rbraunm/carnelian)**,
  under the **MIT** licence (owner, 2026-11-17), so the owner's other projects and anyone
  else can use it. OpenFurrow depends on it like any other package. OpenFurrow itself stays
  Apache-2.0.
- Carnelian keeps the rules of `governance-plan.md`: the standard library only at run time,
  verification-only cryptography, strict defaults, and tests against its specifications and
  real identity providers. It is validated by its own workflow on Linux and Windows, with
  the same required check on its `main`.

## Consequences

- OpenFurrow's sign-in work (worklist GOV-3) is built in Carnelian and then wired into
  OpenFurrow's identity layer (decision 0036).
- The test fixtures for the identity providers (GOV-4) serve both projects.
