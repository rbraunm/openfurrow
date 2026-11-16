# 0024 - The site and the size of the plots are recorded

**Status:** Accepted. Reversible while no trial exists outside development.

## Context

EPPO PP 1/181, Appendix 1 asks for the site's address and coordinates, whether the trial
is in the field or under glass, its exposure and slope (section 1.1); for perennial crops
the spacing, training system, rootstock and age (1.2); and the number, size and shape of
the plots, gross and net, and the zones between them (1.3). The trial held its site as one
line of text and nothing of its plots (worklist REC-12, REC-15).

## Decision

- **Site details** are an optional block: address, latitude and longitude in decimal
  degrees (both or neither, on the globe), elevation, setting (field, glasshouse, growth
  chamber, other), exposure and slope. The trial's site name stays where it is.
- **Planting** gains the training system, rootstock and year planted of perennial crops;
  spacing is already there.
- **Plot dimensions** are an optional block on the design: gross and net length and width
  and the width of the alleys, each a positive quantity, with notes. A net side larger than
  its gross side is refused when both are in the same unit; units are kept as written and
  not converted, so sides in different units are not compared.
- Like planting and soil, a block that is present holds something.
- The report places the site before planting, and the plot sizes in the design.

## Consequences

- Schema 0.11.0, store version 11; every trial's content hash changed.
- Plot area and the shape of a plot are derived from the sides when needed, not stored.
