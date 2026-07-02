# Reproducibility and data availability: the evidence base

Purpose: capture the published literature on data availability and analysis
reproducibility in research -- with an emphasis on agriculture and adjacent
field sciences -- and record what it implies for OpenFurrow's audience and
positioning. This is an evidence file, not a plan; the roadmap and the decision
records are where choices live. Items marked "full text reviewed" were read in
full; the rest are drawn from abstracts, published summaries, and citing works.

## Why this matters for OpenFurrow

Large commercial developers can and do build their own bespoke, internal
analytics stacks on top of established capture tools; they are not the audience
for an open, portable workbench. The opportunity is the public and academic
sector and the underserved middle: universities, publicly funded programs,
research journals, and smaller organizations that cannot build in-house and need
something open, centralized, supported, and reproducible.

The sharpest use case in that sector is the reproducibility of published
research. A trial whose data and analysis are held as one durable, portable,
self-describing artifact -- one that can be re-run to reproduce the reported
figures -- directly addresses a problem the literature documents from several
angles. A useful one-line benchmark, proposed for agricultural research by White
et al. (2025), is whether a study's descriptions are complete enough to reproduce
it ten years later. That is the bar OpenFurrow's spine is built for:
reproducible-by-default, content-hashed inputs, a deterministic randomization
seed, native auditable analysis, and report-only assumption diagnostics.

The rest of this note is the evidence, grouped by the three claims it supports,
plus an honest read of the limits.

## 1. Published data decays and is often unavailable

- **Data availability falls with article age.** Vines et al. (2014) requested the
  data behind 516 papers 2 to 22 years old and found the odds of a dataset still
  existing fell by about 17% per year, and the odds of finding a working email for
  the first, last, or corresponding author fell by about 7% per year, attributing
  the loss mainly to broken email chains and obsolete storage media. This is the
  empirical version of "the student who ran it has moved on and the data is gone."
- **"Available on request" mostly does not deliver.** Tedersoo et al. (2021)
  evaluated data availability across nine disciplines in Nature and Science and
  found only about 42% of datasets could actually be obtained from authors on
  request. Reliance on the weak "on request" mechanism ranged from about 1% in
  psychology to about 52% in forestry -- the field nearest agriculture leaned
  hardest on the least reliable route. They conclude such statements are
  inefficient and should not be allowed.
- **Policy alone is only a partial fix.** Stodden, Seiler and Ma (2018) requested
  data and code for 204 articles published under a sharing policy; they obtained
  materials for 44% and could reproduce results for 26%.
- **Even when archived, much data is not reusable.** Roche et al. (2015), cited in
  the agricultural-governance literature below, surveyed 100 ecology and evolution
  datasets and found that 64% were archived in a way that rendered reuse partially
  or entirely impossible, due to poor or missing metadata or non-machine-readable
  formatting. Broader audits report data accessible from repositories for only a
  small fraction of examined papers.

## 2. The analysis is rarely shared, and often will not reproduce even when it is

This is the strand that maps most directly onto OpenFurrow's value proposition:
storing the analysis with the data and being able to re-run it.

- **Code sharing lags data sharing badly.** Kambouris et al. (2024), from an
  agriculture and ecosystem-science faculty, surveyed 177 meta-analyses: about
  75% shared data in some form, but only 16% shared code and only 15% shared both.
  Mislan et al. (2016) found that in 2015 only 14% of 96 ecology journals required
  code versus 38% for data; Culina et al. (2020) found that even after most of
  those journals came to mandate or encourage code, only 27% of sampled articles
  actually shared any.
- **When both data and code exist, reproduction still frequently fails.** Kambouris
  et al. (2024) reproduced a target result from only about 27% (values exact) up to
  73% (values within 10%) of the 26 articles that shared both -- roughly 4% to 11%
  of the original 177. The failure modes are the important part, because they are
  structural and avoidable: stochastic methods (bootstrapping, MCMC, multiple
  imputation) run without a recorded random seed; mismatches between shared code
  and shared data; and underspecified environments (in their sample the R version
  was stated in only 62% of cases and package versions in only 23%).
