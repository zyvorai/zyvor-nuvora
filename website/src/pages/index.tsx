import type {ReactNode} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import useBaseUrl from '@docusaurus/useBaseUrl';
import Layout from '@theme/Layout';
import Heading from '@theme/Heading';
import FeatureHighlights from '@site/src/components/FeatureHighlights';
import ScreenshotStrip from '@site/src/components/ScreenshotStrip';
import Reveal from '@site/src/components/Reveal';

import styles from './index.module.css';

function HomepageHeader() {
  const hero = useBaseUrl('/11-overview-dark.png');
  return (
    <header className={clsx('hero hero--primary', styles.heroBanner)}>
      <div className="container">
        <div className={styles.heroGrid}>
          <div>
            <Heading as="h1" className="hero__title">
              Your models.
              <br />
              Your knowledge.
              <br />
              Your control.
            </Heading>
            <p className="hero__subtitle">
              A self-hosted AI application platform. Connect your own model
              endpoints, ground every answer in cited evidence, run
              tool-using agents, and keep each consequential action behind a
              different human's approval.
            </p>
            <div className={styles.buttons}>
              <Link
                className="button button--secondary button--lg"
                to="/docs/getting-started/quickstart">
                Get Started
              </Link>
              <Link
                className="button button--outline button--lg button--secondary"
                to="/gallery">
                Take the tour
              </Link>
              <Link
                className="button button--outline button--lg button--secondary"
                to="https://github.com/zyvorai/zyvor-nuvora">
                View on GitHub
              </Link>
            </div>
          </div>
          <div className={styles.heroMedia}>
            <img
              src={hero}
              alt="Nuvora workspace overview in dark mode"
            />
            <p className={styles.heroMediaCaption}>
              Captured against a live k3s deployment, not a mockup.
            </p>
          </div>
        </div>
      </div>
    </header>
  );
}

function ProblemStatement() {
  const flow = useBaseUrl('/readme-how-it-works.jpg');
  return (
    <section className={styles.problem}>
      <div className="container">
        <Reveal className="row">
          <div className="col col--8 col--offset-2 text--center">
            <Heading as="h2" className={styles.sectionHeading}>
              Private AI that shows its work
            </Heading>
            <p>
              Most teams can't send prompts or documents to a hosted AI
              vendor, and can't trust an answer nobody can trace. Nuvora runs
              on your hardware and talks only to model endpoints on your
              allow-list. That can be vLLM, Ollama, any OpenAI-compatible
              server, or Bedrock. Every grounded answer cites the passage it
              came from.
            </p>
            <p>
              When an agent or workflow wants to send, write, or spend, it
              stops and waits. A <em>different</em> person approves the exact
              action, fingerprint included. The decision lands in a
              hash-chained audit log that you can export and verify offline.
            </p>
          </div>
        </Reveal>
        <Reveal>
          <img className={styles.flowCard} src={flow} alt="How a request flows through Nuvora" />
        </Reveal>
      </div>
    </section>
  );
}

function TrustBand() {
  return (
    <section className={styles.trust}>
      <div className="container">
        <Reveal className={styles.trustGrid}>
          <div>
            <Heading as="h3" className={styles.sectionHeading}>
              Source-available, and honest about its limits
            </Heading>
            <p>
              Zyvor Production License v1.0: free for evaluation, development
              and other non-production use; production use needs a commercial
              license. CI runs on every push: backend tests on Python
              3.11–3.13, console typecheck, tests and build, Helm lint and
              render, shellcheck, and a real-browser smoke test. 0.1.0 is an
              evaluation release, and the capability matrix says exactly what
              isn't built yet.
            </p>
            <Link to="/docs/security">Read the security model →</Link>
          </div>
          <div className={styles.trustBadges}>
            <img
              src="https://github.com/zyvorai/zyvor-nuvora/actions/workflows/ci.yml/badge.svg"
              alt="CI status"
            />
            <img
              src="https://img.shields.io/badge/License-Zyvor%20Production%20v1.0-orange.svg"
              alt="Zyvor Production License v1.0"
            />
          </div>
        </Reveal>
      </div>
    </section>
  );
}

function DeployCTA() {
  return (
    <section className={styles.enterprise}>
      <div className="container text--center">
        <Reveal>
          <Heading as="h2" className={styles.sectionHeading}>
            One command to a k3s host
          </Heading>
          <p className={styles.enterpriseCopy}>
            <code>./scripts/deploy-remote.sh HOST USER</code> builds on the
            host, installs the Helm chart, and serves HTTPS on NodePort 30789.
          </p>
          <Link
            className="button button--primary button--lg"
            to="/docs/getting-started/deploy">
            Deploy guide
          </Link>
        </Reveal>
      </div>
    </section>
  );
}

export default function Home(): ReactNode {
  return (
    <Layout
      title="Nuvora: your models, your knowledge, your control"
      description="A self-hosted AI application platform: your own model endpoints, cited retrieval, tool-using agents, separate-human approvals, and hash-chained evidence.">
      <HomepageHeader />
      <main>
        <ProblemStatement />
        <Reveal>
          <FeatureHighlights />
        </Reveal>
        <Reveal>
          <ScreenshotStrip />
        </Reveal>
        <TrustBand />
        <DeployCTA />
      </main>
    </Layout>
  );
}
