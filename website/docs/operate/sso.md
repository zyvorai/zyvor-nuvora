---
sidebar_position: 1
---

# Single sign-on (OIDC)

Nuvora signs people in through any OpenID Connect provider: Keycloak (including Haven), Microsoft Entra ID, Okta, Auth0 or Google Workspace. Password sign-in keeps working for the bootstrap administrator and any local accounts.

## How it works

- **Console sign-in:** the authorization code flow with PKCE (`S256`). State, nonce and the PKCE verifier travel in a short-lived, HMAC-signed, `HttpOnly` cookie scoped to `/api/auth/oidc`.
- **ID token checks:** the ID token comes straight from the token endpoint over verified TLS. Nuvora checks `iss`, `aud`, `exp`, `nbf` and `nonce`, as OIDC Core 3.1.3.7 allows.
- **Just-in-time users:** the first sign-in creates the user. Each later sign-in re-syncs their role from identity-provider groups.
- **Account rules:** SSO accounts can't sign in with a password or change one. A local account with the same username is never taken over; that sign-in is refused.
- **Bearer JWTs for automation:** access tokens from the same issuer are verified against its JWKS, using RS256/384/512, PS256/384/512, ES256 or ES384. `none` and HMAC are refused. Keys are cached for 10 minutes and refreshed once when a token carries an unknown `kid`. This needs the `sso` extra (`cryptography`), which the container image includes.
- **Audit:** events use the actor `oidc:<username>`, for example `user.provisioned`, `user.role_synced` and `session.created`.

## Configure

Register a confidential client with redirect URL `https://<your-host>/api/auth/oidc/callback`, then set:

| Variable | Default | Purpose |
|---|---|---|
| `NUVORA_OIDC_ISSUER` | — | Issuer URL, e.g. `https://keycloak.example.com/realms/zyvor`. Empty disables SSO |
| `NUVORA_OIDC_CLIENT_ID` | — | Client ID, also the default bearer audience |
| `NUVORA_OIDC_CLIENT_SECRET` | — | Client secret. Also signs login state, so every replica must share it |
| `NUVORA_OIDC_REDIRECT_URL` | `https://<Host>/api/auth/oidc/callback` | Set it explicitly behind proxies |
| `NUVORA_OIDC_SCOPES` | `openid profile email` | `openid` is always added |
| `NUVORA_OIDC_ROLES_CLAIM` | `roles` | Dotted path, e.g. `realm_access.roles` (Keycloak) or `groups` |
| `NUVORA_OIDC_ROLE_MAP` | — | `nuvora-admins=admin,nuvora-devs=developer,ops=approver`. The highest mapped role wins |
| `NUVORA_OIDC_DEFAULT_ROLE` | `viewer` | Role when no group maps. `none` refuses those users |
| `NUVORA_OIDC_IDENTITY_CLAIM` | `preferred_username` | Falls back to `email`, then `sub` |
| `NUVORA_OIDC_TENANT_CLAIM` | — | Claim that names the workspace. Otherwise `NUVORA_OIDC_DEFAULT_TENANT` (`default`) |
| `NUVORA_OIDC_AUDIENCE` | client ID | Expected `aud` for bearer JWTs |
| `NUVORA_OIDC_LABEL` | `Single sign-on` | Button text on the sign-in page |

With Helm:

```bash
kubectl create secret generic nuvora-oidc --from-literal=client-secret='…'
helm upgrade --install nuvora deploy/helm \
  --set oidc.issuer=https://keycloak.example.com/realms/zyvor \
  --set oidc.clientId=nuvora --set oidc.clientSecret=nuvora-oidc \
  --set oidc.rolesClaim=realm_access.roles \
  --set oidc.roleMap='nuvora-admins=admin\,nuvora-devs=developer'
```

The sign-in page shows **Sign in with SSO** whenever `GET /api/auth/providers` reports an OIDC provider. A failed callback returns to the sign-in page with the reason, for example an expired token, a wrong audience or no mapped role.

## Limits

- One identity provider per deployment.
- There's no SAML, SCIM deprovisioning or back-channel logout. Removing someone from the provider stops new sign-ins, but an open Nuvora session lasts until it expires (8 hours) or an administrator removes the user.
- The role is re-read at each sign-in, not during a session.
