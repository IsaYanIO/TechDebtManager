#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TechDebtManager — единый пайплайн анализа технического долга.

Этапы:
    1. clone   — копирует код репозитория GitHub/GitLab в workspace/<repo>;
    2. sonar   — (опционально) поднимает SonarQube в Docker, запускает
                 sonar-scanner и собирает метрики и issues в
                 data/sonar_full_data.json;
    3. explain — отправляет найденные проблемы в GigaChat и сохраняет
                 объяснения, ранжирование и рекомендации в
                 data/gigachat_explanations.txt.

Примеры:
    python main.py all --repo https://github.com/user/project --start-sonarqube
    python main.py clone --repo https://gitlab.com/user/project
    python main.py sonar --source workspace/project
    python main.py explain

Настройки читаются из переменных окружения или из файла .env рядом с main.py.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.parse import quote, urlparse

try:
    import requests
except ImportError:  # библиотека проверяется в _require_requests()
    requests = None

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
WORKSPACE_DIR = BASE_DIR / "workspace"
SONAR_COMPOSE_FILE = BASE_DIR / "docker-compose.yml"  # сервис sonarqube в общем compose

SONAR_DATA_PATH = DATA_DIR / "sonar_full_data.json"
GIGACHAT_REPORT_PATH = DATA_DIR / "gigachat_explanations.txt"

DEFAULT_PROJECT_KEY = "TechDebtManager"
DEFAULT_SONAR_URL = "http://localhost:9000"
DEFAULT_GIGACHAT_MODEL = "GigaChat-2-Max"
DEFAULT_TIMEOUT = 300
MAX_ISSUES = 50


class PipelineError(RuntimeError):
    """Понятная пользователю ошибка пайплайна."""


def log(message):
    print(message, flush=True)


def load_env_file(path):
    """Читает KEY=VALUE из .env, не перетирая уже заданные переменные окружения."""
    path = Path(path)
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def read_setting(name, default=""):
    return os.environ.get(name, default).strip()


def require_requests():
    if requests is None:
        raise PipelineError(
            "Не установлена библиотека requests. Выполните: pip install -r requirements.txt"
        )


# ---------------------------------------------------------------------------
# 1. Копирование кода из GitHub/GitLab
# ---------------------------------------------------------------------------

def parse_repo_url(repo_url):
    cleaned = repo_url.strip().rstrip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]

    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise PipelineError(
            f"Некорректная ссылка на репозиторий: {repo_url!r}. "
            "Ожидается https://github.com/owner/repo или https://gitlab.com/owner/repo"
        )

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise PipelineError(f"В ссылке нет владельца и репозитория: {repo_url!r}")

    return parsed.netloc.lower(), parts[0], parts[1]


def clone_repository(repo_url, destination=None, token="", branch=None, force=False):
    """Скачивает код репозитория GitHub/GitLab в workspace/<repo> (или в destination)."""
    host, owner, repo = parse_repo_url(repo_url)
    token = token or read_setting("GIT_TOKEN") or read_setting("GITHUB_TOKEN")

    dest = (
        Path(destination).expanduser().resolve()
        if destination
        else (WORKSPACE_DIR / repo).resolve()
    )

    if dest.exists() and any(dest.iterdir()):
        inside_workspace = WORKSPACE_DIR.resolve() in dest.parents
        if not (force or inside_workspace):
            raise PipelineError(
                f"Папка {dest} уже существует. Используйте --force, чтобы перезаписать её."
            )
        log(f"♻️  Очищаю {dest}")
        shutil.rmtree(dest)

    dest.mkdir(parents=True, exist_ok=True)
    log(f"📥 Копирование {owner}/{repo} ({host}) -> {dest}")

    if git_clone(host, owner, repo, dest, token, branch):
        log(f"✅ Репозиторий скачан: {dest}")
        return dest

    log("⚠️  git clone не удался — скачиваю архив репозитория")
    download_archive(host, owner, repo, branch, token, dest)
    log(f"✅ Архив распакован: {dest}")
    return dest


