import {useState} from 'react';
import type {ReactNode} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import useBaseUrl from '@docusaurus/useBaseUrl';
import Layout from '@theme/Layout';
import Heading from '@theme/Heading';
import CodeBlock from '@theme/CodeBlock';
import Reveal from '@site/src/components/Reveal';

import styles from './index.module.css';

const REPO = 'https://github.com/zyvorai/zyvor-nuvora';

function Hero() {
  const shot = useBaseUrl('/12-playground-dark.png');
  return (
    <header className={styles.hero}>
      <div className={styles.aurora} aria-hidden>
        <span />
        <span />
        <span />
      </div>
      <div className={styles.gridGlow} aria-hidden />
      <div className={clsx('container', styles.heroInner)}>
        <a className={styles.pill} href="#capabilities">
          <span className={styles.pillDot} />
          New in 0.3: guardrails, routers, MCP agents, multimodal, connectors, training
          <span aria-hidden> →</span>
        </a>
        <Heading as="h1" className={styles.heroTitle}>
          Private AI
          <br />
          <span className={styles.gradientText}>that shows its work.</span>
        </Heading>
        <p className={styles.heroLede}>
          Build assistants, agents and workflows on your own models. Every answer
          cites its sources, every consequential action waits for a different
          person to approve it, and every step lands in an audit chain you can
          verify offline.
        </p>
        <div className={styles.heroButtons}>
          <Link className={styles.btnPrimary} to="/docs/getting-started/quickstart">
            Get started
          </Link>
          <Link className={styles.btnGhost} to="/gallery">
            Take the tour
          </Link>
          <Link className={styles.btnGhost} to={REPO}>
            GitHub
          </Link>
        </div>
        <div className={styles.terminal}>
          <span className={styles.prompt}>$</span>
          <code>python3 -m nuvora.server --demo</code>
          <span className={styles.terminalNote}>no GPU · no pip install · no hosted model</span>
        </div>

        <div className={styles.stage}>
          <div className={styles.frame}>
            <div className={styles.frameBar}>
              <span />
              <span />
              <span />
              <em>nuvora.example.com</em>
            </div>
            <img src={shot} alt="Nuvora playground with an answer and the evidence passages behind it" />
          </div>
          <div className={clsx(styles.float, styles.floatA)}>
            <b>3 sources cited</b>
            <span>every passage with a content digest</span>
          </div>
          <div className={clsx(styles.float, styles.floatB)}>
            <b>Approval required</b>
            <span>author is never approver</span>
          </div>
          <div className={clsx(styles.float, styles.floatC)}>
            <b>Audit chain verified</b>
            <span>hash-chained, exportable</span>
          </div>
        </div>
      </div>
    </header>
  );
}

const STEPS = [
  {n: '01', title: 'Ground', body: 'Hybrid retrieval finds the passages behind the answer, filtered by who may see them.'},
  {n: '02', title: 'Act', body: 'Agents and workflows call your APIs and MCP tools within a bounded budget.'},
  {n: '03', title: 'Approve', body: 'Anything that writes, sends or spends pauses until a second person signs off.'},
  {n: '04', title: 'Prove', body: 'Runs, guardrail decisions and approvals land in a hash-chained audit log.'},
];

