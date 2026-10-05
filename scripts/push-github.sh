#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
set -euo pipefail
# Run locally after reviewing the repository and signing in with gh.
command -v gh >/dev/null || { echo 'Install GitHub CLI and run gh auth login first.' >&2; exit 1; }
cd "$(dirname "$0")/.."
if [ ! -d .git ]; then
  git init -b main
  git add .
  git commit -m 'feat: Nuvora private AI platform with Netra UX, k3s deploy and docs site'
fi
gh repo create zyvorai/zyvor-nuvora --public --source=. --remote=origin --push \
  --description 'Nuvora: self-hosted AI application platform. Your models, your knowledge, your control.' \
  --homepage 'https://zyvorai.github.io/zyvor-nuvora/'
gh repo edit zyvorai/zyvor-nuvora --add-topic ai,llm,rag,agents,self-hosted,private-ai,kubernetes,k3s,helm,python,react,governance
gh api repos/zyvorai/zyvor-nuvora/pages -X POST -f build_type=workflow >/dev/null || true
echo 'Upload docs/social/nuvora-share-card.png under Settings → General → Social preview.'
