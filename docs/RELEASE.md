# Release process

Repository: [zyvorai/zyvor-nuvora](https://github.com/zyvorai/zyvor-nuvora), public and source-available under the Zyvor Production License v1.0. Production use needs a commercial license from Zyvor AI Labs.

The compiled console is checked in to support a Python-only quickstart. Run `cd web && npm ci && npm run build` before committing changes to the console.

Before pushing:
1. Run `make check`.
2. Run the browser smoke against a local demo server. To refresh the screenshots, run it against a deployment with `NUVORA_TEST_URL` and `NUVORA_SCREENSHOT_DIR=docs/ux`, and replace any real host name on the sign-in shot.
3. Rebuild the social and README artwork with `docs/social/build.sh`.
4. Update `CHANGELOG.md`, `docs/API.md`, `docs/CAPABILITIES.md` and `docs/VALIDATION.md`.

CI runs the backend matrix, the console build and tests, Helm and shell checks, and a Chromium smoke. Pushing to `main` also publishes the docs site to GitHub Pages.

Before a production release, complete the integration and readiness work in docs/ROADMAP.md and document measured capability status. Do not publish competitor performance claims from this evaluation build.
