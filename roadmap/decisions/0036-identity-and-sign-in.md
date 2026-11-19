# 0036 - Identity and signing in

**Status:** Accepted. Reversible while no trial exists outside development.

## Context

The university pilot needs sign-in with roles and the university's identity provider;
an open configuration where everyone can do everything stays supported (owner,
2026-11-16; `governance-plan.md`, F3). Sign-in uses no third-party library, so the
project's licence never limits where it runs.

## Decision

- **Two sign-in modes**, the server setting `identity.signInMode`:
  - `open` (the default): no sign-in, and every request acts as everyone, who holds every
    permission.
  - `accounts`: every web request belongs to a signed-in account and every API request to
    a bearer token. Switching to it is refused until an active account is administrator at
    the server, so the store cannot lock itself out.
- **Accounts** have a user name, a display name, an optional e-mail, a preferred language,
  and an active flag.
- **User names are in any script** (owner, 2026-11-17), since identity providers in the
  target regions send Arabic, Persian, Chinese or accented ones. A user name is kept in one
  form whatever way it was typed: compatibility-normalized (NFKC) and case-folded, so
  `José` typed composed or decomposed, `Ａｎａ` in full width and `ANA` are the names they
  look like. It holds 2 to 64 letters, combining marks, digits, `.`, `_`, `@` and `-`,
  starts with a letter or digit, and the part before any `@` is in one script (Japanese
  and Korean writing count as one each), so a Cyrillic `а` cannot stand in for a Latin `a`.
  Spaces, joiners and symbols are refused. Local passwords are 12 to 256 characters,
  hashed with the standard library's scrypt (`scrypt$n$r$p$salt$hash`, n = 2^15).
  Sign-in refusals give one message whatever went wrong, so user names are not revealed,
  and are recorded in the audit log without the password.
- **Tokens.** A session (lifetime: the server setting `identity.sessionHours`, 12 by
  default) and API tokens are random 256-bit strings kept only as their SHA-256;
  deactivating an account ends them all. The session cookie is HttpOnly, SameSite=Strict,
  and Secure under TLS.
- **Changes come from the site's own pages.** With accounts, a web request that changes
  something must carry an Origin or Referer naming this host, or it is refused with 403.
- **The command line and the library act as the store's operator** and hold every
  permission: whoever holds the store's file or database login holds the store. Their
  changes are audited as the operator, with the surface.
- **A preferred language** applies to a signed-in person's pages when the address names
  none.

## Consequences

- Store version 16.
- Identity providers (OpenID Connect, SAML 2.0, LDAP, SCIM 2.0) are the project's own
  library, next (worklist GOV-3), with their test fixtures (GOV-4).
- Accounts, groups and roles are managed on the command line and in the web interface's
  administration area, which also switches the sign-in mode; opening the server to everyone
  is confirmed there.
