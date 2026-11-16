# SPDX-License-Identifier: Apache-2.0
"""Spatially balanced complete blocks (decision 0021).

Treatments are laid out in linear blocks, each block a complete set, so the trial is
analysed as an ordinary RCBD. A spatially balanced layout also spreads the treatments
so that every pair of them is, on average across blocks, the same distance apart, and
no treatment sits at the same position in more blocks than it must (van Es, Gomes,
Sellmann and van Es 2007, Geoderma 140:346-352). For a pair (i, j),

    S(i, j) = sum over blocks of |position of i - position of j|,

and perfect balance gives every pair S = r(t + 1)/3 for t treatments in r blocks.

Method `sha256SpatialBalance1`. Every quantity is an integer, so any implementation in
any language reproduces the layout exactly:

1. The random stream is that of `sha256FisherYates1` (steps 1 to 3 in
   `randomization.py`) with the text "sha256SpatialBalance1" in place of the method name.
2. The start is every block shuffled as `sha256FisherYates1` steps 4 to 6 do, on this
   stream.
3. The cost of a layout is D + W * R, where D is the sum over pairs i < j of
   (3 S(i, j) - r(t + 1))^2; R is the sum over treatments and positions of
   max(n - q, 0), n being the number of blocks with that treatment at that position and
   q = ceil(r / t); and W = 9 (t + 1)^2.
4. The search makes M = min(20000, 200 r t) moves. The threshold of move k (counting
   from 0) is T(k) = floor(T0 (M - 1 - k) / M), with T0 = floor(C0 / 10) and C0 the cost
   of the start. A move draws a block below the number of blocks that may move (block 1
   may not when it is left in treatment order), then a position x below t, then a
   position y below t - 1, increased by one when y >= x; it swaps the treatments at x
   and y in that block when the change in cost is at most T(k).
5. The layout is the one of lowest cost met, the first if several tie.
"""

from __future__ import annotations

import functools

from openfurrow.design.stream import Sha256Stream, shuffled
from openfurrow.schema.layout import PlotAssignment, TrialLayout
from openfurrow.schema.trialPackage import DesignType, RandomizationMethod, TrialPackage

_maxMoves = 20000
_movesPerPlot = 200


