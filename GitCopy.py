# -*- coding: utf-8 -*-
import os
import requests
import base64
from urllib.parse import quote

def copy_repo_code(repo_url, destination=None, token=""):
    """
    Копирует файлы из репозитория GitHub в указанную папку.
    
    :param repo_url: Ссылка на репозиторий (например, https://github.com/user/repo)
    :param destination: Путь к папке (по умолчанию Рабочий стол/GitProj)
    :param token: Ваш GitHub токен (если есть)
    """
    
    # 1. Определяем папку назначения
    if destination is None:
        # Ищем рабочий стол (Desktop) в домашней директории пользователя
        home = os.path.expanduser("~")
        desktop = os.path.join(home, "Desktop")
        
        # Если папки Desktop нет (например, система на русском), пробуем "Рабочий стол"
        if not os.path.exists(desktop):
            desktop = os.path.join(home, "Рабочий стол")
            
        destination = os.path.join(desktop, "GitProj")
    
    # Создаем папку, если её нет
    os.makedirs(destination, exist_ok=True)
    print(f"Файлы будут сохранены в: {destination}")

    # 2. Парсим ссылку на репозиторий
    # Убираем лишние слэши в конце и отрезаем суффикс ".git", если он есть
    clean_url = repo_url.strip().rstrip('/')
    if clean_url.endswith('.git'):
        clean_url = clean_url[:-4]

    # Разбиваем ссылку на части
    parts = clean_url.split('/')
    if len(parts) < 5:
        print("Ошибка: Некорректная ссылка на репозиторий.")
        return

    owner = parts[-2]
    repo_name = parts[-1]
    
    print(f"Владелец: {owner}, Репозиторий: {repo_name}")

    # 3. Получаем информацию о репозитории (чтобы узнать ветку по умолчанию)
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    
    repo_api_url = f"https://api.github.com/repos/{owner}/{repo_name}"
    response = requests.get(repo_api_url, headers=headers)
    
    if response.status_code != 200:
        print(f"Ошибка доступа к репозиторию. Код ответа: {response.status_code}")
        print("Проверьте ссылку или токен.")
        return

    repo_data = response.json()
    default_branch = repo_data.get("default_branch", "main")
    print(f"Ветка по умолчанию: {default_branch}")

    # 4. Рекурсивная функция для скачивания файлов
    def download_contents(api_path, local_path):
        # Формируем URL для получения содержимого папки/файла
        # api_path - это путь внутри репозитория (например, "src/utils")
        url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{quote(api_path)}"
        params = {"ref": default_branch}
        
        r = requests.get(url, headers=headers, params=params)
        
        if r.status_code != 200:
            print(f"Не удалось получить {api_path}. Пропускаем.")
            return

        data = r.json()

        # Если это список (папка) — проходим по каждому элементу
        if isinstance(data, list):
            for item in data:
                # Формируем новый локальный путь
                new_local_path = os.path.join(local_path, item['name'])
                
                if item['type'] == 'dir':
                    # Если папка — создаем её и заходим внутрь
                    os.makedirs(new_local_path, exist_ok=True)
                    download_contents(item['path'], new_local_path)
                else:
                    # Если файл — скачиваем
                    download_file(item['path'], new_local_path, headers, default_branch)
        
        # Если это словарь (одиночный файл)
        elif isinstance(data, dict) and data.get('type') == 'file':
            download_file(api_path, os.path.join(local_path, data['name']), headers, default_branch)

    def download_file(file_path_in_repo, save_path, headers, branch):
        # Получаем файл (используем raw формат, чтобы не возиться с base64)
        # Некоторые файлы могут быть большими, поэтому используем download_url, если он есть
        url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{quote(file_path_in_repo)}"
        params = {"ref": branch}
        
        # Просим GitHub вернуть сырой контент
        file_headers = headers.copy()
        file_headers["Accept"] = "application/vnd.github.v3.raw"
        
        resp = requests.get(url, headers=file_headers, params=params)
        
        if resp.status_code == 200:
            with open(save_path, 'wb') as f:
                f.write(resp.content)
            print(f"Скачан: {file_path_in_repo}")
        else:
            print(f"Не удалось скачать {file_path_in_repo}")

    # Запускаем скачивание с корня репозитория
    download_contents("", destination)
    print("\nГотово!")

# --- Блок для запуска программы ---
if __name__ == "__main__":
    print("=== Копирование кода из GitHub ===")
    url_input = input("Введите ссылку на репозиторий GitHub: ").strip()
    
    # Спрашиваем про папку (можно нажать Enter, чтобы использовать путь по умолчанию)
    custom_dest = input("Введите путь к папке (или нажмите Enter для Рабочий стол/GitProj): ").strip()
    if custom_dest == "":
        custom_dest = None
    
    # Спрашиваем токен (можно нажать Enter, если нет)
    token_input = input("Введите ваш GitHub токен (или нажмите Enter, если нет): ").strip()
    
    copy_repo_code(url_input, custom_dest, token_input)
