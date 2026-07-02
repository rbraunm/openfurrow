# Reproducibility and data availability: the evidence base

Purpose: capture the published literature on data availability and analysis
reproducibility in research -- with an emphasis on agriculture and adjacent
field sciences -- and record what it implies for OpenFurrow's audience and
positioning. This is an evidence file, not a plan; the roadmap and the decision
records are where choices live.

## Why this matters for OpenFurrow

Large commercial developers can and do build their own bespoke, internal
analytics stacks on top of established capture tools; they are not the audience
for an open, portable workbench. The opportunity is the public and academic
sector and the underserved middle: universities, publicly funded programs,
research journals, and smaller organizations that cannot build in-house and that
need something open, centralized, supported, and reproducible.

The sharpest use case in that sector is the reproducibility of published
research. A trial whose data and analysis are both held as one durable, portable,
self-describing artifact -- one that can be re-run to reproduce the reported
figures -- directly addresses a problem the literature documents from several
angles. That is the spine OpenFurrow already has: reproducible-by-default,
content-hashed inputs, a deterministic randomization seed, native auditable
analysis, and now report-only assumption diagnostics.

The rest of this note is the evidence that the problem is real and cited, grouped
by the three claims it supports, plus an honest read of the limits.

## 1. Published data decays and is often unavailable

- **Data availability falls with article age.** Vines et al. (2014) requested the
  data behind 516 papers between 2 and 22 years old and found the odds of a
  dataset still existing fell by about 17% per year, and the odds of finding a
  working email for the first, last, or corresponding author fell by about 7% per
  year. They attribute the loss mainly to broken email chains and obsolete
  storage media. This is the empirical version of "the student who ran it has
  moved on and the data is gone."
- **"Available on request" mostly does not deliver.** Tedersoo et al. (2021)
  evaluated data availability across nine disciplines in Nature and Science and
  found that only about 42% of datasets could actually be obtained from authors
  on request. Reliance on the weak "on request" mechanism ranged from about 1% in
  psychology to about 52% in forestry -- i.e., the field closest to agriculture
  leaned hardest on the least reliable route. They conclude such statements are
  inefficient and should not be allowed by journals.
- **Policy alone is only a partial fix.** Stodden, Seiler and Ma (2018) requested
  data and code for 204 articles published under a journal's sharing policy;
  they obtained materials for 44% and could reproduce results for 26%. Their
  verdict: an improvement over no policy, but far short of guaranteeing
  availability or reproducibility.
- **Even audits that go looking find little.** Reviews in this space report data
  accessible from repositories for a small fraction of examined papers (for
  example, on the order of a couple of percent in one cancer-biology cohort), and
  a recurring "fate of data" literature documents datasets quietly disappearing
  after publication.

## 2. The analysis is rarely shared, and often will not reproduce even when it is

This is the strand that maps most directly onto OpenFurrow's value proposition:
storing the analysis alongside the data and being able to re-run it.

- **Code sharing lags data sharing badly.** Kambouris et al. (2024), out of an
  agriculture and ecosystem-science faculty, surveyed 177 meta-analyses: about
  75% shared data in some form, but only 16% shared code, and only 15% shared
  both. Mislan et al. (2016) found that in 2015 only 14% of 96 ecology journals
  required code, versus 38% for data. Culina et al. (2020) found that even after
  75% of those journals came to mandate or encourage code, only 27% of sampled
  articles actually shared any.
- **When both data and code exist, reproduction still frequently fails.**
  Kambouris et al. (2024) attempted to reproduce a target result from each of the
  26 articles that shared both, and succeeded for roughly 27% (all values exact)
  up to about 73% (values within 10%) of that subset -- which is only about 4% to
  11% of the original 177. The failure modes they document are the important
  part, because they are structural and avoidable:
  - random-number methods (bootstrapping, MCMC, multiple imputation) run
    **without a recorded random seed**, so the exact published value cannot be
    recovered;
  - **mismatches between the shared code and the shared data** (code referencing a
    variable that appears in no data file);
  - **underspecified computational environments** -- in their sample the R version
    was stated in only 62% of cases and package versions in only 23%.
- **Why this is the OpenFurrow argument.** A single, self-describing artifact that
  carries the data, the exact analysis, a fixed seed, and a content hash of the
  inputs removes precisely these failure modes: the seed makes stochastic steps
  recoverable, the one-artifact design removes code/data mismatch, the recorded
  method and versions remove environment drift, and the hash makes any change to
  the inputs visible. The literature is, in effect, a list of the things this
  design is built to prevent.

## 3. Agriculture specifically lags -- and is actively asking for this

- **The field knows it has a data-sharing problem.** Agricultural research has
  long leaned on informal sharing networks, and reviews describe entrenched
  research culture and weak data/standards governance as the roadblocks to
  interoperability and reuse, calling on researchers to treat long-term
  stewardship of data as part of the job (Governing Agricultural Data, 2022; the
  CGIAR Platform for Big Data in Agriculture is one cross-institutional response).
- **FAIR adoption in agriculture is aspirational, not achieved.** A systematic
  review (Agriculture, 2022) finds FAIR principles could play a key role in
  agricultural performance but that there are few published studies of actual
  adoption, and it sets out the specific barriers to making agricultural data
  FAIR.
