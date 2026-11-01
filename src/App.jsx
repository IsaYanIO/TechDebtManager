// src/App.jsx
import { useState } from 'react';
import { fetchMetrics } from './sonarService';
import './App.css';

function App() {
  // Состояния для хранения введённых данных и результатов
  const [projectKey, setProjectKey] = useState('');
  const [token, setToken] = useState('');
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Функция, которая вызывается при нажатии кнопки "Загрузить"
  const handleFetch = async () => {
    if (!projectKey || !token) {
      setError('Пожалуйста, заполни Project Key и Token');
      return;
    }

    setLoading(true);
    setError('');
    setMetrics(null);

    try {
      const data = await fetchMetrics(projectKey, token);
      setMetrics(data);
    } catch (err) {
      setError('Не удалось загрузить метрики. Проверь ключ проекта и токен.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="container">
      <h1>SonarQube Dashboard</h1>
      
      {/* Форма ввода */}
      <div className="input-group">
        <input 
          type="text" 
          placeholder="Project Key (например, my_project)" 
          value={projectKey}
          onChange={(e) => setProjectKey(e.target.value)}
        />
        <input 
          type="password" 
          placeholder="SonarQube Token" 
          value={token}
          onChange={(e) => setToken(e.target.value)}
        />
        <button onClick={handleFetch} disabled={loading}>
          {loading ? 'Загрузка...' : 'Загрузить метрики'}
        </button>
      </div>

      {/* Отображение ошибки */}
      {error && <p className="error">{error}</p>}

      {/* Отображение метрик */}
      {metrics && (
        <div className="metrics-grid">
          {metrics.map((m) => (
            <div key={m.metric} className="metric-card">
              <h3>{formatMetricName(m.metric)}</h3>
              <p className="metric-value">{m.value}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Вспомогательная функция для красивого названия метрик
function formatMetricName(key) {
  const names = {
    code_smells: 'Code Smells',
    coverage: 'Coverage',
    complexity: 'Complexity',
    ncloc: 'Lines of Code',
  };
  return names[key] || key;
}

export default App;