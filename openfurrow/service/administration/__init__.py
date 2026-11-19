# SPDX-License-Identifier: Apache-2.0
"""The administration area of the web interface (worklist GOV-6): accounts, groups, roles and who holds them, settings
by scope and the sign-in mode, identity providers, trusted workload rules, adding and deleting scheduled tasks,
retention (what the store holds, and pruning), and the audit log.

Like every page, these are thin over the `Workspace` facade: the facade checks each permission and writes each audit
event, so a page only reads the request, makes its one or two calls and renders. A section is offered to the people
who may use it, and a refusal is the facade's.
"""

from __future__ import annotations

from collections.abc import Callable

from flask import Blueprint, Response, g

from openfurrow.service.administration.accessPages import registerAccessPages
from openfurrow.service.administration.auditPages import registerAuditPages
from openfurrow.service.administration.pages import Pages
from openfurrow.service.administration.providerPages import registerProviderPages
from openfurrow.service.administration.retentionPages import registerRetentionPages
from openfurrow.service.administration.settingPages import registerSettingPages
from openfurrow.service.administration.taskPages import registerTaskPages
from openfurrow.service.administration.workloadPages import registerWorkloadPages
from openfurrow.workspace import NotFoundError, Workspace


def registerAdministration(blueprint: Blueprint, workspace: Workspace, translatorOf: Callable, contextOf: Callable,
                           localized: Callable, momentOf: Callable, levelNameOf: Callable) -> None:
  """Add the administration pages to the web interface's blueprint, and to every page the sections its reader may use."""
  pages = Pages(workspace, translatorOf, contextOf, localized, momentOf, levelNameOf)

  @blueprint.app_context_processor
  def administrationSections() -> dict:
    if "administrationSections" not in g:
      g.administrationSections = pages.sections()
    return {"administrationSections": g.administrationSections}

  @blueprint.get("/administration")
  def administrationIndex() -> Response:
    translator = pages.translator()
    if not pages.sections():
      raise NotFoundError(translator.text("web.administration.index.nothing"))
    return pages.render("administrationIndex.html", translator)

  registerAccessPages(blueprint, workspace, pages)
  registerSettingPages(blueprint, workspace, pages)
  registerProviderPages(blueprint, workspace, pages)
  registerWorkloadPages(blueprint, workspace, pages)
  registerTaskPages(blueprint, workspace, pages)
  registerRetentionPages(blueprint, workspace, pages)
  registerAuditPages(blueprint, workspace, pages)
