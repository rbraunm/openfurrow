# SPDX-License-Identifier: Apache-2.0
"""Least squares on the plots present, for a table with missing plots (decision 0043).

The model is the design's own: a value is a general level plus its treatment's effect and,
in blocks, its block's effect. It is fitted by least squares to the plots that have a
value, computed natively with numpy (decision 0002):

- the error sum of squares is the residual sum of squares of that fit, on
  n - rank degrees of freedom;
- a term's sum of squares is Type III: what the error sum of squares rises by when the
  term is dropped from the model, so treatment is adjusted for blocks and blocks for
  treatment. With unequal numbers these do not add up to the total;
- a treatment's adjusted (least-squares) mean is the fitted value averaged over every
  block of the design with equal weight, and the covariance matrix of those means, in
  units of the error variance, gives every standard error.

Before any number, the design is checked for estimability on its own structure: the rank
of its matrix of block and treatment indicators and the connectedness of the plots that
have values. statsmodels validates the fit in the tests, never at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy

from openfurrow.analysis.anova import AnalysisError


@dataclass(frozen=True)
class TreatmentFit:
  """The least-squares fit of treatments, with blocks or without, to the values present."""

  designMatrix: numpy.ndarray
  residuals: numpy.ndarray
  treatmentMeans: numpy.ndarray
  meanCovariance: numpy.ndarray
  treatmentEffects: numpy.ndarray
  blockEffects: numpy.ndarray | None
  errorSumOfSquares: float
  errorDegreesOfFreedom: int
  treatmentSumOfSquares: float
  blockSumOfSquares: float | None
  totalSumOfSquares: float

  def residualOf(self, vector: numpy.ndarray) -> numpy.ndarray:
    """What is left of `vector`, one entry per value present, after the model is fitted to it."""
    return vector - self.designMatrix @ _solve(self.designMatrix, vector)


def _solve(designMatrix: numpy.ndarray, values: numpy.ndarray) -> numpy.ndarray:
  return numpy.linalg.lstsq(designMatrix, values, rcond=None)[0]


def _residualSumOfSquares(designMatrix: numpy.ndarray, values: numpy.ndarray) -> float:
  residuals = values - designMatrix @ _solve(designMatrix, values)
  return float(residuals @ residuals)


def _indicators(index: numpy.ndarray, count: int) -> numpy.ndarray:
  columns = numpy.zeros((index.size, count), dtype=float)
  columns[numpy.arange(index.size), index] = 1.0
  return columns


def _designMatrix(
  treatmentIndex: numpy.ndarray, treatmentCount: int, blockIndex: numpy.ndarray | None, blockCount: int,
) -> numpy.ndarray:
  """A general level, then every block but the first, then every treatment but the first."""
  columns = [numpy.ones((treatmentIndex.size, 1), dtype=float)]
  if blockIndex is not None:
    columns.append(_indicators(blockIndex, blockCount)[:, 1:])
  columns.append(_indicators(treatmentIndex, treatmentCount)[:, 1:])
  return numpy.hstack(columns)


def _meanContrasts(treatmentCount: int, blockCount: int) -> numpy.ndarray:
  """One row per treatment: the coefficients whose combination is its mean over every block alike."""
  blockColumns = max(blockCount - 1, 0)
  contrasts = numpy.zeros((treatmentCount, 1 + blockColumns + treatmentCount - 1), dtype=float)
  contrasts[:, 0] = 1.0
  if blockColumns:
    contrasts[:, 1:1 + blockColumns] = 1.0 / blockCount
  for treatment in range(1, treatmentCount):
    contrasts[treatment, blockColumns + treatment] = 1.0
  return contrasts


def designRank(present: numpy.ndarray) -> int:
  """The rank of the indicators of every block and every treatment over the plots present ([block, treatment])."""
  blockCount, treatmentCount = present.shape
  blockIndex, treatmentIndex = numpy.nonzero(present)
  indicators = numpy.hstack([_indicators(blockIndex, blockCount), _indicators(treatmentIndex, treatmentCount)])
  return int(numpy.linalg.matrix_rank(indicators))


def connectedSets(present: numpy.ndarray) -> list[tuple[list[int], list[int]]]:
  """The plots present, as sets of blocks and treatments joined by sharing a block or a treatment.

  `present` is indexed [block, treatment]. Each set is (block indexes, treatment indexes);
  blocks and treatments with no value belong to none.
  """
  blockCount, treatmentCount = present.shape
  parent = list(range(blockCount + treatmentCount))

  def root(node: int) -> int:
    while parent[node] != node:
      parent[node] = parent[parent[node]]
      node = parent[node]
    return node

  for block in range(blockCount):
    for treatment in range(treatmentCount):
      if present[block, treatment]:
        parent[root(block)] = root(blockCount + treatment)
  members: dict[int, tuple[list[int], list[int]]] = {}
  for block in range(blockCount):
    if present[block].any():
      members.setdefault(root(block), ([], []))[0].append(block)
  for treatment in range(treatmentCount):
    if present[:, treatment].any():
      members.setdefault(root(blockCount + treatment), ([], []))[1].append(treatment)
  return sorted(members.values(), key=lambda pair: (pair[1], pair[0]))


def requireEstimableBlocks(
  assessmentCode: str, present: numpy.ndarray, treatmentCodes: list[str], blocks: list[int],
  plotNumbers: numpy.ndarray,
) -> None:
  """Refuse a block design whose missing plots leave something that cannot be estimated, saying what and where.

  `present` and `plotNumbers` are indexed [block, treatment].
  """
  blockCount, treatmentCount = present.shape
  reasons = []
  for treatment in numpy.flatnonzero(~present.any(axis=0)):
    reasons.append(
      f"treatment '{treatmentCodes[treatment]}' has no value in any block "
      f"(plots {sorted(int(number) for number in plotNumbers[:, treatment])}), so its mean cannot be estimated"
    )
  for block in numpy.flatnonzero(~present.any(axis=1)):
    reasons.append(
      f"block {blocks[block]} has no value on any plot "
      f"(plots {sorted(int(number) for number in plotNumbers[block])}), so means adjusted to all "
      f"{blockCount} blocks cannot be estimated"
    )
  if not reasons:
    rank = designRank(present)
    valueCount = int(present.sum())
    sets = connectedSets(present)
    if rank != blockCount + treatmentCount - len(sets):
      raise AnalysisError(
        f"internal error: design rank {rank} disagrees with {len(sets)} connected sets of "
        f"{blockCount} blocks and {treatmentCount} treatments"
      )
    if len(sets) > 1:
      described = "; ".join(
        f"treatments {[treatmentCodes[t] for t in treatmentSet]} in blocks {[blocks[b] for b in blockSet]}"
        for blockSet, treatmentSet in sets
      )
      reasons.append(
        f"the design is disconnected: the plots with values fall into {len(sets)} sets that share no block, "
        f"directly or through a chain of blocks, so differences between treatments of different sets cannot be "
        f"estimated ({described})"
      )
    elif valueCount - rank < 1:
      reasons.append(
        f"no degrees of freedom are left for error: {valueCount} plots have values, and the blocks and "
        f"treatments take {rank} of them"
      )
  if reasons:
    raise AnalysisError(f"assessment '{assessmentCode}' is not estimable with its missing plots: " + "; ".join(reasons))


def requireEstimableGroups(
  assessmentCode: str, counts: list[int], treatmentCodes: list[str], plotNumbers: list[list[int]],
) -> None:
  """Refuse a design without blocks whose missing plots leave a treatment or the error without a value."""
  reasons = [
    f"treatment '{code}' has no value on any plot (plots {sorted(plots)}), so its mean cannot be estimated"
    for code, count, plots in zip(treatmentCodes, counts, plotNumbers) if count == 0
  ]
  if not reasons and sum(counts) - len(counts) < 1:
    reasons.append(
      f"no degrees of freedom are left for error: {sum(counts)} plots have values, and the treatments take "
      f"{len(counts)} of them"
    )
  if reasons:
    raise AnalysisError(f"assessment '{assessmentCode}' is not estimable with its missing plots: " + "; ".join(reasons))


def meanCovariance(
  treatmentIndex: numpy.ndarray, treatmentCount: int, blockIndex: numpy.ndarray | None, blockCount: int,
) -> numpy.ndarray:
  """The covariance matrix of the adjusted treatment means, in units of the error variance.

  It depends only on which plots have values, never on the values.
  """
  designMatrix = _designMatrix(treatmentIndex, treatmentCount, blockIndex, blockCount)
  contrasts = _meanContrasts(treatmentCount, blockCount if blockIndex is not None else 0)
  return contrasts @ numpy.linalg.inv(designMatrix.T @ designMatrix) @ contrasts.T


def withoutRoundingResidue(sumOfSquares: float, values: numpy.ndarray) -> float:
  """A residual sum of squares of `values`, or zero when it is no more than the arithmetic's own rounding."""
  # A model that reproduces the values exactly leaves residuals near 1e-16 of them, not zeros. Passed on, they would
  # give an F ratio of rounding errors where the analysis has to refuse for want of any error.
  return 0.0 if sumOfSquares <= 1.0e-22 * float(values @ values) else sumOfSquares


