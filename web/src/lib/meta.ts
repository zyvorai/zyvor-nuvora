// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
export type Scalar = string | number | boolean;

const KEY = /^[a-z][a-z0-9_]{0,39}$/;

function scalar(raw: string): Scalar {
  const v = raw.trim();
  if (v === 'true' || v === 'false') return v === 'true';
  if (/^-?\d+(\.\d+)?$/.test(v)) return Number(v);
  return v;
}

// "team=ops" per line; numbers and true/false become typed values.
export function parseMeta(text: string): { meta: Record<string, Scalar>; error?: string } {
  const meta: Record<string, Scalar> = {};
  for (const raw of text.split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    const at = line.indexOf('=');
    const key = line.slice(0, at).trim();
    if (at < 1 || !KEY.test(key)) return { meta, error: `Use key=value with a lowercase key (got "${line}")` };
    meta[key] = scalar(line.slice(at + 1));
  }
  return { meta };
}

export function formatMeta(meta: Record<string, Scalar> | undefined): string {
  return Object.entries(meta || {})
    .map(([k, v]) => `${k}=${v}`)
    .join('\n');
}

// Like parseMeta, but "team=ops|sales" matches any listed value.
export function parseFilter(text: string): { filter?: Record<string, Scalar | { in: Scalar[] }>; error?: string } {
  const { meta, error } = parseMeta(text);
  if (error) return { error };
  if (!Object.keys(meta).length) return {};
  const filter: Record<string, Scalar | { in: Scalar[] }> = {};
  for (const [k, v] of Object.entries(meta)) filter[k] = typeof v === 'string' && v.includes('|') ? { in: v.split('|').map(scalar) } : v;
  return { filter };
}

export function splitGroups(text: string): string[] {
  return [...new Set(text.split(',').map((g) => g.trim()).filter(Boolean))];
}