- **The same failure modes recur across agricultural and numerical modeling.**
  White et al. (2025), a Perspective from crop-modeling authorities, catalog why
  numerical and statistical results fail to reproduce: data inadvertently modified
  over time (handling of outliers or missing values, or database values being
  updated); workflows that require manual file manipulation, inviting error;
  uncontrolled stochastic steps such as weather generation; and software, version,
  or compiler differences. Research using computational notebooks has often proved
  unreproducible because the executed steps differed from the documented order (as
  reviewed by White et al. 2025). Comparing 455 systems-biology models,
  Tiwari et al. (2021) could not reproduce half. In geoscience, Konkol et al. (2019)
  recreated analyses from 41 open-access papers and found four irreproducible and
  two only partially resolved, with 33 requiring active troubleshooting.
- **Why this is the OpenFurrow argument.** A single, self-describing artifact that
  carries the data, the exact analysis, a fixed seed, the method, and a content hash
  of the inputs removes precisely these failure modes: the seed makes stochastic
  steps recoverable, the one-artifact design removes code/data mismatch, the recorded
  method and versions remove environment drift, and the hash makes any change to the
  inputs visible. The literature is, in effect, a list of the things this design is
  built to prevent.

## 3. Agriculture specifically lags -- and is actively asking for this

- **Agriculture trails other data-intensive fields, by its own account.** Devare et
  al. (2023, full text reviewed) document that agriculture has lagged biomedicine in
  making data open and interoperable; that agricultural data still too often lives on
  individual laptops; that even when it reaches public repositories it has
  traditionally been summary tables or metadata rather than the raw, well-described
  data needed for reanalysis; and that where raw data is available it is often
  opaquely annotated and not interoperable, with variables described by individual
  choice rather than standards. They tie this to a "my research, my data" research
  culture in a field that is traditionally field-based, multi-season, and
  hypothesis-driven, where reanalysis of secondary data is still new to most
  scientists.
- **The public-sector and university gap is explicit.** Devare et al. (2023) note
  that most of the 76 US land-grant universities have no explicit policy governing
  open data sharing, and that where data policies exist, few require the consistent
  use of standards. On the journal side they cite Vasilevsky et al. (2017): just
  under 40 of 318 biomedical journals explicitly required data sharing as a condition
  of publication. This is precisely the underserved, standards-poor middle that an
  open, supported tool could serve.
- **FAIR adoption in agriculture is aspirational, not achieved.** A systematic review
  (Sarabia-Sanchez et al., Agriculture 2022) finds FAIR principles could play a key
  role but that there are few published studies of actual adoption, and it sets out
  the specific barriers to making agricultural data FAIR.
- **There are explicit calls for exactly this category of tool.** An agronomic-
  provenance framework paper (Computers and Electronics in Agriculture, 2019) argues
  that even exemplary agricultural research can be irreproducible, that funders and
  reviewers are demanding open data and reproducibility, and that there are no
  accepted criteria for tying data-driven agronomic experiments to their provenance.
  It proposes wrapping reusable analysis scripts in a workflow that captures
  provenance to standard (W3C PROV) repositories, so experiments can be managed,
  shared, and re-run -- positioning such a layer as the primary integration point for
  statistical tools in agronomy. White et al. (2025) similarly recommend open-source,
  peer-reviewed software; placing inputs, parameters, and control scripts in public
  repositories; version control; and publisher certification or peer review of
  reproducibility (as piloted at PLOS Computational Biology), pointing to the
  minimum data-and-code standards proposed for ecology and evolution by Jenkins et
  al. (2023). A regional-agronomy reproducibility guide makes the same point plainly:
  the only way to assure reproducibility is to keep the whole analytical workflow in
  scripts, ideally in free software so a license is not a barrier. That is a
  description of the product category.
- **Even purpose-built repositories fall short on the analysis-critical detail.**
  White et al. (2025) note that datasets in a major public agricultural repository
  frequently lack the environment and management data needed to reuse them, and that
  in a study of 426 modeled potato experiments (Ojeda et al. 2021) errors occurred in
  every element -- inputs, parameters, and evaluation data. Completeness, not just
  availability, is the bar.
