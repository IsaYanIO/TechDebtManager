import { useEffect, useState } from 'react';
import { LEVELS, parseGigachatReport } from './gigachatReport';

const STEPS = [
  { id: 'clone', label: 'Клонирование репозитория' },
  { id: 'scan', label: 'Проверка SonarQube' },
  { id: 'explain', label: 'Объяснение и ранжирование GigaChat' },
];

async function requestJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => null);

  if (!response.ok) {
    const detail = data?.detail;
    const message =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((item) => item.msg).join('; ')
          : `HTTP ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }

  return data;
}

async function loadLatestSummary() {
  const stamp = Date.now();
  const [reportResponse, sonarResponse] = await Promise.all([
    fetch(`/data/gigachat_explanations.txt?ts=${stamp}`, { cache: 'no-store' }),
    fetch(`/data/sonar_full_data.json?ts=${stamp}`, { cache: 'no-store' }),
  ]);

  if (!reportResponse.ok || !sonarResponse.ok) {
    throw new Error('результаты проверки ещё не сохранены');
  }

  return {
    report: parseGigachatReport(await reportResponse.text()),
    sonar: await sonarResponse.json(),
  };
}

function stepIndex(job) {
  if (!job) return -1;
  if (job.stage === 'cloning') return 0;
  if (job.stage === 'scanning' || job.stage === 'collecting') return 1;
  if (job.stage === 'analyzing') return 2;
  if (job.stage === 'done') return STEPS.length;
  return -1;
}

function typeClass(type) {
  return `type-${type.toLowerCase().replace(/[^a-z]+/g, '-')}`;
}

export default function CheckDialog({ open, onClose, onFinished }) {
  const [repoUrl, setRepoUrl] = useState('');
  const [branch, setBranch] = useState('');
  const [token, setToken] = useState('');
  const [job, setJob] = useState(null);
  const [summary, setSummary] = useState(null);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [elapsed, setElapsed] = useState(0);

  const running = job?.status === 'queued' || job?.status === 'running';
  const jobId = job?.job_id;

  useEffect(() => {
    if (!open) return undefined;

    const onKeyDown = (event) => {
      if (event.key === 'Escape') onClose();
    };
    const previousOverflow = document.body.style.overflow;

    document.body.style.overflow = 'hidden';
    window.addEventListener('keydown', onKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [open, onClose]);

  useEffect(() => {
    if (!running) return undefined;
    const timer = setInterval(() => setElapsed((value) => value + 1), 1000);
    return () => clearInterval(timer);
  }, [running, jobId]);

  useEffect(() => {
    if (!jobId || !running) return undefined;

    const timer = setInterval(() => {
      requestJson(`/api/check/${jobId}`)
        .then(setJob)
        .catch((err) => {
          if (err.status === 404) {
            setJob((current) => ({
              ...(current || {}),
              status: 'error',
              stage: 'error',
              message: 'Задача потеряна: API был перезапущен. Запустите проверку снова.',
              error: err.message,
            }));
            return;
          }
          setError(err.message);
        });
    }, 2000);

    return () => clearInterval(timer);
  }, [jobId, running]);

  useEffect(() => {
    if (job?.status !== 'done') return undefined;

    let active = true;
    loadLatestSummary()
      .then(({ report, sonar }) => {
        if (!active) return;
        setSummary({ report, sonar });
        onFinished?.();
      })
      .catch((err) => {
        if (active) setError(`Не удалось прочитать результаты: ${err.message}`);
      });

    return () => {
      active = false;
    };
  }, [job?.status, onFinished]);

  async function handleSubmit(event) {
    event.preventDefault();
    const url = repoUrl.trim();
    if (!url) {
      setError('Укажите ссылку на репозиторий');
      return;
    }

    setSubmitting(true);
    setError('');
    setSummary(null);
    setJob(null);
    setElapsed(0);

    try {
      const created = await requestJson('/api/check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          repo_url: url,
          branch: branch.trim() || null,
          git_token: token.trim() || null,
        }),
      });
      setJob(created);
    } catch (err) {
      setError(
        err.message === 'Failed to fetch'
          ? 'API недоступен. Запустите сервис api: docker compose up -d api'
          : err.message,
      );
    } finally {
      setSubmitting(false);
    }
  }

  function reset() {
    setJob(null);
    setSummary(null);
    setError('');
    setElapsed(0);
  }

  const activeIndex = stepIndex(job);
  const failed = job?.status === 'error';

  function stateFor(index) {
    if (job?.status === 'done') return 'done';
    if (failed) {
      if (activeIndex === -1) return 'idle';
      if (index < activeIndex) return 'done';
      if (index === activeIndex) return 'error';
      return 'idle';
    }
    if (index < activeIndex) return 'done';
    if (index === activeIndex) return 'active';
    return 'idle';
  }

  const metrics = summary
    ? Object.fromEntries((summary.sonar.metrics || []).map((metric) => [metric.key, metric.value]))
    : {};
  const topFindings = summary ? summary.report.findings.slice(0, 3) : [];

  return (
    <div
      className={`overlay ${open ? 'open' : ''}`}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section className="check-dialog" role="dialog" aria-modal="true" aria-labelledby="check-title">
        <header className="check-head">
          <div>
            <p className="check-eyebrow">Новая проверка</p>
            <h2 id="check-title">Репозиторий под контролем</h2>
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="Закрыть">
            ×
          </button>
        </header>

        {!job && !summary && (
          <form className="check-form" onSubmit={handleSubmit}>
            <label>
              Ссылка на репозиторий
              <input
                type="url"
                placeholder="https://github.com/owner/repo"
                value={repoUrl}
                onChange={(event) => setRepoUrl(event.target.value)}
                autoFocus
                required
              />
            </label>

            <div className="check-row">
              <label>
                Ветка (необязательно)
                <input
                  type="text"
                  placeholder="main"
                  value={branch}
                  onChange={(event) => setBranch(event.target.value)}
                />
              </label>
              <label>
                Токен GitHub/GitLab (необязательно)
                <input
                  type="password"
                  placeholder="для приватных репозиториев"
                  value={token}
                  onChange={(event) => setToken(event.target.value)}
                />
              </label>
            </div>

            <button type="submit" className="primary" disabled={submitting}>
              {submitting ? 'Запускаю…' : 'Скачать и проверить'}
            </button>

            <p className="check-hint">
              Код скачается в workspace/, SonarQube проверит качество, GigaChat объяснит
              и расставит проблемы по важности.
            </p>

            {error && <p className="check-error">{error}</p>}
          </form>
        )}

        {job && !summary && (
          <div className="check-progress">
            <p className="check-repo">{job.repo_url}</p>

            <ol className="steps">
              {STEPS.map((step, index) => {
                const state = stateFor(index);
                return (
                  <li className={`step ${state}`} key={step.id}>
                    <span className="step-dot">
                      {state === 'done' ? '✓' : state === 'error' ? '!' : index + 1}
                    </span>
                    {step.label}
                  </li>
                );
              })}
            </ol>

            <p className="check-message">
              {job.message}
              {running ? ` · ${elapsed} с` : ''}
            </p>

            {failed && (
              <>
                <p className="check-error">{job.message}</p>
                <button type="button" className="primary" onClick={reset}>
                  Попробовать снова
                </button>
              </>
            )}

            {job.status === 'done' && <p className="check-message">Готовлю итоги…</p>}
            {error && <p className="check-error">{error}</p>}
          </div>
        )}

        {summary && (
          <div className="check-result">
            <p className="check-eyebrow">Итоги проверки</p>
            <h3>{summary.sonar.project_key}</h3>

            <div className="result-grid">
              <div className="result-card">
                <p>Проблем объяснено</p>
                <p>{summary.report.counts.total}</p>
              </div>
              <div className="result-card">
                <p>Критичных</p>
                <p>{summary.report.counts.critical}</p>
              </div>
              <div className="result-card">
                <p>Баги</p>
                <p>{metrics.bugs ?? '0'}</p>
              </div>
              <div className="result-card">
                <p>Код-смеллы</p>
                <p>{metrics.code_smells ?? '0'}</p>
              </div>
              <div className="result-card">
                <p>Покрытие</p>
                <p>{metrics.coverage ?? '0'}%</p>
              </div>
            </div>

            {topFindings.length > 0 ? (
              <ul className="result-findings">
                {topFindings.map((finding) => (
                  <li className="result-finding" key={finding.id}>
                    <div className="result-finding-top">
                      <span className={`pill priority-${finding.level}`}>
                        {LEVELS[finding.level].label}
                      </span>
                      <span className={`pill ${typeClass(finding.type)}`}>
                        {finding.typeLabel}
                      </span>
                      <span className="location">
                        {finding.file}
                        {finding.line ? `:${finding.line}` : ''}
                      </span>
                    </div>
                    {finding.what && <p>{finding.what}</p>}
                    {finding.recommendation && (
                      <p>
                        <b>Рекомендация.</b> {finding.recommendation}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="check-hint">
                SonarQube не нашёл проблем — технический долг не обнаружен.
              </p>
            )}

            {error && <p className="check-error">{error}</p>}

            <div className="result-actions">
              <button type="button" className="primary" onClick={onClose}>
                Открыть дашборд
              </button>
              <button type="button" className="secondary" onClick={reset}>
                Проверить другой репозиторий
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
