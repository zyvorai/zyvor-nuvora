# Contributing

Run `make check`: backend tests, the console build and the console tests. For console changes, also run the browser smoke against a local demo server with `node scripts/browser-smoke.cjs` (Playwright; set `NUVORA_TEST_URL` for another instance).

Changes to roles, tenant predicates, provider egress, approvals, idempotency and recovery need tests at their public boundary. New integrations must state what was validated against a real service versus a stub. Do not commit credentials, databases, node_modules or confidential evidence.

Follow docs/UX.md for console changes. Preserve meaningful empty/error states, show synthetic evidence class, and never imply that a queued/exported job already ran.

Contributions are accepted under the Zyvor Production License v1.0. New source files should carry the `SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0` header.
