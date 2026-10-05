import { useState } from 'react';

// Pure-SVG charts. Colours come from CSS tokens via currentColor and classes.

export function scale(values: number[], height: number, pad = 2): (v: number) => number {
  const max = Math.max(0, ...values);
  const min = Math.min(0, ...values);
  const span = max - min || 1;
  return (v) => pad + (height - pad * 2) * (1 - (v - min) / span);
}

export function Sparkline({ values, label, width = 120, height = 32 }: { values: number[]; label: string; width?: number; height?: number }) {
  const data = values.length > 1 ? values : [0, ...values, 0].slice(0, Math.max(2, values.length));
  const y = scale(data, height);
  const step = width / (data.length - 1);
  const line = data.map((v, i) => `${i ? 'L' : 'M'}${(i * step).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  return (
    <svg className="spark" viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img" aria-label={label}>
      <title>{label}</title>
      <path className="spark__area" d={`${line} L${width},${height} L0,${height} Z`} />
      <path className="spark__line" d={line} />
    </svg>
  );
}

export type Series = { label: string; values: number[]; tone?: 'blue' | 'green' | 'amber' | 'purple' | 'cyan' };

export function AreaChart({
  labels,
  series,
  format = (v) => String(v),
  height = 200,
  title,
}: {
  labels: string[];
  series: Series[];
  format?: (v: number) => string;
  height?: number;
  title: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 640;
  const n = Math.max(labels.length, 2);
  const all = series.flatMap((s) => s.values);
  const y = scale(all, height - 24, 8);
  const x = (i: number) => (i * width) / (n - 1);
  const tick = Math.ceil(labels.length / 7);
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${width} ${height - 24}`} style={{ height: height - 24 }} role="img" aria-label={title} preserveAspectRatio="none" onMouseLeave={() => setHover(null)}>
        <title>{title}</title>
        {[0.25, 0.5, 0.75].map((f) => (
          <line key={f} className="chart__grid" x1={0} x2={width} y1={(height - 24) * f} y2={(height - 24) * f} />
        ))}
        {series.map((s) => {
          const line = s.values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
          return (
            <g key={s.label} className={'chart__series ' + (s.tone ?? 'blue')}>
              <path className="chart__area" d={`${line} L${x(s.values.length - 1)},${height - 24} L0,${height - 24} Z`} />
              <path className="chart__line" d={line} />
            </g>
          );
        })}
        {labels.map((_, i) => (
          <rect key={i} x={x(i) - width / n / 2} width={width / n} y={0} height={height - 24} fill="transparent" onMouseEnter={() => setHover(i)} />
        ))}
        {hover !== null && <line className="chart__cursor" x1={x(hover)} x2={x(hover)} y1={0} y2={height - 24} />}
      </svg>
      <div className="chart__axis" aria-hidden="true">
        {labels.map((l, i) =>
          (i % tick === 0 && labels.length - 1 - i >= tick / 2) || i === labels.length - 1 ? (
            <span key={l + i} style={{ left: `${(x(i) / width) * 100}%` }} className={i === 0 ? 'first' : i === labels.length - 1 ? 'last' : ''}>
              {l}
            </span>
          ) : null,
        )}
      </div>
      <figcaption className="chart__legend">
        {series.map((s) => (
          <span key={s.label} className={'chart__key ' + (s.tone ?? 'blue')}>
            <i />
            {s.label}
            {hover !== null && <b>{format(s.values[hover] ?? 0)}</b>}
          </span>
        ))}
        {hover !== null && <span className="muted">{labels[hover]}</span>}
      </figcaption>
    </figure>
  );
}

export function BarList({ items, format = (v) => String(v) }: { items: { label: string; value: number }[]; format?: (v: number) => string }) {
  const max = Math.max(1e-9, ...items.map((i) => i.value));
  return (
    <ul className="bar-list">
      {items.map((i) => (
        <li key={i.label}>
          <span className="bar-list__label">{i.label}</span>
          <span className="bar-list__track">
            <span className="bar-list__fill" style={{ width: `${Math.max(2, (i.value / max) * 100)}%` }} />
          </span>
          <b>{format(i.value)}</b>
        </li>
      ))}
    </ul>
  );
}

export function Donut({ parts, label, size = 132 }: { parts: { label: string; value: number; tone: string }[]; label: string; size?: number }) {
  const total = parts.reduce((s, p) => s + p.value, 0);
  const r = 15.915;
  let offset = 25;
  return (
    <div className="donut">
      <svg viewBox="0 0 42 42" width={size} height={size} role="img" aria-label={label}>
        <title>{label}</title>
        <circle className="donut__track" cx="21" cy="21" r={r} />
        {total > 0 &&
          parts.map((p) => {
            const pct = (p.value / total) * 100;
            const el = <circle key={p.label} className={'donut__part ' + p.tone} cx="21" cy="21" r={r} strokeDasharray={`${pct} ${100 - pct}`} strokeDashoffset={offset} />;
            offset -= pct;
            return el;
          })}
        <text x="21" y="22.5" textAnchor="middle" className="donut__total">
          {total}
        </text>
      </svg>
      <ul className="donut__legend">
        {parts.map((p) => (
          <li key={p.label} className={p.tone}>
            <i />
            {p.label} <b>{p.value}</b>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function Gauge({ value, max, label }: { value: number; max: number; label: string }) {
  const pct = max > 0 ? Math.min(1, value / max) : 0;
  const tone = pct > 0.9 ? 'red' : pct > 0.7 ? 'amber' : 'green';
  return (
    <div className="gauge" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={max} aria-valuenow={value}>
      <div className="gauge__track">
        <div className={'gauge__fill ' + tone} style={{ width: `${pct * 100}%` }} />
      </div>
      <small>
        {Math.round(pct * 100)}% of {label}
      </small>
    </div>
  );
}

export function ProgressRing({ done, total, size = 44 }: { done: number; total: number; size?: number }) {
  const pct = total ? (done / total) * 100 : 0;
  return (
    <svg className="ring" viewBox="0 0 42 42" width={size} height={size} role="img" aria-label={`${done} of ${total} done`}>
      <circle className="donut__track" cx="21" cy="21" r="15.915" />
      <circle className="ring__fill" cx="21" cy="21" r="15.915" strokeDasharray={`${pct} ${100 - pct}`} strokeDashoffset="25" />
      <text x="21" y="24" textAnchor="middle" className="ring__text">
        {done}/{total}
      </text>
    </svg>
  );
}
