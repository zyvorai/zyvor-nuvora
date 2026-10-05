import type {ReactNode} from 'react';
import Layout from '@theme/Layout';
import Heading from '@theme/Heading';
import useBaseUrl from '@docusaurus/useBaseUrl';
import styles from './gallery.module.css';

type Shot = {
  src: string;
  caption: string;
};

// docs/ux is written by scripts/browser-smoke.cjs in this order.
const TOUR: Shot[] = [
  {src: '/00-login.png', caption: 'Sign in'},
  {src: '/01-overview.png', caption: 'Overview'},
  {src: '/02-playground.png', caption: 'Playground'},
  {src: '/03-knowledge.png', caption: 'Knowledge'},
  {src: '/04-agents.png', caption: 'Agents'},
  {src: '/05-workflows.png', caption: 'Workflows'},
  {src: '/06-runs.png', caption: 'Runs'},
  {src: '/07-approvals.png', caption: 'Approvals'},
  {src: '/08-guardrails.png', caption: 'Guardrails'},
  {src: '/09-evidence.png', caption: 'Evidence'},
  {src: '/10-usage.png', caption: 'Usage & cost'},
  {src: '/12-playground-dark.png', caption: 'Playground, dark'},
  {src: '/14-command-palette.png', caption: 'Command palette'},
  {src: '/15-workflow-builder.png', caption: 'Workflow builder'},
  {src: '/16-api-keys.png', caption: 'API keys'},
  {src: '/17-settings.png', caption: 'Settings'},
];

function ShotCard({shot}: {shot: Shot}) {
  const src = useBaseUrl(shot.src);
  return (
    <figure className={styles.shot}>
      <img src={src} alt={shot.caption} loading="lazy" />
      <figcaption>{shot.caption}</figcaption>
    </figure>
  );
}

export default function Gallery(): ReactNode {
  const hero = useBaseUrl('/11-overview-dark.png');
  return (
    <Layout
      title="Tour"
      description="A walkthrough of the Nuvora console, captured against a live k3s deployment.">
      <header className={styles.header}>
        <div className="container">
          <Heading as="h1">Product tour</Heading>
          <p>
            Every screenshot below was captured by the browser smoke test
            against a running k3s deployment, not a mockup.
          </p>
        </div>
      </header>
      <main className="container">
        <div className={styles.demo}>
          <img src={hero} alt="Nuvora overview in dark mode" />
          <p className={styles.caption}>
            The Overview: your intelligence stack (models, knowledge, agents,
            control), workspace posture, and recent runs.
          </p>
        </div>
        <div className={styles.grid}>
          {TOUR.map((shot) => (
            <ShotCard key={shot.src} shot={shot} />
          ))}
        </div>
      </main>
    </Layout>
  );
}
