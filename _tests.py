# tests/test_main.py
import json
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

import main


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    """Перенаправляет DATA_DIR/WORKSPACE_DIR/BASE_DIR в tmp_path."""
    data_dir = tmp_path / "data"
    workspace_dir = tmp_path / "workspace"
    data_dir.mkdir()
    workspace_dir.mkdir()

    monkeypatch.setattr(main, "BASE_DIR", tmp_path)
    monkeypatch.setattr(main, "DATA_DIR", data_dir)
    monkeypatch.setattr(main, "WORKSPACE_DIR", workspace_dir)
    monkeypatch.setattr(main, "SONAR_DATA_PATH", data_dir / "sonar_full_data.json")
    monkeypatch.setattr(main, "GIGACHAT_REPORT_PATH", data_dir / "gigachat_explanations.txt")
    return {"base": tmp_path, "data": data_dir, "workspace": workspace_dir}


@pytest.fixture
def clean_env(monkeypatch):
    """Убирает переменные окружения, влияющие на настройки."""
    for name in (
        "GIT_TOKEN", "GITHUB_TOKEN", "REPO_URL", "PROJECT_KEY", "SONAR_URL",
        "SONAR_TOKEN", "GIGACHAT_CREDENTIALS", "GIGACHAT_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


# ---------------------------------------------------------------------------
# load_env_file / read_setting
# ---------------------------------------------------------------------------

class TestLoadEnvFile:
    def test_missing_file_is_noop(self, tmp_path, clean_env):
        main.load_env_file(tmp_path / "missing.env")  # не падает
        assert "REPO_URL" not in main.os.environ

    def test_parses_values_and_skips_garbage(self, tmp_path, clean_env):
        env = tmp_path / ".env"
        env.write_text(
            "# comment\n"
            "\n"
            "REPO_URL=https://github.com/user/repo\n"
            'QUOTED="value with spaces"\n'
            "SINGLE='single'\n"
            "NO_EQUALS_LINE\n"
            "EMPTY_KEY=\n",
            encoding="utf-8",
        )
        main.load_env_file(env)
        assert main.os.environ["REPO_URL"] == "https://github.com/user/repo"
        assert main.os.environ["QUOTED"] == "value with spaces"
        assert main.os.environ["SINGLE"] == "single"
        assert main.os.environ["EMPTY_KEY"] == ""

    def test_does_not_override_existing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REPO_URL", "already-set")
        env = tmp_path / ".env"
        env.write_text("REPO_URL=https://example.com/new\n", encoding="utf-8")
        main.load_env_file(env)
        assert main.os.environ["REPO_URL"] == "already-set"


class TestReadSetting:
    def test_returns_value(self, monkeypatch):
        monkeypatch.setenv("FOO", "bar")
        assert main.read_setting("FOO") == "bar"

    def test_strips_and_returns_default(self, monkeypatch):
        monkeypatch.setenv("FOO", "  bar  ")
        assert main.read_setting("FOO") == "bar"
        monkeypatch.delenv("FOO", raising=False)
        assert main.read_setting("FOO", "dflt") == "dflt"


class TestRequireRequests:
    def test_raises_when_requests_missing(self, monkeypatch):
        monkeypatch.setattr(main, "requests", None)
        with pytest.raises(main.PipelineError):
            main.require_requests()

    def test_ok_when_present(self):
        main.require_requests()  # не бросает


# ---------------------------------------------------------------------------
# parse_repo_url
# ---------------------------------------------------------------------------

class TestParseRepoUrl:
    @pytest.mark.parametrize(
        "url, expected",
        [
            ("https://github.com/user/repo", ("github.com", "user", "repo")),
            ("https://github.com/user/repo/", ("github.com", "user", "repo")),
            ("https://github.com/user/repo.git", ("github.com", "user", "repo")),
            ("https://GitHub.com/user/repo", ("github.com", "user", "repo")),
            ("https://gitlab.com/group/sub/repo", ("gitlab.com", "group", "sub")),
            ("  https://github.com/user/repo  ", ("github.com", "user", "repo")),
        ],
    )
    def test_valid(self, url, expected):
        assert main.parse_repo_url(url) == expected

    @pytest.mark.parametrize(
        "url",
        [
            "ftp://github.com/user/repo",
            "git@github.com:user/repo.git",
            "https://github.com/user",
            "https://github.com/",
            "",
        ],
    )
    def test_invalid(self, url):
        with pytest.raises(main.PipelineError):
            main.parse_repo_url(url)


# ---------------------------------------------------------------------------
# drop_archive_root / extract_tar / extract_zip
# ---------------------------------------------------------------------------

class TestDropArchiveRoot:
    def test_single_root(self):
        assert main.drop_archive_root(["repo-1/file.py", "repo-1/sub/x.py"]) == "repo-1"

    def test_multiple_roots(self):
        assert main.drop_archive_root(["a/x", "b/y"]) is None

    def test_empty(self):
        assert main.drop_archive_root([]) is None


class TestExtractTar:
    def test_strips_single_root(self, tmp_path):
        src = tmp_path / "repo.tar.gz"
        work = tmp_path / "work"
        (work / "root" / "pkg").mkdir(parents=True)
        (work / "root" / "pkg" / "a.py").write_text("x = 1", encoding="utf-8")
        (work / "root" / "README.md").write_text("hi", encoding="utf-8")
        with tarfile.open(src, "w:gz") as tar:
            tar.add(work / "root", arcname="root")

        dest = tmp_path / "out"
        dest.mkdir()
        main.extract_tar(src, dest)

        assert (dest / "pkg" / "a.py").read_text(encoding="utf-8") == "x = 1"
        assert (dest / "README.md").read_text(encoding="utf-8") == "hi"

    def test_multiple_roots_kept(self, tmp_path):
        src = tmp_path / "m.tar.gz"
        work = tmp_path / "work"
        (work / "a").mkdir(parents=True)
        (work / "b").mkdir(parents=True)
        (work / "a" / "x.txt").write_text("1", encoding="utf-8")
        (work / "b" / "y.txt").write_text("2", encoding="utf-8")
        with tarfile.open(src, "w:gz") as tar:
            tar.add(work / "a", arcname="a")
            tar.add(work / "b", arcname="b")

        dest = tmp_path / "out"
        dest.mkdir()
        main.extract_tar(src, dest)

        assert (dest / "a" / "x.txt").exists()
        assert (dest / "b" / "y.txt").exists()


class TestExtractZip:
    def test_strips_single_root(self, tmp_path):
        src = tmp_path / "repo.zip"
        with zipfile.ZipFile(src, "w") as zf:
            zf.writestr("root/file.py", "print(1)")
            zf.writestr("root/sub/", "")  # директория
            zf.writestr("root/sub/x.py", "print(2)")

        dest = tmp_path / "out"
        dest.mkdir()
        main.extract_zip(src, dest)

        assert (dest / "file.py").read_text() == "print(1)"
        assert (dest / "sub" / "x.py").read_text() == "print(2)"


# ---------------------------------------------------------------------------
# clone_repository
# ---------------------------------------------------------------------------

class TestCloneRepository:
    def test_uses_git_clone_when_successful(self, isolated_dirs, monkeypatch):
        calls = {}

        def fake_git_clone(host, owner, repo, dest, token, branch):
            calls["git"] = (host, owner, repo, str(dest), token, branch)
            Path(dest).mkdir(parents=True, exist_ok=True)
            return True

        def fake_download(*args, **kwargs):
            raise AssertionError("download_archive не должен вызываться")

        monkeypatch.setattr(main, "git_clone", fake_git_clone)
        monkeypatch.setattr(main, "download_archive", fake_download)
        monkeypatch.setenv("GIT_TOKEN", "tok")

        dest = main.clone_repository("https://github.com/user/repo", branch="dev")

        assert dest == (isolated_dirs["workspace"] / "repo").resolve()
        assert dest.is_dir()
        host, owner, repo, _, token, branch = calls["git"]
        assert (host, owner, repo, token, branch) == ("github.com", "user", "repo", "tok", "dev")

    def test_falls_back_to_archive(self, isolated_dirs, monkeypatch):
        monkeypatch.setattr(main, "git_clone", lambda *a, **k: False)
        called = {}

        def fake_download(host, owner, repo, branch, token, dest):
            called["args"] = (host, owner, repo, branch, token, str(dest))
            Path(dest, "f.txt").write_text("x")

        monkeypatch.setattr(main, "download_archive", fake_download)

        dest = main.clone_repository("https://gitlab.com/grp/proj", branch="main")
        assert dest == (isolated_dirs["workspace"] / "proj").resolve()
        assert called["args"][:4] == ("gitlab.com", "grp", "proj", "main")

    def test_refuses_nonempty_destination_outside_workspace(self, isolated_dirs, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "git_clone", lambda *a, **k: True)
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_text("x")

        with pytest.raises(main.PipelineError):
            main.clone_repository("https://github.com/u/r", destination=str(outside))

        assert (outside / "keep.txt").exists()

    def test_overwrites_nonempty_destination_inside_workspace(self, isolated_dirs, monkeypatch):
        existing = isolated_dirs["workspace"] / "repo"
        existing.mkdir()
        (existing / "old.txt").write_text("old")

        def fake_download(host, owner, repo, branch, token, dest):
            Path(dest).mkdir(parents=True, exist_ok=True)
            (Path(dest) / "new.txt").write_text("new")

        monkeypatch.setattr(main, "git_clone", lambda *a, **k: False)
        monkeypatch.setattr(main, "download_archive", fake_download)

        dest = main.clone_repository("https://github.com/u/repo")
        assert (dest / "new.txt").exists()
        assert not (dest / "old.txt").exists()


# ---------------------------------------------------------------------------
# SonarQube: sonar_get и обёртки
# ---------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, payload, ok=True, status_code=200):
        self._payload = payload
        self.ok = ok
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if not self.ok:
            raise main.requests.HTTPError("boom")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestSonarGet:
    def test_builds_url_and_auth(self, monkeypatch):
        captured = {}

        def fake_get(url, params=None, auth=None, timeout=None):
            captured.update(url=url, params=params, auth=auth, timeout=timeout)
            return FakeResponse({"ok": True})

        monkeypatch.setattr(main.requests, "get", fake_get)

        result = main.sonar_get("/api/x", "http://sonar/", "tok", {"a": "1"})

        assert result == {"ok": True}
        assert captured["url"] == "http://sonar/api/x"
        assert captured["auth"] == ("tok", "")
        assert captured["params"] == {"a": "1"}

    def test_no_token_no_auth(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            main.requests, "get",
            lambda url, params=None, auth=None, timeout=None: (
                captured.update(auth=auth) or FakeResponse({})
            ),
        )
        main.sonar_get("/x", "http://sonar", "")
        assert captured["auth"] is None

    def test_wraps_request_error(self, monkeypatch):
        def boom(*a, **k):
            raise main.requests.RequestException("net")

        monkeypatch.setattr(main.requests, "get", boom)
        with pytest.raises(main.PipelineError):
            main.sonar_get("/x", "http://sonar", "")


class TestMetricsAndIssuesPagination:
    def test_get_all_metrics_definitions_paginates(self, monkeypatch):
        pages = {
            1: {"metrics": [{"key": "a"}, {"key": "b"}], "total": 3},
            2: {"metrics": [{"key": "c"}], "total": 3},
        }

        def fake_sonar_get(path, url, token, params=None):
            assert path == "/api/metrics/search"
            return pages[params["p"]]

        monkeypatch.setattr(main, "sonar_get", fake_sonar_get)
        monkeypatch.setattr(main.time, "sleep", lambda *_: None)

        result = main.get_all_metrics_definitions("http://s", "")
        assert [m["key"] for m in result] == ["a", "b", "c"]

    def test_get_project_issues_paginates(self, monkeypatch):
        pages = {
            1: {"issues": [{"id": 1}, {"id": 2}], "total": 3},
            2: {"issues": [{"id": 3}], "total": 3},
        }

        def fake_sonar_get(path, url, token, params=None):
            assert path == "/api/issues/search"
            return pages[params["p"]]

        monkeypatch.setattr(main, "sonar_get", fake_sonar_get)
        monkeypatch.setattr(main.time, "sleep", lambda *_: None)

        issues = main.get_project_issues("proj", "http://s", "")
        assert [i["id"] for i in issues] == [1, 2, 3]

    def test_get_project_measures_chunks_by_100(self, monkeypatch):
        calls = []

        def fake_sonar_get(path, url, token, params=None):
            calls.append(params["metricKeys"])
            return {"component": {"measures": [
                {"metric": params["metricKeys"].split(",")[0], "value": "1"}
            ]}}

        monkeypatch.setattr(main, "sonar_get", fake_sonar_get)
        monkeypatch.setattr(main.time, "sleep", lambda *_: None)

        metrics = [f"m{i}" for i in range(150)]
        result = main.get_project_measures("p", metrics, "http://s", "")

        assert len(calls) == 2
        assert len(calls[0].split(",")) == 100
        assert len(calls[1].split(",")) == 50
        assert set(result) == {"m0", "m100"}


class TestCollectSonarData:
    def test_writes_json_and_merges_values(self, isolated_dirs, monkeypatch):
        monkeypatch.setattr(
            main, "get_all_metrics_definitions",
            lambda url, tok: [{"key": "bugs", "name": "Bugs"}, {"key": "coverage", "name": "Coverage"}],
        )
        monkeypatch.setattr(
            main, "get_project_measures",
            lambda key, keys, url, tok: {"bugs": "3", "coverage": "77.5"},
        )
        monkeypatch.setattr(
            main, "get_project_issues",
            lambda key, url, tok: [{"rule": "r1", "severity": "MAJOR"}],
        )

        out = isolated_dirs["data"] / "out.json"
        payload = main.collect_sonar_data("proj", "http://s", "tok", out)

        assert payload["project_key"] == "proj"
        assert payload["sonar_url"] == "http://s"
        assert payload["issues"] == [{"rule": "r1", "severity": "MAJOR"}]
        values = {m["key"]: m["value"] for m in payload["metrics"]}
        assert values == {"bugs": "3", "coverage": "77.5"}

        on_disk = json.loads(out.read_text(encoding="utf-8"))
        assert on_disk["metrics"][0]["name"] == "Bugs"
        assert on_disk["generated_at"]  # непустая метка времени


# ---------------------------------------------------------------------------
# Ожидание SonarQube / CE, read_ce_task_id
# ---------------------------------------------------------------------------

class TestWaitForSonarQube:
    def test_returns_true_when_up(self, monkeypatch):
        monkeypatch.setattr(
            main.requests, "get",
            lambda url, timeout=None: FakeResponse({"status": "UP"}),
        )
        assert main.wait_for_sonarqube("http://s", timeout=5) is True

    def test_returns_false_on_timeout(self, monkeypatch):
        monkeypatch.setattr(
            main.requests, "get",
            lambda url, timeout=None: FakeResponse({"status": "STARTING"}),
        )
        monkeypatch.setattr(main.time, "sleep", lambda *_: None)
        # подменяем time.time так, чтобы дедлайн сразу истёк
        ticks = iter([0, 100, 200, 300, 400, 500])
        monkeypatch.setattr(main.time, "time", lambda: next(ticks, 10_000))
        assert main.wait_for_sonarqube("http://s", timeout=1) is False


class TestWaitForComputation:
    def test_success_by_task_id(self, monkeypatch):
        monkeypatch.setattr(
            main.requests, "get",
            lambda url, params=None, auth=None, timeout=None: FakeResponse(
                {"task": {"status": "SUCCESS"}}
            ),
        )
        assert main.wait_for_computation("p", "http://s", "", timeout=5, task_id="t1") is True

    def test_failed_task_raises(self, monkeypatch):
        monkeypatch.setattr(
            main.requests, "get",
            lambda url, params=None, auth=None, timeout=None: FakeResponse(
                {"task": {"status": "FAILED", "errorMsg": "bad report"}}
            ),
        )
        with pytest.raises(main.PipelineError) as exc:
            main.wait_for_computation("p", "http://s", "", timeout=5, task_id="t1")
        assert "bad report" in str(exc.value)

    def test_component_mode_success(self, monkeypatch):
        monkeypatch.setattr(main.time, "sleep", lambda *_: None)
        monkeypatch.setattr(
            main.requests, "get",
            lambda url, params=None, auth=None, timeout=None: FakeResponse(
                {"current": {"status": "SUCCESS"}, "queue": []}
            ),
        )
        assert main.wait_for_computation("p", "http://s", "", timeout=5) is True


class TestReadCeTaskId:
    def test_reads_from_report(self, tmp_path):
        report_dir = tmp_path / ".scannerwork"
        report_dir.mkdir()
        (report_dir / "report-task.txt").write_text(
            "projectKey=proj\nceTaskId=abc-123\n", encoding="utf-8"
        )
        assert main.read_ce_task_id(tmp_path) == "abc-123"

    def test_missing_file(self, tmp_path):
        assert main.read_ce_task_id(tmp_path) is None

    def test_empty_value(self, tmp_path):
        d = tmp_path / ".scannerwork"
        d.mkdir()
        (d / "report-task.txt").write_text("ceTaskId=\n", encoding="utf-8")
        assert main.read_ce_task_id(tmp_path) is None


# ---------------------------------------------------------------------------
# run_sonar_scanner / find_compose_command / start_sonarqube
# ---------------------------------------------------------------------------

class TestRunSonarScanner:
    def test_local_scanner(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main.shutil, "which", lambda name: "/usr/bin/sonar-scanner" if name == "sonar-scanner" else None)
        captured = {}

        def fake_run(cmd, check=False, cwd=None):
            captured["cmd"] = cmd
            captured["cwd"] = cwd
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr(main.subprocess, "run", fake_run)

        task_id = main.run_sonar_scanner(tmp_path, "proj", "http://s", "tok")
        assert task_id is None
        assert captured["cmd"][0] == "/usr/bin/sonar-scanner"
        assert any("sonar.projectKey=proj" in c for c in captured["cmd"])
        assert any("sonar.token=tok" in c for c in captured["cmd"])
        assert captured["cwd"] == str(tmp_path.resolve())

    def test_docker_fallback(self, tmp_path, monkeypatch):
        def fake_which(name):
            return None if name == "sonar-scanner" else ("/usr/bin/docker" if name == "docker" else None)

        monkeypatch.setattr(main.shutil, "which", fake_which)
        captured = {}

        def fake_run(cmd, check=False, cwd=None):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr(main.subprocess, "run", fake_run)

        main.run_sonar_scanner(tmp_path, "proj", "http://s", "tok")
        cmd = captured["cmd"]
        assert cmd[0] == "/usr/bin/docker"
        assert "sonarsource/sonar-scanner-cli" in cmd
        assert any("SONAR_HOST_URL=http://s" == x or x == "SONAR_HOST_URL=http://s" for x in cmd)

    def test_raises_when_neither_available(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main.shutil, "which", lambda name: None)
        with pytest.raises(main.PipelineError):
            main.run_sonar_scanner(tmp_path, "p", "http://s", "t")

    def test_nonzero_exit_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main.shutil, "which", lambda name: "/usr/bin/sonar-scanner" if name == "sonar-scanner" else None)
        monkeypatch.setattr(main.subprocess, "run", lambda cmd, check=False, cwd=None: subprocess.CompletedProcess(cmd, 1))
        with pytest.raises(main.PipelineError):
            main.run_sonar_scanner(tmp_path, "p", "http://s", "t")


