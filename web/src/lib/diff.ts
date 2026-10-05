// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
export type DiffLine = { op: 'same' | 'add' | 'del'; text: string };

// Line diff by longest common subsequence; inputs are small (pretty-printed resources).
export function diffLines(before: string, after: string): DiffLine[] {
  const a = before.split('\n');
  const b = after.split('\n');
  const n = a.length;
  const m = b.length;
  const lcs: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--) lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      out.push({ op: 'same', text: a[i] });
      i++;
      j++;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) out.push({ op: 'del', text: a[i++] });
    else out.push({ op: 'add', text: b[j++] });
  }
  while (i < n) out.push({ op: 'del', text: a[i++] });
  while (j < m) out.push({ op: 'add', text: b[j++] });
  return out;
}

const META = new Set(['id', 'revision', 'created', 'updated', 'collection', 'resource_id', 'snapshot_of']);

export function pretty(value: unknown): string {
  if (!value || typeof value !== 'object') return JSON.stringify(value, null, 2);
  const clean = Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .filter(([k]) => !META.has(k))
      .sort(([x], [y]) => x.localeCompare(y)),
  );
  return JSON.stringify(clean, null, 2);
}
