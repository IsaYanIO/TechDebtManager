# Где взять токены для запуска

Для запуска TechDebtManager нужны два обязательных ключа и два необязательных.
Все они хранятся только в файле `.env` в корне проекта (он в `.gitignore` и в
репозиторий не попадает). Шаблон — `.env.example`.

| Переменная | Обязательна | Что это | Где получить |
| --- | --- | --- | --- |
| `SONAR_TOKEN` | да | пользовательский токен SonarQube | веб-интерфейс SonarQube, раздел My Account → Security |
| `GIGACHAT_CREDENTIALS` | да | Authorization key GigaChat API | личный кабинет GigaChat Studio (developers.sber.ru) |
| `CLOUDPUB_TOKEN` | нет | API-токен CloudPub (публикация с личного ПК) | личный кабинет cloudpub.ru |
| `GIT_TOKEN` | нет | токен GitHub/GitLab для приватных репозиториев | GitHub → Settings → Developer settings → Tokens |

Порядок действий при первом запуске: скопировать `.env.example` в `.env`,
запустить стек, получить `SONAR_TOKEN` уже внутри запущенного SonarQube,
получить `GIGACHAT_CREDENTIALS` в Studio, вписать оба и пересоздать `api`.

```bash
cp .env.example .env          # Windows: copy .env.example .env
docker compose up -d --build db sonarqube api dashboard
```

Дальше — по разделам ниже. После заполнения `.env` изменения подхватываются
только пересозданием контейнеров:

```bash
docker compose up -d --force-recreate api
```

---

## 1. SONAR_TOKEN — токен SonarQube

Токен создаётся не на сайте, а в вашем локальном экземпляре SonarQube, поэтому
сначала его нужно запустить.

1. Запустите SonarQube и дождитесь готовности (2–3 минуты):

   ```bash
   docker compose up -d db sonarqube
   docker compose logs -f sonarqube      # ждите "SonarQube is operational"
   ```

2. Откройте http://localhost:9000.
3. Войдите первый раз: логин `admin`, пароль `admin`. SonarQube сразу потребует
   сменить пароль — задайте свой и запомните его (он нужен только для входа
   в веб-интерфейс, для сканирования используется токен).
4. Нажмите на аватар в правом верхнем углу → **My Account**.
5. Вкладка **Security**.
6. В поле имени введите `techdebt`, выберите тип **User Token** и срок действия
   (например, **No expiration**, иначе сканирование перестанет работать после
   истечения срока).
7. Нажмите **Generate** и скопируйте токен — он показывается один раз.
8. Вставьте в `.env`:

   ```
   SONAR_TOKEN=скопированный_токен
   ```

9. Пересоздайте API, чтобы он прочитал значение:

   ```bash
   docker compose up -d --force-recreate api
   ```

**Проверка:**

```bash
curl -s -u "$SONAR_TOKEN:" http://localhost:9000/api/authentication/validate
# {"valid":true}
```

Если получили `{"valid":false}` или `401` — токен скопирован не полностью,
создан в другом экземпляре SonarQube или уже удалён. При переустановке
SonarQube с удалением томов (`down -v`) все токены пропадают, нужен новый.

---

## 2. GIGACHAT_CREDENTIALS — ключ GigaChat API

Ключ выдаётся в личном кабинете Studio для разработчиков Сбера. Нужен аккаунт
Сбер ID; для физических лиц по умолчанию доступен тариф Freemium.

1. Откройте https://developers.sber.ru/studio и войдите по Сбер ID.
2. Нажмите **Создать проект** в левом меню.
3. Выберите **GigaChat API** в разделе AI-модели.
4. Укажите название проекта, примите пользовательское соглашение и создайте его.
5. В проекте слева откройте **Настройки API**.
6. Нажмите **Получить ключ** (кнопка доступна ролям «Владелец» и «Администратор»).
7. В открывшемся окне **Сохраните ваш Authorization Key** скопируйте поле
   **Authorization Key** — это и есть значение для `GIGACHAT_CREDENTIALS`.

   Поле выглядит как длинная строка Base64: это `Base64(client_id:client_secret)`.
   Туда же сохраните Client ID и Client Secret — они тоже показываются один раз
   и в кабинете не хранятся. Если ключ утерян, в проекте есть кнопка
   **Получить новый ключ** (старый можно оставить действующим ещё некоторое время).

8. Вставьте в `.env`:

   ```
   GIGACHAT_CREDENTIALS=скопированный_authorization_key
   GIGACHAT_MODEL=GigaChat-2-Max
   ```

   `GIGACHAT_MODEL` необязателен. Если выбранная модель недоступна на вашем
   тарифе, GigaChat вернёт ошибку — поставьте `GigaChat-2` или `GigaChat`.

9. Пересоздайте API:

   ```bash
   docker compose up -d --force-recreate api
   ```

**Проверка** (запрос токена доступа; `-k` нужен из-за сертификата НУЦ Минцифры):

```bash
curl -sk -X POST 'https://ngw.devices.sberbank.ru:9443/api/v2/oauth' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -H 'Accept: application/json' \
  -H "RqUID: $(python -c 'import uuid;print(uuid.uuid4())')" \
  -H "Authorization: Basic $GIGACHAT_CREDENTIALS" \
  --data-urlencode 'scope=GIGACHAT_API_PERS'
# {"access_token":"...","expires_at":...}
```

