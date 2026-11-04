import json
import os
from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole

# ⚠️ ВАЖНО: Вставьте ваш ключ авторизации из личного кабинета GigaChat API
GIGACHAT_CREDENTIALS = "Ключ авторизации"

# Указываем модель явно (GigaChat-2-Max — оптимальный вариант для анализа и генерации текста)
GIGACHAT_MODEL = "GigaChat-2-Max"

def explain_and_rank_with_gigachat(sonar_data_path="sonar_full_data.json"):
    # 1. Проверяем наличие файла с данными
    if not os.path.exists(sonar_data_path):
        print(f"❌ Ошибка: Файл {sonar_data_path} не найден! Сначала запустите скрипт сбора данных из SonarQube.")
        return

    try:
        with open(sonar_data_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ Ошибка чтения файла: {e}")
        return

    # 2. Подготавливаем данные из SonarQube для промпта
    issues_text = []
    for i in data.get("issues", [])[:50]:  # Ограничиваем первыми 50 проблемами
        issues_text.append(
            f"- [{i.get('severity', 'UNKNOWN')}] {i.get('type', 'ISSUE')} в {i.get('component', '?')}:{i.get('line', '?')}: "
            f"{i.get('message', 'Без описания')} (трудозатраты: {i.get('effort', 'неизвестно')})"
        )

    if not issues_text:
        print("⚠️ В файле нет проблем (issues). Нечего отправлять в GigaChat.")
        return

    # 3. Формируем промпт для нейросети
    prompt = f"""Ты — опытный техлид. Ниже — список проблем, найденных SonarQube.

Общая статистика проекта:
- Багов: {next((m['value'] for m in data.get('metrics', []) if m['key']=='bugs'), '0')}
- Уязвимостей: {next((m['value'] for m in data.get('metrics', []) if m['key']=='vulnerabilities'), '0')}
- Код-смеллов: {next((m['value'] for m in data.get('metrics', []) if m['key']=='code_smells'), '0')}

Проблемы:
{chr(10).join(issues_text)}

Задачи:
1. Объясни каждую проблему простым человеческим языком (что не так и почему это важно).
2. Расположи проблемы по важности (от самых критичных к менее важным), учитывая severity и потенциальное влияние на бизнес.
3. Дай краткую рекомендацию по исправлению для каждой.

Ответ оформи в виде структурированного списка."""

    print(f"⏳ Отправка запроса в GigaChat (модель: {GIGACHAT_MODEL})...")

    # 4. Инициализируем клиент GigaChat с явным указанием модели
    try:
        with GigaChat(
            credentials=GIGACHAT_CREDENTIALS,
            model=GIGACHAT_MODEL,        # <-- Ключевое исправление: явно задаём модель
            verify_ssl_certs=False
        ) as client:
            # Отправляем запрос в формате Chat
            chat = Chat(
                model=GIGACHAT_MODEL,
                messages=[Messages(role=MessagesRole.USER, content=prompt)]
            )
            response = client.chat(chat)
            result = response.choices[0].message.content

        # 5. Сохраняем результат в файл
        with open("gigachat_explanations.txt", "w", encoding="utf-8") as f:
            f.write(result)

        print("✅ Успех! Объяснения и ранжирование сохранены в файл 'gigachat_explanations.txt'")
        return result

    except Exception as e:
        print(f"❌ Ошибка при обращении к GigaChat: {e}")
        return None

# --- ТОЧКА ВХОДА ---
if __name__ == "__main__":
    print("=== Запуск анализа GigaChat ===")
    explain_and_rank_with_gigachat()
