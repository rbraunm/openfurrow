# 0021 - Spatially balanced complete blocks, by a procedure of our own

**Status:** Accepted. Reversible while no trial exists outside development.

## Context

The research specialist named the spatially balanced RCBD among the arrangements in use
(worklist REC-7). In a field, neighbouring plots share soil and pest pressure; a plain
RCBD can, by chance, put the same two treatments side by side in every block, or a
treatment at the edge of every block. A spatially balanced layout spreads them: every
pair of treatments is, on average across blocks, the same distance apart, and no
treatment takes the same position more often than it must (van Es, Gomes, Sellmann and
van Es 2007, Geoderma 140:346-352). It is analysed as an ordinary RCBD. ARM offers such
layouts but does not publish its procedure; the published method uses simulated
annealing, whose acceptance rule calls the exponential function, which math libraries do
not all round alike.

## Decision

- **A method of our own, `sha256SpatialBalance1`**, specified in full in
  `openfurrow/design/spatialBalance.py`: the start is the shuffle of
  `sha256FisherYates1` on a stream of its own; the search is threshold accepting (Dueck
  and Scheuer 1990) with a fixed number of moves and a falling integer threshold, every
  draw from the SHA-256 stream; the cost is the sum over pairs of
  (3 S - r(t + 1))^2 plus a weighted count of repeated positions, S being the pair's
  summed distance. Every quantity is an integer, so any implementation reproduces the
  layout exactly, and a layout is checked by regenerating it, as decision 0015 requires.
- **RCBD only.** A split plot is refused with the method. The first block may be left in
  treatment order.
- **Analysed as an RCBD**; the report names the arrangement.

## Evidence

Measured over five seeds per size (spread = standard deviation of the pairs' mean
distances; repeats = positions a treatment holds more often than it must):

| Treatments x blocks | Plain spread | Balanced spread | Repeats plain / balanced | Seconds |
|---|---|---|---|---|
| 5 x 4 | 0.51 | 0.32 | 5.8 / 0 | 0.1 |
| 10 x 4 | 1.15 | 0.69 | 5.4 / 0 | 0.3 |
| 20 x 6 | 1.88 | 1.32 | 12.4 / 0 | 1.6 |
| 30 x 4 | 3.47 | 2.85 | 6.8 / 0 | 4.1 |

Five times as many moves narrowed the spread only slightly (0.32 to 0.29 at 5 x 4), so the
number of moves is set where more buys little. Layouts are kept in memory once made,
because each check of a trial regenerates its layout.

## Consequences

- No schema or store change beyond the new method name.
- Our layouts will not equal ARM's for the same treatments; a layout made in ARM comes in
  as an imported layout.
