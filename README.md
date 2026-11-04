Инструкция
1. Запустить терминал в папке с sonarqube-docker
2. Выполнить команду
   docker compose up -d
4. Запустить терминал в папке с необходимым проектом
5. Выполнить команду
   docker run --rm -e SONAR_HOST_URL="http://host.docker.internal:9000" -e SONAR_TOKEN="ТОКЕН" -v "${PWD}:/usr/src" sonarsource/sonar-scanner-cli:5.0 --% -Dsonar.projectKey=КЛЮЧ_ПРОЕКТА -Dsonar.sources=.
   
