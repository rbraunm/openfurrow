# 0026 - Transforms take an offset, and the log may be base 10

**Status:** Accepted. Extends decision 0006. Reversible while no trial exists outside
development.

## Context

Decision 0006 introduced plain transforms with fail-loud domains and left offsets for a
later slice. Counts with zeros cannot be logged without one, and the field's usual form is
log10(x + 1) or sqrt(x + 0.5) (Gomez and Gomez, section 7.2.2.1). The second opinion on the
readiness bar ranked "the transformation the reference used, offsets included" among the
first things a pilot needs (worklist USR-3).

## Decision

- **A rating may declare `transformOffset`**, zero or more, added before a log, base-10 log
  or square root, and taken off again when a mean is back-transformed. Any other transform
  refuses an offset. The domain check applies to the shifted value and names the
  original ones.
- **`log10` is a transform** beside the natural log. The base scales every sum of squares
  alike, so F and the separation are the same; the printed figures match references that
  use base 10.
- The offset is part of the record: stored, exported and covered by the content hash, and
  the report names the scale with it ("base-10 log of (x + 1)").
- **Validated** against Gomez and Gomez Tables 7.16 and 7.17 (log10(count + 1)).

## Consequences

- Schema 0.12.0, store version 12; every trial's content hash changed.
- The book averages per-plot values rounded to four decimals, so its transformed means
  differ from the exact ones by up to 0.00005; the tests allow exactly that.