def git_clone(host, owner, repo, dest, token, branch):
    git = shutil.which("git")
    if not git:
        return False

    if token:
        user = "oauth2" if "gitlab" in host else "x-access-token"
        clone_url = f"https://{user}:{quote(token, safe='')}@{host}/{owner}/{repo}.git"
    else:
        clone_url = f"https://{host}/{owner}/{repo}.git"

    command = [git, "clone", "--depth", "1", "--quiet"]
    if branch:
        command += ["--branch", branch]
    command += [clone_url, str(dest)]

    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"  # не зависать на запросе пароля

    try:
        subprocess.run(
            command,
            check=True,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return True
    except subprocess.CalledProcessError as exc:
        message = (exc.stderr or "").strip().splitlines()
        if message:
            log(f"   git: {message[-1]}")
        return False


def download_archive(host, owner, repo, branch, token, dest):
    require_requests()
    headers = {"User-Agent": "TechDebtManager"}

    if "github" in host:
        kind = "tar"
        url = f"https://api.github.com/repos/{owner}/{repo}/tarball"
        if branch:
            url += f"/{quote(branch)}"
        params = None
        if token:
            headers["Authorization"] = f"token {token}"
    else:
        kind = "zip"
        project = quote(f"{owner}/{repo}", safe="")
        url = f"https://{host}/api/v4/projects/{project}/repository/archive.zip"
        params = {"sha": branch} if branch else None
        if token:
            headers["PRIVATE-TOKEN"] = token

    suffix = ".tar.gz" if kind == "tar" else ".zip"
    with tempfile.TemporaryDirectory() as tmp_dir:
        archive_path = Path(tmp_dir) / f"repository{suffix}"
        try:
            with requests.get(
                url,
                headers=headers,
                params=params,
                stream=True,
                timeout=180,
                allow_redirects=True,
            ) as response:
                response.raise_for_status()
                with archive_path.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=262144):
                        handle.write(chunk)
        except requests.RequestException as exc:
            raise PipelineError(f"Не удалось скачать архив репозитория: {exc}") from exc

        if kind == "tar":
            extract_tar(archive_path, dest)
        else:
            extract_zip(archive_path, dest)


def drop_archive_root(names):
    """Определяет единственную корневую папку архива GitHub/GitLab."""
    roots = {name.split("/", 1)[0] for name in names if name}
    return roots.pop() if len(roots) == 1 else None


def extract_tar(archive_path, dest):
    with tarfile.open(archive_path) as archive:
        members = archive.getmembers()
        root = drop_archive_root([member.name for member in members])
        prepared = []
        for member in members:
            name = member.name
            if root:
                if name == root:
                    continue
                if not name.startswith(f"{root}/"):
                    continue
                name = name[len(root) + 1:]
            if name:
                member.name = name
                prepared.append(member)
        try:
            archive.extractall(dest, members=prepared, filter="data")
        except TypeError:  # Python < 3.12
            archive.extractall(dest, members=prepared)


def extract_zip(archive_path, dest):
    with zipfile.ZipFile(archive_path) as archive:
        root = drop_archive_root(archive.namelist())
        for info in archive.infolist():
            name = info.filename
            if root:
                if name == root:
                    continue
                if not name.startswith(f"{root}/"):
                    continue
                name = name[len(root) + 1:]
            if not name or name.endswith("/"):
                continue
            target = dest / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as handle:
                shutil.copyfileobj(source, handle)


# ---------------------------------------------------------------------------
# 2. SonarQube: запуск анализа и сбор результатов
# ---------------------------------------------------------------------------

def sonar_get(path, sonar_url, sonar_token, params=None):
    require_requests()
    url = f"{sonar_url.rstrip('/')}{path}"
    auth = (sonar_token, "") if sonar_token else None
    try:
        response = requests.get(url, params=params, auth=auth, timeout=60)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise PipelineError(f"Запрос к SonarQube {path} не удался: {exc}") from exc


def get_all_metrics_definitions(sonar_url, sonar_token):
    metrics = []
    page = 1
    while True:
        data = sonar_get("/api/metrics/search", sonar_url, sonar_token, {"p": page, "ps": 500})
        batch = data.get("metrics", [])
        metrics.extend(batch)
        if not batch or len(metrics) >= data.get("total", 0):
            return metrics
        page += 1
        time.sleep(0.1)


