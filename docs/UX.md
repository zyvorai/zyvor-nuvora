# Nuvora UX

The console follows the Zyvor Apple UX contract: [docs/design/APPLE-UX-CONTRACT.md](design/APPLE-UX-CONTRACT.md).

Netra's design system was ported directly into Nuvora. That covers its tokens (`styles.css`), story primitives (`apple-story.css`), navigation with mega-panels, `PageHero`, theme handling, and the login layout. Zyvor AI Labs relicensed those files under Apache-2.0 for this repository; see [THIRD-PARTY.md](../THIRD-PARTY.md).

## Console features

- **Sign in:** a split-screen hero with the workspace named on the card. The password is never stored in the browser.
- **Command palette:** ⌘K or `/` searches pages, resources and actions, and falls back to asking the playground. `?` lists shortcuts; `g` then a letter jumps to a page.
- **Playground:** multi-turn conversations kept in this browser only, streamed answers with Stop, compare two models side by side, citation hover cards, copy and regenerate.
- **Onboarding:** a checklist on Overview derived from live data, and guided empty states with a create action on every browse page.
- **Resource drawers:** every resource opens in a drawer with Overview, History, Diff and JSON tabs, plus run, edit, duplicate and delete. `#kind/id` deep-links to it.
- **Workflows:** an SVG DAG of the pinned revision, a visual builder, and a run inspector with a step timeline and inline approval.
- **Charts:** usage series by metric, per-model cost, cache share, the budget gauge, Overview sparklines, run outcomes and evaluation score trends.
- **Operations:** a notification bell, a profile menu with password change, API keys, Settings, member role editing, and evidence filters with CSV and chain export.

## Verification

- `web/src/App.test.tsx` (jsdom) covers:
  - sign-in, wrong-password rejection, and changing the workspace
  - mega-menu navigation
  - grounded playground answers and role-gated generation
  - agent runs, theme switching, and admin-only access
  - the command palette, shortcuts, drawer history and diff, API keys and profile-menu logout
- `scripts/browser-smoke.cjs` (Playwright) runs against a live instance and covers:
  - every one of the 19 pages
  - a two-turn playground conversation, the command palette, the workflow drawer and builder
  - API key create and revoke, and the Settings page
  - the evaluate-to-runs flow and evidence-chain verification
  - dark mode persisting across a reload
  - no horizontal overflow at 390px
  - logout

  It writes the screenshots in [docs/ux](ux/). The current set was captured from the k3s deployment.
