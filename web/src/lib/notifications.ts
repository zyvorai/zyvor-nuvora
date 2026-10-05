import type { Row } from '../api';
import type { Collections } from './types';

export type Note = { id: string; tone: 'amber' | 'red' | 'green' | 'blue'; title: string; detail: string; time: number; href: string };

const DAY = 86400;

// Derived from data the console already polls; nothing is stored server-side.
export function notifications(collections: Collections, principal: Row, now = Date.now() / 1000): Note[] {
  const canDecide = principal.role === 'admin' || principal.role === 'approver';
  const notes: Note[] = [];
  for (const a of collections.approvals || []) {
    if (a.status !== 'pending' || a.expires < now) continue;
    const mine = a.proposer === principal.username;
    if (!canDecide && !mine) continue;
    notes.push({
      id: 'approval:' + a.id,
      tone: 'amber',
      title: mine ? `Waiting on another approver: ${a.name}` : `Decision needed: ${a.name}`,
      detail: `Proposed by ${a.proposer}`,
      time: a.created,
      href: a.job_id ? '#jobs/' + a.job_id : '#approvals',
    });
  }
  for (const j of collections.jobs || []) {
    if (now - (j.updated || j.created) > DAY) continue;
    if (j.status === 'failed' || j.status === 'rejected')
      notes.push({ id: 'job:' + j.id + ':' + j.status, tone: 'red', title: `${j.name} ${j.status}`, detail: j.result?.error || 'Inspect the run evidence', time: j.updated || j.created, href: '#jobs/' + j.id });
    else if (j.status === 'completed' && j.principal?.username === principal.username)
      notes.push({ id: 'job:' + j.id + ':completed', tone: 'green', title: `${j.name} completed`, detail: j.type === 'evaluation' && j.result ? `Score ${Math.round((j.result.score || 0) * 100)}%` : 'Evidence is ready', time: j.updated || j.created, href: '#jobs/' + j.id });
  }
  return notes.sort((a, b) => b.time - a.time).slice(0, 20);
}

export function passwordStrength(value: string): { score: number; label: string } {
  if (!value) return { score: 0, label: '' };
  let score = 0;
  if (value.length >= 12) score++;
  if (value.length >= 16) score++;
  if (/[a-z]/.test(value) && /[A-Z]/.test(value)) score++;
  if (/\d/.test(value)) score++;
  if (/[^A-Za-z0-9]/.test(value)) score++;
  if (value.length < 12) score = Math.min(score, 1);
  return { score, label: ['Too short', 'Weak', 'Fair', 'Good', 'Strong', 'Excellent'][score] };
}
