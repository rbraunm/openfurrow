# SPDX-License-Identifier: Apache-2.0
"""The kind `federationRefresh`: read a research federation's discovery aggregate again (decisions 0040, 0041).

Each federation provider with a discovery aggregate has one such task, made with the
provider. A run fetches and checks the aggregate and replaces the provider's discovery
list in one transaction; a refresh that fails leaves the previous list in place.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from openfurrow.tasks.model import RunContext, TaskKind


class FederationRefreshParameters(BaseModel):
  model_config = ConfigDict(extra="forbid")

  provider: str


def refreshFederation(context: RunContext, parameters: FederationRefreshParameters) -> str:
  context.logger.info("reading the discovery aggregate of %s", parameters.provider)
  outcome = context.workspace.refreshFederationDiscovery(parameters.provider)
  for entityID, reason in outcome.skipped:
    context.logger.warning("left out %s: %s", entityID, reason)
  validUntil = outcome.validUntil.isoformat(timespec="seconds")
  return (f"{outcome.offered} institutions offered, {outcome.hidden} hidden from discovery, "
          f"{len(outcome.skipped)} entities skipped; the aggregate holds until {validUntil}")


federationRefresh = TaskKind(
  name="federationRefresh", parameters=FederationRefreshParameters, defaultSchedule="0 */6 * * *",
  defaultTimeLimitSeconds=15 * 60, run=refreshFederation,
)
