# What a trial record holds

Purpose: establish, field by field, what a field trial's record contains in established
practice, after a research specialist who runs such trials said the tool needs far more
than a design and its numbers (worklist, "Trial record"). This is an evidence file; the
items it feeds are REC-1 to REC-9 in `../worklist.md`.

Sources marked **[read]** were opened and read for this note. Sources marked **[reported]**
were found through assisted web research and are cited as reported, not re-read.

## 1. The standard's own list

EPPO PP 1/181 (5), the standard behind good experimental practice for efficacy trials,
sets out in its Appendix 1 what a trial report contains. **[read]**

- **1.1 Objective and site.** The pests the crop is to be protected against (scientific
  names or EPPO codes); field or glasshouse; the purpose of the trial; the site's address
  and coordinates; crop and cultivar; exposure and slope.
- **1.2 Trial conditions.** For annual crops the sowing or planting date, density and row
  spacing; for perennial crops spacing, training, rootstock and age; the preceding crop;
  tillage, fertilizer and irrigation; whether the crop was growing normally or under
  stress at treatment.
- **1.3 Design and layout.** The design and layout of the plots, preferably with a plan;
  number, size and shape of plots; gross and net plots and the zones between them; the
  assignment of plots to treatments and blocks; the type of design; the arrangement of
  the untreated control (included, imbricated or excluded).
- **2.1 Test and reference products.** The common name of each active substance; the
  exact name of each formulated product; for reference products the approval number and
  recommended use.
- **2.2 Mode of application.** Method and equipment; pressure, nozzle type, spray quality
  and travel speed; the number of applications and the date of each; the growth stage of
  the crop at each application (BBCH) and the development stage or level of the pest;
  the timing system; doses of formulated product per hectare and spray volumes; any
  deviation from the intended dose; other products applied to the whole trial.
- **3.1.1 Meteorological data.** The standard data for the day of application, always;
  the weather around it; extremes during the trial; irrigation.
- **3.1.2 Edaphic data.** Soil type, pH and organic matter; soil moisture at application;
  seed-bed quality; the fertilizer regime.
- **3.2 Assessments.** The type and date of each assessment; the method; the scale used;
  phytotoxicity for each plot; effects on non-target organisms; yield and quality.
- **4 Results.** All the data, simply and systematically, preferably in tables.

Its companion PP 1/152 (4) names the completely randomized design and the randomized
complete block as the principal designs and requires each block to be randomized
separately. **[read]**

## 2. How the incumbent tool arranges it

ARM (Gylling Data Management). **[reported]**

- **Two layers.** A protocol holds the treatments, the planned assessments and the rules
  of the study; a trial adds the randomization, the site description and the data.
- **Site description** in sections: crop, pest, site and design, soil, application,
  moisture and weather.
- **Treatments as lines.** A treatment is one or more lines, each with a type, a product
  name, a formulation concentration and type, a rate and its unit, and an application
  code that ties it to an application.
- **Assessment headers.** Rating date, rating type, rating unit, crop stage, pest stage,
  part rated, sample size and unit, collection basis, days after application, number of
  subsamples, minimum and maximum.
- **Designs.** RCBD, completely randomized, Latin square, split-plot, split-block,
  strip-block and lattices, with manual adjustment of the map.
- **Checks on entry.** Lookup lists; study rules that are required (an error) or
  recommended (a warning); date consistency; an alert when a value falls outside the
  assessment's minimum and maximum, which the user may confirm and keep.

## 3. Vocabularies to build on

**[reported]** EPPO codes for crops and pests; the BBCH scale for growth stages; the
trait, method and scale model of MIAPPE, BrAPI and the Crop Ontology for assessment
definitions; ICASA for management, soil and weather terms.

## 4. What this implies

- The specialist's list is the standard's list. The record is built to the shape of PP
  1/181's Appendix 1, section for section.
- A trial has what was planned and what was done. Applications are events with a date,
  equipment and conditions, and a deviation from the plan is recorded, not overwritten.
- A treatment is a set of lines, each a product at a rate at one or more applications.
- An assessment has a definition (what is rated, on which scale, on which part) and
  occasions (when, at which crop and pest stage, how many days after which application).
- Entry rules have two strengths. What cannot be a value at all is refused; what is
  merely unlikely is flagged, and the record keeps that it was confirmed.

## References

- EPPO PP 1/181 (5), Conduct and reporting of efficacy evaluation trials, including good
  experimental practice, Appendix 1; EPPO PP 1/152 (4), Design and analysis of efficacy
  evaluation trials (pp1.eppo.int). **[read]**
- Gylling Data Management, ARM documentation: components of a trial, the treatments list,
  protocols, the raw-data labels sheet, the design catalogue, study rules and the 2021
  change to rating limits (gdmdata.com). **[reported]**
- MIAPPE 1.1 (Papoutsoglou et al. 2020); the BrAPI phenotyping concept dictionary; the
  ICASA dictionary; the BBCH scale and EPPO codes (eppo.int). **[reported]**
