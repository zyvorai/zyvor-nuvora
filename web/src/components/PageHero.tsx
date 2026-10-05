import type { ReactNode } from 'react';

export type HeroTint = 'green' | 'amber' | 'purple' | 'red';

type PageHeroProps = {
  eyebrow: string;
  title: string;
  lede: string;
  tint?: HeroTint;
  action?: ReactNode;
};

export default function PageHero({ eyebrow, title, lede, tint, action }: PageHeroProps) {
  return (
    <header className={tint ? `page-hero hero-tint-${tint}` : 'page-hero'}>
      <p className="eyebrow">{eyebrow}</p>
      <h1>{title}</h1>
      <p>{lede}</p>
      {action && <div className="apple-cta-row">{action}</div>}
    </header>
  );
}
