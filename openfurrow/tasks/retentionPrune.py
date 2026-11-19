# SPDX-License-Identifier: Apache-2.0
"""The kind `retentionPrune`: remove what the retention rules let go (decisions 0041, 0044).

Every store has one such task, made with the store and run daily. While every area is
kept, the default, a run finds nothing and says so.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from openfurrow.retention import summaryOf
from openfurrow.tasks.model import RunContext, TaskKind


class RetentionPruneParameters(BaseModel):
  model_config = ConfigDict(extra="forbid")


def pruneRetention(context: RunContext, parameters: RetentionPruneParameters) -> str:
  report = context.workspace.prune()
  for line in report.lines:
    context.logger.info("pruned %s of %s at %s (%s bytes) under %s, set at %s", line.count, line.area.value, line.scope,
                        line.sizeBytes, line.rule, line.source)
  return summaryOf(report)


retentionPrune = TaskKind(
  name="retentionPrune", parameters=RetentionPruneParameters, defaultSchedule="15 3 * * *",
  defaultTimeLimitSeconds=30 * 60, run=pruneRetention,
)