class TestComposeAndStartSonar:
    def test_find_compose_prefers_docker_compose(self, monkeypatch):
        monkeypatch.setattr(main.shutil, "which", lambda name: "/usr/bin/docker")
        monkeypatch.setattr(main.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0))
        assert main.find_compose_command() == ["docker", "compose"]

    def test_find_compose_falls_back(self, monkeypatch):
        def fake_which(name):
            if name == "docker":
                return "/usr/bin/docker"
            if name == "docker-compose":
                return "/usr/bin/docker-compose"
            return None

        def fake_run(cmd, check=False, **kwargs):
            # docker compose version падает
            raise subprocess.CalledProcessError(1, cmd)

        monkeypatch.setattr(main.shutil, "which", fake_which)
        monkeypatch.setattr(main.subprocess, "run", fake_run)
        assert main.find_compose_command() == ["docker-compose"]

    def test_find_compose_missing(self, monkeypatch):
        monkeypatch.setattr(main.shutil, "which", lambda name: None)
        with pytest.raises(main.PipelineError):
            main.find_compose_command()

    def test_start_sonarqube_missing_file(self, tmp_path):
        with pytest.raises(main.PipelineError):
            main.start_sonarqube(tmp_path / "nope.yml")

    def test_start_sonarqube_runs_compose(self, tmp_path, monkeypatch):
        compose = tmp_path / "docker-compose.yml"
        compose.write_text("services: {}\n")
        monkeypatch.setattr(main, "find_compose_command", lambda: ["docker", "compose"])
        captured = {}

        def fake_run(cmd, cwd=None, check=False):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr(main.subprocess, "run", fake_run)
        main.start_sonarqube(compose)
        assert captured["cmd"][-1] == "sonarqube"
        assert "-f" in captured["cmd"]

    def test_start_sonarqube_nonzero_raises(self, tmp_path, monkeypatch):
        compose = tmp_path / "dc.yml"
        compose.write_text("x")
        monkeypatch.setattr(main, "find_compose_command", lambda: ["docker", "compose"])
        monkeypatch.setattr(main.subprocess, "run", lambda cmd, cwd=None, check=False: subprocess.CompletedProcess(cmd, 2))
        with pytest.raises(main.PipelineError):
            main.start_sonarqube(compose)


