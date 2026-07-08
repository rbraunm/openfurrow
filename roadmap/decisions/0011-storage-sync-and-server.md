# 0011 - Storage, sync, and the self-hostable server

**Status:** Accepted. Direction adopted, not locked. Reversible.

## Context

Storage today is a local SQLite store and file exchange for a single user (ADR 0001). The
audience (ADR 0008) is resource-constrained and values owned, offline-capable data; some
of them also need to collaborate as a team without standing up infrastructure from
scratch or surrendering their data to someone else's cloud. ADR 0005 defines a
configurable-privacy and access-control model for a team mode. The platform plan makes
storage a local-first floor with an optional, user-owned collaboration server.

## Decision

- **Local-first is the floor.** A local file and SQLite, fully offline and owned, remain
  the default and require no server. Everything works without collaboration (ADR 0001).
- **An optional, user-owned self-hostable server** provides team collaboration: the Flask
  service (ADR 0009) in server mode, multi-user, with the ADR 0005 privacy,
  access-control, audit, and at-rest encryption features. It is run by the user, in their
  own environment, and the data stays theirs -- self-hosted collaboration, not our cloud.
- **A sync model** governs how trials and observations move between a device or analyst
  and the server; its mechanism is an open sub-decision. The content hash (ADRs 0001 and
  0006) gives sync a fixity check for free.
- **Delivery: CloudFormation first, a free AWS Marketplace AMI later.** A CloudFormation
  template a user launches in their own AWS account is the first vehicle -- no seller
  registration or listing burden, and the data stays in the user's account. A free AWS
  Marketplace AMI is a later discoverability upgrade; a free listing carries no banking or
  tax requirement but does carry support, patching, vulnerability-scanning, and
  security-hardening obligations (see `../research/platform-and-interop.md`). Both keep
  data user-owned.
- **Encryption and security hygiene** -- no password authentication, key-based access, no
  embedded credentials, at-rest encryption -- are baseline for the server, aligned with
  ADR 0005 and with the Marketplace AMI requirements.

## Consequences

- Collaboration never requires giving up data ownership; the server is the user's.
- The local-first floor keeps the tool fully usable with no server and no account.
- Running a server introduces operational surface (hosting, security, updates) that the
  CloudFormation-first path keeps in the user's hands and low-ceremony.
- Realizes ADR 0005 (team mode) and evolves ADR 0001 (storage beyond a single local
  file).

## Open questions

- The sync mechanism (custom versus an existing replicated store).
- Marketplace-versus-CloudFormation timing, and whether both ship.
- How the sync model interacts with the content-hash identity of a trial when multiple
  parties contribute observations to it.
