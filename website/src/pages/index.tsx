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

function utm(path: string, campaign: string): string {
  return `https://zyvor.dev${path}?utm_source=github&utm_medium=nuvora&utm_campaign=${campaign}`;
}

function SalesButtons({campaign, quickstart}: {campaign: string; quickstart?: boolean}) {
  return (
    <div className={styles.heroButtons}>
      <a className={styles.btnPrimary} href={utm('/schedule', campaign)}>
        Book a demo
      </a>
      <a className={styles.btnGhost} href={utm('/poc', campaign)}>
        Start a 30-day PoC
      </a>
      {quickstart ? (
        <Link className={styles.btnGhost} to="/docs/getting-started/quickstart">
          Quickstart
        </Link>
      ) : null}
    </div>
  );
}

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
        <p className={styles.pill}>
          <span className={styles.pillDot} />
          Self-hosted AI applications and agents
        </p>
        <Heading as="h1" className={styles.heroTitle}>
          The AI platform you run.
          <br />
          <span className={styles.gradientText}>Every answer cited. Every action approved.</span>
        </Heading>
        <p className={styles.heroLede}>
          Build assistants, agents and workflows on the models you choose, inside
          your own network. Nuvora grounds every answer in your documents, holds
          every consequential action for a second person, and keeps a record your
          auditors can verify.
        </p>
        <SalesButtons campaign="pages_hero" quickstart />
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
            <b>Sources cited</b>
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

const KICKERS = [
  {
    kicker: 'Your data stays home.',
    body: 'Prompts, documents and answers stay on infrastructure you run, and an exact host allow-list decides where any request may go.',
  },
  {
    kicker: 'Any model, your terms.',
    body: 'vLLM, Ollama or any OpenAI-compatible endpoint. Switch models without rewriting the app, and see every token against a budget.',
  },
  {
    kicker: 'Nothing acts alone.',
    body: 'Anything that writes, sends or spends waits for a different person to approve the exact action.',
  },
  {
    kicker: 'Proof, not promises.',
    body: 'Runs, guardrail decisions and approvals land in a hash-chained audit log you can export and check offline.',
  },
];

function Kickers() {
  return (
    <section className={styles.sectionTight}>
      <div className={clsx('container', styles.kickers)}>
        {KICKERS.map((k, i) => (
          <Reveal key={k.kicker} delay={i * 90} className={styles.kicker}>
            <p className={styles.kickerTitle}>{k.kicker}</p>
            <p className={styles.kickerBody}>{k.body}</p>
          </Reveal>
        ))}
      </div>
    </section>
  );
}

type Pillar = {
  tab: string;
  title: string;
  body: string;
  points: string[];
  shot: string;
  alt: string;
  link: {label: string; to: string};
};

