import { useCallback, useEffect, useMemo, useState } from 'react';
import { LEVELS, parseGigachatReport } from './gigachatReport';
import CheckDialog from './CheckDialog';
import './App.css';

// В Docker файлы отдаёт nginx (alias /srv/data), в dev-режиме — плагин из vite.config.js
const DATA_BASE = '/data';

const FILTERS = [
  { id: 'all', label: 'Все' },
  { id: 'critical', label: 'Критично' },
  { id: 'high', label: 'Высоко' },
  { id: 'medium', label: 'Средне' },
  { id: 'low', label: 'Низко' },
];

async function fetchPipelineFile(name) {
  const response = await fetch(`${DATA_BASE}/${name}`, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`${name}: HTTP ${response.status}`);
  }
  return response;
}

async function loadPipelineData() {
  const [reportResponse, sonarResponse] = await Promise.all([
    fetchPipelineFile('gigachat_explanations.txt'),
    fetchPipelineFile('sonar_full_data.json'),
  ]);

  return {
    report: parseGigachatReport(await reportResponse.text()),
    sonar: await sonarResponse.json(),
  };
}

function metricValue(metrics, key, fallback = '—') {
  const value = metrics[key];
  return value === null || value === undefined || value === '' ? fallback : value;
}

function metricNumber(metrics, key, fallback = '0') {
  const value = metricValue(metrics, key, fallback);
  const number = Number(value);
  return Number.isFinite(number) ? new Intl.NumberFormat('ru-RU').format(number) : value;
}

