# TechDebtManager

Пайплайн технического долга в одном проекте: код из GitHub/GitLab → анализ SonarQube →
объяснение и ранжирование проблем через GigaChat → React-дашборд с запуском проверки
прямо из интерфейса.

```
GitHub / GitLab
      │  кнопка «Проверить репозиторий» или python main.py clone
      ▼
workspace/<repo>
      │  sonar-scanner → SonarQube
      ▼
data/sonar_full_data.json
      │  GigaChat
      ▼
data/gigachat_explanations.txt
      │  nginx /data
      ▼
dashboard (React + Vite)
```

## Структура

```
TechDev/
├── docker-compose.yml            # db, sonarqube, pipeline, api, dashboard, два туннеля CloudPub
├── docker/pipeline.Dockerfile    # Python + git + JDK + sonar-scanner
├── main.py                       # все этапы пайплайна в одном файле
├── api.py                        # FastAPI для запуска проверки из дашборда
├── dashboard/
│   ├── Dockerfile                # сборка React и раздача через nginx
│   ├── nginx.conf
│   └── src/                      # React-приложение и окно проверки
├── requirements.txt
├── TOKENS.md                     # где получить SONAR_TOKEN, GigaChat, CloudPub, GIT_TOKEN
├── .env.example
├── data/                         # результаты, монтируется в контейнеры
└── workspace/                    # скачанный код репозиториев
```

## Запуск в Docker

Нужен Docker с Compose v2 и около 4 ГБ свободной памяти. Порты по умолчанию:
8081 — дашборд, 9000 — SonarQube, 8000 — API (только localhost).

### 1. Файл настроек

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

Заполните в `.env`:

- `GIGACHAT_CREDENTIALS` — Authorization key из GigaChat Studio (Base64 от
  `client_id:client_secret`); модель задаётся в `GIGACHAT_MODEL`;
- `GIT_TOKEN` — только для приватных репозиториев; токен также можно ввести
  в окне проверки.

`SONAR_TOKEN` добавьте после первого запуска SonarQube — шаг 3.

Подробная инструкция по всем ключам — где зарегистрироваться, где нажать и как
проверить каждый токен — в [TOKENS.md](TOKENS.md).

### 2. Запуск сервисов

```bash
docker compose up -d --build db sonarqube api dashboard
```

Первая сборка занимает несколько минут, SonarQube стартует 2–3 минуты.

| Сервис | Адрес | Назначение |
| --- | --- | --- |
| dashboard | http://localhost:8081 | интерфейс и окно проверки репозитория |
| SonarQube | http://localhost:9000 | анализ кода, при первом входе admin / admin |
| api | http://127.0.0.1:8000 | запуск проверок, доступен только с этой машины |

Снаружи (после запуска с профилем `cloudpub`, см. раздел ниже) доступны два адреса:
дашборд и веб-интерфейс SonarQube за Basic Auth. Локальный http://localhost:9000
работает всегда, даже без CloudPub.

Состояние: `docker compose ps`. Если порт 9000 занят старым контейнером SonarQube,
остановите его: `docker stop <имя-контейнера>`.

### 3. Токен SonarQube

1. Откройте http://localhost:9000 и войдите: `admin` / `admin` (пароль попросят сменить).
2. My Account → Security → **Generate Tokens**: имя `techdebt`, тип **User Token**,
   нажмите Generate и скопируйте токен.
3. Добавьте его в `.env`:

   ```
   SONAR_TOKEN=ваш_токен
   ```

4. Пересоздайте API, чтобы он прочитал новое значение:

   ```bash
   docker compose up -d --force-recreate api
   ```

Без валидного токена сканирование завершится ошибкой 401.

### 4. Проверка из интерфейса

1. Откройте http://localhost:8081.
2. Нажмите **«Проверить репозиторий»** в правом верхнем углу.
3. Укажите ссылку вида `https://github.com/owner/repo`; при необходимости — ветку
   и токен для приватного репозитория.
