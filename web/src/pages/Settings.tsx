import { useEffect, useState } from 'react';
import { Moon, ShieldCheck, Sun } from 'lucide-react';
import { api, type Row } from '../api';
import { Gauge } from '../components/charts';
import { Badge, Card, Skeleton } from '../components/kit';
import type { Theme } from '../theme';

export default function Settings({ principal, theme, onTheme, onPassword }: { principal: Row; theme: Theme; onTheme: (t: Theme) => void; onPassword: () => void }) {
  const admin = principal.role === 'admin';
  const [settings, setSettings] = useState<Row | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!admin) return;
    api('/api/settings')
      .then(setSettings)
      .catch((e) => setError(String(e)));
  }, [admin]);

  return (
    <div className="grid settings">
      <Card title="Account">
        <dl className="facts">
          <div>
            <dt>Username</dt>
            <dd>{principal.username}</dd>
          </div>
          <div>
            <dt>Role</dt>
            <dd>
              <Badge value={principal.role} />
            </dd>
          </div>
          <div>
            <dt>Workspace</dt>
            <dd>{principal.tenant}</dd>
          </div>
        </dl>
        <div className="actions">
          <button type="button" className="btn-secondary" onClick={onPassword}>
            <ShieldCheck size={15} />
            Change password
          </button>
          <a className="buttonlike btn-secondary" href="#keys">
            Manage API keys
          </a>
        </div>
      </Card>

      <Card title="Appearance">
        <div className="theme-choice" role="radiogroup" aria-label="Theme">
          {(['light', 'dark'] as Theme[]).map((t) => (
            <button key={t} type="button" role="radio" aria-checked={theme === t} className={'theme-choice__item ' + t} onClick={() => onTheme(t)}>
              <span className="theme-choice__swatch" aria-hidden="true">
                {t === 'light' ? <Sun size={18} /> : <Moon size={18} />}
              </span>
              {t === 'light' ? 'Light' : 'Dark'}
            </button>
          ))}
        </div>
        <p className="note">Saved in this browser. The login screen keeps its dark hero in both themes.</p>
      </Card>

      <Card title="Workspace" className={admin ? 'span3' : ''}>
        {!admin ? (
          <p className="muted">Workspace configuration is visible to administrators.</p>
        ) : error ? (
          <p role="alert" className="error">
            {error}
          </p>
        ) : !settings ? (
          <Skeleton rows={6} label="Loading settings" />
        ) : (
          <div className="settings-grid">
            <dl className="facts">
              <div>
                <dt>Release</dt>
                <dd>
                  {settings.version} · {settings.maturity}
                </dd>
              </div>
              <div>
                <dt>Transport</dt>
                <dd>
                  <Badge value={settings.transport} />
                </dd>
              </div>
              <div>
                <dt>Background worker</dt>
                <dd>
                  <Badge value={settings.worker} />
                </dd>
              </div>
              <div>
                <dt>Demo models</dt>
                <dd>{settings.demo_models ? 'Offline demo model present (synthetic output)' : 'None'}</dd>
              </div>
              <div>
                <dt>Provider allow-list</dt>
                <dd>{settings.provider_hosts.length ? settings.provider_hosts.map((h: string) => <code key={h} className="host-chip">{h}</code>) : 'None'}</dd>
              </div>
            </dl>
            <div className="settings-side">
              <h3>Guardrail policy</h3>
              <dl className="facts">
                <div>
                  <dt>PII redaction</dt>
                  <dd>{settings.policy.redact_pii ? 'On' : 'Off'}</dd>
                </div>
                <div>
                  <dt>Injection detection</dt>
                  <dd>{settings.policy.detect_injection ? 'On' : 'Off'}</dd>
                </div>
                <div>
                  <dt>Max characters</dt>
                  <dd>{Number(settings.policy.max_chars || 0).toLocaleString()}</dd>
                </div>
                <div>
                  <dt>Denied topics</dt>
                  <dd>{settings.policy.blocked_topics?.length ? settings.policy.blocked_topics.join(', ') : 'None'}</dd>
                </div>
              </dl>
              <Gauge value={settings.budget.used_24h} max={settings.budget.limit} label={`${Number(settings.budget.limit).toLocaleString()} daily tokens`} />
              <h3>Server limits</h3>
              <dl className="facts">
                {Object.entries(settings.limits as Record<string, number>).map(([k, v]) => (
                  <div key={k}>
                    <dt>{k.replaceAll('_', ' ')}</dt>
                    <dd>{v.toLocaleString()}</dd>
                  </div>
                ))}
              </dl>
              <a className="link-inline" href="#policies">
                Edit guardrails ›
              </a>
            </div>
          </div>
        )}
        {admin && <p className="note">Provider hosts, TLS and limits come from the server environment. Change them in the deployment, not here.</p>}
      </Card>
    </div>
  );
}
