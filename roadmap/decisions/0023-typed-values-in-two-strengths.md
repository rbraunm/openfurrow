# 0023 - Values typed in the tool are checked in two strengths

**Status:** Accepted. Reversible while no trial exists outside development.

## Context

Observations reached the tool only from files (worklist USR-4), and one value outside an
assessment's limits rejected the whole file. The research specialist asked for
validation rules for data entry (REC-9). The incumbent tool raises an alert when a value
falls outside the assessment's minimum and maximum, which the user may confirm and keep.
The owner decided (2026-11-15) that a typed value outside its range is flagged and kept
once confirmed, with the confirmation recorded, not refused.

## Decision

- **An entry page per trial and assessment**: one box per plot and per check plot, a
  blank box for no value, numbers in the reader's decimal mark or with a point.
- **Two strengths.** What cannot be a value (not a number, a category the rating does
  not have, a number with both a point and a comma) is refused, the plot is named and
  nothing is saved. A number outside the rating's limits is held back and marked; it is
  saved only once ticked, and then every value of the assessment is saved together.
- **The confirmation is data.** An observation carries `outOfRangeConfirmed`; it is
  stored, exported and covered by the content hash.
- **One rule for every value that enters**: a trial document is checked by the same rule
  (right type, an allowed category, a finite number, outside the limits only when
  confirmed, a confirmation only when outside). A document with a confirmed value comes
  back in; one claiming a confirmation it does not need is refused. A CSV import still
  refuses a value outside the limits.
- **Saving replaces the assessment's values.** Emptying a box removes that value. Who
  changed a value, and when, is not recorded yet (worklist USR-8).

## Consequences

- Schema 0.10.0, store version 10; every trial's content hash changed.
- A trial document whose values do not fit their ratings is now refused on import; it was
  accepted before.