4. Нажмите **«Скачать и проверить»**.

Окно покажет этапы: клонирование → проверка SonarQube → объяснение GigaChat.
По завершении появятся итоги: сколько проблем найдено, сколько критичных, баги,
код-смеллы, покрытие и топ-3 проблемы с рекомендациями. Кнопка **«Открыть дашборд»**
закрывает окно; данные на странице обновляются автоматически.

Проверка выполняется в отдельном сервисе `api`: код скачивается в `workspace/`,
SonarQube анализирует проект под ключом `<PROJECT_KEY>-<owner>-<repo>`, отчёт
сохраняется в `data/`.

### 5. Пайплайн из командной строки

```bash
docker compose run --rm --build pipeline all --repo https://github.com/owner/repo
```

Контейнер `pipeline` одноразовый: скачивает код в `workspace/`, запускает
`sonar-scanner` внутри себя (SonarQube доступен как `http://sonarqube:9000`),
сохраняет отчёт в `data/` и отправляет проблемы в GigaChat.

Отдельные этапы:

```bash
docker compose run --rm pipeline clone --repo https://github.com/owner/repo
docker compose run --rm pipeline sonar
docker compose run --rm pipeline explain
```

### Остановка и обновление

```bash
docker compose ps                            # состояние сервисов
docker compose logs -f sonarqube             # логи SonarQube
docker compose logs -f api                   # логи проверок
docker compose up -d --build api dashboard   # обновить интерфейс и API
docker compose --profile cloudpub down       # остановить всё, включая туннели; данные сохраняются
docker compose --profile cloudpub down -v    # дополнительно удалить данные SonarQube, PostgreSQL и адреса туннелей
```

На Linux перед первым запуском может понадобиться:
`sudo sysctl -w vm.max_map_count=262144`.

## Публикация через CloudPub