- **There are explicit calls for exactly this category of tool.** A framework paper
  on agronomic experiments and data provenance argues that even exemplary
  agricultural research can be irreproducible, that funders and reviewers are
  demanding open data and reproducibility, and that there are as yet no accepted
  criteria for integrating data-driven agronomic experiments with their
  provenance -- and it proposes managing and re-enacting experiments through
  reusable analysis scripts. A regional-agronomy reproducibility guide makes the
  same point plainly: the only way to assure reproducibility is to keep the whole
  analytical workflow in scripts, ideally in free software so that a license is
  not a barrier. That is a description of the product category.
- **Standards already exist to build against.** The plant-phenotyping community
  has the MIAPPE metadata standard and the Breeding API for findable,
  interoperable, reusable experiment data; long-term-experiment programs and
  their funders have explicit FAIR and open-data expectations. These are
  integration targets and potential allies, not competitors.
- **There is ag-specific reproducibility-crisis work too**, including a study of
  the reproducibility and external validity of on-farm experimental research,
  which argues for far more systematic description of the populations and
  settings that field studies generalize to.

## 4. Honest read of the limits

- **A documented problem is not an adopting customer.** "There is a real,
  cited literature complaining about this" is a strong signal that the pain is
  genuine. It is not the same as a journal, university, or program committing to
  adopt and maintain a tool; that is a governance, trust, and incentives lift.
- **Policy interventions help but under-deliver on their own.** Mandates and
  "on request" statements have repeatedly failed to produce actual code sharing
  or reproducibility (sections 1 and 2). The trend is improving over time (for
  example, one bioscience department's share-all-relevant-data rate rose from
  about 7% in 2014 to about 45% in 2023), which cuts both ways: momentum exists,
  but the ceiling for policy-without-tooling is visibly low. A supported tool that
  makes the reproducible path the easy path is a plausible complement to policy,
  which is the opening.
- **The incumbents in this space are standards and repositories** (FAIR, MIAPPE,
  the Breeding API, general-purpose repositories such as Dryad, Zenodo, and
  Figshare), not one-stop reproducible-analysis workbenches. That is the gap, and
  it argues for interoperating with those standards rather than competing with
  them.

## References

Access is marked **[open]** or **[paywalled]**. Items flagged **-> obtain** are
paywalled and worth reading in full; see the note to the owner below.

Data availability and decay:
- Vines, T. H., et al. (2014). The availability of research data declines rapidly
  with article age. Current Biology 24(1):94-97. doi:10.1016/j.cub.2013.11.014.
  **[open]** (author copy on arXiv 1312.5670; dataset on Dryad).
- Tedersoo, L., et al. (2021). Data sharing practices and data availability upon
  request differ across scientific disciplines. Scientific Data 8:192. **[open]**
  (PMC8381906).
- Stodden, V., Seiler, J., & Ma, Z. (2018). An empirical analysis of journal
  policy effectiveness for computational reproducibility. PNAS 115(11):2584-2589.
  **[open]** (PMC5856507).
- Caetano, D. S., & Aisenberg, A. (2014). Forgotten treasures: the fate of data in
  animal behaviour studies. Animal Behaviour 98:1-5. **[paywalled]**

Analysis / computational reproducibility:
- Kambouris, S., Wilkinson, D. P., Smith, E. T., & Fidler, F. (2024).
  Computationally reproducing results from meta-analyses in ecology and
  evolutionary biology using shared code and data. PLOS ONE 19(3):e0300333.
  **[open]** (PMC10936784). Full text reviewed for this note.
- Culina, A., van den Berg, I., Evans, S., & Sanchez-Tojar, A. (2020). Low
  availability of code in ecology: a call for urgent action. PLOS Biology
  18(7):e3000763. **[open]**.
- Mislan, K. A. S., Heer, J. M., & White, E. P. (2016). Elevating the status of
  code in ecology. Trends in Ecology & Evolution 31(1):4-7. **[paywalled]**

Agriculture-specific:
- Towards integration of data-driven agronomic experiments with data provenance
  (RFlow). Computers and Electronics in Agriculture (2019). **[paywalled] -> obtain**.
- Agricultural data management and sharing: best practices and case study.
  Agronomy Journal (2021), doi:10.1002/agj2.20639. **[open]**.
- The role of FAIR data towards sustainable agricultural performance: a systematic
  literature review. Agriculture (MDPI, 2022), 12(2):309. **[open]**.
- Governing agricultural data: challenges and recommendations. In: Big data in
  agriculture (Springer, 2022). **[paywalled] -> obtain**.
- Kool, H., Andersson, J. A., & Giller, K. E. (2020). Reproducibility and external
  validity of on-farm experimental research in Africa. Experimental Agriculture
  56(4):587-607. **[paywalled] -> obtain**.
- The benefits and struggles of FAIR data: the case of reusing plant phenotyping
  data. (2023). **[open]** (PMC10345100). Introduces MIAPPE and the Breeding API.

Context (general reproducibility):
- Perkel, J. M. (2020). Challenge to scientists: does your ten-year-old code still
  run? Nature 584:656-658. **[paywalled]**.
- National Academies (2019). Reproducibility and Replicability in Science.
  **[open]**.

## Note to the owner: full texts worth obtaining

Most of the load-bearing evidence is open access and already summarized above.
The paywalled items most worth reading in full, if obtainable, are the three
agriculture-specific ones marked **-> obtain**: the agronomic-experiments and
data-provenance (RFlow) paper, the Governing Agricultural Data chapter, and the
on-farm reproducibility and external-validity study. The first two speak most
directly to the "one-stop, reproducible, provenance-aware agronomic analysis"
category; the third is the clearest ag-specific reproducibility-crisis evidence.
