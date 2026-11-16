# 0019 - Planting, soil and weather are recorded with the trial

**Status:** Accepted. Reversible while no trial exists outside development.

## Context

The research specialist asked for planting details such as seeding rate and emergence,
soil information and weather information (worklist REC-1, REC-5, REC-6). EPPO PP 1/181,
Appendix 1 asks for them in section 1.2 (sowing date, density, row spacing, preceding
crop, cultivation) and section 3.1 (soil type, pH, organic matter, seed-bed, fertilizer;
the weather on application days, the weather through the trial, irrigation).

## Decision

- **Planting** is one optional block: cultivar, the crop's EPPO code, sowing date,
  seeding rate, plant density, row and in-row spacing, sowing depth, emergence date,
  preceding crop, tillage, notes. Emergence cannot come before sowing.
- **Soil** is one optional block: soil type, texture, pH with how it was measured (in
  water and in calcium chloride differ by about half a unit), organic matter, seed-bed
  quality, the fertilizer regime, notes. pH is held to 0-14 and organic matter to 0-100%.
- **Weather** is a log of days in date order, one record per day: rainfall, irrigation,
  minimum and maximum air temperature, notes. Rain and irrigation cannot be negative; the
  two temperatures of a day must share a unit and the minimum cannot exceed the maximum.
  The conditions at an application stay with the application (decision 0016).
- **Each fact is kept once.** EPPO names fertilizer and irrigation in two sections; the
  fertilizer regime lives with the soil and irrigation in the weather log.
- **A block that is present holds something.** An empty block would be stored the same
  as no block and come back different, so it is refused.
- **Field notation is kept.** pH is written `pH`, as the field writes it.
- The report places planting before the design and soil and weather after the
  applications, in the standard's order.

## Deferred

- The site itself (coordinates, field or glasshouse, slope and exposure) and the
  details of perennial crops (worklist REC-12).
- Reading a weather log from a file (REC-13); soil particle-size fractions and layers.

## Consequences

- Schema 0.6.0, store version 6; every trial's content hash changed.