CloudPub даёт публичные HTTPS-адреса без проброса портов и настройки роутера: два независимых
туннеля — для дашборда (`dashboard:80`) и для веб-интерфейса SonarQube (`sonarqube:9000`).
ПК с Docker Desktop должен быть включён. Токен берётся в личном кабинете
[cloudpub.ru](https://cloudpub.ru).

1. Добавьте токен в `.env`:

   ```
   CLOUDPUB_TOKEN=ваш_токен
   ```

2. Запустите стек с профилем `cloudpub`:

   ```bash
   docker compose --profile cloudpub up -d --build
   ```

3. Посмотрите публичный адрес в логах:

   ```bash
   docker compose logs -f cloudpub
   ```

   В логе будет строка вида `Сервис опубликован: dashboard:80 -> <имя>.cloudpub.ru`.

4. Откройте этот HTTPS-адрес. Дашборд проксирует `/api` на сервис `api`, поэтому
   проверка репозиториев работает и снаружи.

### Второй туннель: SonarQube

Сервис `cloudpub_sonar` публикует веб-интерфейс SonarQube и защищён Basic Auth CloudPub.
Он запускается тем же профилем `cloudpub` и поднимается вместе со стеком.

```bash
docker compose --profile cloudpub up -d --build db sonarqube api dashboard cloudpub cloudpub_sonar
docker compose logs -f cloudpub_sonar     # здесь появится адрес SonarQube
```

В логе будет строка вида
`Сервис опубликован: http://sonarqube:9000 -> https://<имя>.cloudpub.ru:443` — это адрес
веб-интерфейса SonarQube. При открытии браузер спросит логин и пароль Basic Auth
(учётная запись CloudPub), после этого откроется обычная страница входа SonarQube
(`admin` и ваш пароль). Внутри: **Projects** → проект с ключом
`<PROJECT_KEY>-<owner>-<repo>` → Issues, Measures, Quality Gate.

Туннель SonarQube использует отдельный том `cloudpub_sonar_config`, поэтому адрес дашборда
не меняется. Адреса обоих туннелей переживают перезапуск контейнеров.

> Важно: SonarQube показывает исходный код всех проанализированных проектов и имеет
> административный доступ. Не публикуйте его без `--auth basic`, не оставляйте пароль
> `admin` и не выключайте туннель через `stop`, если не хотите, чтобы интерфейс оставался
> доступен снаружи. Сканирование при этом всегда идёт по внутреннему адресу
> `http://sonarqube:9000` и от публикации не зависит.

> Публичный адрес дашборда доступен всем, у него нет авторизации: любой, кто знает ссылку,
> может запускать проверки и расходовать кредиты GigaChat. Для постоянного хостинга
> закройте дашборд Basic Auth в nginx или ограничьте доступ средствами CloudPub.

Остановить только туннели:

```bash
docker compose --profile cloudpub stop cloudpub cloudpub_sonar
```

## Запуск без Docker

```bash
pip install -r requirements.txt

# SonarQube в Docker, остальное — на хосте
docker compose up -d sonarqube

python main.py all --repo https://github.com/owner/repo --start-sonarqube
```

Этапы по отдельности: `python main.py clone|sonar|explain`, подробности — `python main.py --help`.
Локальный `sonar-scanner` используется, если установлен; иначе скрипт запускает
контейнер `sonarsource/sonar-scanner-cli`.

Дашборд для разработки:

```bash
cd dashboard
npm install
npm run dev
```

http://localhost:5173. Данные в dev-режиме отдаёт плагин из `vite.config.js`,
запросы `/api` проксируются на `http://127.0.0.1:8000` (запустите `docker compose up -d api`).

## Дашборд

Что показывает:

- сводку проекта из SonarQube (баги, код-смеллы, уязвимости, покрытие, техдолг, Quality Gate);
- проблемы, объяснённые GigaChat: «что не так», «почему это важно», причина приоритета и рекомендация;
- ранжирование от критичных к менее важным с фильтром по уровню;
- сверку каждой проблемы с исходной issue SonarQube (severity, правило, трудозатраты);
- полный текст ответа GigaChat в свёрнутом блоке;
- окно запуска проверки нового репозитория с прогрессом и итогами.

Данные читаются при открытии страницы из `/data/gigachat_explanations.txt` и
`/data/sonar_full_data.json`. Если файлов ещё нет, дашборд предложит запустить проверку.

## Что было объединено

| Было | Стало |
| --- | --- |
| `TechDebtManager-GitCopy/GitCopy.py` | `main.py`, команда `clone` |
| `sonar_parser/sonar_parser.py` | `main.py`, команда `sonar` |
| `sonar_parser/report_analyze.py` | `main.py`, команда `explain` |
| `sonar-test/docker-compose.yml` | корневой `docker-compose.yml` |
| `TechDebtManager-ReactDasboard` | `dashboard` |
| `sonar_parser/*.json`, `*.txt` | `data/*.json`, `*.txt` |

Ключи доступа лежат в `.env` (файл в `.gitignore`), в коде их нет.

## Если что-то не работает

- **Кнопка проверки пишет «API недоступен»** — поднимите сервис: `docker compose up -d api`.
- **«Проверка уже выполняется»** — одновременно идёт одна проверка, дождитесь завершения.
- **401/403 при сканировании** — проверьте `SONAR_TOKEN` и что токен от того же экземпляра SonarQube.
- **SonarQube долго стартует** — проверка ждёт до 600 секунд; смотрите `docker compose logs -f sonarqube`.
- **Дашборд пишет об ошибке данных** — выполните проверку из интерфейса или прогон пайплайна.
- **Порт занят** — порт дашборда задаётся переменной `DASHBOARD_PORT` (по умолчанию 8081),
  API — `API_PORT` (по умолчанию 8000):
  `DASHBOARD_PORT=8082 docker compose up -d dashboard`.
- **GigaChat вернул ошибку** — проверьте `GIGACHAT_CREDENTIALS` и доступ к API.
