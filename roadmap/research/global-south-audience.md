# The global-South research audience: landscape and fit

Purpose: ground the candidate audience -- resource-constrained, largely
public-sector agricultural research in the global South -- with evidence on who is
there, what tools they already use, who funds the space, and where OpenFurrow
actually fits, so the audience commitment is grounded rather than assumed. This is
an evidence file, not a plan; the roadmap and decision records are where choices
live. Findings are drawn from the sources listed at the end (institutional pages,
funder statements, and literature), gathered the way `research/landscape.md` was.

## Who is there

The institutions are national agricultural research systems (NARS), universities,
regional centres of excellence, CGIAR centers, and crop-breeding networks. Research
operates largely in English, French, and Portuguese, so the anglophone research
community is reachable with an English UI while French and lusophone regions are the
first real localization pulls (see decision 0007). The people OpenFurrow fits are
researchers running agronomy, efficacy, variety-evaluation, and on-farm trials --
which, as the tool landscape shows, is a different niche from molecular breeding
pipelines.

## The tool landscape, and where the niches actually are

### Breeding trial management: densely occupied, well funded

The plant-breeding niche is thoroughly served by a Gates- and CGIAR-funded stack,
so it is not a place to compete head-to-head:

- The Integrated Breeding Platform's Breeding Management System (BMS) was built
  explicitly to support plant breeders in developing countries, is deployed with
  NARS across Africa, is BrAPI-compliant, and already offers NARS internal data
  ownership with optional sharing to CGIAR centers.
- BreedBase (Boyce Thompson Institute / Cornell) is a breeding management and
  analysis system that NARS partners have adopted at scale for cassava, yam, banana,
  and sweetpotato.
- The Enterprise Breeding System (EBS) is CGIAR's newer entrant, and the Excellence
  in Breeding platform (now folded into OneCGIAR) drives adoption, digitization
  training, and field data-capture equipment.

### Field data collection: established and open

Open-source Android field data capture (the Field Book app and similar handheld
tools) is promoted through the CGIAR breeding-modernization programs. This is an
integration target, not a competitor.

### Analysis: a gap that recently reopened -- the wedge

- GenStat (VSN International) is the classic "by and for agricultural researchers"
  statistics package. Its free GenStat Discovery Edition served the developing world
  from 2003, reaching on the order of 89 countries and thousands of researchers,
  supported by the University of Reading's Statistical Services Centre, the World
  Agroforestry Centre, and ILRI. It was **discontinued around 2020**, replaced by
  tiered paid licensing. The free, purpose-built analysis tool for this exact
  audience is now gone.
- The remaining free option is the R ecosystem (agricolae, META-R, Mr.Bean) --
  powerful but a steeper learning curve -- or spreadsheets.
- The rationale given at that tool's launch is almost verbatim OpenFurrow's thesis:
  high-quality statistics software is unaffordable for many African institutes and
  universities; research often goes unpublished because the statistical analysis was
  incorrect or inappropriate; and results suffer from non-visibility. Free, correct,
  auditable analysis plus reproducibility and visibility is precisely what OpenFurrow
  offers.

This is the wedge: free and affordable, correct, auditable, reproducible analysis
and trial management for agronomy, efficacy, variety-evaluation, and on-farm trials
-- adjacent to the breeding platforms, filling the gap the GenStat Discovery
discontinuation reopened.

### Standards to build against

BrAPI (the Breeding API), MIAPPE, and the ICASA crop-modeling variables are the
interoperability standards of this ecosystem -- integration targets and potential
allies, consistent with the interoperability track in `milestones.md`.

## Who funds the space

- **The Gates Foundation dominates.** It funds CGIAR (including a budget doubling),
  the CGIAR Open Access / Open Data Initiative (2015), the Platform for Big Data in
  Agriculture (2017), the breeding-modernization programs, the Breeding Management
  System, and the BrAPI initiative; its 2021 open-data policy requires FAIR and open
  licenses; and it has made multi-billion-dollar smallholder and climate-adaptation
  commitments.
- **Other major donors** in developing-world agriculture are the World Bank, the FAO
  (co-lead with Gates of a large smallholder-data program), IFAD, the EU, and Canada's
  IDRC, with research-capacity building channelled through bodies such as RUFORUM and the
  University of Reading.
- **A recent shift: USAID's closure.** USAID (which ran Feed the Future) was historically
  a major donor in this space. It was shut down in 2025 and its remaining programs were
  absorbed into the US State Department amid deep cuts, so US bilateral funding for
  developing-world agricultural research contracted sharply. The other donors above remain,
  but the landscape is materially thinner, which if anything strengthens the case for a
  free, owned, low-cost tool and cautions against leaning on US bilateral aid as a funding
  path.
- **Caveat on fit.** The money concentrates on two things: CGIAR institutional
  breeding and agronomy platforms, and farmer-facing digital advisory and AI (SMS,
  apps, weather and pest alerts). Independent-researcher analysis tooling -- the
  GenStat Discovery slot -- is adjacent to, not squarely inside, the main funding
  streams. The natural funding fit for OpenFurrow is the open-data, FAIR, and
  reproducibility mandates and the research-capacity-building lines, not the
  farmer-advisory or breeding-pipeline lines.

## Data sovereignty: a responsibility and a differentiator