def fitTreatments(
  values: numpy.ndarray, treatmentIndex: numpy.ndarray, treatmentCount: int,
  blockIndex: numpy.ndarray | None = None, blockCount: int = 0,
) -> TreatmentFit:
  """Fit treatments, and blocks when given, to the values present; the design must be estimable."""
  designMatrix = _designMatrix(treatmentIndex, treatmentCount, blockIndex, blockCount)
  parameterCount = designMatrix.shape[1]
  if numpy.linalg.matrix_rank(designMatrix) != parameterCount or values.size <= parameterCount:
    raise AnalysisError("internal error: the least-squares fit was asked for a design that is not estimable")
  coefficients = _solve(designMatrix, values)
  residuals = values - designMatrix @ coefficients
  errorSumOfSquares = withoutRoundingResidue(float(residuals @ residuals), values)
  blockColumns = blockCount - 1 if blockIndex is not None else 0
  withoutTreatments = designMatrix[:, :1 + blockColumns]
  treatmentSumOfSquares = _residualSumOfSquares(withoutTreatments, values) - errorSumOfSquares
  blockSumOfSquares = None
  blockEffects = None
  if blockIndex is not None:
    withoutBlocks = numpy.delete(designMatrix, numpy.s_[1:1 + blockColumns], axis=1)
    blockSumOfSquares = _residualSumOfSquares(withoutBlocks, values) - errorSumOfSquares
    blockEffects = numpy.concatenate(([0.0], coefficients[1:1 + blockColumns]))
    blockEffects = blockEffects - blockEffects.mean()
  treatmentEffects = numpy.concatenate(([0.0], coefficients[1 + blockColumns:]))
  return TreatmentFit(
    designMatrix=designMatrix,
    residuals=residuals,
    treatmentMeans=_meanContrasts(treatmentCount, blockCount if blockIndex is not None else 0) @ coefficients,
    meanCovariance=meanCovariance(treatmentIndex, treatmentCount, blockIndex, blockCount),
    treatmentEffects=treatmentEffects - treatmentEffects.mean(),
    blockEffects=blockEffects,
    errorSumOfSquares=errorSumOfSquares,
    errorDegreesOfFreedom=int(values.size - parameterCount),
    treatmentSumOfSquares=treatmentSumOfSquares,
    blockSumOfSquares=blockSumOfSquares,
    totalSumOfSquares=float(((values - values.mean()) ** 2).sum()),
  )
