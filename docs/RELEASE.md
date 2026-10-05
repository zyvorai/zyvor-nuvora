# Release 0.1.0 preparation

Target repository: `zyvorai/zyvor-nuvora`. It has not been created by this delivery.

Review the source and docs, then create it locally with `scripts/push-github.sh` after `gh auth login`. The script starts private and requires your local Git author settings. Use a different owner/name by editing the script before running. The directory contains no user credentials, test database or model weights.

The compiled console is checked in to support a Python-only quickstart. Run `cd web && npm ci && npm run build` before committing changes to the console. Verify backend/frontend checks before pushing. CI includes a browser smoke test. To run it against a deployment, set `NUVORA_TEST_URL`.

Before a production release, complete the integration and readiness work in docs/ROADMAP.md and document measured capability status. Do not publish competitor performance claims from this evaluation build.
