#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP API для дашборда: проверка репозитория и статус задачи.

Работает в том же образе, что и пайплайн, и переиспользует его функции:
clone -> SonarQube -> GigaChat. Задачи выполняются в фоновом потоке,
состояние хранится в памяти процесса, одновременно идёт одна проверка.
"""

import re
import threading
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import main as pipeline

pipeline.load_env_file(pipeline.BASE_DIR / ".env")

app = FastAPI(title="TechDebtManager API", version="1.0.0")

_jobs = {}
_lock = threading.Lock()
_active_job_id = None


class CheckRequest(BaseModel):
    repo_url: str = Field(min_length=8, max_length=500)
    branch: str | None = Field(default=None, max_length=200)
    git_token: str | None = Field(default=None, max_length=500)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def update_job(job_id, **fields):
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(fields)


def project_key_for(owner, repo):
    base = pipeline.read_setting("PROJECT_KEY", pipeline.DEFAULT_PROJECT_KEY)
    slug = re.sub(r"[^A-Za-z0-9_.:-]+", "-", f"{base}-{owner}-{repo}").strip("-")
    return slug[:120] or pipeline.DEFAULT_PROJECT_KEY


def run_job(job_id, repo_url, branch, git_token):
    global _active_job_id
    try:
        _host, owner, repo = pipeline.parse_repo_url(repo_url)

        update_job(
            job_id,
            status="running",
            stage="cloning",
            message=f"Клонирую {owner}/{repo} в workspace/",
        )
        destination = pipeline.clone_repository(
            repo_url, token=git_token or "", branch=branch, force=True
        )

        sonar_url = pipeline.read_setting("SONAR_URL", pipeline.DEFAULT_SONAR_URL)
        sonar_token = pipeline.read_setting("SONAR_TOKEN")
        credentials = pipeline.read_setting("GIGACHAT_CREDENTIALS")

        if not sonar_token:
            raise pipeline.PipelineError(
                "Не задан SONAR_TOKEN. Добавьте токен SonarQube в .env и перезапустите API."
            )
        if not credentials:
            raise pipeline.PipelineError(
                "Не задан GIGACHAT_CREDENTIALS. Добавьте ключ GigaChat в .env и перезапустите API."
            )

        update_job(job_id, stage="scanning", message="Жду SonarQube и запускаю sonar-scanner")
        if not pipeline.wait_for_sonarqube(sonar_url, timeout=600):
            raise pipeline.PipelineError(
                f"SonarQube недоступен по адресу {sonar_url}. Проверьте сервис sonarqube."
            )

        project_key = project_key_for(owner, repo)
        task_id = pipeline.run_sonar_scanner(destination, project_key, sonar_url, sonar_token)
        pipeline.wait_for_computation(
            project_key, sonar_url, sonar_token, timeout=600, task_id=task_id
        )

        update_job(job_id, stage="collecting", message="Собираю метрики и issues")
        payload = pipeline.collect_sonar_data(project_key, sonar_url, sonar_token)
        issues = payload.get("issues") or []

        if issues:
            update_job(job_id, stage="analyzing", message="GigaChat объясняет и ранжирует проблемы")
            model = pipeline.read_setting("GIGACHAT_MODEL", pipeline.DEFAULT_GIGACHAT_MODEL)
            pipeline.explain_and_rank_with_gigachat(
                pipeline.SONAR_DATA_PATH, pipeline.GIGACHAT_REPORT_PATH, credentials, model
            )
        else:
            pipeline.GIGACHAT_REPORT_PATH.write_text(
                "SonarQube не нашёл проблем в проекте.\n", encoding="utf-8"
            )

        update_job(
            job_id,
            status="done",
            stage="done",
            message="Проверка завершена",
            finished_at=now(),
            result={
                "repo": f"{owner}/{repo}",
                "project_key": project_key,
                "issues": len(issues),
            },
        )
    except pipeline.PipelineError as exc:
        update_job(job_id, status="error", message=str(exc), error=str(exc), finished_at=now())
    except Exception as exc:  # noqa: BLE001 — показываем пользователю любую ошибку запуска
        update_job(
            job_id,
            status="error",
            message=f"Непредвиденная ошибка: {exc}",
            error=str(exc),
            finished_at=now(),
        )
    finally:
        with _lock:
            _active_job_id = None


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/check")
def start_check(request: CheckRequest):
    global _active_job_id
    repo_url = request.repo_url.strip()

    try:
        pipeline.parse_repo_url(repo_url)
    except pipeline.PipelineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with _lock:
        if _active_job_id and _jobs.get(_active_job_id, {}).get("status") in ("queued", "running"):
            raise HTTPException(
                status_code=409,
                detail="Проверка уже выполняется. Дождитесь её завершения.",
            )

        job_id = uuid.uuid4().hex[:12]
        _jobs[job_id] = {
            "job_id": job_id,
            "repo_url": repo_url,
            "status": "queued",
            "stage": "queued",
            "message": "Проверка поставлена в очередь",
            "error": None,
            "result": None,
            "created_at": now(),
            "finished_at": None,
        }
        _active_job_id = job_id

        branch = (request.branch or "").strip() or None
        git_token = (request.git_token or "").strip() or ""

    thread = threading.Thread(
        target=run_job,
        args=(job_id, repo_url, branch, git_token),
        daemon=True,
    )
    thread.start()

    with _lock:
        return dict(_jobs[job_id])


@app.get("/api/check/{job_id}")
def check_status(job_id: str):
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Задача не найдена")
        return dict(job)
