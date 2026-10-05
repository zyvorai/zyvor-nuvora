// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
// Subsequence fuzzy scoring for the command palette. Higher is better; null means no match.
// Rewards contiguous runs, word-start hits and an early first hit.
export function fuzzyScore(query: string, text: string): number | null {
  const q = query.trim().toLowerCase();
  if (!q) return 0;
  const t = text.toLowerCase();
  if (t.includes(q)) return 1000 - t.indexOf(q) * 2 - (t.length - q.length) * 0.1;
  let score = 0;
  let ti = 0;
  let run = 0;
  let first = -1;
  for (const ch of q) {
    if (ch === ' ') continue;
    const at = t.indexOf(ch, ti);
    if (at < 0) return null;
    if (first < 0) first = at;
    run = at === ti ? run + 1 : 1;
    const wordStart = at === 0 || /[\s\-_/·.]/.test(t[at - 1]);
    score += 10 + run * 5 + (wordStart ? 15 : 0);
    ti = at + 1;
  }
  return score - first - (t.length - q.length) * 0.05;
}

export function fuzzyFilter<T>(query: string, items: T[], text: (item: T) => string, limit = 50): T[] {
  if (!query.trim()) return items.slice(0, limit);
  return items
    .map((item) => ({ item, score: fuzzyScore(query, text(item)) }))
    .filter((x): x is { item: T; score: number } => x.score !== null)
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
    .map((x) => x.item);
}
