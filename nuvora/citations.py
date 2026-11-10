# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Simple lexical overlap score between an answer and retrieved passages."""
import re

def overlap_score(answer, passages):
    """0.0–1.0: fraction of answer tokens that appear in any passage (stopwords ignored)."""
    if not answer or not passages:
        return 0.0
    stop = {'the','a','an','of','to','and','or','in','on','for','with','is','are','was','were','be','as','at','by'}
    tokens = [w for w in re.findall(r'\w+', answer.lower()) if w not in stop and len(w) > 2]
    if not tokens:
        return 0.0
    blob = ' '.join(str(p) for p in passages).lower()
    hits = sum(1 for t in tokens if t in blob)
    return round(hits / len(tokens), 3)
