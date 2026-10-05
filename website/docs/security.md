---
sidebar_position: 4
---

# Security model

Nuvora is an evaluation release. This page says what it enforces and what it doesn't.

## Enforced

- **Tenant isolation.** Every query is scoped by tenant, so an ID alone never grants access.
- **Roles.** The four roles (`viewer`, `developer`, `approver`, `admin`) are checked by the API on every request.
- **Sessions.**
  - Cookies are HttpOnly and `SameSite=Strict`, and Secure over TLS.
  - Mutations need a CSRF token and pass Origin validation.
  - Bearer tokens are scoped and stored only as digests. Owners and admins can list and revoke them, and demotion below developer revokes them.
  - Changing your password signs out your other sessions.
- **Single sign-on.**
  - OIDC sign-in uses the code flow with PKCE and a signed, short-lived state cookie. The ID token's issuer, audience, expiry and nonce are checked.
  - Bearer JWTs are signature-verified against the issuer's JWKS, with asymmetric algorithms only.
  - SSO users can't use or change a password, and an SSO sign-in never takes over a local account.
- **Passwords.**
  - Passwords need 12–256 characters and are stored as PBKDF2-SHA256 hashes.
  - The only exception is the deploy demo password for the bootstrap administrator, and only when it's explicitly allowed.
  - The console never stores passwords in the browser. Playground conversations are kept in local storage, per workspace and user.
- **Outbound calls.**
  - Calls go only to hosts on an exact allow-list, over HTTPS for remote hosts. Redirects are refused.
  - Credentials are environment references, never stored values.
- **Separation of duties.** Consequential actions need a different person's approval, bound to an exact fingerprint.
- **Streaming.** Streamed answers pass the output guardrails at sentence boundaries before any text reaches the browser.
- **Evidence.** The audit log is hash-chained, and `scripts/verify-evidence.py` checks an export offline.
- **Transport.** Remote binds require direct TLS or an explicitly trusted TLS proxy. The content security policy is `script-src 'self'`.

## Not enforced

- **The host is trusted.** A host administrator can read or change the database. The audit chain is unsigned, so anchor chain tips externally if you need independent proof.
- **Guardrails are pattern-based.** They block configured topics and some instruction-override patterns and redact emails and account numbers. They aren't robust jailbreak prevention.
- **Code runs only in Keep.** The server itself isn't an isolated agent runtime. `run_code` exists only when Keep is configured, runs in a FluxVM sandbox without network, and needs a different person's approval of the exact code. There are no browser tools.
- **Your providers see your data.** External model providers receive whatever content is sent to them, under their own terms.
- **No encryption at rest.** Neither SQLite nor PostgreSQL data is encrypted by Nuvora. Use an encrypted volume or database encryption, and `sslmode=require` for PostgreSQL.
- **Per-process limits.** With several replicas, the four-concurrent-calls limit and in-flight budget reservations apply per replica.

## Reporting

Report vulnerabilities privately to the maintainers, not in a public issue. Don't include credentials or confidential documents.