- **Standards already exist to build against.** The plant-phenotyping community has
  the MIAPPE metadata standard and the Breeding API; crop modeling has the ICASA data
  standards and the AgMIP ecosystem; the public sector has the CGIAR ontologies and
  GARDIAN data-to-analytics ecosystem, the USDA Ag Data Commons, and metadata schemas
  such as CG Core and the Crop Ontology. These are integration targets and potential
  allies, not competitors.
- **There is ag-specific reproducibility-crisis work too**, including Kool et al.
  (2020), which reviews on-farm experimental studies, scores how well they describe
  the yield-determining factors needed to reproduce them (internal validity), and
  assesses how well they define the populations and settings their findings
  generalize to (external validity).

## 4. Honest read of the limits

- **A documented problem is not an adopting customer.** "There is a real, cited
  literature complaining about this" is a strong signal that the pain is genuine. It
  is not the same as a journal, university, or program committing to adopt and
  maintain a tool; that is a governance, trust, and incentives lift.
- **Policy interventions help but under-deliver on their own.** Mandates and "on
  request" statements have repeatedly failed to produce actual code sharing or
  reproducibility (sections 1 and 2), and only a small minority of journals require
  data or code as a condition of publication (Vasilevsky et al. 2017; Mislan et al.
  2016). The trend is improving over time -- one bioscience department's
  share-all-relevant-data rate rose from about 7% in 2014 to about 45% in 2023 --
  which cuts both ways: momentum exists, but the ceiling for policy without tooling is
  visibly low. A supported tool that makes the reproducible path the easy path is a
  plausible complement to policy, which is the opening.
- **The incumbents here are standards, repositories, and public-sector platforms**
  (FAIR, MIAPPE, the Breeding API, ICASA/AgMIP, CGIAR's GARDIAN, the USDA Ag Data
  Commons, and general repositories such as Dryad, Zenodo, and Figshare), not one-stop
  reproducible-analysis workbenches. That is the gap, and it argues for interoperating
  with those standards rather than competing with them.

## References

Access is marked **[open]** or **[paywalled]**. Items flagged **-> obtain** are
paywalled and worth reading in full; see the note to the owner below.

Data availability and decay:
- Vines, T. H., et al. (2014). The availability of research data declines rapidly with
  article age. Current Biology 24(1):94-97. doi:10.1016/j.cub.2013.11.014. **[open]**
  (author copy on arXiv 1312.5670; dataset on Dryad).
- Tedersoo, L., et al. (2021). Data sharing practices and data availability upon
  request differ across scientific disciplines. Scientific Data 8:192. **[open]**
  (PMC8381906).
- Stodden, V., Seiler, J., & Ma, Z. (2018). An empirical analysis of journal policy
  effectiveness for computational reproducibility. PNAS 115(11):2584-2589. **[open]**.
- Roche, D. G., Kruuk, L. E. B., Lanfear, R., & Binning, S. A. (2015). Public data
  archiving in ecology and evolution: how well are we doing? PLOS Biology
  13(11):e1002295. **[open]**.
- Deeb, H., Creasey, S., Lucini de Ugarte, D., et al. (2025). The rise of open data
  practices among bioscientists at the University of Edinburgh. PLOS ONE 20(7):e0328065.
  doi:10.1371/journal.pone.0328065. **[open]** (the share-all-relevant-data rate rose
  from about 7% in 2014 to about 45% in 2023).

Analysis / computational reproducibility:
- Kambouris, S., Wilkinson, D. P., Smith, E. T., & Fidler, F. (2024). Computationally
  reproducing results from meta-analyses in ecology and evolutionary biology using
  shared code and data. PLOS ONE 19(3):e0300333. **[open]** (PMC10936784). Full text
  reviewed.
- Culina, A., van den Berg, I., Evans, S., & Sanchez-Tojar, A. (2020). Low availability
  of code in ecology: a call for urgent action. PLOS Biology 18(7):e3000763. **[open]**.