const PILLARS: Pillar[] = [
  {
    tab: 'Model choice',
    title: 'Use the best model for each job, on your endpoints.',
    body: 'Connect the models you already run and pick per task. Discover models automatically, set prices, and let routers start small and escalate only when an answer looks weak.',
    points: [
      'vLLM, Ollama, any OpenAI-compatible endpoint, or AWS-hosted models',
      'Fabric and Gryvia presets with model discovery',
      'An exact host allow-list: nothing reaches a host that is not on it',
    ],
    shot: '/17-settings.png',
    alt: 'Nuvora settings with model endpoints and integrations',
    link: {label: 'Connect a model', to: '/docs/getting-started/connect-a-model'},
  },
  {
    tab: 'Your data',
    title: 'AI that knows your business, and who may see what.',
    body: 'Upload documents or sync them from your systems. Hybrid retrieval returns the passages behind every answer, filtered by the groups each person belongs to.',
    points: [
      'Web, S3 and Confluence connectors with incremental sync',
      'OCR for scans, audio transcription, typed extraction with review',
      'Fine-tuning and distillation jobs sent to a trainer you run',
    ],
    shot: '/03-knowledge.png',
    alt: 'Nuvora knowledge base with documents and content digests',
    link: {label: 'Connectors', to: '/docs/operate/connectors'},
  },
  {
    tab: 'Agents and workflows',
    title: 'Agents that do real work, inside the lines.',
    body: 'Give agents a closed set of tools: your OpenAPI actions, MCP servers and suite integrations. Chain steps in a visual builder with branches, reviews and handoffs.',
    points: [
      'OpenAPI import and remote MCP servers, registered by an admin',
      'Session and long-term memory, with writes behind approval',
      'Workflow steps for retrieval, extraction, images and Zyntra handoff',
    ],
    shot: '/15-workflow-builder.png',
    alt: 'Nuvora workflow builder with retrieval, model and approval steps on a canvas',
    link: {label: 'Agents and tools', to: '/docs/operate/agents-and-tools'},
  },
  {
    tab: 'Safety and guardrails',
    title: 'One policy, applied to every input, output and tool call.',
    body: 'Write guardrails once and they screen prompts, answers and tool arguments alike. When a classifier is unsure or unavailable, the request is blocked, not waved through.',
    points: [
      'Word and regex filters, PII detection with checksum validation',
      'Grounding checks that score answers against retrieved sources',
      'Exact-action approvals: different person, fingerprint, one-hour expiry',
    ],
    shot: '/08-guardrails.png',
    alt: 'Nuvora guardrails page with filter, PII and grounding policies',
    link: {label: 'Guardrails', to: '/docs/operate/guardrails'},
  },
  {
    tab: 'Cost control',
    title: 'Spend where it matters, and see every token.',
    body: 'Cascade routers try the cheapest capable model first. Caching, batch jobs and per-workspace budgets keep costs predictable, and the ledger shows what each run cost.',
    points: [
      'Cascade routers that escalate on weak or unsure answers',
      'Prompt cache, with provider cached-token pricing tracked separately',
      'Token budgets, concurrency caps and batch requests',
    ],
    shot: '/10-usage.png',
    alt: 'Nuvora usage ledger with token spend and budgets per workspace',
    link: {label: 'Routing', to: '/docs/operate/routing'},
  },
  {
    tab: 'Evaluate and prove',
    title: 'Know it works before you ship. Prove it after.',
    body: 'Evaluation suites score grounding and judge criteria per case, and prompt experiments compare variants on the same suite. Every run is traced and every decision recorded.',
    points: [
      'Assertions, LLM-judge and grounded cases, with reasons',
      'Run waterfall with per-step timing and OpenTelemetry export',
      'Hash-chained audit log, exportable and verifiable offline',
    ],
    shot: '/18-eval-case-editor.png',
    alt: 'Nuvora evaluation case editor with grounded and judge criteria',
    link: {label: 'Documents and evaluations', to: '/docs/operate/documents-and-evaluations'},
  },
];

function CapabilityTour() {
  const [active, setActive] = useState(0);
  const p = PILLARS[active];
  const src = useBaseUrl(p.shot);
  return (
    <section id="capabilities" className={clsx(styles.section, styles.sectionTint)}>
      <div className="container">
        <Reveal className={styles.sectionHead}>
          <p className={styles.eyebrow}>Meet Nuvora</p>
          <Heading as="h2" className={styles.h2}>
            Everything you need to put AI in production.
            <br />
            <span className={styles.muted}>In one platform you control.</span>
          </Heading>
        </Reveal>
        <div className={styles.tabs} role="tablist" aria-label="Nuvora capabilities">
          {PILLARS.map((pillar, i) => (
            <button
              key={pillar.tab}
              type="button"
              role="tab"
              id={`cap-tab-${i}`}
              aria-selected={i === active}
              aria-controls="cap-panel"
              className={clsx(styles.tab, i === active && styles.tabActive)}
              onClick={() => setActive(i)}>
              {pillar.tab}
            </button>
          ))}
        </div>
        <div id="cap-panel" role="tabpanel" aria-labelledby={`cap-tab-${active}`} className={styles.split}>
          <div>
            <Heading as="h3" className={styles.panelTitle}>
              {p.title}
            </Heading>
            <p className={styles.panelBody}>{p.body}</p>
            <ul className={styles.checksLight}>
              {p.points.map((point) => (
                <li key={point}>{point}</li>
              ))}
            </ul>
            <Link className={styles.arrowLink} to={p.link.to}>
              {p.link.label} →
            </Link>
          </div>
          <div className={styles.tourFrame}>
            <img key={p.shot} src={src} alt={p.alt} className={styles.tourImg} />
          </div>
        </div>
      </div>
    </section>
  );
}

