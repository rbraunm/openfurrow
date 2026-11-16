# 0018 - Targets are named once; a rating names the target it rates

**Status:** Accepted. Reversible while no trial exists outside development.

## Context

The trial record had no place for the pests, weeds and diseases a trial is about, which
the research specialist asked for (worklist REC-2) and which EPPO PP 1/181, Appendix 1,
section 1.1 lists first: the organisms the crop is protected against, by scientific name or
EPPO code. A rating of disease severity said which disease only in its name.

## Decision

- **A trial lists its targets**: a code, a common name, a kind (weed, disease, insect,
  mite, nematode, mollusc, other), and the scientific name and EPPO code where known.
  "Target" is EPPO's word and covers weeds and diseases, which are not pests in common
  speech.
- **An EPPO code is checked for its shape** (five or six capital letters or digits), not
  against EPPO's list, which the tool does not carry.
- **A rating may name the target it rates**, by code, and the code must be declared. A
  rating of the crop itself (yield, phytotoxicity) names none.
- The stage of a target at an application or an assessment stays text for now.

## Consequences

- Schema 0.5.0, store version 5; every trial's content hash changed.
- The report lists the targets, and the ratings table shows each rating's target.
- The crop's own EPPO code belongs with the planting details (REC-1).
