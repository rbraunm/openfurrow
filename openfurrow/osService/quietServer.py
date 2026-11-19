# SPDX-License-Identifier: Apache-2.0
"""The web server as a service runs it: what it logs holds no personal data.

Werkzeug's own lines name the client's address and the address requested, with its
query, and an unhandled error is logged with its message. Here a request is one line of
its method, the pattern of the route it matched and its status; an error is its type and
the code it passed through (`host.describe`).
"""

from __future__ import annotations

import logging
import sys

from flask import Flask, Response, request
from werkzeug.serving import ThreadedWSGIServer, WSGIRequestHandler

from openfurrow.osService.host import describe

requestLog = logging.getLogger("openfurrow.service.request")


def _route() -> str:
  return "(no route)" if request.url_rule is None else request.url_rule.rule


def logRequestsByRoute(application: Flask) -> None:
  @application.after_request
  def logRequest(response: Response) -> Response:
    requestLog.info("%s %s %s", request.method, _route(), response.status_code)
    return response

  def logException(errorInformation) -> None:
    requestLog.error("%s %s failed: %s", request.method, _route(), describe(errorInformation[1]))

  application.log_exception = logException


class QuietRequestHandler(WSGIRequestHandler):
  def log(self, type: str, message: str, *args) -> None:
    pass

  def send_error(self, code, message=None, explain=None) -> None:
    requestLog.warning("a request was refused before it reached a route: %s", int(code))
    super().send_error(code, message, explain)


class QuietServer(ThreadedWSGIServer):
  def handle_error(self, request, client_address) -> None:
    requestLog.error("a connection failed: %s", describe(sys.exception()))

  def log(self, type: str, message: str, *args) -> None:
    requestLog.error("a request failed in the server: %s", describe(sys.exception()))
