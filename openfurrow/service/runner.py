# SPDX-License-Identifier: Apache-2.0
"""Running the service, with optional HTTPS.

Kept separate from the app itself: `createApp` builds something a test client (or a
WSGI server) can drive without ever binding a socket, and this module is the only place
that binds one. Unit B3's `serve` command calls `runService`.

HTTPS is opt-in (`service.tls.enabled`). It is off by default because the first target
is a local single-user tool on loopback, where TLS buys nothing; it becomes necessary
as soon as the service is reachable from another machine, and then it is one config
setting rather than a rebuild.

**Automatic certificate issuance (Let's Encrypt / ACME) is not implemented.** It needs a
public DNS name, inbound reachability, and a renewal daemon -- none of which a local or
LAN deployment has, so building it now would be speculative. It belongs with the
internet-facing self-hostable server (decision 0011), and nothing here blocks it: an
ACME-obtained certificate is just a certificate and key pointed at by the same two
settings.

The development server is Flask's own. A production self-hosted deployment should sit
behind a real WSGI server; that is part of the server unit, not this one.
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask

from openfurrow.config import OpenFurrowConfig, defaultConfig


class ServiceError(RuntimeError):
  """The service cannot be started as configured."""


def runService(application: Flask, config: OpenFurrowConfig | None = None) -> None:
  """Bind and serve `application` per the config's service settings."""
  settings = (config or defaultConfig()).service
  application.run(
    host=settings.host,
    port=settings.port,
    ssl_context=tlsContext(config or defaultConfig()),
  )


def tlsContext(config: OpenFurrowConfig) -> tuple[str, str] | None:
  """The (certificate, key) pair to serve with, or None for plain HTTP.

  Fails loud if TLS is enabled but a file is missing: a service that thinks it is
  serving HTTPS while actually serving HTTP is a security bug, and the whole point of
  the no-silent-fallback rule is that it must never happen quietly.
  """
  tls = config.service.tls
  if not tls.enabled:
    return None

  # The config model already rejects enabled-without-paths at construction; this checks
  # the files are actually there before we bind and claim to be serving HTTPS.
  missing = [
    path for path in (tls.certificateFile, tls.privateKeyFile)
    if not Path(path).exists()
  ]
  if missing:
    raise ServiceError(
      f"tls.enabled is true but these file(s) do not exist: {', '.join(missing)}"
    )
  return (tls.certificateFile, tls.privateKeyFile)


def serviceUrl(config: OpenFurrowConfig) -> str:
  """The URL the service will be reachable at, for an operator to click."""
  settings = config.service
  scheme = "https" if settings.tls.enabled else "http"
  return f"{scheme}://{settings.host}:{settings.port}"
