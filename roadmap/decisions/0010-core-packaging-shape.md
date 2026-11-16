# 0010 - Core packaging shape

**Status:** Accepted. Direction adopted, not locked. Reversible.

## Context

The core is the single validated implementation of the statistics (ADR 0002). Multiple
surfaces will use it -- the CLI, the Flask service, potentially on-device execution. How
the core is physically packaged and deployed (an importable library, embedded in the
service process, or run on a device via native Python) is a real decision, but committing
to one shape now would be premature: the surfaces that constrain the choice do not exist
yet, and the analyst-versus-field split (analysis in the core, collection on the phone)
is itself soft and revisitable.

## Decision

- **The invariant, fixed:** there is exactly one implementation of the math -- the core
  -- and every surface uses it rather than reimplementing or re-validating the analysis
  (ADR 0002). Surfaces reach the core through a stable API (ADR 0009).
- **The packaging and deployment shape is deliberately left open.** The core may be
  consumed as an importable library, embedded in the Flask service process, or run on a
  device via native Python; the choice is made per surface, as that surface is built, and
  may differ between surfaces. None of these is foreclosed, including running the core on
  a phone.
- **What this fixes now:** settle a stable internal core API -- the operations surfaces
  call (build and validate a package, generate a layout, import observations, analyze,
  separate means, assess assumptions, build a report, exchange, hash) -- and package the
  core so surfaces can install and reuse it.

## Consequences

- Surfaces can be built against the core API without a premature commitment to how the
  core is deployed underneath them.
- "Where analysis runs" (the core, not the phone, as the default) is a lean, not a lock:
  on-device execution via native Python remains a legitimate option this decision keeps
  open.
- The stable core API is the contract; changing the core's internal implementation behind
  it is free (greenfield; ADR 0002).

## Open questions

- The concrete packaging (an installable package and its boundaries) as the service and
  other surfaces firm up.
- Whether any surface ultimately runs the core on-device, and what that constrains.
