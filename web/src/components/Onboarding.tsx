// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import { useState } from 'react';
import { Check, ChevronRight, X } from 'lucide-react';
import type { Row } from '../api';
import type { Page } from '../lib/navGroups';
import type { Collections } from '../lib/types';
import { ProgressRing } from './charts';

type Step = { id: string; title: string; text: string; page: Page; cta: string; done: boolean; adminOnly?: boolean };

export function onboardingSteps(collections: Collections, overview: Row): Step[] {
  const jobs = collections.jobs || [];
  return [
    {
      id: 'model',
      title: 'Connect a production model',
      text: 'Point Nuvora at an OpenAI-compatible, Ollama or Bedrock endpoint on the operator allow-list.',
      page: 'models',
      cta: 'Add a model',
      done: (collections.models || []).some((m) => m.provider !== 'demo'),
      adminOnly: true,
    },
    {
      id: 'knowledge',
      title: 'Index your own document',
      text: 'Add a document so answers can cite your evidence, not the bundled guide.',
      page: 'knowledge',
      cta: 'Add a document',
      done: (overview.counts?.documents || 0) > 1 || (collections.knowledge || []).length > 1,
    },
    {
      id: 'ask',
      title: 'Ask a grounded question',
      text: 'Choose a knowledge base in Playground and inspect the passages behind the answer.',
      page: 'playground',
      cta: 'Open playground',
      done: (overview.usage?.requests || 0) > 0,
    },
    {
      id: 'agent',
      title: 'Run an agent',
      text: 'Give a bounded agent a task and read its tool trace in Runs.',
      page: 'agents',
      cta: 'Run an agent',
      done: jobs.some((j) => j.type === 'agent'),
    },
    {
      id: 'approval',
      title: 'Decide an approval',
      text: 'Start the reviewed workflow, then approve or reject its exact action as a different person.',
      page: 'approvals',
      cta: 'Review approvals',
      done: (collections.approvals || []).some((a) => a.status !== 'pending'),
    },
    {
      id: 'evaluate',
      title: 'Measure with an evaluation',
      text: 'Run a suite and read its release verdict before you promote a change.',
      page: 'evaluations',
      cta: 'Run an evaluation',
      done: jobs.some((j) => j.type === 'evaluation'),
    },
  ];
}

export default function Onboarding({
  collections,
  overview,
  principal,
  onNavigate,
}: {
  collections: Collections;
  overview: Row;
  principal: Row;
  onNavigate: (p: Page) => void;
}) {
  const key = `nuvora-onboarding:${principal.tenant}:${principal.username}`;
  const [hidden, setHidden] = useState(() => {
    try {
      return localStorage.getItem(key) === 'dismissed';
    } catch {
      return false;
    }
  });
  const steps = onboardingSteps(collections, overview).filter((s) => !s.adminOnly || principal.role === 'admin');
  const done = steps.filter((s) => s.done).length;
  if (hidden || !overview.counts || done === steps.length) return null;
  const next = steps.find((s) => !s.done);

  const dismiss = () => {
    try {
      localStorage.setItem(key, 'dismissed');
    } catch {
      /* ignore */
    }
    setHidden(true);
  };

  return (
    <section className="card onboarding" aria-labelledby="onboarding-title">
      <header className="onboarding__head">
        <ProgressRing done={done} total={steps.length} />
        <div>
          <p className="kit-eyebrow">Get started</p>
          <h2 id="onboarding-title">Set up your workspace</h2>
          <p className="muted small">
            {done} of {steps.length} done{next ? ` · Next: ${next.title.toLowerCase()}` : ''}
          </p>
        </div>
        <button type="button" className="icon" aria-label="Dismiss setup checklist" onClick={dismiss}>
          <X size={16} />
        </button>
      </header>
      <ol className="onboarding__steps">
        {steps.map((s) => (
          <li key={s.id} className={s.done ? 'done' : s === next ? 'next' : ''}>
            <span className="onboarding__check" aria-hidden="true">
              {s.done ? <Check size={14} strokeWidth={2.5} /> : null}
            </span>
            <div>
              <b>{s.title}</b>
              <span>{s.text}</span>
            </div>
            {s.done ? (
              <span className="sr-only">Done</span>
            ) : (
              <button type="button" className={s === next ? 'primary compact' : 'btn-secondary compact'} onClick={() => onNavigate(s.page)}>
                {s.cta}
                <ChevronRight size={14} />
              </button>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
