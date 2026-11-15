# TechDebtManager Dashboard

React-дашборд проекта TechDebtManager. Читает результаты пайплайна во время работы:

- `/data/gigachat_explanations.txt` — объяснения, ранжирование и рекомендации GigaChat;
- `/data/sonar_full_data.json` — метрики и issues SonarQube.

В Docker файлы отдаёт nginx из примонтированного `../data` (`nginx.conf`, `location /data/`),
в dev-режиме — плагин из `vite.config.js`. Пересобирать дашборд после каждого прогона не нужно.

## Проверка репозитория из интерфейса

Кнопка «Проверить репозиторий» открывает окно с формой: ссылка на GitHub/GitLab,
ветка и токен (необязательно). Запрос уходит в `/api/check`, прогресс — в
`/api/check/{job_id}`, итоги читаются из `/data`.

В Docker `/api` проксируется на сервис `api`, в dev — на `http://127.0.0.1:8000`
(запустите `docker compose up -d api`; адрес можно изменить через `API_PROXY_TARGET`).

## Локальный запуск

```bash
npm install
npm run dev
```

http://localhost:5173

## Запуск в Docker

Из корня проекта:

```bash
docker compose up -d --build api dashboard
```

http://localhost:8081

## Сборка

```bash
npm run build
npm run preview
```
