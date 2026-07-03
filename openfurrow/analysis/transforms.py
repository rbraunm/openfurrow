# SPDX-License-Identifier: Apache-2.0
"""Variance-stabilizing transforms for numeric assessments (decision 0006).

Each transform is the plain form -- no offset -- with a fail-loud domain: a value
outside the transform's domain raises, naming the offending values, rather than
being silently clamped or shifted. Offsets for zeros and boundary values (log(y+c),
the empirical logit, and count-based adjustments that need the trial count) are a
separate future slice; see decision 0006.

The functions here are pure math over sequences of floats. Applying a transform in
the analysis path, and surfacing it in reports and recommendations, is wired
separately.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from openfurrow.schema.trialPackage import MeasurementKind, Transform

# Which transforms suit which measurement kind. `none` is always allowed (omitted
# here) and `unspecified` imposes no constraint -- the kind is declared, not
# inferred, so it is never second-guessed. Used by the declared-transform sanity
# check and, later, by transform recommendation.
compatibleTransforms: dict[MeasurementKind, frozenset[Transform]] = {
  MeasurementKind.count: frozenset({Transform.sqrt, Transform.log}),
  MeasurementKind.proportion: frozenset({Transform.arcsinSqrt, Transform.logit}),
  MeasurementKind.continuous: frozenset({Transform.sqrt, Transform.log}),
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


def applyTransform(transform: Transform, values: Sequence[float]) -> list[float]:
  """Apply a transform to a sequence of numeric values, returning transformed floats.

  Raises TransformError, naming the offending values, if any value is outside the
  transform's domain. `none` returns the values unchanged.
  """
  data = [float(value) for value in values]
  if transform is Transform.none:
    return data
  if transform is Transform.sqrt:
    _requireDomain(transform, data, lambda v: v >= 0.0, "values >= 0")
    return [math.sqrt(v) for v in data]
  if transform is Transform.log:
    _requireDomain(transform, data, lambda v: v > 0.0, "values > 0")
    return [math.log(v) for v in data]
  if transform is Transform.arcsinSqrt:
    _requireDomain(transform, data, lambda v: 0.0 <= v <= 1.0, "proportions in [0, 1]")
    return [math.asin(math.sqrt(v)) for v in data]
  if transform is Transform.logit:
    _requireDomain(transform, data, lambda v: 0.0 < v < 1.0, "proportions in the open interval (0, 1)")
    return [math.log(v / (1.0 - v)) for v in data]
  raise TransformError(f"unknown transform: {transform}")  # defensive; the enum is exhaustive above


def backTransformMean(transform: Transform, value: float) -> float:
  """Back-transform a value from the transformed scale to the original scale.

  This is the inverse of the forward function, used to express a transformed-scale
  mean as a point estimate on the original scale -- for `log` a geometric-mean
  estimate, for the proportion transforms the inverse map -- not a symmetric
  interval. `none` returns the value unchanged.
  """
  scalar = float(value)
  if transform is Transform.none:
    return scalar
  if transform is Transform.sqrt:
    return scalar * scalar
  if transform is Transform.log:
    return math.exp(scalar)
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
