# TechDebtManager
=======
# SonarQube Dashboard

Небольшое React-приложение для визуализации метрик проекта из SonarQube.
Позволяет ввести Project Key и токен, получить метрики через SonarQube Web API
и отобразить их в виде карточек: Code Smells, Coverage, Complexity, Lines of Code.

## Стек технологий

- **React 18** (функциональные компоненты, хуки)
- **Vite** — сборка и dev-сервер
- **SonarQube Web API** — источник метрик (`/api/measures/component`)
- Нативный `fetch` для HTTP-запросов

## Требования

Перед запуском убедитесь, что у вас установлено:

- **Node.js** версии 18 или выше (вместе с npm). Скачать: https://nodejs.org/ (выбирай LTS).
- **SonarQube** (локальный или удалённый) — откуда будем брать метрики.
- **Токен SonarQube** — генерируется в профиле: *My Account → Security → Generate Tokens*.

# Проверить, что Node.js установлен:

```bash
node -v
npm -v
```
# Запуск дашборда:

URL сервера SonarQube задаётся в файле src/sonarService.js: const SONAR_URL = 'http://localhost:9000';

В командной строке убедитесь, что находитесь в папке проекта (sonar-dashboard) и установите зависимости командой npm install
В командной строке убедитесь, что находитесь в папке проекта (sonar-dashboard) и выполните команду npm run dev
Открой в браузере адрес, который выведет Vite (обычно http://localhost:5173/).

Project Key — ключ проекта в SonarQube (виден в Projects → твой проект).
Token — токен из My Account → Security.

Нажмите «Загрузить метрики».
Под формой появятся карточки с метриками: Code Smells, Coverage, Complexity, Lines of Code.

# Возможные проблемы:

CORS-ошибка в браузере. Если SonarQube и приложение на разных портах,браузер может заблокировать запрос.
Решения: настроить прокси в vite.config.js или запустить SonarQube с настройкой CORS.

401 Unauthorized. Проверь, что токен скопирован целиком и не истёк.

Пустые метрики. Убедись, что проект уже проанализирован в SonarQube (то есть у него есть хотя бы один успешный scan).

# Структура пректа:
sonar-dashboard/
├── src/
│   ├── App.jsx           # главный компонент: форма + вывод метрик
│   ├── App.css           # стили дашборда
│   ├── sonarService.js   # запрос к SonarQube Web API
│   └── main.jsx          # точка входа React
├── index.html
├── package.json
├── vite.config.js
└── ...
