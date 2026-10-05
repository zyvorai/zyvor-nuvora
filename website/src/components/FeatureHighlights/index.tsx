import type {ReactNode} from 'react';
import Link from '@docusaurus/Link';
import Heading from '@theme/Heading';
import styles from './styles.module.css';

type FeatureItem = {
  title: string;
  description: ReactNode;
  to: string;
};

const FeatureList: FeatureItem[] = [
  {
    title: 'Your models',
    description:
      'Fabric and Gryvia presets with model discovery, any OpenAI-compatible server, Ollama, optional Bedrock, and a labeled offline demo. Exact host allow-list; credentials stay in environment variables.',
    to: '/docs/operate/integrations',
  },
  {
    title: 'Cited knowledge',
    description:
      'Upload PDF, Word, HTML, Markdown or CSV. Hybrid BM25 + vector retrieval with optional semantic embeddings and LLM rerank. Every grounded answer shows its passages.',
    to: '/docs/operate/documents-and-evaluations',
  },
  {
    title: 'Agents with scoped tools',
    description:
      'A bounded model-and-tool loop over typed tools, including read-only Netra evidence and Keep sandboxed code. Code, memory writes and external actions wait for a person.',
    to: '/docs/core-concepts/approvals',
  },
  {
    title: 'Reviewed workflows',
    description:
      'Validated DAGs with approval steps and Zyntra handoffs, durable checkpoints and pinned revisions, built visually or as JSON.',
    to: '/docs/core-concepts/approvals',
  },
  {
    title: 'Author ≠ approver',
    description:
      'Consequential actions pause with the exact arguments and a fingerprint. Self-approval is disabled in the console and refused by the API.',
    to: '/docs/core-concepts/approvals',
  },
  {
    title: 'Hash-chained evidence',
    description:
      'Every run, decision and change becomes an audit event linked by sha256. Export it and verify the chain offline.',
    to: '/docs/security',
  },
  {
    title: 'Guardrails',
    description:
      'Topic and instruction-override patterns, size limits, and email/account redaction, applied to inputs and outputs.',
    to: '/docs/security',
  },
  {
    title: 'Usage, cost, evaluation',
    description:
      'A usage ledger with token budgets, plus evaluation suites that combine assertions, LLM-judge criteria and groundedness into a release verdict.',
    to: '/docs/operate/documents-and-evaluations',
  },
  {
    title: 'Self-hosted, SSO, scales out',
    description:
      'A standard-library core with optional extras. OIDC single sign-on, SQLite or PostgreSQL with several replicas, Docker, Helm, and a one-command k3s deploy.',
    to: '/docs/operate/postgres',
  },
];

function Feature({title, description, to}: FeatureItem) {
  return (
    <div className="col col--4">
      <Link to={to} className={styles.card}>
        <Heading as="h3">{title}</Heading>
        <p>{description}</p>
      </Link>
    </div>
  );
}

export default function FeatureHighlights(): ReactNode {
  return (
    <section className={styles.features}>
      <div className="container">
        <div className="row">
          {FeatureList.map((props, idx) => (
            <Feature key={idx} {...props} />
          ))}
        </div>
      </div>
    </section>
  );
}