# ---------------------------------------------------------------------------
# build_analysis_prompt / load_sonar_data / explain
# ---------------------------------------------------------------------------

class TestBuildAnalysisPrompt:
    def _data(self, issues):
        return {
            "project_key": "Proj",
            "metrics": [
                {"key": "ncloc", "value": "100"},
                {"key": "bugs", "value": "2"},
                {"key": "coverage", "value": ""},
            ],
            "issues": issues,
        }

    def test_raises_when_no_issues(self):
        with pytest.raises(main.PipelineError):
            main.build_analysis_prompt(self._data([]))

    def test_includes_metrics_issues_and_truncation(self):
        issues = [
            {"severity": "MAJOR", "type": "BUG", "component": "proj:src/a.py",
             "line": 10, "message": "bad", "rule": "r1", "effort": "5min"}
        ]
        prompt = main.build_analysis_prompt(self._data(issues))
        assert "Проект" not in prompt  # проверка отсутствия лишнего текста
        assert '«Proj»' in prompt
        assert "ncloc): 100" in prompt
        assert "покрытие тестами: нет данных" in prompt  # пустое -> fallback
        assert "src/a.py:10" in prompt
        assert "### 1." in prompt and "### 2." in prompt and "### 3." in prompt

    def test_truncates_to_max_issues(self, monkeypatch):
        monkeypatch.setattr(main, "MAX_ISSUES", 2)
        issues = [
            {"severity": "MAJOR", "type": "BUG", "component": f"p:f{i}.py",
             "line": i, "message": "m", "rule": "r"}
            for i in range(5)
        ]
        prompt = main.build_analysis_prompt(self._data(issues))
        assert "f0.py" in prompt and "f1.py" in prompt
        assert "f2.py" not in prompt
        assert "показаны первые 2 из 5" in prompt