function formatDebt(rawMinutes) {
  const minutes = Number(rawMinutes);
  if (!Number.isFinite(minutes)) return '—';
  if (minutes < 60) return `${minutes} мин`;

  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} ч ${rest} мин` : `${hours} ч`;
}

function formatDate(timestamp) {
  if (timestamp === null || timestamp === undefined) return null;

  const value = Number(timestamp);
  if (!Number.isFinite(value)) return null;

  return new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }).format(new Date(value));
}

function plural(count, one, few, many) {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

function findSonarIssue(issues, finding) {
  if (!finding.file) return null;
  return (
    issues.find(
      (issue) => issue.file === finding.file && issue.line === finding.line,
    ) || null
  );
}

function FindingCard({ finding }) {
  const level = LEVELS[finding.level];

  return (
    <article className={`card level-${finding.level}`}>
      <div className="rank">{finding.rank ?? '•'}</div>

      <div className="card-content">
        <div className="card-head">
          <span className={`pill type-${finding.type.toLowerCase().replace(/[^a-z]+/g, '-')}`}>
            {finding.typeLabel}
          </span>

          {finding.file && (
            <span className="location">
              {finding.file}
              {finding.line ? <b>:{finding.line}</b> : null}
            </span>
          )}

          <span className={`pill priority-${finding.level}`}>{level.label}</span>

          {finding.priorityLabel && (
            <span className="priority-note">GigaChat: {finding.priorityLabel}</span>
          )}
        </div>

        {finding.what && (
          <p className="finding-text">
            <span className="label">Что не так.</span> {finding.what}
          </p>
        )}

        {finding.why && (
          <p className="finding-text muted">
            <span className="label">Почему это важно.</span> {finding.why}
          </p>
        )}

        {finding.reason && (
          <p className="finding-text muted">
            <span className="label">Почему такой приоритет.</span> {finding.reason}
          </p>
        )}

        {finding.recommendation && (
          <div className="advice">
            <span className="advice-label">Рекомендация</span>
            <p>{finding.recommendation}</p>
          </div>
        )}

        {finding.sonar && (
          <p className="sonar">
            SonarQube: <b>{finding.sonar.severity}</b> · правило {finding.sonar.rule}
            {finding.sonar.effort ? ` · ${finding.sonar.effort}` : ''}
          </p>
        )}
      </div>
    </article>
  );
}

function App() {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState('all');
  const [checkOpen, setCheckOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const refreshData = useCallback(() => setReloadKey((value) => value + 1), []);

  useEffect(() => {
    let active = true;

    loadPipelineData()
      .then((loaded) => {
        if (!active) return;
        setData(loaded);
        setError('');
      })
      .catch((err) => {
        if (active) setError(err.message);
      });

    return () => {
      active = false;
    };
  }, [reloadKey]);

  const report = data?.report ?? null;
  const sonar = data?.sonar ?? null;

  const metrics = useMemo(
    () =>
      Object.fromEntries(
        (sonar?.metrics || []).map((metric) => [metric.key, metric.value]),
      ),
    [sonar],
  );

  const sonarIssues = useMemo(
    () =>
      (sonar?.issues || []).map((issue) => ({
        ...issue,
        file: String(issue.component || '').split(':').pop(),
      })),
    [sonar],
  );

  const findings = useMemo(
    () =>
      (report?.findings || []).map((finding) => ({
        ...finding,
        sonar: findSonarIssue(sonarIssues, finding),
      })),
    [report, sonarIssues],
  );

  if (error) {
    return (
      <div className="page">
        <div className="notice">
          Не удалось загрузить данные пайплайна: {error}
          <br />
          Запустите проверку репозитория — результат появится здесь автоматически.
          <br />
          <button
            type="button"
            className="check-button"
            onClick={() => setCheckOpen(true)}
          >
            <span className="check-button-plus">+</span>
            Проверить репозиторий
          </button>
        </div>

        <CheckDialog
          open={checkOpen}
          onClose={() => setCheckOpen(false)}
          onFinished={refreshData}
        />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="page">
        <div className="empty">Загружаю данные пайплайна…</div>
      </div>
    );
  }

  const visibleFindings =
    filter === 'all' ? findings : findings.filter((finding) => finding.level === filter);

  const qualityGate = metricValue(metrics, 'alert_status');
  const lastCommit = formatDate(metricValue(metrics, 'last_commit_date', null));

  const kpis = [
    { label: 'Объяснено проблем', value: report.counts.total, hint: 'GigaChat' },
    { label: 'Баги', value: metricNumber(metrics, 'bugs'), hint: 'SonarQube' },
    { label: 'Код-смеллы', value: metricNumber(metrics, 'code_smells'), hint: 'SonarQube' },
    { label: 'Уязвимости', value: metricNumber(metrics, 'vulnerabilities'), hint: 'SonarQube' },
    { label: 'Покрытие тестами', value: `${metricValue(metrics, 'coverage', '0')}%`, hint: 'Line coverage' },
    { label: 'Технический долг', value: formatDebt(metricValue(metrics, 'sqale_index')), hint: 'Оценка SonarQube' },
  ];

  return (
    <div className="page">
      <header className="hero">
        <div className="hero-head">
          <div className="brand">
            <span className="brand-mark">TD</span>
            <div>
              <p className="brand-name">TechDebtManager</p>
              <p className="brand-sub">SonarQube → GigaChat → React</p>
            </div>
          </div>

          <div className="hero-actions">
            <div className="hero-meta">
              <span>
                project: <b>{sonar.project_key}</b>
              </span>
              <span>
                ncloc: <b>{metricNumber(metrics, 'ncloc')}</b>
              </span>
              {lastCommit && (
                <span>
                  последний коммит: <b>{lastCommit}</b>
                </span>
              )}
              {qualityGate !== '—' && (
                <span className={`gate gate-${String(qualityGate).toLowerCase()}`}>
                  Quality Gate: {qualityGate}
                </span>
              )}
            </div>

            <button
              type="button"
              className="check-button"
              onClick={() => setCheckOpen(true)}
            >
              <span className="check-button-plus">+</span>
              Проверить репозиторий
            </button>
          </div>
        </div>

        <h1>Технический долг человеческим языком</h1>
        <p className="hero-lead">
          {report.counts.total > 0 ? (
            <>
              GigaChat объяснил {report.counts.total}{' '}
              {plural(report.counts.total, 'проблему', 'проблемы', 'проблем')} из отчёта
              SonarQube и расставил их по важности — от критичных к косметическим.
            </>
          ) : (
            <>SonarQube не нашёл проблем в этом проекте — проверка чистая.</>
          )}
        </p>

        <div className="kpis">
          {kpis.map((item) => (
            <div className="kpi" key={item.label}>
              <p className="kpi-label">{item.label}</p>
              <p className="kpi-value">{item.value}</p>
              <p className="kpi-hint">{item.hint}</p>
            </div>
          ))}
        </div>
      </header>

      {!report.hasStructure && report.counts.total > 0 && (
        <p className="notice">
          Не удалось разобрать структуру ответа GigaChat — ниже приведён полный текст.
        </p>
      )}

      {report.counts.total === 0 && (
        <p className="empty">
          SonarQube не нашёл проблем в этом проекте — технический долг не обнаружен.
          Можно проверить другой репозиторий.
        </p>
      )}

      {report.hasStructure && (
        <section className="section">
          <div className="section-head">
            <div>
              <h2>Ранжированные проблемы</h2>
              <p className="section-sub">
                Объяснения и приоритеты — от GigaChat, severity и правила — из SonarQube
              </p>
            </div>

            <div className="filters">
              {FILTERS.map((item) => {
                const count =
                  item.id === 'all' ? report.counts.total : report.counts[item.id];
                return (
                  <button
                    key={item.id}
                    type="button"
                    className={filter === item.id ? 'active' : ''}
                    onClick={() => setFilter(item.id)}
                  >
                    {item.label}
                    <span>{count}</span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="findings">
            {visibleFindings.length ? (
              visibleFindings.map((finding) => (
                <FindingCard key={finding.id} finding={finding} />
              ))
            ) : (
              <p className="empty">Проблем с таким уровнем важности нет.</p>
            )}
          </div>
        </section>
      )}

      {report.generalRecommendations.length > 0 && (
        <section className="section">
          <h2>Общие рекомендации</h2>
          <div className="recs">
            {report.generalRecommendations.map((item) => (
              <article className="rec" key={item.id}>
                <h3>{item.title}</h3>
                <p>{item.text}</p>
              </article>
            ))}
          </div>
        </section>
      )}

      <details className="raw">
        <summary>Полный ответ GigaChat ({report.raw.length} символов)</summary>
        <pre>{report.raw}</pre>
      </details>

      <footer className="footer">
        <span>
          Данные: <code>data/gigachat_explanations.txt</code>,{' '}
          <code>data/sonar_full_data.json</code>
        </span>
        <span>Проверка: кнопка «Проверить репозиторий»</span>
      </footer>

      <CheckDialog
        open={checkOpen}
        onClose={() => setCheckOpen(false)}
        onFinished={refreshData}
      />
    </div>
  );
}

export default App;