def balanceCost(orders: list[list[int]], treatmentCount: int) -> int:
  """The cost of step 3 for blocks given as treatment indices in position order, counted in full."""
  blockCount = len(orders)
  position = [{treatment: index for index, treatment in enumerate(order)} for order in orders]
  target = blockCount * (treatmentCount + 1)
  distance = 0
  for first in range(treatmentCount):
    for second in range(first + 1, treatmentCount):
      total = sum(abs(blockPositions[first] - blockPositions[second]) for blockPositions in position)
      distance += (3 * total - target) ** 2
  allowed = -(-blockCount // treatmentCount)
  repeats = 0
  for treatment in range(treatmentCount):
    for place in range(treatmentCount):
      count = sum(1 for blockPositions in position if blockPositions[treatment] == place)
      repeats += max(count - allowed, 0)
  return distance + _repeatWeight(treatmentCount) * repeats


def _repeatWeight(treatmentCount: int) -> int:
  return 9 * (treatmentCount + 1) ** 2


@functools.lru_cache(maxsize=64)
def spatiallyBalancedOrders(
  treatmentCount: int, blockCount: int, seed: int, firstBlockFixed: bool,
) -> tuple[tuple[tuple[int, ...], ...], int]:
  """The blocks of method sha256SpatialBalance1 and their cost, kept as the search tracked it.

  Blocks are treatment indices in position order. Every layout check regenerates the
  layout, and the search takes seconds for large trials, so results are kept in memory;
  they depend on nothing but the arguments.
  """
  stream = Sha256Stream(seed, RandomizationMethod.sha256SpatialBalance1.value)
  orders = [
    list(range(treatmentCount)) if block == 0 and firstBlockFixed else shuffled(treatmentCount, stream)
    for block in range(blockCount)
  ]
  where = [[0] * treatmentCount for _ in range(blockCount)]
  for block, order in enumerate(orders):
    for place, treatment in enumerate(order):
      where[block][treatment] = place
  pairTotals = [[0] * treatmentCount for _ in range(treatmentCount)]
  for first in range(treatmentCount):
    for second in range(treatmentCount):
      pairTotals[first][second] = sum(abs(where[b][first] - where[b][second]) for b in range(blockCount))
  counts = [[0] * treatmentCount for _ in range(treatmentCount)]
  for block in range(blockCount):
    for treatment in range(treatmentCount):
      counts[treatment][where[block][treatment]] += 1

  target = blockCount * (treatmentCount + 1)
  allowed = -(-blockCount // treatmentCount)
  weight = _repeatWeight(treatmentCount)
  cost = balanceCost(orders, treatmentCount)
  best, bestOrders = cost, [list(order) for order in orders]
  movable = list(range(1 if firstBlockFixed else 0, blockCount))
  if not movable or treatmentCount < 2:
    return tuple(tuple(order) for order in bestOrders), best
  moves = min(_maxMoves, _movesPerPlot * blockCount * treatmentCount)
  startThreshold = cost // 10

  def overflow(count: int) -> int:
    return max(count - allowed, 0)

  for move in range(moves):
    threshold = (startThreshold * (moves - 1 - move)) // moves
    block = movable[stream.below(len(movable))]
    x = stream.below(treatmentCount)
    y = stream.below(treatmentCount - 1)
    if y >= x:
      y += 1
    order = orders[block]
    u, v = order[x], order[y]
    change = 0
    pairChanges = []
    for other in order:
      if other == u or other == v:
        continue
      place = where[block][other]
      shiftU = abs(y - place) - abs(x - place)
      if shiftU:
        oldU, oldV = pairTotals[u][other], pairTotals[v][other]
        newU, newV = oldU + shiftU, oldV - shiftU
        change += (3 * newU - target) ** 2 - (3 * oldU - target) ** 2
        change += (3 * newV - target) ** 2 - (3 * oldV - target) ** 2
        pairChanges.append((other, newU, newV))
    change += weight * (
      overflow(counts[u][x] - 1) - overflow(counts[u][x]) + overflow(counts[u][y] + 1) - overflow(counts[u][y])
      + overflow(counts[v][y] - 1) - overflow(counts[v][y]) + overflow(counts[v][x] + 1) - overflow(counts[v][x])
    )
    if change > threshold:
      continue
    order[x], order[y] = v, u
    where[block][u], where[block][v] = y, x
    counts[u][x] -= 1
    counts[u][y] += 1
    counts[v][y] -= 1
    counts[v][x] += 1
    for other, newU, newV in pairChanges:
      pairTotals[u][other] = pairTotals[other][u] = newU
      pairTotals[v][other] = pairTotals[other][v] = newV
    cost += change
    if cost < best:
      best, bestOrders = cost, [list(blockOrder) for blockOrder in orders]
  return tuple(tuple(order) for order in bestOrders), best


def generateSpatiallyBalancedLayout(package: TrialPackage) -> TrialLayout:
  """Generate the spatially balanced RCBD plot map for a trial package from its seed."""
  design = package.design
  if design.designType is not DesignType.rcbd:
    raise ValueError(f"spatial balance applies to an RCBD, got {design.designType.value}")
  if design.randomizationMethod is not RandomizationMethod.sha256SpatialBalance1:
    raise ValueError("generateSpatiallyBalancedLayout requires method sha256SpatialBalance1")
  treatmentCodes = [treatment.treatmentCode for treatment in package.treatments]
  if len(treatmentCodes) > 99:
    raise ValueError(f"{len(treatmentCodes)} treatments exceeds the 99-per-block plot-number scheme")
  orders, _ = spatiallyBalancedOrders(
    len(treatmentCodes), design.replications, design.randomizationSeed, design.firstBlockInTreatmentOrder,
  )
  plots = [
    PlotAssignment(
      plotNumber=(block + 1) * 100 + place + 1,
      block=block + 1,
      positionInBlock=place + 1,
      treatmentCode=treatmentCodes[treatment],
    )
    for block, order in enumerate(orders)
    for place, treatment in enumerate(order)
  ]
  from openfurrow.design.randomization import generatedCheckPlots

  return TrialLayout.forPackage(package, plots, generatedCheckPlots(package, plots))