class TestLoadSonarData:
    def test_missing_file(self, tmp_path):
        with pytest.raises(main.PipelineError):
            main.load_sonar_data(tmp_path / "nope.json")

    def test_bad_json(self, tmp_path):
        p = tmp_path / "x.json"
        p.write_text("{not json")
        with pytest.raises(main.PipelineError):
            main.load_sonar_data(p)

    def test_ok(self, tmp_path):
        p = tmp_path / "x.json"
        p.write_text('{"a": 1}')
        assert main.load_sonar_data(p) == {"a": 1}


class TestExplainWithGigachat:
    def test_missing_credentials(self, tmp_path):
        with pytest.raises(main.PipelineError):
            main.explain_and_rank_with_gigachat(
                tmp_path / "in.json", tmp_path / "out.txt", credentials="",
            )

    def test_missing_gigachat_library(self, tmp_path, monkeypatch):
        data = {"project_key": "p", "metrics": [],
                "issues": [{"severity": "S", "type": "T", "component": "c",
                            "line": 1, "message": "m", "rule": "r"}]}
        in_path = tmp_path / "in.json"
        in_path.write_text(json.dumps(data))

        # имитируем отсутствие пакета gigachat
        monkeypatch.setitem(sys.modules, "gigachat", None)
        with pytest.raises(main.PipelineError):
            main.explain_and_rank_with_gigachat(
                in_path, tmp_path / "out.txt", credentials="cred",
            )

    def test_success_writes_file(self, tmp_path, monkeypatch):
        data = {"project_key": "p", "metrics": [],
                "issues": [{"severity": "S", "type": "T", "component": "c",
                            "line": 1, "message": "m", "rule": "r"}]}
        in_path = tmp_path / "in.json"
        in_path.write_text(json.dumps(data))
        out_path = tmp_path / "out.txt"

        class FakeChat:
            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def chat(self, chat):
                class Msg:
                    content = "ANSWER"

                class Choice:
                    message = Msg()

                class Resp:
                    choices = [Choice()]

                return Resp()

        class FakeGigaChat:
            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def chat(self, chat):
                return FakeChat().chat(chat)

        fake_module = type(sys)("gigachat")
        fake_module.GigaChat = FakeGigaChat
        fake_models = type(sys)("gigachat.models")
        fake_models.Chat = lambda **kw: kw
        fake_models.Messages = lambda **kw: kw
        fake_models.MessagesRole = type("MessagesRole", (), {"USER": "user"})

        monkeypatch.setitem(sys.modules, "gigachat", fake_module)
        monkeypatch.setitem(sys.modules, "gigachat.models", fake_models)

        result = main.explain_and_rank_with_gigachat(in_path, out_path, credentials="cred")
        assert result == "ANSWER"
        assert out_path.read_text(encoding="utf-8") == "ANSWER"

    def test_gigachat_error_wrapped(self, tmp_path, monkeypatch):
        data = {"project_key": "p", "metrics": [],
                "issues": [{"severity": "S", "type": "T", "component": "c",
                            "line": 1, "message": "m", "rule": "r"}]}
        in_path = tmp_path / "in.json"
        in_path.write_text(json.dumps(data))

        class Boom:
            def __init__(self, **kw):
                raise RuntimeError("auth fail")

        fake_module = type(sys)("gigachat")
        fake_module.GigaChat = Boom
        fake_models = type(sys)("gigachat.models")
        fake_models.Chat = lambda **kw: kw
        fake_models.Messages = lambda **kw: kw
        fake_models.MessagesRole = type("MessagesRole", (), {"USER": "user"})

        monkeypatch.setitem(sys.modules, "gigachat", fake_module)
        monkeypatch.setitem(sys.modules, "gigachat.models", fake_models)

        with pytest.raises(main.PipelineError):
            main.explain_and_rank_with_gigachat(in_path, tmp_path / "o.txt", credentials="c")


