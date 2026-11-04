Инструкция по запуску
1. Запустить Docker
2. Запустить терминал в папке с docker-compose.yml
3. Выполнить команду
   docker compose up -d
4. Открыть страницу http://localhost:9000/

Инструкция по сканированию
1. Запустить терминал в папке с необходимым проектом
2. Выполнить команду
   docker run --rm -e SONAR_HOST_URL="http://host.docker.internal:9000" -e SONAR_TOKEN="ТОКЕН" -v "${PWD}:/usr/src" sonarsource/sonar-scanner-cli:5.0 --% -Dsonar.projectKey=КЛЮЧ_ПРОЕКТА -Dsonar.sources=.
3. Проверить результаты на странице http://localhost:9000/

Инструкция по остановке
1. Закрыть терминал со сканированием проекта
2. Выполнить команду в терминале с запущенным docker-compose.yml
   docker compose down
3. Закрыть Docker
