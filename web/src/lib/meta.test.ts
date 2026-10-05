// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { describe, expect, it } from 'vitest';
import { formatMeta, parseFilter, parseMeta, splitGroups } from './meta';
import { connectorKeys } from '../components/CreateForm';
import { syncSummary } from '../pages/Catalog';

describe('metadata helpers', () => {
  it('parses typed key=value lines and round-trips', () => {
    const { meta } = parseMeta('team=ops\nyear=2026\npublic=true\nnote=a=b');
    expect(meta).toEqual({ team: 'ops', year: 2026, public: true, note: 'a=b' });
    expect(parseMeta(formatMeta(meta)).meta).toEqual(meta);
    expect(parseMeta('Bad Key=1').error).toMatch(/lowercase/);
  });
  it('builds equality and membership filters', () => {
    expect(parseFilter('')).toEqual({});
    expect(parseFilter('team=ops|sales\nyear=2026').filter).toEqual({ team: { in: ['ops', 'sales'] }, year: 2026 });
  });
  it('splits and de-duplicates groups', () => {
    expect(splitGroups(' finance, legal ,finance,')).toEqual(['finance', 'legal']);
  });
});

describe('connectors', () => {
  it('sends only the fields of the chosen source', () => {
    expect(connectorKeys('s3')).not.toContain('url');
    expect(connectorKeys('confluence')).toContain('space');
    expect(connectorKeys(undefined)).toContain('depth');
  });
  it('summarises the last sync', () => {
    expect(syncSummary({})).toBe('never synced');
    expect(syncSummary({ last_result: { added: 2, updated: 1, unchanged: 3, removed: 0, failed: 1 } })).toBe('2 added · 1 updated · 3 unchanged · 0 removed · 1 failed');
  });
});