def get_project_measures(project_key, metric_keys, sonar_url, sonar_token):
    measures = {}
    for start in range(0, len(metric_keys), 100):
        chunk = metric_keys[start:start + 100]
        data = sonar_get(
            "/api/measures/component",
            sonar_url,
            sonar_token,
            {"component": project_key, "metricKeys": ",".join(chunk)},
        )
        for measure in data.get("component", {}).get("measures", []):
            measures[measure["metric"]] = measure.get("value")
        time.sleep(0.1)
    return measures


def get_project_issues(project_key, sonar_url, sonar_token):
    issues = []
    page = 1
    while True:
        data = sonar_get(
            "/api/issues/search",
            sonar_url,
            sonar_token,
            {
                "componentKeys": project_key,
                "p": page,
                "ps": 500,
                "resolved": "false",
            },
        )
        batch = data.get("issues", [])
        issues.extend(batch)
        if not batch or len(issues) >= data.get("total", 0):
            break
        page += 1
        time.sleep(0.1)
    return issues


def collect_sonar_data(project_key, sonar_url, sonar_token, output_path=SONAR_DATA_PATH):
    """Собирает все метрики и открытые issues проекта в один JSON-файл."""
    log("🔎 Сбор метрик SonarQube...")
    definitions = get_all_metrics_definitions(sonar_url, sonar_token)
    measures = get_project_measures(
        project_key, [item["key"] for item in definitions], sonar_url, sonar_token
    )

    metrics = [
        {
            "key": definition.get("key"),
            "name": definition.get("name"),
            "description": definition.get("description"),
            "domain": definition.get("domain"),
            "type": definition.get("type"),
            "direction": definition.get("direction"),
            "value": measures.get(definition.get("key")),
        }
        for definition in definitions
    ]

    issues = get_project_issues(project_key, sonar_url, sonar_token)

    payload = {
        "project_key": project_key,
        "sonar_url": sonar_url,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "metrics": metrics,
        "issues": issues,
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=4, ensure_ascii=False), encoding="utf-8"
    )

    values = {metric["key"]: metric["value"] for metric in metrics}
    log(
        f"🐞 Issues: {len(issues)} | багов: {values.get('bugs', 0)} | "
        f"код-смеллов: {values.get('code_smells', 0)} | "
        f"покрытие: {values.get('coverage', 0)}%"
    )
    log(f"💾 Данные SonarQube сохранены: {output_path}")
    return payload


def wait_for_sonarqube(sonar_url, timeout=DEFAULT_TIMEOUT):
    """Ждёт, пока SonarQube поднимется и отдаст статус UP."""
    require_requests()
    url = f"{sonar_url.rstrip('/')}/api/system/status"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = requests.get(url, timeout=10)
            if response.ok and response.json().get("status") == "UP":
                log("✅ SonarQube готов к работе")
                return True
        except requests.RequestException:
            pass
        log("   ... SonarQube ещё запускается")
        time.sleep(5)
    return False


def read_ce_task_id(source):
    """Возвращает ceTaskId из отчёта sonar-scanner, если он есть."""
    report = Path(source) / ".scannerwork" / "report-task.txt"
    try:
        for line in report.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() == "ceTaskId" and value.strip():
                return value.strip()
    except OSError:
        pass
    return None


def wait_for_computation(
    project_key, sonar_url, sonar_token, timeout=DEFAULT_TIMEOUT, task_id=None
):
    """Ждёт завершения фоновой обработки отчёта (Compute Engine).

    Если известен ceTaskId, следит за конкретной задачей: это точнее, чем
    /api/ce/component, где последняя успешная задача остаётся в current.
    """
    require_requests()
    auth = (sonar_token, "") if sonar_token else None
    deadline = time.time() + timeout

    if task_id:
        url = f"{sonar_url.rstrip('/')}/api/ce/task"
        while time.time() < deadline:
            try:
                response = requests.get(url, params={"id": task_id}, auth=auth, timeout=15)
                if response.ok:
                    task = response.json().get("task") or {}
                    status = task.get("status")
                    if status == "SUCCESS":
                        log("✅ SonarQube обработал отчёт")
                        return True
                    if status in ("FAILED", "CANCELED"):
                        error = task.get("error") or {}
                        detail = task.get("errorMsg") or error.get("message") or ""
                        raise PipelineError(
                            "SonarQube не смог обработать отчёт"
                            + (f": {detail}" if detail else " — смотрите логи задачи в интерфейсе.")
                        )
            except requests.RequestException:
                pass
            log("   ... SonarQube обрабатывает отчёт")
            time.sleep(2)
        log("⚠️  SonarQube всё ещё обрабатывает отчёт — собираю то, что уже доступно")
        return False

    url = f"{sonar_url.rstrip('/')}/api/ce/component"
    time.sleep(2)  # даём SonarQube поставить задачу в очередь
    while time.time() < deadline:
        try:
            response = requests.get(url, params={"component": project_key}, auth=auth, timeout=15)
            if response.ok:
                data = response.json()
                current = data.get("current") or {}
                queue = data.get("queue") or []
                status = current.get("status")
                if status in ("FAILED", "CANCELED"):
                    raise PipelineError(
                        "SonarQube не смог обработать отчёт — смотрите логи задачи в интерфейсе."
                    )
                if status == "SUCCESS" and not queue:
                    return True
                if not current and not queue:
                    return True
        except requests.RequestException:
            pass
        log("   ... SonarQube обрабатывает отчёт")
        time.sleep(3)
    log("⚠️  SonarQube всё ещё обрабатывает отчёт — собираю то, что уже доступно")
    return False


