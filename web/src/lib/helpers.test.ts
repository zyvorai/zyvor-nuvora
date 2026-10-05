import { describe, expect, it } from 'vitest';
import { fuzzyFilter, fuzzyScore } from './fuzzy';
import { diffLines, pretty } from './diff';
import { layout, topoOrder } from './dag';
import { scale } from '../components/charts';
import { notifications, passwordStrength } from './notifications';

describe('fuzzy', () => {
  it('matches subsequences and ranks contiguous hits first', () => {
    expect(fuzzyScore('pg', 'Playground')).not.toBeNull();
    expect(fuzzyScore('xyz', 'Playground')).toBeNull();
    expect(fuzzyFilter('run', ['Batch inference', 'Runs', 'Guardrails'], (x) => x)[0]).toBe('Runs');
  });
  it('returns everything for an empty query', () => {
    expect(fuzzyFilter('', ['a', 'b'], (x) => x)).toEqual(['a', 'b']);
  });
});

describe('diff', () => {
  it('marks added and removed lines', () => {
    const d = diffLines('a\nb\nc', 'a\nc\nd');
    expect(d.map((l) => l.op + l.text)).toEqual(['samea', 'delb', 'samec', 'addd']);
  });
  it('ignores metadata and sorts keys', () => {
    expect(pretty({ revision: 3, name: 'x', a: 1 })).toBe('{\n  "a": 1,\n  "name": "x"\n}');
  });
});

describe('dag', () => {
  const steps = [
    { id: 'find', type: 'retrieve' },
    { id: 'draft', type: 'generate', depends_on: ['find'] },
    { id: 'check', type: 'condition', depends_on: ['find'] },
    { id: 'review', type: 'approval', depends_on: ['draft'], when: 'check' },
  ];
  it('assigns layers by longest path', () => {
    const l = layout(steps);
    const layer = Object.fromEntries(l.nodes.map((n) => [n.id, n.layer]));
    expect(layer).toEqual({ input: 0, find: 1, draft: 2, check: 2, review: 3 });
    expect(l.rows).toBe(2);
    expect(l.edges.some((e) => e.conditional && e.from === 'check')).toBe(true);
  });
  it('orders steps topologically and rejects cycles', () => {
    const order = topoOrder([...steps].reverse())!.map((s) => s.id);
    expect(order[0]).toBe('find');
    expect(order[3]).toBe('review');
    expect(topoOrder([{ id: 'a', type: 'generate', depends_on: ['b'] }, { id: 'b', type: 'generate', depends_on: ['a'] }])).toBeNull();
  });
});

describe('chart scale', () => {
  it('maps the max to the top and zero to the bottom', () => {
    const y = scale([0, 10], 100, 0);
    expect(y(10)).toBe(0);
    expect(y(0)).toBe(100);
  });
});

describe('notifications', () => {
  const now = 1000000;
  const collections = {
    approvals: [
      { id: 'a1', status: 'pending', expires: now + 60, proposer: 'bob', name: 'Approve deploy', created: now - 30, job_id: 'j1' },
      { id: 'a2', status: 'pending', expires: now - 1, proposer: 'bob', name: 'Expired', created: now - 90 },
    ],
    jobs: [
      { id: 'j2', name: 'agent run', status: 'failed', created: now - 20, updated: now - 10, result: { error: 'boom' } },
      { id: 'j3', name: 'old run', status: 'failed', created: now - 200000, updated: now - 200000 },
    ],
  };
  it('shows decisions to approvers and recent failures, newest first', () => {
    const notes = notifications(collections, { role: 'approver', username: 'carol' }, now);
    expect(notes.map((n) => n.id)).toEqual(['job:j2:failed', 'approval:a1']);
    expect(notes[1].href).toBe('#jobs/j1');
  });
  it('hides other people’s approvals from developers', () => {
    expect(notifications(collections, { role: 'developer', username: 'carol' }, now).map((n) => n.id)).toEqual(['job:j2:failed']);
  });
});

describe('passwordStrength', () => {
  it('caps short passwords and rewards variety', () => {
    expect(passwordStrength('Ab1!').score).toBeLessThanOrEqual(1);
    expect(passwordStrength('correct-Horse-battery-9').score).toBe(5);
  });
});
