# SPDX-License-Identifier: Apache-2.0
"""Randomized complete block design (RCBD) layout generation.

Each block receives every treatment exactly once; the order within a block is an
independent random permutation. Randomization is driven by numpy's PCG64
bit generator, whose stream is documented as reproducible across numpy versions
and platforms, so the same seed always yields the same layout. The RNG produces
only an index permutation per block -- it never touches the treatment data
directly -- which keeps the seed-to-layout mapping simple to audit.
"""

from __future__ import annotations

import numpy

from openfurrow.schema.layout import PlotAssignment, TrialLayout
from openfurrow.schema.trialPackage import DesignType, TrialPackage

_maxTreatmentsPerBlock = 99  # plotNumber = block * 100 + position; positions must stay 2-digit


def generateRcbdLayout(package: TrialPackage) -> TrialLayout:
  """Generate the RCBD plot map for a trial package.

  The package's design must be RCBD. Raises if the treatment count would
  overflow the two-digit plot-position field rather than emitting colliding
  plot numbers.
  """
  design = package.design
  if design.designType is not DesignType.rcbd:
    raise ValueError(f"generateRcbdLayout requires an RCBD design, got {design.designType.value}")

  treatmentCodes = [treatment.treatmentCode for treatment in package.treatments]
  treatmentCount = len(treatmentCodes)
  if treatmentCount > _maxTreatmentsPerBlock:
    raise ValueError(
      f"{treatmentCount} treatments exceeds the {_maxTreatmentsPerBlock}-per-block plot-number scheme"
    )

  generator = numpy.random.Generator(numpy.random.PCG64(design.randomizationSeed))
  plots: list[PlotAssignment] = []
  for block in range(1, design.replications + 1):
    order = generator.permutation(treatmentCount)  # independent draw per block
    for position, treatmentIndex in enumerate(order, start=1):
      plots.append(
        PlotAssignment(
          plotNumber=block * 100 + position,
          block=block,
          positionInBlock=position,
          treatmentCode=treatmentCodes[int(treatmentIndex)],
        )
      )

  return TrialLayout(
    trialCode=package.trial.trialCode,
    designType=DesignType.rcbd,
    randomizationSeed=design.randomizationSeed,
    replications=design.replications,
    treatmentCodes=treatmentCodes,
    plots=plots,
  )
