# Nuvora UX contract — apple.com

Nuvora's console (`web/`) and docs site (`website/`) follow the same apple.com-style
contract as Zyvor Netra (`zyvor-netra/docs/design/APPLE-UX-CONTRACT.md`). Nuvora has
its own identity: models, knowledge and agents that show their work, with a person in
the loop for anything consequential.

Netra's tokens, primitives, navigation, page hero and login layout were ported directly:
- `web/src/styles.css` holds the tokens. `:root` is Apple light, the default; `[data-theme="dark"]` is opt-in.
- `web/src/styles/apple-story.css` holds the primitives.
- `web/src/styles/nuvora.css` holds Nuvora's work-tier additions, built on tokens only.
- The docs site reuses the same values in `website/src/css/custom.css`.

## Surface tiers

| Tier | Nuvora pages | Density | Layout |
|---|---|---|---|
| **Story** | Login, Overview | Very low | Eyebrow, `.apple-display`, lede, one CTA. `overview-stage` + `.apple-metric-band` instead of a tile grid |
| **Browse** | Models, Connectors & actions, Model studio, Prompts, Batch inference, Evidence, Access | Medium | `PageHero` + `Toolbar` + `TableWrap` (hairline table) + `ListEmpty` |
| **Work** | Playground, Knowledge, Agents, Workflows, Runs, Evaluations, Approvals, Guardrails, Usage & cost | High | `.card` panels, `.split` layouts, inline evidence; tokens only |

## Navigation

There are five groups, each a mega-panel with a one-line blurb per page (`web/src/lib/navGroups.ts`):

| Group | Pages |
|---|---|
| **Overview** | Overview |
| **Workspace** | Playground, Models, Knowledge |
| **Build** | Agents, Connectors & actions, Workflows, Prompts, Model studio |
| **Operate** | Runs, Evaluations, Batch inference |
| **Govern** | Approvals, Guardrails, Usage & cost, Evidence, Access |

Routing uses hashes (`#playground`). An unknown hash falls back to Overview. The workspace chip reads `tenant · role`. A pending dot appears on Approvals when a decision is waiting.

## Tokens

| Token | Light (default) | Dark |
|---|---|---|
| `--bg-page` | `#ffffff` | `#000000` |
| `--surface-1` (card) | `#ffffff` + hairline | `#1d1d1f` |
| `--text-primary` | `#1d1d1f` | `#f5f5f7` |
| `--text-secondary` | `#6e6e73` | `#a1a1a6` |
| `--apple-blue` (CTA, focus) | `#0071e3` | `#0071e3` |
| `--apple-link` | `#0066cc` | `#2997ff` |

The type scale is Netra's (`--fs-h1` … `--fs-link`). Don't add raw `px` font sizes above 17px. Page heroes are compact titles, so the data starts within the first screen.

## Laws

1. **Elevation runs up.**
   - Dark: page `#000`, then panel `#1d1d1f`, then cards lighter, popovers lightest.
   - Light: white page, white card with a hairline.
   - A grey panel on a white page is a bug.
2. **Color is deviation.** Nominal values are graphite and blue means intent. Use red, amber or green only for real outcomes: blocked, waiting, verified.
3. **One primary action per view.** The page's create action sits in the `PageHero` action slot.
4. **No hard-coded hex or rgba in components or page CSS.** Use tokens.
5. **Synthetic is labeled.** Offline demo output always says so. A training export is never called a training run.
6. **Approvals show the exact action.** Show the proposer, expiry and fingerprint. Self-approval is disabled in the console and refused by the API.
7. **The backend is the authority.** Controls respect roles, but the API enforces them.

## Load-bearing markup (tests depend on it)

- **Login:**
  - Heading `Sign in.`.
  - Labels `Username` and `Password`, plus `Workspace` behind the `Workspace: default · Change` disclosure.
  - A `role="alert"` error reading `Wrong username or password.`
- **Overview:** heading `Your intelligence stack`.
- **Nav:**
  - Group buttons by group name, page buttons by page label.
  - Theme toggle aria-labels `Switch to light mode` / `Switch to dark mode`.
- **Theme:** `data-theme` is set on `<html>`; the default is `light`. A stored `nuvora-theme` wins, applied before paint by `/theme-init.js`, an external file because the CSP is `script-src 'self'`.

## Author checklist

1. Pick the tier first.
2. Story pages get one composition and no card grid.
3. Browse pages use `Toolbar` + `TableWrap`; search uses `.input-field`.
4. Empty lists get a title, a sentence and a next action (`ListEmpty`).
5. Check light and dark at 1440px and 390px; there must be no horizontal scroll at 390px. `scripts/browser-smoke.cjs` checks every page.
