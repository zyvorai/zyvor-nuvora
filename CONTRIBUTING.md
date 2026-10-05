# Contributing

Run `make test` and `cd web && npm ci && npm run build && npm test`. Changes to roles, tenant predicates, provider egress, approvals, idempotency and recovery need tests at their public boundary. New integrations must state what was validated against a real service versus a stub. Do not commit credentials, databases, node_modules or confidential evidence.

Follow docs/UX.md for console changes. Preserve meaningful empty/error states, show synthetic evidence class, and never imply that a queued/exported job already ran.