# ---------------------------------------------------------------------------
# default_source_dir и CLI
# ---------------------------------------------------------------------------

class TestDefaultSourceDir:
    def test_raises_without_workspace(self, isolated_dirs, monkeypatch):
        monkeypatch.setattr(main, "WORKSPACE_DIR", isolated_dirs["base"] / "nope")
        with pytest.raises(main.PipelineError):
            main.default_source_dir()

    def test_raises_on_empty_workspace(self, isolated_dirs):
        with pytest.raises(main.PipelineError):
            main.default_source_dir()

    def test_returns_latest(self, isolated_dirs, monkeypatch):
        old = isolated_dirs["workspace"] / "old"
        new = isolated_dirs["workspace"] / "new"
        old.mkdir()
        new.mkdir()
        old_stat = old.stat()
        new_stat = new.stat()
        monkeypatch.setattr(Path, "stat", lambda self: new_stat if self == new else old_stat)
        assert main.default_source_dir() == new


class TestCli:
    def test_no_command_exits_nonzero(self, clean_env):
        with pytest.raises(SystemExit) as exc:
            main.main([])
        assert exc.value.code != 0

    def test_pipeline_error_returns_1(self, clean_env, monkeypatch):
        monkeypatch.setattr(main, "load_env_file", lambda p: None)
        rc = main.main(["clone"])  # без --repo
        assert rc == 1

    def test_keyboard_interrupt_returns_130(self, clean_env, monkeypatch):
        def boom(args):
            raise KeyboardInterrupt

        monkeypatch.setattr(main, "load_env_file", lambda p: None)
        monkeypatch.setattr(main, "cmd_clone", boom)
        rc = main.main(["clone", "--repo", "https://github.com/u/r"])
        assert rc == 130

    def test_clone_happy_path(self, isolated_dirs, monkeypatch):
        monkeypatch.setattr(main, "load_env_file", lambda p: None)
        calls = []
        monkeypatch.setattr(
            main, "clone_repository",
            lambda repo, dest, token, branch, force: calls.append((repo, dest, token, branch, force)) or Path(isolated_dirs["workspace"] / "r"),
        )
        rc = main.main(["clone", "--repo", "https://github.com/u/r", "--force"])
        assert rc == 0
        assert calls == [("https://github.com/u/r", None, "", None, True)]

    def test_sonar_requires_existing_source(self, clean_env, isolated_dirs, monkeypatch):
        monkeypatch.setattr(main, "load_env_file", lambda p: None)
        monkeypatch.setattr(main, "default_source_dir", lambda: (_ for _ in ()).throw(main.PipelineError("empty")))
        rc = main.main(["sonar"])
        assert rc == 1

    def test_explain_requires_credentials(self, clean_env, isolated_dirs, monkeypatch):
        monkeypatch.setattr(main, "load_env_file", lambda p: None)
        rc = main.main(["explain"])
        assert rc == 1

    def test_explain_calls_pipeline(self, clean_env, isolated_dirs, monkeypatch):
        monkeypatch.setattr(main, "load_env_file", lambda p: None)
        monkeypatch.setenv("GIGACHAT_CREDENTIALS", "cred")
        captured = {}
        monkeypatch.setattr(
            main, "explain_and_rank_with_gigachat",
            lambda i, o, c, m: captured.update(input=i, output=o, cred=c, model=m) or "ok",
        )
        rc = main.main(["explain"])
        assert rc == 0
        assert captured["cred"] == "cred"

    def test_all_skips_gigachat(self, clean_env, isolated_dirs, monkeypatch):
        monkeypatch.setattr(main, "load_env_file", lambda p: None)
        monkeypatch.setattr(main, "clone_repository", lambda *a, **k: isolated_dirs["workspace"] / "r")
        monkeypatch.setattr(main, "process_with_sonar", lambda args, src: {})
        called = {}
        monkeypatch.setattr(main, "explain_and_rank_with_gigachat", lambda *a, **k: called.setdefault("hit", True))
        rc = main.main(["all", "--repo", "https://github.com/u/r", "--skip-gigachat"])
        assert rc == 0
        assert "hit" not in called

    def test_all_requires_repo(self, clean_env, isolated_dirs, monkeypatch):
        monkeypatch.setattr(main, "load_env_file", lambda p: None)
        rc = main.main(["all"])
        assert rc == 1

    def test_process_with_sonar_happy(self, isolated_dirs, monkeypatch):
        args = type("A", (), {
            "sonar_url": "http://s/",
            "start_sonarqube": False,
            "scan_timeout": 5,
            "skip_scan": False,
            "project_key": "p",
            "sonar_token": "t",
        })()
        monkeypatch.setattr(main, "wait_for_sonarqube", lambda url, t: True)
        monkeypatch.setattr(main, "run_sonar_scanner", lambda *a: "task-1")
        called = {}
        monkeypatch.setattr(main, "wait_for_computation", lambda *a, **k: called.setdefault("comp", a))
        monkeypatch.setattr(main, "collect_sonar_data", lambda *a, **k: {"ok": True})

        result = main.process_with_sonar(args, isolated_dirs["workspace"])
        assert result == {"ok": True}
        assert called["comp"][4] == "task-1"

    def test_process_with_sonar_skip_scan(self, isolated_dirs, monkeypatch):
        args = type("A", (), {
            "sonar_url": "http://s",
            "start_sonarqube": False,
            "scan_timeout": 5,
            "skip_scan": True,
            "project_key": "p",
            "sonar_token": "t",
        })()
        monkeypatch.setattr(main, "wait_for_sonarqube", lambda url, t: True)
        monkeypatch.setattr(main, "run_sonar_scanner", lambda *a: (_ for _ in ()).throw(AssertionError("не должен вызываться")))
        monkeypatch.setattr(main, "collect_sonar_data", lambda *a, **k: {"ok": True})
        assert main.process_with_sonar(args, isolated_dirs["workspace"]) == {"ok": True}

    def test_process_with_sonar_unavailable(self, isolated_dirs, monkeypatch):
        args = type("A", (), {
            "sonar_url": "http://s",
            "start_sonarqube": False,
            "scan_timeout": 1,
            "skip_scan": True,
            "project_key": "p",
            "sonar_token": "t",
        })()
        monkeypatch.setattr(main, "wait_for_sonarqube", lambda url, t: False)
        with pytest.raises(main.PipelineError):
            main.process_with_sonar(args, isolated_dirs["workspace"])