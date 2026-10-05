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
      'OpenAI-compatible (vLLM, llama.cpp), Ollama, optional Bedrock, and a labeled offline demo. Remote hosts need HTTPS and an exact allow-list entry; credentials stay in environment variables.',
    to: '/docs/core-concepts/architecture',
  },
  {
    title: 'Cited knowledge',
    description:
      'Chunked documents with content digests and hybrid BM25 + vector retrieval. Every grounded answer shows the passages it used.',
    to: '/docs/core-concepts/architecture',
  },
  {
    title: 'Agents with scoped tools',
    description:
      'A bounded model-and-tool loop over registered, typed tool schemas. Memory writes and external actions wait for a person.',
    to: '/docs/core-concepts/approvals',
  },
  {
    title: 'Reviewed workflows',
    description:
      'Validated DAGs of retrieve, generate, template, condition, extract and approval steps, with durable checkpoints and pinned revisions.',
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
      'A per-workspace usage ledger with token budgets and concurrency caps, plus evaluation suites with release verdicts.',
    to: '/docs/core-concepts/architecture',
  },
  {
    title: 'Self-hosted, zero deps',
    description:
      'A Python standard-library server with a prebuilt React console. Docker, Helm, and a one-command k3s deploy over HTTPS.',
    to: '/docs/getting-started/deploy',
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
