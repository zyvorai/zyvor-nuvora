// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { describe, expect, it } from 'vitest';
import { navGroups, pages, readFocus, readPage } from './navGroups';

describe('navigation', () => {
  it('reaches every routable page with a label and blurb', () => {
    const reachable = new Set<string>();
    for (const g of navGroups) {
      if (g.page) reachable.add(g.page);
      for (const c of g.children ?? []) {
        expect(c.label.length).toBeGreaterThan(0);
        expect(c.blurb.length).toBeGreaterThan(10);
        reachable.add(c.page);
      }
    }
    expect([...reachable].sort()).toEqual([...pages].sort());
  });
  it('falls back to overview for unknown hashes', () => {
    expect(readPage('#jobs')).toBe('jobs');
    expect(readPage('#nope')).toBe('overview');
    expect(readPage('')).toBe('overview');
  });
  it('reads a resource deep link', () => {
    expect(readPage('#agents/abc')).toBe('agents');
    expect(readFocus('#agents/abc')).toBe('abc');
    expect(readFocus('#agents')).toBeUndefined();
  });
});
