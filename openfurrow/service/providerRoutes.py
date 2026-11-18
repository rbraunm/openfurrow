# SPDX-License-Identifier: Apache-2.0
"""SCIM provisioning (decision 0040): a provider's requests below /scim/<provider>/v2 go to Carnelian,
which checks the provider's bearer token; nothing here reads a session or a cookie."""

from __future__ import annotations

from flask import Flask, Response, request

from openfurrow.workspace import Workspace

methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]


def installProvisioning(application: Flask, base: Workspace) -> None:

  @application.route("/scim/<name>/v2", defaults={"rest": ""}, methods=methods, endpoint="provisioning")
  @application.route("/scim/<name>/v2/<path:rest>", methods=methods, endpoint="provisioning")
  def provisioning(name: str, rest: str) -> Response:
    answer = base.handleProvisioning(name, request.method, "/" + rest, request.query_string.decode("ascii"),
                                     dict(request.headers.items()), request.get_data())
    return Response(answer.body, status=answer.status, headers=answer.headers)
