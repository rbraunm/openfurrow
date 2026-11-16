# 0016 - Treatments are product lines; applications are records of their own

**Status:** Accepted. Reversible while no trial exists outside development.

## Context

A treatment was a code, a name, one product, one rate with its unit and a free-text
timing. A research specialist who runs efficacy trials read the tool's pages and said a
trial has to hold far more: the products in each treatment, how and when they were
applied, and the conditions at the time (worklist REC-3, REC-4). The record the field
expects is set out in EPPO PP 1/181, Appendix 1, sections 2.1, 2.2, 3.1.1 and 3.1.2, and
the incumbent tool arranges treatments the same way: one or more lines, each a product at
a rate, tied by an application code to the application it goes on at
(`../research/trialRecord.md`).

One product per treatment cannot hold a tank mix, an adjuvant, or a program over several
timings, which are ordinary in efficacy work. A free-text timing cannot hold what was done
on the day.

## Decision

- **A treatment has lines.** A line is one formulated product: its name, its kind
  (herbicide, fungicide, ... adjuvant), its formulation type, its active substances with
  their concentrations, a rate with its unit, and the basis of the rate (formulated
  product or active substance), which must always be stated. Products that share an
  application are a mixture; products at successive applications are a program. A
  variety or a cultural practice has no lines.
- **A treatment may state its role**: test, reference, untreated control, other control.
  It is declared, never inferred from a name. An untreated control has no lines.
- **An application is a record of its own**, keyed by a code that lines name: the planned
  timing, and once made its date and time of day, method, placement, equipment, nozzle,
  pressure, spray quality, travel speed and spray volume, crop and target stage, and the
  conditions at the time (air temperature, relative humidity, wind speed, cloud cover,
  soil moisture), with notes. One code is one pass over the field: a timing carried out
  on two days, or differently for some treatments, is two applications.
- **References must resolve.** A line may name only applications the trial declares. An
  application no line names is allowed: a pass over the whole trial belongs to the
  record too.
- **A quantity is a value with its unit as written.** Units are not converted or checked
  against a list yet. Impossible values are refused where they enter (a rate or pressure
  that is not above zero, a percentage outside 0 to 100, a number that is not finite, a
  date or time not written in ISO 8601).
- **All of it is canonical**: stored (the store is version 3), exported, covered by the
  content hash, and printed in the report.

## Alternatives

A second opinion consulted on this model proposed splitting an application further, into
a planned timing and one or more executions each scoped to a set of treatments or plots.
That holds a timing done on two days or a plot sprayed again without a new code. It was not
taken now: the one-code-one-pass rule holds those cases as separate applications, as the
incumbent tool does, and the split can be added if a real trial needs it. It is the most
likely change once the specialist's example of a trial setup arrives.

## Consequences

- Schema 0.3.0; every trial's content hash changed, the worked example's included.
- What was a free-text timing on a treatment is now an application's timing.
- Applications have no form yet; they are entered in the trial package (worklist USR-1).
- A deviation from the planned dose or timing is not yet recorded as such (worklist
  USR-8).