- Mislan, K. A. S., Heer, J. M., & White, E. P. (2016). Elevating the status of code in
  ecology. Trends in Ecology & Evolution 31(1):4-7. **[paywalled]**.
- Tiwari, K., et al. (2021). Reproducibility in systems biology modelling. Molecular
  Systems Biology 17:e9982. **[open]**.
- Konkol, M., Kray, C., & Pfeiffer, M. (2019). Computational reproducibility in
  geoscientific papers. International Journal of Geographical Information Science
  33(3):408-429. **[paywalled]**.

Agriculture-specific:
- Devare, M., Arnaud, E., Antezana, E., & King, B. (2023). Governing agricultural data:
  challenges and recommendations. In Williamson, H. F. & Leonelli, S. (eds), Towards
  Responsible Plant Data Linkage. Springer, Cham. doi:10.1007/978-3-031-13276-6_11.
  **[open]** (CC BY). Full text reviewed.
- White, J. W., Boote, K. J., Kimball, B. A., et al. (2025). From field to analysis:
  strengthening reproducibility and confirmation in research for sustainable
  agriculture. npj Sustainable Agriculture 3:27. doi:10.1038/s44264-025-00067-z.
  **[open]**. Full text reviewed.
- da Cruz, S. M. S., & do Nascimento, J. A. P. (2019). Towards integration of
  data-driven agronomic experiments with data provenance (RFlow). Computers and
  Electronics in Agriculture (ScienceDirect PII S0168169917315004).
  **[paywalled] -> obtain** (abstract and figures reviewed; full text behind Elsevier).
- Sarabia-Sanchez and co-authors. The role of FAIR data towards sustainable
  agricultural performance: a systematic literature review. Agriculture (MDPI, 2022),
  12(2):309. **[open]**.
- Kool, H., Andersson, J. A., & Giller, K. E. (2020). Reproducibility and external
  validity of on-farm experimental research in Africa. Experimental Agriculture
  56(4):587-607. doi:10.1017/S0014479720000174. **[paywalled] -> obtain** (abstract
  reviewed; its ground is also covered by White et al. 2025, which cites it).
- The benefits and struggles of FAIR data: the case of reusing plant phenotyping data.
  (2023). **[open]** (PMC10345100). Introduces MIAPPE and the Breeding API.
- Vasilevsky, N. A., Minnier, J., Haendel, M. A., & Champieux, R. E. (2017). Reproducible
  and reusable research: are journal data sharing policies meeting the mark? PeerJ
  5:e3208. **[open]**.
- Jenkins, G. B., et al. (2023). Reproducibility in ecology and evolution: minimum
  standards for data and code. Ecology and Evolution 13:e9961. **[open]**.
- Ojeda, J. J., et al. (2021). Assessing errors during simulation configuration in crop
  models -- a global case study using APSIM-Potato. Ecological Modelling 458:109703.
  **[paywalled]**.

Context (general reproducibility):
- Perkel, J. M. (2020). Challenge to scientists: does your ten-year-old code still run?
  Nature 584:656-658. **[paywalled]**.
- National Academies (2019). Reproducibility and Replicability in Science. **[open]**.

Web resources:
- Regional Agronomy: Reproducibility. reagro.org/reproduce/reproducibility.html.
  **[open]** (argues that assuring reproducibility means keeping the whole analytical
  workflow in scripts, ideally in free software).

## Note to the owner: full texts

Read in full for this note: the governance chapter (Devare et al. 2023), the npj
Sustainable Agriculture Perspective (White et al. 2025), and the computational-
reproducibility study (Kambouris et al. 2024) -- all open access. Most other
load-bearing items are open access and summarized above.

Still paywalled and worth obtaining if you want the primary text:
- The agronomic-provenance (RFlow) paper, Computers and Electronics in Agriculture,
  2019 -- the closest published description of our exact category (Elsevier; only
  gated author copies found).
- Kool et al. 2020, Experimental Agriculture (Cambridge) -- though White et al. 2025
  already covers its on-farm-reproducibility argument and cites it, so this is
  optional.