def find_compose_command():
    if shutil.which("docker"):
        try:
            subprocess.run(
                ["docker", "compose", "version"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return ["docker", "compose"]
        except subprocess.CalledProcessError:
            pass
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    raise PipelineError(
        "Не найден Docker Compose. Установите Docker Desktop и повторите запуск."
    )


def start_sonarqube(compose_file=SONAR_COMPOSE_FILE):
    compose_file = Path(compose_file)
    if not compose_file.is_file():
        raise PipelineError(f"Не найден файл {compose_file}")

    command = find_compose_command()
    log(f"🐳 Запуск SonarQube ({compose_file.name})...")
    result = subprocess.run(
        command + ["-f", str(compose_file), "up", "-d", "sonarqube"],
        cwd=str(BASE_DIR),
        check=False,
    )
    if result.returncode != 0:
        raise PipelineError("docker compose up завершился с ошибкой — смотрите вывод выше.")


SKIP_SCAN_DIRS = {".git", ".idea", "node_modules", "dist", "build", "target", ".gradle", ".venv", "venv"}


def has_java_sources(source):
    """Есть ли в проекте .java файлы вне служебных каталогов."""
    source = Path(source)
    for path in source.rglob("*.java"):
        if SKIP_SCAN_DIRS.isdisjoint(path.relative_to(source).parts[:-1]):
            return True
    return False


def scanner_error_details(log_text):
    """Короткая причина падения sonar-scanner для интерфейса."""
    lines = [line.strip() for line in (log_text or "").splitlines() if line.strip()]
    errors = [line for line in lines if "ERROR" in line and "Re-run SonarScanner" not in line]
    tail = errors[-2:] or lines[-3:]
    return " | ".join(tail)[:600]


def run_sonar_scanner(source, project_key, sonar_url, sonar_token):
    """Запускает локальный sonar-scanner, а при его отсутствии — контейнер."""
    source = Path(source).resolve()
    parameters = [
        f"-Dsonar.host.url={sonar_url}",
        f"-Dsonar.token={sonar_token}",
        f"-Dsonar.projectKey={project_key}",
        f"-Dsonar.projectName={project_key}",
        "-Dsonar.sources=.",
        "-Dsonar.sourceEncoding=UTF-8",
        "-Dsonar.scm.disabled=true",
        "-Dsonar.exclusions=**/.git/**,**/node_modules/**,**/dist/**,**/.venv/**",
    ]

    if has_java_sources(source):
        # Без собранных классов Java-анализатор падает с AnalysisException
        # ("please provide compiled classes with sonar.java.binaries"). Собирать
        # Android/Gradle/Maven проект внутри контейнера нельзя, поэтому отключаем
        # проверку classpath: правила, которым нужен байткод, будут недоступны.
        parameters.append("-Dsonar.java.binaries=.")
        log("ℹ️ Найдены .java файлы без собранных классов — анализ Java без classpath")

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as output:
        scanner = shutil.which("sonar-scanner")
        if scanner:
            log("🧪 Запуск sonar-scanner...")
            result = subprocess.run(
                [scanner, *parameters],
                cwd=str(source),
                check=False,
                stdout=output,
                stderr=subprocess.STDOUT,
                text=True,
            )
        else:
            docker = shutil.which("docker")
            if not docker:
                raise PipelineError(
                    "Не найден sonar-scanner. Установите его локально или запустите "
                    "анализ в контейнере: docker compose run --rm pipeline sonar"
                )

            mount_path = str(source).replace("\\", "/")
            command = [
                docker,
                "run",
                "--rm",
                "-e",
                f"SONAR_HOST_URL={sonar_url}",
                "-e",
                f"SONAR_TOKEN={sonar_token}",
                "-v",
                f"{mount_path}:/usr/src",
                "sonarsource/sonar-scanner-cli",
                *parameters,
            ]
            log("🧪 Запуск sonar-scanner через Docker...")
            result = subprocess.run(
                command,
                check=False,
                stdout=output,
                stderr=subprocess.STDOUT,
                text=True,
            )

        output.seek(0)
        log_text = output.read()

    if log_text:
        sys.stdout.write(log_text)
        sys.stdout.flush()

    if result.returncode != 0:
        details = scanner_error_details(log_text)
        if details:
            raise PipelineError(f"sonar-scanner завершился с ошибкой: {details}")
        raise PipelineError("sonar-scanner завершился с ошибкой — смотрите вывод выше.")

    task_id = read_ce_task_id(source)
    if task_id:
        log(f"   Задача SonarQube: {task_id}")
    return task_id


def process_with_sonar(args, source):
    """Полный цикл SonarQube: (запуск сервера) -> скан -> сбор данных."""
    sonar_url = args.sonar_url.rstrip("/")

    if args.start_sonarqube:
        start_sonarqube()

    if not wait_for_sonarqube(sonar_url, args.scan_timeout):
        raise PipelineError(
            f"SonarQube недоступен по адресу {sonar_url}. "
            "Запустите: docker compose up -d sonarqube"
        )

    if not args.skip_scan:
        task_id = run_sonar_scanner(source, args.project_key, sonar_url, args.sonar_token)
        wait_for_computation(
            args.project_key, sonar_url, args.sonar_token, args.scan_timeout, task_id
        )

    return collect_sonar_data(args.project_key, sonar_url, args.sonar_token)


# ---------------------------------------------------------------------------
# 3. GigaChat: объяснение и ранжирование проблем
# ---------------------------------------------------------------------------

def load_sonar_data(path=SONAR_DATA_PATH):
    path = Path(path)
    if not path.is_file():
        raise PipelineError(
            f"Файл {path} не найден. Сначала соберите данные: python main.py sonar"
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineError(f"Не удалось прочитать {path}: {exc}") from exc


def build_analysis_prompt(data):
    """Формирует промпт, ответ на который разбирает дашборд."""
    metrics = {metric.get("key"): metric.get("value") for metric in data.get("metrics", [])}

    def metric(key, fallback="нет данных"):
        value = metrics.get(key)
        return fallback if value in (None, "") else value

    issues = data.get("issues") or []
    lines = []
    for issue in issues[:MAX_ISSUES]:
        component = str(issue.get("component", "?")).split(":")[-1]
        lines.append(
            f"- [{issue.get('severity', 'UNKNOWN')}] {issue.get('type', 'ISSUE')} "
            f"в {component}:{issue.get('line', '?')}: {issue.get('message', 'Без описания')} "
            f"(правило: {issue.get('rule', '?')}, трудозатраты: {issue.get('effort', 'неизвестно')})"
        )

    if not lines:
        raise PipelineError("В данных SonarQube нет проблем — объяснять нечего.")

    truncated = ""
    if len(issues) > MAX_ISSUES:
        truncated = f"\n(показаны первые {MAX_ISSUES} из {len(issues)} проблем)"

    project_key = data.get("project_key", DEFAULT_PROJECT_KEY)

    return f"""Ты — опытный техлид и наставник. Ниже — проблемы, найденные SonarQube в проекте «{project_key}».

Статистика проекта:
- строк кода (ncloc): {metric("ncloc")}
- багов: {metric("bugs")}
- уязвимостей: {metric("vulnerabilities")}
- код-смеллов: {metric("code_smells")}
- покрытие тестами: {metric("coverage")} %
- технический долг: {metric("sqale_index")} минут
- дублирование: {metric("duplicated_lines_density")} %

Проблемы:
{chr(10).join(lines)}{truncated}

Задачи:
1. Объясни каждую проблему простым человеческим языком: что не так и почему это важно.
2. Расположи проблемы по важности — от самых критичных к менее важным, учитывая severity, тип и влияние на бизнес.
3. Для каждой проблемы дай краткую рекомендацию по исправлению.

Ответ оформи строго по шаблону, без вступлений и выводов:

### 1. Подробное объяснение каждой проблемы:
- **<ТИП> в <файл>:<строка>**
  *Что не так:* ...
  *Почему это важно:* ...

### 2. Проблемы по степени важности (от наиболее важных):
1. **<ТИП> в <файл>:<строка>** *(критичная / средняя / низкая важность)*
   Причина: ...

### 3. Рекомендации по устранению каждой проблемы:
- **Для <ТИП> в <файл>:<строка>:** ...

Значения ТИП, файл и строку бери ровно такими, как в списке проблем."""


def explain_and_rank_with_gigachat(
    sonar_data_path=SONAR_DATA_PATH,
    output_path=GIGACHAT_REPORT_PATH,
    credentials="",
    model=DEFAULT_GIGACHAT_MODEL,
):
    """Отправляет проблемы в GigaChat и сохраняет объяснения, ранжирование и рекомендации."""
    data = load_sonar_data(sonar_data_path)
    prompt = build_analysis_prompt(data)

    if not credentials:
        raise PipelineError(
            "Не задан ключ GigaChat. Добавьте GIGACHAT_CREDENTIALS в .env (см. .env.example)."
        )

    try:
        from gigachat import GigaChat
        from gigachat.models import Chat, Messages, MessagesRole
    except ImportError as exc:
        raise PipelineError(
            "Не установлена библиотека gigachat. Выполните: pip install -r requirements.txt"
        ) from exc

    log(f"🤖 Отправка {min(len(data.get('issues') or []), MAX_ISSUES)} проблем в GigaChat ({model})...")
    try:
        with GigaChat(credentials=credentials, model=model, verify_ssl_certs=False) as client:
            chat = Chat(
                model=model,
                messages=[Messages(role=MessagesRole.USER, content=prompt)],
            )
            result = client.chat(chat).choices[0].message.content
    except Exception as exc:  # сеть, авторизация, лимиты GigaChat
        raise PipelineError(f"GigaChat вернул ошибку: {exc}") from exc

    if not result:
        raise PipelineError("GigaChat вернул пустой ответ.")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result, encoding="utf-8")
    log(f"✅ Объяснения и ранжирование сохранены: {output_path}")
    return result


# ---------------------------------------------------------------------------
# 4. CLI
# ---------------------------------------------------------------------------

def add_repo_arguments(parser):
    parser.add_argument("--repo", default=read_setting("REPO_URL"), help="Ссылка на репозиторий GitHub или GitLab")
    parser.add_argument("--dest", help="Куда скачать код (по умолчанию workspace/<repo>)")
    parser.add_argument("--branch", help="Ветка репозитория (по умолчанию основная)")
    parser.add_argument(
        "--git-token",
        default=read_setting("GIT_TOKEN") or read_setting("GITHUB_TOKEN"),
        help="Токен GitHub/GitLab для приватных репозиториев",
    )
    parser.add_argument("--force", action="store_true", help="Перезаписать существующую папку с кодом")


def add_sonar_arguments(parser):
    parser.add_argument("--source", help="Папка с кодом для анализа (по умолчанию последний клон из workspace)")
    parser.add_argument("--project-key", default=read_setting("PROJECT_KEY", DEFAULT_PROJECT_KEY), help="Ключ проекта в SonarQube")
    parser.add_argument("--sonar-url", default=read_setting("SONAR_URL", DEFAULT_SONAR_URL), help="Адрес SonarQube")
    parser.add_argument("--sonar-token", default=read_setting("SONAR_TOKEN"), help="Токен SonarQube")
    parser.add_argument("--start-sonarqube", action="store_true", help="Поднять SonarQube через docker compose")
    parser.add_argument("--skip-scan", action="store_true", help="Не запускать sonar-scanner, только собрать данные")
    parser.add_argument("--scan-timeout", type=int, default=DEFAULT_TIMEOUT, help="Таймаут ожидания SonarQube, сек")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="TechDebtManager: GitHub/GitLab -> SonarQube -> GigaChat -> React-дашборд",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Примеры:\n"
            "  python main.py all --repo https://github.com/owner/repo --start-sonarqube\n"
            "  python main.py sonar --source workspace/repo\n"
            "  python main.py explain"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    clone = subparsers.add_parser("clone", help="Скачать код репозитория GitHub/GitLab")
    add_repo_arguments(clone)
    clone.set_defaults(handler=cmd_clone)

    sonar = subparsers.add_parser("sonar", help="Проанализировать код и собрать данные SonarQube")
    add_sonar_arguments(sonar)
    sonar.set_defaults(handler=cmd_sonar)

    explain = subparsers.add_parser("explain", help="Объяснить и ранжировать проблемы через GigaChat")
    explain.add_argument("--input", default=str(SONAR_DATA_PATH), help="JSON с данными SonarQube")
    explain.add_argument("--output", default=str(GIGACHAT_REPORT_PATH), help="Куда сохранить ответ GigaChat")
    explain.add_argument("--model", default=read_setting("GIGACHAT_MODEL", DEFAULT_GIGACHAT_MODEL), help="Модель GigaChat")
    explain.set_defaults(handler=cmd_explain)

    pipeline = subparsers.add_parser("all", help="Полный пайплайн: clone -> sonar -> GigaChat")
    add_repo_arguments(pipeline)
    add_sonar_arguments(pipeline)
    pipeline.add_argument("--model", default=read_setting("GIGACHAT_MODEL", DEFAULT_GIGACHAT_MODEL), help="Модель GigaChat")
    pipeline.add_argument("--skip-gigachat", action="store_true", help="Остановиться после сбора данных SonarQube")
    pipeline.set_defaults(handler=cmd_all)

    return parser


def default_source_dir():
    if not WORKSPACE_DIR.is_dir():
        raise PipelineError(
            "Нет скачанного кода. Сначала выполните: python main.py clone --repo <ссылка>"
        )
    candidates = [path for path in WORKSPACE_DIR.iterdir() if path.is_dir()]
    if not candidates:
        raise PipelineError(
            "Папка workspace пуста. Сначала выполните: python main.py clone --repo <ссылка>"
        )
    return max(candidates, key=lambda path: path.stat().st_mtime)


def cmd_clone(args):
    if not args.repo:
        raise PipelineError("Укажите ссылку на репозиторий: --repo https://github.com/owner/repo")
    destination = clone_repository(args.repo, args.dest, args.git_token, args.branch, args.force)
    log(f"✅ Код готов: {destination}")


def cmd_sonar(args):
    source = Path(args.source).expanduser() if args.source else default_source_dir()
    if not source.is_dir():
        raise PipelineError(f"Папка с кодом не найдена: {source}")
    process_with_sonar(args, source)
    log("✅ Этап SonarQube завершён")


def cmd_explain(args):
    credentials = read_setting("GIGACHAT_CREDENTIALS")
    if not credentials:
        raise PipelineError(
            "Не задан GIGACHAT_CREDENTIALS. Добавьте ключ в .env (см. .env.example)."
        )
    explain_and_rank_with_gigachat(args.input, args.output, credentials, args.model)


def cmd_all(args):
    if not args.repo:
        raise PipelineError("Укажите ссылку на репозиторий: --repo https://github.com/owner/repo")

    destination = clone_repository(args.repo, args.dest, args.git_token, args.branch, args.force)
    process_with_sonar(args, destination)

    if args.skip_gigachat:
        log("⏭  GigaChat пропущен (--skip-gigachat)")
        return

    credentials = read_setting("GIGACHAT_CREDENTIALS")
    if not credentials:
        raise PipelineError(
            "Данные SonarQube собраны, но GIGACHAT_CREDENTIALS не задан — добавьте ключ в .env."
        )
    explain_and_rank_with_gigachat(SONAR_DATA_PATH, GIGACHAT_REPORT_PATH, credentials, args.model)
    log("🎉 Пайплайн завершён. Обновите дашборд: cd dashboard && npm run dev")


def main(argv=None):
    load_env_file(BASE_DIR / ".env")
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        args.handler(args)
    except PipelineError as exc:
        log(f"❌ {exc}")
        return 1
    except KeyboardInterrupt:
        log("\n⏹  Остановлено пользователем")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
