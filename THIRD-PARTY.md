# Third-party software

The Python runtime uses the standard library. The optional AWS adapter uses boto3 under Apache-2.0. The frontend uses React/React DOM (MIT), lucide-react (ISC), and Vite/TypeScript and their transitive build dependencies under their respective licenses. Dependency versions are pinned in web/package-lock.json.

## Zyvor Netra design system

Parts of the console were adapted from Zyvor Netra (https://github.com/zyvorai/zyvor-netra):
- the design tokens and story primitives (`web/src/styles.css`, `web/src/styles/apple-story.css`)
- `web/src/theme.ts`, the navigation and page hero components, and the login layout
- the Zyvor logo marks (`web/public/zyvor-*.svg`)
- the deploy guard library (`scripts/lib/deploy-guards.sh`)

In Netra these files are licensed under LicenseRef-Zyvor-Production-1.0. Zyvor AI Labs, the copyright holder, relicenses these adapted copies under Apache-2.0 as part of Nuvora. The Zyvor name and logo remain trademarks of Zyvor AI Labs.

No model weights are bundled. Model access and weight licenses remain the operator's responsibility.
