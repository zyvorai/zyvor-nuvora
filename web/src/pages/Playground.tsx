import { useState, type FormEvent } from 'react';
import { BookOpen, Sparkles } from 'lucide-react';
import { api, money, type Row } from '../api';
import { Badge, Card, Field, ListEmpty } from '../components/kit';
import type { Act } from '../lib/types';

export default function Playground({ models, knowledge, canWrite, act }: { models: Row[]; knowledge: Row[]; canWrite: boolean; act: Act }) {
  const [model, setModel] = useState('auto');
  const [kb, setKB] = useState('');
  const [message, setMessage] = useState('How does Keep protect an agent?');
  const [answer, setAnswer] = useState<Row | null>(null);
  const [citations, setCitations] = useState<Row[]>([]);
  const [busy, setBusy] = useState(false);

  async function run(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    await act(async () => {
      let context = '';
      if (kb) {
        const r = await api('/api/retrieve', { knowledge_ids: [kb], query: message });
        setCitations(r.citations);
        context = JSON.stringify(r.citations);
      } else setCitations([]);
      const r = await api('/api/chat', {
        model,
        messages: [
          { role: 'system', content: kb ? 'Answer using the supplied evidence. Cite document ids. If evidence is absent, say so.' : 'Be helpful and precise.' },
          { role: 'user', content: context ? message + '\nEvidence:\n' + context : message },
        ],
        temperature: 0,
        cache: true,
      });
      setAnswer(r);
    });
    setBusy(false);
  }

  return (
    <div className="split">
      <Card title="Ask your model">
        <form onSubmit={run}>
          <div className="form-grid">
            <Field label="Model">
              <select value={model} onChange={(e) => setModel(e.target.value)}>
                <option value="auto">Auto · lowest configured price</option>
                {models
                  .filter((m) => m.capability === 'chat')
                  .map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                    </option>
                  ))}
              </select>
            </Field>
            <Field label="Grounding">
              <select value={kb} onChange={(e) => setKB(e.target.value)}>
                <option value="">No knowledge base</option>
                {knowledge.map((k) => (
                  <option key={k.id} value={k.id}>
                    {k.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="Your question">
            <textarea rows={6} value={message} onChange={(e) => setMessage(e.target.value)} required />
          </Field>
          <button type="submit" className="primary" disabled={!canWrite || busy}>
            <Sparkles size={16} />
            {busy ? 'Generating…' : 'Generate answer'}
          </button>
        </form>
        {answer && (
          <div className="answer">
            <div className="kit-section__head">
              <h3>Response</h3>
              <Badge value={answer.evidence_class} />
            </div>
            <p>{answer.content}</p>
            <div className="small muted">
              {answer.cached ? 'Cache hit' : 'Fresh response'} · {money(answer.cost)} · {answer.routing}
            </div>
          </div>
        )}
      </Card>
      <Card title="Evidence sources">
        {citations.length ? (
          citations.map((c, i) => (
            <article className="citation" key={i}>
              <span className="kit-eyebrow">Source {i + 1}</span>
              <h3>{c.document}</h3>
              <p>{c.text}</p>
              <small>
                Chunk {c.index} · {c.source}
              </small>
              <code>{String(c.digest).slice(0, 20)}…</code>
            </article>
          ))
        ) : (
          <ListEmpty icon={BookOpen} title="Ground your answer" description="Select a knowledge base to retrieve cited passages." />
        )}
        <p className="note">Offline demo is a transport and workflow fixture. It echoes supplied text; it does not reason or produce a grounded AI answer.</p>
      </Card>
    </div>
  );
}
