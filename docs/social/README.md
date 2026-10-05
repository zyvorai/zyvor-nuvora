# Social and README artwork

Every image here is rendered from HTML in this folder, so the artwork stays editable and versioned.

| Output | Source | Size | Used for |
| --- | --- | --- | --- |
| `nuvora-hero-dark.jpg` | `nuvora-hero.html` | 2400×1260 | README hero |
| `nuvora-share-card.png` | `nuvora-hero.html?light` | 1280×640 | GitHub social preview |
| `nuvora-social-card.jpg` | `nuvora-social-card.html` | 1600×900 | Launch posts |
| `../ux/readme-how-it-works.jpg` | `readme/how-it-works.html` | 1600×480 | README |
| `../ux/readme-capabilities.jpg` | `readme/capabilities.html` | 1600×720 | README |
| `../ux/readme-approvals.jpg` | `readme/approvals.html` | 1600×470 | README |

The hero and launch cards tell the same five-stage story (ask, ground, act, approve, prove). Each stage is drawn in HTML from console fragments, styled by the shared `story.css`, so it stays sharp at thumbnail size. Real console screenshots live in `docs/ux/` and are captured by `scripts/browser-smoke.cjs`.

## Rebuild

```bash
./docs/social/build.sh
```

This needs Google Chrome (set `CHROME=` to use another path) and macOS `sips`. Nothing gets installed.

## GitHub social preview

GitHub has no API for the social preview image. To set it, go to **Settings → General → Social preview** and upload `nuvora-share-card.png`.
