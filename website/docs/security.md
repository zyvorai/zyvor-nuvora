---
sidebar_position: 3
---

# Security model

Nuvora is an evaluation release. This page says what it enforces and what it doesn't.

## Enforced

- **Tenant isolation.** Every query is scoped by tenant, so an ID alone never grants access.
- **Roles.** The four roles (`viewer`, `developer`, `approver`, `admin`) are checked by the API on every request.
- **Sessions.**
  - Cookies are HttpOnly and `SameSite=Strict`, and Secure over TLS.
  - Mutations need a CSRF token and pass Origin validation.
  - Bearer tokens are scoped and stored only as digests.
- **Passwords.**
  - Passwords need 12–256 characters and are stored as PBKDF2-SHA256 hashes.
  - The only exception is the deploy demo password for the bootstrap administrator, and only when it's explicitly allowed.
- **Outbound calls.**
  - Calls go only to hosts on an exact allow-list, over HTTPS for remote hosts. Redirects are refused.
  - Credentials are environment references, never stored values.
- **Separation of duties.** Consequential actions need a different person's approval, bound to an exact fingerprint.
- **Evidence.** The audit log is hash-chained, and `scripts/verify-evidence.py` checks an export offline.
- **Transport.** Remote binds require direct TLS or an explicitly trusted TLS proxy. The content security policy is `script-src 'self'`.

## Not enforced

- **The host is trusted.** A host administrator can read or change the database. The audit chain is unsigned, so anchor chain tips externally if you need independent proof.
- **Guardrails are pattern-based.** They block configured topics and some instruction-override patterns and redact emails and account numbers. They aren't robust jailbreak prevention.
- **No sandbox.** The server isn't an isolated agent runtime. Keep microVM execution is roadmap work, and no untrusted code or browser tools are registered.
- **Your providers see your data.** External model providers receive whatever content is sent to them, under their own terms.
- **No encryption at rest.** SQLite isn't encrypted by Nuvora, so use an encrypted volume.

## Reporting

Report vulnerabilities privately to the maintainers, not in a public issue. Don't include credentials or confidential documents.
