# SPDX-License-Identifier: Apache-2.0
"""Randomized complete block design (RCBD) layout generation.

Each block receives every treatment exactly once, in an order shuffled independently
of the other blocks. The project owns the whole procedure (decision 0015): no
library's random number generator takes part, so the layout a seed produces is fixed
by this file alone and can be reproduced in any language.

Method `sha256FisherYates1`:

1. The random stream for a seed is the concatenation of
   SHA-256("sha256FisherYates1:<seed>:<counter>") for counter = 0, 1, 2, ..., the seed
   and the counter written in decimal and the text encoded as ASCII.
2. Random words are read from the stream eight bytes at a time, big-endian.
3. An integer below a bound n is drawn by rejection: a word at or above the largest
   multiple of n that fits in 64 bits is discarded, and the first word kept is reduced
   modulo n. Every result is equally likely.
4. A block's order starts as the treatments in package order and is shuffled by
   Fisher-Yates: for each position from the last down to the second, its entry is
   swapped with the entry at a position drawn below that position's number.
5. Blocks are shuffled in order, block 1 first, each continuing the stream where the
   previous one stopped.
6. When the design leaves the first block in treatment order, block 1 keeps package
   order and draws nothing from the stream; shuffling starts with block 2 at the start
   of the stream. A design without that option is laid out by steps 1 to 5 alone.

A changed procedure gets a new method name. This one stays as it is, so a layout
recorded under it can always be regenerated and checked.
"""

from __future__ import annotations

import hashlib

from openfurrow.schema.layout import PlotAssignment, TrialLayout
from openfurrow.schema.trialPackage import DesignType, RandomizationMethod, TrialPackage

_maxTreatmentsPerBlock = 99  # plotNumber = block * 100 + position; positions must stay 2-digit
_wordBytes = 8
_wordRange = 1 << (8 * _wordBytes)


class _Sha256Stream:
  """The random stream of method sha256FisherYates1 for one seed."""

  def __init__(self, seed: int) -> None:
    self._seed = seed
    self._counter = 0
    self._buffer = b""

  def nextWord(self) -> int:
    if len(self._buffer) < _wordBytes:
      text = f"{RandomizationMethod.sha256FisherYates1.value}:{self._seed}:{self._counter}"
      self._buffer += hashlib.sha256(text.encode("ascii")).digest()
      self._counter += 1
    word = int.from_bytes(self._buffer[:_wordBytes], "big")
    self._buffer = self._buffer[_wordBytes:]
    return word

  def below(self, bound: int) -> int:
    limit = _wordRange - _wordRange % bound
    while True:
      word = self.nextWord()
      if word < limit:
        return word % bound


def generateRcbdLayout(package: TrialPackage) -> TrialLayout:
  """Generate the RCBD plot map for a trial package from its seed.

  The package's design must be an RCBD whose layout is generated. Raises for a layout
  that is supplied with the trial instead, and if the treatment count would overflow
  the two-digit plot-position field rather than emitting colliding plot numbers.
  """
  design = package.design
  if design.designType is not DesignType.rcbd:
    raise ValueError(f"generateRcbdLayout requires an RCBD design, got {design.designType.value}")
  if design.randomizationMethod is not RandomizationMethod.sha256FisherYates1:
    raise ValueError(
      f"a layout with randomization method '{design.randomizationMethod.value}' "
      f"is supplied with the trial, not generated"
    )

  treatmentCodes = [treatment.treatmentCode for treatment in package.treatments]
  treatmentCount = len(treatmentCodes)
  if treatmentCount > _maxTreatmentsPerBlock:
    raise ValueError(
      f"{treatmentCount} treatments exceeds the {_maxTreatmentsPerBlock}-per-block plot-number scheme"
    )

  stream = _Sha256Stream(design.randomizationSeed)
  plots: list[PlotAssignment] = []
  for block in range(1, design.replications + 1):
    order = list(range(treatmentCount))
    if not (block == 1 and design.firstBlockInTreatmentOrder):
      for position in range(treatmentCount - 1, 0, -1):
        chosen = stream.below(position + 1)
        order[position], order[chosen] = order[chosen], order[position]
    for positionInBlock, treatmentIndex in enumerate(order, start=1):
      plots.append(
        PlotAssignment(
          plotNumber=block * 100 + positionInBlock,
          block=block,
          positionInBlock=positionInBlock,
          treatmentCode=treatmentCodes[treatmentIndex],
        )
      )

  return TrialLayout.forPackage(package, plots)
