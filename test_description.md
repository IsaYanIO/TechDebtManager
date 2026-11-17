##Что на данный момент покрыто тестами
    Файл main.py:
Парсинг URL — валидные/невалидные формы, .git, завершающие слэши, регистр хоста.

.env и настройки — комментарии, кавычки, setdefault (не перетирает существующие переменные).

Клонирование — успешный git clone без fallback, fallback на архив, защита от непустой папки вне workspace, перезапись внутри workspace.

Распаковка — tar/zip со снятием единственной корневой папки и без него.

Sonar API — построение URL, auth, обёртка RequestException, пагинация метрик/issues, чанкование measure-ключей по 100.

collect_sonar_data — слияние definitions+measures, запись JSON, поля generated_at/project_key/sonar_url.

Ожидание — wait_for_sonarqube (UP/таймаут), wait_for_computation (по task_id, FAILED, по component), read_ce_task_id (включая пустое значение).

run_sonar_scanner — локальный сканер, Docker-fallback, отсутствие обоих, ненулевой код возврата.

Compose/start — выбор docker compose → docker-compose → ошибка, отсутствие файла, ошибка up.

Промпт/данные/GigaChat — отказ при пустых issues, fallback для пустых метрик, обрезка до MAX_ISSUES, обёртка ошибок GigaChat, запись результата.

CLI — --repo обязателен, коды возврата 0/1/130, --skip-gigachat, process_with_sonar c --skip-scan.