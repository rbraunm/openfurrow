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
- **Service install and uninstall on every platform.** The application installs and
  uninstalls itself as services of the operating system, so a user can run a persistent
  local GUI or a private server: `openfurrow service install|uninstall|start|stop|status`.
  A deployment is two services on one store, the web server and the scheduler (decision
  0041): Windows services, systemd units on Linux, launchd daemons on macOS (daemons, not
  agents: they run with nobody logged in). Install and uninstall are explicit and
  reversible. Whatever is refused is refused by name before the first change: a shell that
  is not elevated, a store that does not exist, an address in use, services already
  installed, an unsupported platform, uninstalling what is not installed. An install that
  fails part of the way is undone; uninstall removes the services, the account the install
  made and the rights it gave, and leaves the store, its logs and the environment file.
  - **What a deployment chooses**: the store, the web server's address and port, a logs
    folder (`logs` beside the store unless named), an environment file and a suffix for
    the services' names (`openfurrow-web`, `openfurrow-scheduler`, then `-<suffix>`), so
    several deployments share a machine. Nothing else records a deployment: each service's
    definition is generated from it and read back from the installed definition, which is
    how `status`, `start`, `stop` and `uninstall` find the store by the suffix alone.
  - **The store's folder is the services'.** A file store lives in a folder of its own,
    because SQLite writes beside the file and so the services' accounts are given the
    folder; a store among other files is refused. A PostgreSQL store's URL carries a
    password, so no definition holds it: it is in the environment file as
    `OPENFURROW_STORE`, and the logs folder is named.
  - **The environment file** carries what the services take from their environment, such
    as identity providers' secrets (decision 0040): `NAME=value` lines, the value plain,
    in single quotes or in double quotes with `\"` and `\\`. That is the form systemd's
    `EnvironmentFile` and OpenFurrow's own reader take alike, so a file means the same on
    every platform; any other line is refused by its number, never showing a value. The
    install closes the file to everyone but administrators and the services.
  - **One process per service**, `python -m openfurrow.osService.host web|scheduler`,
    under a supervisor that tells the service manager where it stands (starting, running
    once the web server listens or the scheduler has opened the store, stopping, stopped)
    and exits non-zero when its work fails, so the service manager's restart rule applies.
    A stopped web server stops listening; a stopped scheduler lets its runs finish or
    records them stopped, as at Ctrl+C.
  - **Least privilege.** No service runs as an administrator. On Windows each service runs
    as LocalService, the built-in account with the fewest rights (an ordinary user's on
    the machine, none of the machine's own on the network), and what it needs beyond that
    is given to the service alone: each service carries an identifier of its own in its
    token, `NT SERVICE\<service name>`, and the two identifiers, not LocalService, are
    given "modify" on the store's folder and "read" on the environment file. A service is
    not run as the virtual account of that name, which would keep even more to itself:
    Windows makes a user profile for such an account at the service's first start and
    keeps it loaded until the machine restarts (measured: deleting it answers "in use"), so
    an uninstall would not be reversible. LocalSystem can do anything. What LocalService
    costs is recorded as worklist PLT-11:
    files the services make are owned by an account other services also run as, and they
    share its folder for temporary files. On Linux and macOS one unprivileged account per
    deployment (`openfurrow`, `_openfurrow`, with the suffix), made by the install when
    absent, owns the store's folder and the logs; an account the install did not make is
    never removed.
  - **Windows**: real services, made through the service manager's own calls (ctypes on
    advapi32): no PowerShell, no third-party package, no helper binary. Delayed automatic
    start; restart after 5 seconds, then 30, then every 60, on a dead process or a non-zero
    exit code. The service manager starts a file run by its path, which connects to the
    service manager on the standard library alone and loads OpenFurrow only then, so a slow
    first import never meets the thirty seconds a new service process has to connect; what
    fails before OpenFurrow's log is open goes to the application event log. A system
    shutdown gives a service seconds, so there the scheduler stops its runs at once.
    Windows starts a failed service again whatever it is told in between, so `service
    stop` on one says so rather than report it stopped; uninstalling keeps it down.
  - **Linux**: systemd notify units, enabled for boot; `Restart=on-failure`;
    `KillMode=mixed`, so a stop reaches the scheduler and not its runs; the file system
    read-only but for the store's folder and the logs, no home directories, a private
    `/tmp`, no new privileges; `EnvironmentFile` readable by root only. The scheduler is
    not ordered after the web unit: it needs the store, not the web server. Because of the
    hardening, a store or a Python in a home directory or `/tmp` is refused by name.
  - **macOS**: launchd daemons in `/Library/LaunchDaemons`, run at load and kept alive
    after an unsuccessful exit. launchd has no word for "ready", so a daemon counts as
    running once its process exists, and it reads no environment file, so the process
    does.
  - **Logs**: one file per service in the logs folder, a new one each UTC day, 90 kept.
    They hold no personal data: a request is logged by its route's pattern and status,
    never by the address asked for or the client's, and an error after start by its type
    and the code it passed through, never by its message.
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
- The installed web service is Werkzeug's threaded server on the address it is given. The
  install sets up no HTTPS, no reverse proxy and no production WSGI server (worklist
  PLT-9), and it needs a Python already on the machine, installed where a service's
  account can read it (worklist PLT-10).
- Python and OpenFurrow must be readable by the services' accounts: installed for all
  users on Windows, outside home directories on Linux. The install asks the interpreter
  what it would load and refuses by name when a service could not read it.

## Open questions

- Whether the web UI is server-rendered by Flask or is a separate front end consuming the
  API (the web UI ADR; current lean: one app serving an API the UI consumes).
- The concrete API shape and its versioning.
- The authentication mechanism for service and server mode (with ADR 0005).
