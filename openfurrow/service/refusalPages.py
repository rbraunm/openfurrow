# SPDX-License-Identifier: Apache-2.0
"""What a person reads when a page is refused or is not there (decision 0037, worklist GOV-6).

The API answers a refusal in JSON; a page of the web interface answers with a page, in the reader's language: 403 says
which permission is missing and where, 404 that the thing is not there, or not theirs to see. An address nothing
answers at gets the same 404 page, except below /api/.
"""

from __future__ import annotations

from collections.abc import Callable

from flask import Blueprint, Response, render_template, request
from werkzeug.exceptions import NotFound

from openfurrow.store.hierarchy import ScopeError
from openfurrow.workspace import NotFoundError, NotPermitted


def registerRefusalPages(blueprint: Blueprint, translatorOf: Callable, contextOf: Callable) -> None:

  def page(template: str, status: int, **context) -> Response:
    translator = translatorOf()
    return Response(render_template(template, **context, **contextOf(translator)), status=status)

  @blueprint.errorhandler(NotPermitted)
  def notPermitted(error: NotPermitted) -> Response:
    kind, _, name = error.scope.partition(":")
    return page("refused.html", 403, permission=error.permission.value, scopeKind=kind, scopeName=name)

  @blueprint.errorhandler(NotFoundError)
  @blueprint.errorhandler(ScopeError)
  def notFound(error: Exception) -> Response:
    return page("notFound.html", 404, detail=str(error))

  @blueprint.app_errorhandler(NotFound)
  def noSuchAddress(error: NotFound) -> Response | NotFound:
    if request.path.startswith("/api/"):
      return error
    return page("notFound.html", 404, detail=None)
