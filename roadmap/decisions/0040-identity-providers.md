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
  it. The service's own metadata, for the federation to register, is at
  `/signin/with/<provider>/metadata`. Searching every institution of eduGAIN (about 6,600
  identity providers, a 95 MB signed file) is left until a deployment needs it.
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
- **Everything is audited**: sign-ins, links, accounts and groups made or changed by a
  provider, with the surface `provisioning` for SCIM.

## Consequences

- Store version 17: the providers, the links, the provisioned resources and the pending
  sign-ins.
- OpenFurrow depends on Carnelian, pinned to a commit of its repository until Carnelian is
  published as a package.
- Each provider is tested against the testbed's real one (Keycloak, Samba Active Directory)
  and SCIM against Entra ID's documented requests.
