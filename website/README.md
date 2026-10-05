# Nuvora docs site

Built with [Docusaurus](https://docusaurus.io/). It serves the live docs at https://zyvorai.github.io/zyvor-nuvora/.

## Local development

```bash
npm ci
npm start
```

## Build

```bash
npm run build
npm run serve   # preview the production build locally
```

## Images

Screenshots and social art aren't copied into `website/static/`. Instead, `docusaurus.config.ts` uses `staticDirectories` to serve `../docs/ux` and `../docs/social` in place, so the README and this site reference the same files.
- Console screenshots come from `scripts/browser-smoke.cjs`.
- Cards come from `docs/social/build.sh`.

## Deployment

`.github/workflows/pages.yml` builds and publishes the site to GitHub Pages on every push to `main` that touches `website/`, `docs/ux/`, or `docs/social/`. Don't use `npm run deploy`, because this repo has no `gh-pages` branch.