function Pipeline() {
  return (
    <section className={styles.section}>
      <div className="container">
        <Reveal className={styles.sectionHead}>
          <p className={styles.eyebrow}>How it works</p>
          <Heading as="h2" className={styles.h2}>
            From a question to an approved, recorded action.
          </Heading>
        </Reveal>
        <div className={styles.pipeline}>
          {STEPS.map((s, i) => (
            <Reveal key={s.n} delay={i * 110} className={styles.step}>
              <span className={styles.stepNum}>{s.n}</span>
              <Heading as="h3">{s.title}</Heading>
              <p>{s.body}</p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

type Tile = {title: string; body: string; tags?: string[]; size?: 'wide' | 'tall'; tone?: 'ink' | 'glow'};

const TILES: Tile[] = [
  {
    title: 'Your models, your endpoints',
    body: 'Connect any model you run, on an exact host allow-list. Cascade routers start small and escalate when a judge flags a weak answer, with cached tokens priced in.',
    tags: ['vLLM', 'Ollama', 'OpenAI-compatible', 'AWS', 'Cascade routing', 'Prompt caching'],
    size: 'wide',
    tone: 'glow',
  },
  {
    title: 'Author is never approver',
    body: 'Consequential steps wait for a different person, who sees the exact action and its fingerprint.',
    size: 'tall',
    tone: 'ink',
  },
  {
    title: 'Guardrails as policy',
    body: 'Word and regex filters, PII with checksum validation, contextual grounding and an optional classifier model.',
  },
  {
    title: 'Knowledge with access rules',
    body: 'Web, S3 and Confluence connectors sync incrementally. Group rules from SSO decide who retrieves what.',
  },
  {
    title: 'Agents with real tools',
    body: 'Import OpenAPI actions, attach MCP servers, keep long-term memory, and trace every step in a waterfall.',
    tags: ['OpenAPI', 'MCP', 'Memory', 'OTLP'],
  },
  {
    title: 'Documents, images, audio',
    body: 'OCR, transcription and vision in chat. Extraction blueprints turn documents into fields, with low-confidence review.',
  },
  {
    title: 'Evaluate and experiment',
    body: 'Grounded and LLM-judge evaluations, plus prompt experiments that compare variants on the same suite.',
  },
  {
    title: 'Fine-tune and distill',
    body: 'Validated datasets go to your own trainer for LoRA, QLoRA or distillation, and the result registers as a model.',
  },
  {
    title: 'Image generation',
    body: 'An images API and playground mode, with budgets, guardrails and expiring artifacts.',
  },
  {
    title: 'Evidence and cost',
    body: 'A usage ledger with budgets per workspace beside an audit chain you can export and verify offline.',
  },
];

function Bento() {
  return (
    <section id="capabilities" className={clsx(styles.section, styles.sectionTint)}>
      <div className="container">
        <Reveal className={styles.sectionHead}>
          <p className={styles.eyebrow}>Capabilities</p>
          <Heading as="h2" className={styles.h2}>
            Everything an AI platform needs.
            <br />
            <span className={styles.muted}>Nothing that leaves your network.</span>
          </Heading>
        </Reveal>
        <div className={styles.bento}>
          {TILES.map((t, i) => (
            <Reveal
              key={t.title}
              delay={(i % 3) * 80}
              className={clsx(
                styles.tile,
                t.size === 'wide' && styles.tileWide,
                t.size === 'tall' && styles.tileTall,
                t.tone === 'ink' && styles.tileInk,
                t.tone === 'glow' && styles.tileGlow,
              )}>
              <Heading as="h3">{t.title}</Heading>
              <p>{t.body}</p>
              {t.tags ? (
                <div className={styles.tags}>
                  {t.tags.map((tag) => (
                    <span key={tag}>{tag}</span>
                  ))}
                </div>
              ) : null}
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

const TOUR = [
  {id: 'playground', label: 'Playground', src: '/02-playground.png', caption: 'Ask, ground and verify: every answer next to its sources.'},
  {id: 'builder', label: 'Workflow builder', src: '/15-workflow-builder.png', caption: 'Retrieval, model, tool and approval steps on one canvas.'},
  {id: 'approvals', label: 'Approvals', src: '/07-approvals.png', caption: 'The exact action, its proposer, expiry and fingerprint.'},
  {id: 'guardrails', label: 'Guardrails', src: '/08-guardrails.png', caption: 'Filters, PII and grounding checks, edited as policy.'},
  {id: 'evidence', label: 'Evidence', src: '/09-evidence.png', caption: 'A hash-chained audit log you can export and verify.'},
  {id: 'usage', label: 'Usage', src: '/10-usage.png', caption: 'Tokens, cost and cache savings per workspace.'},
];

function Tour() {
  const [active, setActive] = useState(0);
  const shot = TOUR[active];
  const src = useBaseUrl(shot.src);
  return (
    <section className={styles.section}>
      <div className="container">
        <Reveal className={styles.sectionHead}>
          <p className={styles.eyebrow}>The console</p>
          <Heading as="h2" className={styles.h2}>
            A real product, not a mockup.
          </Heading>
        </Reveal>
        <div className={styles.tabs} role="tablist" aria-label="Console views">
          {TOUR.map((t, i) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={i === active}
              className={clsx(styles.tab, i === active && styles.tabActive)}
              onClick={() => setActive(i)}>
              {t.label}
            </button>
          ))}
        </div>
        <div className={styles.tourFrame} role="tabpanel">
          <img key={shot.id} src={src} alt={shot.caption} className={styles.tourImg} />
        </div>
        <p className={styles.tourCaption}>
          {shot.caption} <Link to="/gallery">See all views →</Link>
        </p>
      </div>
    </section>
  );
}

const PY = `import os
from openai import OpenAI

client = OpenAI(
    base_url="https://nuvora.example.com/v1",
    api_key=os.environ["NUVORA_TOKEN"],  # a scoped service token
)

reply = client.chat.completions.create(
    model="auto",  # or a model id, or "router:<id>"
    messages=[{"role": "user", "content": "Summarize our refund policy"}],
)
print(reply.choices[0].message.content)`;

function DropIn() {
  return (
    <section className={clsx(styles.section, styles.sectionInk)}>
      <div className={clsx('container', styles.split)}>
        <Reveal>
          <p className={styles.eyebrow}>Drop-in API</p>
          <Heading as="h2" className={styles.h2}>
            Point your existing clients at Nuvora.
          </Heading>
          <p className={styles.inkLede}>
            Chat, streaming and image endpoints speak the OpenAI wire format, so
            SDKs and tools work unchanged. Behind them, every request passes
            guardrails, routing, budgets and the audit chain.
          </p>
          <ul className={styles.checks}>
            <li>Scoped service tokens per workspace</li>
            <li>Token budgets and concurrency caps</li>
            <li>Every call metered and recorded</li>
          </ul>
        </Reveal>
        <Reveal delay={120} className={styles.code}>
          <CodeBlock language="python" title="client.py">
            {PY}
          </CodeBlock>
        </Reveal>
      </div>
    </section>
  );
}

const PAINS = [
  ['You can’t send prompts or documents to a hosted AI vendor', 'Your own endpoints only, on an exact host allow-list'],
  ['Answers sound right, but nobody can say where they came from', 'Cited passages with content digests on every grounded answer'],
  ['An agent wants to send, write or spend', 'The step pauses until a different person approves the exact action'],
  ['Audit asks what happened six weeks ago', 'A hash-chained audit log you can export and verify offline'],
  ['Teams share a platform but not their data', 'Tenant-scoped storage, four roles, SSO groups and document access rules'],
  ['Finance asks what AI costs', 'A usage ledger per workspace, with budgets and cache savings'],
];

function Pains() {
  return (
    <section className={styles.section}>
      <div className="container">
        <Reveal className={styles.sectionHead}>
          <p className={styles.eyebrow}>Why Nuvora</p>
          <Heading as="h2" className={styles.h2}>
            Built for the questions risk teams ask.
          </Heading>
        </Reveal>
        <div className={styles.pains}>
          {PAINS.map(([pain, answer], i) => (
            <Reveal key={pain} delay={(i % 2) * 90} className={styles.pain}>
              <p className={styles.painQ}>{pain}</p>
              <p className={styles.painA}>{answer}</p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

function Closing() {
  return (
    <section className={styles.closing}>
      <div className={styles.closingGlow} aria-hidden />
      <div className="container">
        <Reveal className={styles.closingInner}>
          <Heading as="h2" className={styles.closingTitle}>
            Run it on your laptop in a minute.
            <br />
            <span className={styles.gradientText}>Run it on your cluster in one command.</span>
          </Heading>
          <div className={styles.closingCode}>
            <code>./scripts/deploy-remote.sh HOST USER</code>
          </div>
          <p className={styles.closingNote}>
            Builds on the host, imports into k3s and serves HTTPS with a generated
            admin password. SQLite on one node, PostgreSQL across replicas.
          </p>
          <div className={styles.heroButtons}>
            <Link className={styles.btnPrimary} to="/docs/getting-started/deploy">
              Deploy guide
            </Link>
            <Link className={styles.btnGhost} to="/docs/security">
              Security model
            </Link>
          </div>
          <p className={styles.license}>
            Zyvor Production License v1.0: free for evaluation, development and
            other non-production use; production needs a commercial license. The
            capability matrix in the repository says exactly what is and isn’t
            built.
          </p>
        </Reveal>
      </div>
    </section>
  );
}

export default function Home(): ReactNode {
  return (
    <Layout
      title="Nuvora: private AI that shows its work"
      description="A self-hosted AI application platform: your own model endpoints, cited retrieval, tool-using agents, guardrails, separate-human approvals and hash-chained evidence.">
      <Hero />
      <main>
        <Pipeline />
        <Bento />
        <Tour />
        <DropIn />
        <Pains />
        <Closing />
      </main>
    </Layout>
  );
}
