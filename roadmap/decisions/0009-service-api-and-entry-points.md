# 0009 - Service, API, and entry points

**Status:** Accepted. Direction adopted, not locked. Reversible.

## Context

The core is a Python library with a CLI. Every surface beyond the CLI -- a web UI,
mobile apps, a collaboration server -- needs to reach the core's operations, and the
math must be implemented once (ADR 0002). Without a defined boundary, each surface risks
reimplementing or re-validating the analysis. The platform plan (`../platform-plan.md`)
makes the service the layer that exposes the core to every other surface.

## Decision

- **One bundled application, multiple entry points.** The distribution is a single
  application. A CLI entry point runs local analysis; a Flask entry point runs a web/HTTP
  API and the web UI. A user can use the CLI alone, run the Flask process directly, or
  install it as an OS service.
- **Flask is the service framework.** A Flask application wraps the core and exposes its
  operations over an HTTP JSON API. This API is the single interface behind every
  non-CLI surface -- the web UI, the mobile apps, and the collaboration server all call
  it -- so the core stays the one implementation of the math (ADR 0002).
- **The web UI is served by the same Flask application** (current lean; settled in the
  web UI ADR): one app serves the API and the UI consumes it, so the same API backs web,
  mobile, and server. The web UI is a separate entry point from the CLI but bundled in
  the same application.
- **A serve command** starts the web app locally, for a personal GUI on the user's own
  machine.
- **Cross-OS service install and uninstall.** The application can install and uninstall
  itself as an operating-system service, so a user can run a persistent local GUI or a
  private server: a Windows service via PowerShell 5.1, a systemd unit on Linux, and a
  launchd agent on macOS. Install and uninstall are explicit, reversible operations.
- **Authentication and sessions** are introduced at the service boundary once it runs as
  a service, deferring to ADR 0005 for the access-control model; the local single-user
  case needs none.

## Consequences

- The core gains a stable API surface that the service calls (ADR 0010 covers the core's
  packaging).
- The CLI and the web UI cannot diverge in behavior, because both reach the core -- the
  CLI directly, the web UI through the API over the core.
- Running as a service raises real concerns (binding, ports, authentication, OS
  integration) addressed here for install, in ADR 0005 for authentication, and in ADR
  0011 for server mode.
- Third-party and niche dependencies are avoided per the engineering standards; Flask and
  the standard-library service mechanisms are the baseline.

## Open questions

- Whether the web UI is server-rendered by Flask or is a separate front end consuming the
  API (the web UI ADR; current lean: one app serving an API the UI consumes).
- The concrete API shape and its versioning.
- The authentication mechanism for service and server mode (with ADR 0005).