Скоупы: `GIGACHAT_API_PERS` — физлица, `GIGACHAT_API_B2B` — юрлица по предоплате,
`GIGACHAT_API_CORP` — юрлица по постоплате. Проект использует версию для физлиц;
если у вас корпоративный доступ, скоуп придётся поменять в коде.

Ответ `401` — ключ неверный или отозван; `402`/сообщение о лимите — закончились
токены на тарифе. Приложение вызывает GigaChat библиотекой `gigachat` с
`verify_ssl_certs=False`, поэтому отдельно ставить сертификаты Минцифры не нужно.

---

## 3. CLOUDPUB_TOKEN — публикация с личного ПК (необязательно)

Нужен, только если хотите открыть дашборд и SonarQube по HTTPS-ссылке из интернета.
Без него проект полностью работает локально на `localhost`.

1. Зарегистрируйтесь в личном кабинете https://cloudpub.ru/dashboard
   (есть бесплатный тариф).
2. На главной странице кабинета найдите блок привязки приложения к аккаунту —
   там показан **API-токен** и готовая команда вида `clo set token <токен>`.
   Скопируйте сам токен (без команды и без `@сервер`, если он есть в строке).
3. Вставьте в `.env`:

   ```
   CLOUDPUB_TOKEN=ваш_токен
   ```

4. Запустите стек с профилем `cloudpub`:

   ```bash
   docker compose --profile cloudpub up -d --build
   docker compose logs -f cloudpub
   docker compose logs -f cloudpub_sonar
   ```

**Проверка:** в логах появятся строки публикации:

```
Сервис опубликован: http://dashboard:80 -> https://<имя>.cloudpub.ru:443
Сервис опубликован: [techdebt-sonar] http://sonarqube:9000 -> https://<имя>.cloudpub.ru:443
```

Если вместо них ошибка авторизации — токен неверный или отозван; если «превышен
лимит» — на бесплатном тарифе закончились доступные публикации/агенты.

Публичные адреса сохраняются между перезапусками, потому что конфигурация
агента лежит в томах `cloudpub_config` и `cloudpub_sonar_config`. Адрес меняется
только после `docker compose down -v`, `docker volume prune` или удаления
публикации в кабинете.

Туннель SonarQube защищён Basic Auth CloudPub: браузер спросит email и пароль
**аккаунта CloudPub**, а после них откроется обычная страница входа SonarQube.
Публичный дашборд авторизации не имеет — не оставляйте его открытым надолго:
любой, кто знает ссылку, может запускать проверки и расходовать кредиты GigaChat.

---

## 4. GIT_TOKEN — приватные репозитории (необязательно)

Публичные репозитории клонируются без токена. Токен нужен для приватных, а также
если GitHub ограничивает частоту анонимных запросов. Его можно не хранить в `.env`,
а вводить в окне «Проверить репозиторий» при каждом запуске.

**GitHub:**

1. https://github.com/settings/tokens → **Tokens (classic)** →
   **Generate new token (classic)**.
2. Note: `techdebtmanager`, Expiration: по вкусу (например, 90 дней).
3. Отметьте scope **`repo`** (для публичных репозиториев достаточно
   `public_repo`). Больше ничего не нужно.
4. **Generate token** и скопируйте значение `ghp_...` — показывается один раз.

Fine-grained токен тоже подойдёт: доступ к нужным репозиториям и разрешение
**Contents: Read-only**.

**GitLab:** https://gitlab.com/-/user_settings/personal_access_tokens → создайте
токен со scope **`read_repository`** и ролью Reporter.

В `.env`:

```
GIT_TOKEN=ваш_токен
```

**Проверка** (подставьте приватный репозиторий и свой логин):

```bash
git ls-remote https://<ваш_логин>:<токен>@github.com/<owner>/<private-repo>.git
```

Если команда выводит список ссылок — токен рабочий. Токен с истёкшим сроком
даёт `403`/`Authentication failed` при клонировании.

---

## Остальные переменные `.env`

| Переменная | По умолчанию | Зачем |
| --- | --- | --- |
| `SONAR_URL` | `http://localhost:9000` | адрес SonarQube при локальном запуске; в Docker переопределяется на `http://sonarqube:9000` |
| `PROJECT_KEY` | `TechDebtManager` | префикс ключа проекта в SonarQube; полный ключ — `<PROJECT_KEY>-<owner>-<repo>` |
| `GIGACHAT_MODEL` | `GigaChat-2-Max` | модель GigaChat |
| `REPO_URL` | — | репозиторий по умолчанию для `python main.py all` |
| `DASHBOARD_PORT` | `8081` | порт дашборда на хосте |
| `API_PORT` | `8000` | порт API на хосте (слушается только на 127.0.0.1) |

## Правила безопасности

- `.env` содержит секреты и уже в `.gitignore`; не добавляйте его в git и не
  прикладывайте к скриншотам и тикетам.
- Токены в коде не нужны: всё читается из окружения или `.env`.
- При утечке: в SonarQube удалите токен в My Account → Security, в GigaChat
  выпустите новый ключ, в GitHub отзовите PAT, в CloudPub перевыпустите токен
  в кабинете — затем обновите `.env` и пересоздайте контейнеры.
- `SONAR_TOKEN` даёт право запускать анализ от вашего пользователя, а аккаунт
  `admin` SonarQube — полный доступ к серверу анализа.
