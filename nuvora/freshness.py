# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Document freshness helpers. Prefer newer source_version / last_seen."""
import time

def score(doc, now=None):
    """0.0–1.0 freshness. Higher is fresher.
    Uses last_seen (unix) or source_version string if numeric.
    """
    now = now or time.time()
    last = doc.get('last_seen') or doc.get('updated') or 0
    age_days = max(0, (now - float(last)) / 86400)
    # decay: full score under 1 day, half at 30 days, near 0 at 365
    if age_days < 1:
        return 1.0
    if age_days > 365:
        return 0.1
    return max(0.1, 1.0 - (age_days / 365) * 0.9)

def prefer_fresh(docs, now=None):
    """Sort documents by freshness score descending, stable for ties."""
    return sorted(docs, key=lambda d: (-score(d, now), d.get('name', '')))
