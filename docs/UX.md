# Nuvora UX

The console follows the Zyvor Apple UX contract: [docs/design/APPLE-UX-CONTRACT.md](design/APPLE-UX-CONTRACT.md).

Netra's design system was ported directly into Nuvora. That covers its tokens (`styles.css`), story primitives (`apple-story.css`), navigation with mega-panels, `PageHero`, theme handling, and the login layout. Zyvor AI Labs relicensed those files under Apache-2.0 for this repository; see [THIRD-PARTY.md](../THIRD-PARTY.md).

## Verification

- `web/src/App.test.tsx` (jsdom) covers:
  - sign-in, wrong-password rejection, and changing the workspace
  - mega-menu navigation
  - grounded playground answers and role-gated generation
  - agent runs, theme switching, and admin-only access
- `scripts/browser-smoke.cjs` (Playwright) runs against a live instance and covers:
  - every one of the 17 pages
  - the evaluate-to-runs flow and evidence-chain verification
  - dark mode persisting across a reload
  - no horizontal overflow at 390px
  - logout

  It writes the screenshots in [docs/ux](ux/). The current set was captured from the k3s deployment.
