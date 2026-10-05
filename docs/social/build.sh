#!/usr/bin/env bash
# Render the social cards in docs/social/ and the README cards in docs/social/readme/.
# Needs Google Chrome and macOS `sips` (both already on a Mac); nothing is installed.
#   ./docs/social/build.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
UX="$HERE/../ux"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
[[ -x "$CHROME" ]] || { echo "Google Chrome not found (set CHROME=...)" >&2; exit 1; }
TMP="$(mktemp -d "${TMPDIR:-/tmp}/nuvora-social.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

shoot() { # <url> <width> <height> <scale> <png>
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --allow-file-access-from-files \
    --force-device-scale-factor="$4" --virtual-time-budget=3000 \
    --window-size="$2,$3" --screenshot="$5" "$1" >/dev/null 2>&1
}
jpeg() { # <png> <out.jpg>
  sips -s format jpeg -s formatOptions 90 "$1" --out "$2" >/dev/null
  echo "wrote ${2#"$HERE/../../"} ($(sips -g pixelWidth -g pixelHeight "$2" | awk '/pixel/{printf "%s ", $2}')px, $(du -k "$2" | cut -f1) KB)"
}

shoot "file://$HERE/nuvora-hero.html" 1200 630 2 "$TMP/hero.png"
jpeg "$TMP/hero.png" "$HERE/nuvora-hero-dark.jpg"

shoot "file://$HERE/nuvora-hero.html?light" 1200 630 2 "$TMP/share.png"
sips -z 640 1280 "$TMP/share.png" --out "$HERE/nuvora-share-card.png" >/dev/null
echo "wrote docs/social/nuvora-share-card.png (1280x640, GitHub social preview)"

shoot "file://$HERE/nuvora-social-card.html" 1600 900 1 "$TMP/social.png"
jpeg "$TMP/social.png" "$HERE/nuvora-social-card.jpg"

shoot "file://$HERE/readme/how-it-works.html" 1600 480 1 "$TMP/how.png"
jpeg "$TMP/how.png" "$UX/readme-how-it-works.jpg"
shoot "file://$HERE/readme/capabilities.html" 1600 720 1 "$TMP/cap.png"
jpeg "$TMP/cap.png" "$UX/readme-capabilities.jpg"
shoot "file://$HERE/readme/approvals.html" 1600 470 1 "$TMP/appr.png"
jpeg "$TMP/appr.png" "$UX/readme-approvals.jpg"