Data sovereignty and farmers' and collective data rights are a live, contested topic
in global-South agriculture. The CARE Principles for Indigenous Data Governance --
Collective benefit, Authority to control, Responsibility, Ethics -- have emerged as a
people-centric complement to the machine-oriented FAIR principles, and critics of
current African data-governance policy argue it over-focuses on personal privacy
while overlooking collective and community risks, calling for participatory,
farmer-centered governance. CGIAR has begun promoting data-governance frameworks that
protect smallholder data rights.

OpenFurrow's owned, portable, single-file model plus the configurable-privacy layer
(decision 0005) aligns with this and is a differentiator the cloud incumbents lack.
But on-farm and participatory trials involve farmer-cooperator data, so CARE, not
just FAIR, is a design responsibility on the community-facing surfaces -- a point in
favor of the project and an obligation, not only a feature.

## Constraints that shape the tool

Poor and intermittent connectivity, limited infrastructure, and cost recur across the
literature as the barriers to digital adoption in this setting. That directly
validates the tool's free, offline-capable, low-spec, owned posture, and the
localization-readiness recorded in decision 0007.

## What this means for OpenFurrow

- The audience is real, mission-aligned, and fundable, and its documented pain --
  unaffordable statistics, incorrect analysis, and invisible results -- maps almost
  exactly onto the tool's core value.
- The wedge is specific and must be stated as such: **not** breeding-pipeline
  management (occupied by well-funded Gates and CGIAR platforms), **but** free and
  affordable, correct, auditable, reproducible analysis and trial management for
  agronomy, efficacy, variety-evaluation, and on-farm trials, run by NARS,
  universities, and independent researchers -- filling the reopened GenStat Discovery
  gap and interoperating with BrAPI, MIAPPE, ICASA, and the public repositories
  rather than fighting them.
- Honest risks: the institutional space is crowded and well funded; the dominant
  funding streams do not squarely target researcher analysis tooling; adoption needs
  a real partner (a NARS, a university network such as RUFORUM, or a CGIAR center)
  both to reach users and to avoid guessing workflows; and CARE and sovereignty are a
  responsibility, not just a checkbox.
- Recommendation: name resource-constrained global-South public-sector agricultural
  research a **primary early audience -- scoped to the analysis and agronomy-trial
  wedge above, and gated on partner validation before heavy build**, distinct from
  the breeding-pipeline space. The readiness investments already decided (offline and
  low-spec intent, decision 0007 localization-readiness, decision 0005 configurable
  privacy) are the right near-term work; the audience commitment should be recorded
  but not treated as a build mandate until a partner is in the loop.

## References

Access is marked **[open]** or **[paywalled]**; institutional and news pages are
marked **[web]**.

Tools and platforms:
- Integrated Breeding Platform / Breeding Management System -- integratedbreeding.net
  (our work; IBP-EiB collaboration) and the Generation Challenge Programme IBP brief.
  **[web]**.
- BreedBase adoption by NARS -- CGIAR MEL project record; Boyce Thompson Institute.
  **[web]**.
- Excellence in Breeding / Enterprise Breeding System -- excellenceinbreeding.org;
  2021 EiB annual report to CGIAR. **[web]**.
- GenStat Discovery Edition: launch and reach -- World Agroforestry (ICRAF) news and
  VVOB "GenStat Discovery Edition for everyday use"; discontinuation -- VSNi, "Genstat
  Discovery Edition: the path forward" (2025). **[web]**.

Funders:
- Devare, M., Arnaud, E., Antezana, E., & King, B. (2023). Governing agricultural
  data: challenges and recommendations. In Towards Responsible Plant Data Linkage.
  Springer. doi:10.1007/978-3-031-13276-6_11 (Gates 2021 open-data policy; CGIAR Open
  Access / Open Data Initiative; Big Data Platform). **[open]**.
- Gates Foundation agricultural-development materials and COP27/COP30 smallholder and
  climate-adaptation commitments -- gatesfoundation.org. **[web]**.
- "Big-data project aims to transform farming in world's poorest countries" -- Nature
  news (2018), the FAO-Gates USD 500-million smallholder-data program. **[web]**.
- Top international agricultural donors overview -- fundsforNGOs (World Bank, FAO, IFAD,
  EU, Gates, and others; USAID historically, until its 2025 closure). **[web]**.
- USAID shutdown and merger into the US State Department (July 2025) -- NPR; US State
  Department statements. **[web]**.

Data sovereignty:
- Datafying African agriculture: from data governance to farmers' rights.
  Development (2024). doi:10.1057/s41301-024-00405-7. **[paywalled]**.
- The rise of digital agriculture and dispossession in Africa -- European Commission
  Knowledge for Policy summary. **[web]**.
- AgriTrust: a federated semantic governance framework for trusted agricultural data
  sharing (2025), arXiv 2511.05572 -- summarizes the CARE Principles and agricultural
  data sovereignty. **[open]**.
- Digital solutions in agriculture for African smallholders -- Brookings (2025), on
  the CGIAR Digital Transformation Accelerator and data-governance frameworks.
  **[web]**.

Constraints:
- Challenges and opportunities in smallholder agriculture digitization in South
  Africa. Frontiers in Sustainable Food Systems (2025).
  doi:10.3389/fsufs.2025.1583224 (connectivity, infrastructure, and cost barriers).
  **[open]**.
