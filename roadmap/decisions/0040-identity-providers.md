# 0040 - Signing in and provisioning through identity providers

**Status:** Accepted. Reversible while no trial exists outside development.

## Context

The university pilot signs people in through the university's identity provider and lets
that provider create, update and deactivate their accounts (`governance-plan.md`, F3).
Carnelian (decision 0039) speaks the protocols: OpenID Connect, SAML 2.0, LDAP and SCIM 2.0.
This decision is how OpenFurrow's accounts and groups (decisions 0036, 0037) meet them.
Policies are settings, not fixed rules (owner, 2026-11-16), so each choice an organization
would make differently is a provider setting with the strict choice as its default.

## Decision

- **Identity providers are configured in the store**, each with a name, a kind
  (`openIDConnect`, `saml`, `samlFederation`, `cas`, `ldap` or `scim`), its settings and an enabled flag, managed on
  the command line by the operator. A provider's secret (an OpenID Connect client secret, an
  LDAP service password) is never stored: its settings name an environment variable, read
  when the secret is needed, and a missing one is an error. A SCIM provider's bearer token
  is kept only as its SHA-256, like every other token (decision 0036).
- **An account is linked to each provider's identity for it**, by the provider's own stable
  subject: the OpenID Connect `sub`, the SAML persistent NameID, the directory user name, or
  the SCIM resource. A link belongs to one provider; another provider's word never reaches
  it.
- **A sign-in whose identity is not linked** follows the provider's setting `newAccounts`:
  - `refuse` (the default): an administrator or provisioning must make the account first;
  - `create`: an account is made from what the provider says;
  - `linkByUserName`: the identity is linked to the account with the same user name, for a
    provider trusted with the organization's names -- typically the one that provisions
    them by SCIM.
- **What a provider says** is taken as it says it, except that an OpenID Connect e-mail
  address is kept only when the provider marks it verified (`email_verified`).
- **A provider's discovery document, metadata and keys** are fetched once and reused for an
  hour in each process; a fetch that fails is not kept, so the next sign-in tries again.
- **Groups** follow the provider's setting `groups`: `ignore` (the default), or `mirror`:
  the provider's groups become OpenFurrow groups named `<provider>/<group>`, owned by the
  provider, their membership set at each sign-in and by provisioning and nowhere else.
  Roles are given to them like any group, so the organization maps its groups to roles in
  one place.
- **Research and education federations** (owner, 2026-11-17: university partners in the
  target regions sign in through them -- InCommon, the national federations, eduGAIN) are a
  provider kind of their own, `samlFederation`. Its settings name the federation's MDQ
  service and signing certificate and the institutions offered here, by entity ID; the
  sign-in page asks which one, in the person's language. Each institution's metadata is
  fetched from the federation and checked against its key and expiry. A person is named by a
  scoped identifier (subject-id, pairwise-id or eduPersonPrincipalName, as the settings
  choose), and an institution may only vouch for the scopes its federation registered for
  it. Searching every institution of eduGAIN (about 6,600
  identity providers, a 95 MB signed file) is left until a deployment needs it.
- **The service's own SAML keys** (owner, 2026-11-18: encrypted sign-ins supported, as
  federations such as InCommon expect): a SAML or federation provider may name a key that
  signs its requests and keys that decrypt its assertions, each a PEM key and certificate
  file on the server (a password, if any, in an environment variable), never stored in the
  database. Signing and decryption keys must differ; every decryption key is published, so
  one can be replaced while the provider still encrypts to the old. Assertions are decrypted
  with RSA-OAEP and AES-GCM; AES-CBC only where the provider's `allowCBC` says so, and then
  only under the response's verified signature. Both kinds publish their metadata, keys
  included, at `/signin/with/<provider>/metadata`. The private-key operations come from
  Carnelian's `keys` extra (pyca/cryptography), which OpenFurrow requires.
- **CAS** (Apereo's protocol 3.0; owner, 2026-11-17: many universities in France, Spain and
  Latin America sign in through it) is a provider kind of its own, `cas`: the person is the
  CAS user name, and the display name, e-mail and groups are the attributes the CAS server
  releases, named in the settings.
- **SCIM provisioning** answers at `/scim/<provider>/v2`. A provisioned user is an account
  (user name, display name, primary e-mail, active), a provisioned group a mirrored group.
  Deleting a user deactivates the account rather than removing it, so its history in the
  audit log keeps its name.
- **The web sign-in** lists the enabled providers beside the password form. A provider's
  answer comes back from another site -- SAML by a cross-site POST -- so the pending
  sign-in is kept in the store, bound to the browser by a short-lived cookie of its own,
  and its return address is exempt from the same-site check: the signed answer is its proof.
  The session cookie stays SameSite=Strict; after a provider's answer the browser is moved
  on by a page of this site, so the cookie travels from then on.
- **Signing out** (owner, 2026-11-18): signing out of OpenFurrow ends only OpenFurrow's
  session, unless the provider's setting `signOutEverywhere` says to sign out there too; and
  when a provider ends a person's session and tells OpenFurrow, OpenFurrow ends it too.
  - Each session started through a provider keeps the provider's own name for its session
    (the OpenID Connect `sid`, the SAML SessionIndex, the CAS service ticket) and what
    signing out of it needs (the ID token; the NameID, its format and the SessionIndex).
  - Signing out everywhere ends the session here first, then sends the browser to the
    provider: OpenID Connect RP-Initiated Logout with the ID token as hint, CAS logout, or a
    signed SAML LogoutRequest whose answer comes back to `/signin/with/<provider>/signout`,
    kept like a pending sign-in. The provider sends the person on to the provider's
    `signedOutURL` when one is set. A provider that cannot sign out leaves the session here
    ended, and the page says so.
  - A provider's own sign-outs end the sessions they name here: an OpenID Connect
    back-channel logout token at `/signin/with/<provider>/backchannel-logout` (with a
    session ID only that session, and only when its subject matches; with only a subject,
    every session of that subject from the provider), a SAML LogoutRequest at the provider's
    sign-out address (that NameID's sessions, only those with the SessionIndexes it names
    when it names any), and a CAS logout notice posted to the return address (only the
    session its ticket started, since CAS does not sign these). These addresses are exempt
    from the same-site check: the signature, or the ticket, is the proof.
  - SAML single logout in either direction needs the provider's `singleLogoutURL` (this
    site's sign-out address, published in the metadata) and its signing key.
  - A logout request from an institution of a research federation is refused: which
    institution sent it cannot be known before it is checked.
  - Every message that may be used only once (a SAML assertion or LogoutRequest, a logout
    token) is claimed in the store, in a transaction of its own, so every process serving
    one database refuses it the second time.
- **Everything is audited**: sign-ins, links, accounts and groups made or changed by a
  provider, with the surface `provisioning` for SCIM; and every sign-out, here, at the
  provider, and from the provider with how many sessions it ended.

## Consequences

- Store version 18: the providers, the links, the provisioned resources, the pending
  sign-ins, the provider sessions behind session tokens and the claimed message
  identifiers.
- OpenFurrow depends on Carnelian as a package from PyPI, with a lower bound only, as the
  Scientific Python packaging guidance has it. The exact version tested is pinned in
  `constraints.txt` like every other dependency, so a new release reaches the validation
  runs only by a deliberate change.
- Each provider is tested against the testbed's real one (Keycloak, Samba Active Directory)
  and SCIM against Entra ID's documented requests.
