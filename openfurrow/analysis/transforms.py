# SPDX-License-Identifier: Apache-2.0
"""Variance-stabilizing transforms for numeric assessments (decision 0006).

A log or square root may add a declared offset first (log10(x + 1), sqrt(x + 0.5)), as
counts with zeros need (decision 0026); the back-transform takes it off again. Every
transform has a fail-loud domain: a value outside it raises, naming the offending
values, rather than being silently clamped or shifted. The empirical logit and other
count-based adjustments remain a future slice; see decision 0006.

The functions here are pure math over sequences of floats. Applying a transform in
the analysis path, and surfacing it in reports and recommendations, is wired
separately.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from openfurrow.schema.assessment import MeasurementKind, Transform

# Which transforms suit which measurement kind. `none` is always allowed (omitted
# here) and `unspecified` imposes no constraint -- the kind is declared, not
# inferred, so it is never second-guessed. Used by the declared-transform sanity
# check and, later, by transform recommendation.
compatibleTransforms: dict[MeasurementKind, frozenset[Transform]] = {
  MeasurementKind.count: frozenset({Transform.sqrt, Transform.log, Transform.log10}),
  MeasurementKind.proportion: frozenset({Transform.arcsinSqrt, Transform.logit}),
  MeasurementKind.continuous: frozenset({Transform.sqrt, Transform.log, Transform.log10}),
}

# The single canonical variance-stabilizing transform to suggest per measurement kind
# when assumptions are flagged. Advisory only, never applied (decision 0006); each is a
# member of compatibleTransforms for its kind.
preferredTransform: dict[MeasurementKind, Transform] = {
  MeasurementKind.count: Transform.sqrt,
  MeasurementKind.proportion: Transform.arcsinSqrt,
  MeasurementKind.continuous: Transform.log,
}


class TransformError(ValueError):
  """A transform could not be applied: a domain violation or an incompatible kind."""


def _requireDomain(transform: Transform, values: list[float], predicate, requirement: str) -> None:
  offending = [value for value in values if not predicate(value)]
  if offending:
    shown = ", ".join(f"{value:g}" for value in offending[:5])
    more = "" if len(offending) <= 5 else f" (and {len(offending) - 5} more)"
    raise TransformError(
      f"{transform.value} transform requires {requirement}; offending values: {shown}{more}"
    )


def applyTransform(transform: Transform, values: Sequence[float], offset: float) -> list[float]:
  """Apply a transform, after adding `offset`, to numeric values, returning transformed floats.

  Raises TransformError, naming the offending values, if any value is outside the
  transform's domain. `none` returns the values unchanged; only a log or a square root
  takes an offset.
  """
  data = [float(value) for value in values]
  if offset != 0.0 and transform not in (Transform.log, Transform.log10, Transform.sqrt):
    raise TransformError(f"{transform.value} transform takes no offset, got {offset:g}")
  shifted = [value + offset for value in data]
  plus = f" + {offset:g}" if offset else ""
  if transform is Transform.none:
    return data
  if transform is Transform.sqrt:
    _requireDomain(transform, data, lambda v: v + offset >= 0.0, f"values{plus} >= 0")
    return [math.sqrt(v) for v in shifted]
  if transform in (Transform.log, Transform.log10):
    _requireDomain(transform, data, lambda v: v + offset > 0.0, f"values{plus} > 0")
    function = math.log if transform is Transform.log else math.log10
    return [function(v) for v in shifted]
  if transform is Transform.arcsinSqrt:
    _requireDomain(transform, data, lambda v: 0.0 <= v <= 1.0, "proportions in [0, 1]")
    return [math.asin(math.sqrt(v)) for v in data]
  if transform is Transform.logit:
    _requireDomain(transform, data, lambda v: 0.0 < v < 1.0, "proportions in the open interval (0, 1)")
    return [math.log(v / (1.0 - v)) for v in data]
  raise TransformError(f"unknown transform: {transform}")


def backTransformInterval(transform: Transform, low: float, high: float, offset: float) -> tuple[float, float]:
  """Back-transform an interval on the analysed scale to the original scale.

  The part of the interval outside the transform's range (below zero on the square-root
  scale, outside 0 to pi/2 on the angular scale) has no value on the original scale, so
  the interval is cut to the range first; inside it each back-transform is increasing.
  """
  if low > high:
    raise TransformError(f"interval ends out of order: {low} > {high}")
  if transform is Transform.sqrt:
    low, high = max(low, 0.0), max(high, 0.0)
  elif transform is Transform.arcsinSqrt:
    low, high = min(max(low, 0.0), math.pi / 2), min(max(high, 0.0), math.pi / 2)
  return backTransformMean(transform, low, offset), backTransformMean(transform, high, offset)


def backTransformMean(transform: Transform, value: float, offset: float) -> float:
  """Back-transform a value from the transformed scale to the original scale, taking the offset off.

  This is the inverse of the forward function, used to express a transformed-scale
  mean as a point estimate on the original scale -- for the logs a geometric-mean
  estimate, for the proportion transforms the inverse map -- not a symmetric
  interval. `none` returns the value unchanged.
  """
  scalar = float(value)
  if transform is Transform.none:
    return scalar
  if transform is Transform.sqrt:
    return scalar * scalar - offset
  if transform is Transform.log:
    return math.exp(scalar) - offset
  if transform is Transform.log10:
    return 10.0 ** scalar - offset
  if transform is Transform.arcsinSqrt:
    return math.sin(scalar) ** 2
  if transform is Transform.logit:
    return 1.0 / (1.0 + math.exp(-scalar))
  raise TransformError(f"unknown transform: {transform}")


def checkTransformKind(transform: Transform, measurementKind: MeasurementKind) -> None:
  """Raise if a declared transform is incompatible with the declared measurement kind.

  `none` is always allowed, and an `unspecified` kind imposes no constraint (the kind
  is declared, not inferred, so it is not second-guessed). A kind paired with a
  transform outside its compatible set -- for example `logit` on count data -- is a
  declared category error and is rejected.
  """
  if transform is Transform.none or measurementKind is MeasurementKind.unspecified:
    return
  allowed = compatibleTransforms.get(measurementKind, frozenset())
  if transform not in allowed:
    appropriate = ", ".join(sorted(candidate.value for candidate in allowed)) or "none"
    raise TransformError(
      f"{transform.value} transform is not appropriate for {measurementKind.value} data "
      f"(appropriate: {appropriate})"
    )