const LOOP = ['Plan', 'Call a tool', 'Policy check', 'Approve', 'Act', 'Record'];

function Agents() {
  const shot = useBaseUrl('/07-approvals.png');
  return (
    <section className={styles.section}>
      <div className={clsx('container', styles.split)}>
        <Reveal>
          <p className={styles.eyebrow}>Agents</p>
          <Heading as="h2" className={styles.h2}>
            Take agents to production with full control.
          </Heading>
          <p className={styles.panelBody}>
            Every step an agent takes is bounded, screened and on the record. The
            moment it wants to change something real, a person signs off on the
            exact action first.
          </p>
          <ol className={styles.loop} aria-label="Agent loop">
            {LOOP.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
          <ul className={styles.checksLight}>
            <li>A closed tool registry and a fixed step limit. No shell, no open internet.</li>
            <li>Code runs in a Keep sandbox with no network, only after a different person approves the exact code.</li>
            <li>Durable jobs survive restarts. Work interrupted by a failed worker is flagged for review, not lost.</li>
            <li>Every step timed in a run waterfall, exportable to your tracing stack.</li>
          </ul>
        </Reveal>
        <Reveal delay={120} className={styles.tourFrame}>
          <img src={shot} alt="Nuvora approvals queue showing a pending action with its fingerprint" className={styles.tourImg} loading="lazy" />
        </Reveal>
      </div>
    </section>
  );
}

const USE_CASES = [
  {glyph: '?', title: 'Ask your documents', body: 'Answers grounded in your policies, contracts and runbooks, with the source passage a click away.'},
  {glyph: '✓', title: 'Assistants that act', body: 'Open the ticket, issue the refund, update the record, after the right person approves.'},
  {glyph: '▤', title: 'Turn documents into data', body: 'Extract typed fields from forms and scans. Low-confidence results wait for a reviewer.'},
  {glyph: '◐', title: 'Images and audio', body: 'Read scans with OCR, transcribe calls, reason over images in chat, and generate images.'},
  {glyph: '⇄', title: 'Automate workflows', body: 'Chain retrieval, models, reviews and handoffs into flows that pause wherever a human should decide.'},
  {glyph: '◎', title: 'Explain incidents', body: 'Ask why traffic dropped. Agents read Netra network evidence and cite it in the answer.'},
];

function UseCases() {
  return (
    <section className={clsx(styles.section, styles.sectionTint)}>
      <div className="container">
        <Reveal className={styles.sectionHead}>
          <p className={styles.eyebrow}>Do more with Nuvora</p>
          <Heading as="h2" className={styles.h2}>
            From idea to production, fast.
          </Heading>
        </Reveal>
        <div className={styles.useGrid}>
          {USE_CASES.map((u, i) => (
            <Reveal key={u.title} delay={(i % 3) * 80} className={styles.tile}>
              <span className={styles.useGlyph} aria-hidden>
                {u.glyph}
              </span>
              <Heading as="h3">{u.title}</Heading>
              <p>{u.body}</p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

const COMPARE = [
  ['Where it runs', 'The provider’s cloud regions', 'Your hardware, your cloud account, or fully air-gapped'],
  ['Where prompts go', 'To the provider’s service', 'Only to hosts on an exact allow-list you control'],
  ['Who approves an agent’s action', 'Whatever confirmation steps you configure', 'A different person, on the exact action, every time'],
  ['What you can prove', 'Logs in the provider’s monitoring service', 'A hash-chained audit log you export and verify offline'],
  ['Where agent code runs', 'A managed runtime in the provider’s cloud', 'A sandbox with no network, after approval'],
  ['How model spend works', 'Metered by the provider', 'Your endpoints, with a ledger and budgets per workspace'],
];

function Compare() {
  return (
    <section className={styles.section}>
      <div className="container">
        <Reveal className={styles.sectionHead}>
          <p className={styles.eyebrow}>Why Nuvora</p>
          <Heading as="h2" className={styles.h2}>
            Everything a hosted AI platform does for you.
            <br />
            <span className={styles.muted}>On ground you own.</span>
          </Heading>
        </Reveal>
        <Reveal className={styles.compareWrap}>
          <table className={styles.compare}>
            <thead>
              <tr>
                <th scope="col" aria-hidden />
                <th scope="col">Typical hosted AI platform</th>
                <th scope="col" className={styles.compareLead}>
                  Nuvora
                </th>
              </tr>
            </thead>
            <tbody>
              {COMPARE.map(([label, hosted, ours]) => (
                <tr key={label}>
                  <th scope="row">{label}</th>
                  <td>{hosted}</td>
                  <td className={styles.compareLead}>{ours}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Reveal>
        <p className={styles.compareNote}>
          Hosted platforms bring managed model catalogs and regional compliance
          programs. Nuvora brings control.
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

const SH = `git clone ${REPO}.git && cd zyvor-nuvora
export NUVORA_ADMIN_PASSWORD='choose-your-own-strong-password'
python3 -m nuvora.server --demo     # http://127.0.0.1:8789

# k3s on your own host, HTTPS with a generated admin password
./scripts/deploy-remote.sh HOST USER`;

function Quickstart() {
  return (
    <section id="quickstart" className={clsx(styles.section, styles.sectionInk)}>
      <div className="container">
        <Reveal className={styles.sectionHead}>
          <p className={styles.eyebrow}>Get started</p>
          <Heading as="h2" className={styles.h2}>
            Running in minutes. Yours for good.
          </Heading>
          <p className={styles.inkLede}>
            Try it offline with Python 3.11 only, point it at a model you run, then
            deploy for the team with Helm or k3s. Existing OpenAI clients work
            unchanged, and every request passes guardrails, routing, budgets and the
            audit chain.
          </p>
        </Reveal>
        <div className={styles.codeGrid}>
          <Reveal className={styles.code}>
            <CodeBlock language="bash" title="Try it">
              {SH}
            </CodeBlock>
          </Reveal>
          <Reveal delay={120} className={styles.code}>
            <CodeBlock language="python" title="client.py">
              {PY}
            </CodeBlock>
          </Reveal>
        </div>
        <div className={styles.heroButtons}>
          <Link className={styles.btnPrimary} to="/docs/getting-started/quickstart">
            Quickstart
          </Link>
          <Link className={styles.btnGhost} to="/docs/getting-started/deploy">
            Deploy guide
          </Link>
          <Link className={styles.btnGhost} to="/gallery">
            Console tour
          </Link>
          <Link className={styles.btnGhost} to={REPO}>
            GitHub
          </Link>
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
            Put AI to work.
            <br />
            <span className={styles.gradientText}>Keep it under control.</span>
          </Heading>
          <p className={styles.closingNote}>
            See Nuvora on your models and your documents, with a second person
            signing off on every agent action.
          </p>
          <SalesButtons campaign="pages_closing" />
          <p className={styles.license}>
            0.3.0 is an evaluation release. Zyvor Production License v1.0: free for
            evaluation, development and other non-production use; production needs a
            commercial license. The{' '}
            <Link to={`${REPO}/blob/main/docs/CAPABILITIES.md`}>capability matrix</Link>{' '}
            says exactly what is and isn’t built.
          </p>
        </Reveal>
      </div>
    </section>
  );
}

export default function Home(): ReactNode {
  return (
    <Layout
      title="Nuvora: the AI platform you run"
      description="The self-hosted AI platform for assistants, agents and workflows: your models, cited answers, guardrails, human approvals and a verifiable audit trail, on infrastructure you control.">
      <Hero />
      <main>
        <Kickers />
        <CapabilityTour />
        <Agents />
        <UseCases />
        <Compare />
        <Quickstart />
        <Closing />
      </main>
    </Layout>
  );
}
