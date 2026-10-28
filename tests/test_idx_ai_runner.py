"""Offline subprocess boundary tests; never invoke a paid AI transport."""

import json
import signal
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("failure", [None, "analysis", "serialization"])
def test_child_loads_repo_dotenv_and_atomically_writes_safe_artifact(
    monkeypatch, tmp_path, failure
):
    from tradingagents.idx_strategies import ai_runner as runner

    candidate = {"symbol": "BBCA.JK"}
    input_path, output_path = tmp_path / "input.json", tmp_path / "output.json"
    input_path.write_text(json.dumps(candidate))
    events = []

    def load_dotenv(path, override=False):
        assert path == runner.REPO_ROOT / ".env"
        assert override is False
        events.append("dotenv")

    def analyze(value):
        assert events == ["dotenv"]
        assert value == candidate
        if failure == "analysis":
            raise RuntimeError("SECRET")
        return {"status": "completed", "data": object() if failure == "serialization" else "report"}

    monkeypatch.setitem(sys.modules, "dotenv", SimpleNamespace(load_dotenv=load_dotenv))
    monkeypatch.setitem(
        sys.modules,
        "tradingagents.idx_strategies.ai_analysis",
        SimpleNamespace(analyze_candidate=analyze),
    )
    original_replace = runner.os.replace
    replacements = []

    def replace(source, target):
        assert not output_path.exists()
        assert isinstance(json.loads(Path(source).read_text()), dict)
        assert stat.S_IMODE(Path(source).stat().st_mode) == 0o600
        replacements.append(target)
        original_replace(source, target)

    monkeypatch.setattr(runner.os, "replace", replace)
    assert runner.main(["--child", str(input_path), str(output_path)]) == 0
    result = json.loads(output_path.read_text())
    assert replacements == [output_path]
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600
    if failure:
        assert result == {"status": "unavailable", "error_class": "analysis_unavailable"}
    else:
        assert result == {"status": "completed", "data": "report"}
    assert set(tmp_path.iterdir()) == {input_path, output_path}


def test_main_rejects_non_child_invocation_without_analysis():
    from tradingagents.idx_strategies import ai_runner as runner

    assert runner.main([]) == 2


@pytest.mark.parametrize("group_missing", [False, True])
def test_timeout_kills_process_group_and_reaps_without_leaking(monkeypatch, group_missing):
    from tradingagents.idx_strategies import ai_runner as runner

    events = []

    class Process:
        pid = 12345

        def __init__(self, *args, **kwargs):
            pass

        def wait(self, timeout=None):
            events.append(("wait", timeout))
            if timeout is not None:
                raise subprocess.TimeoutExpired("SECRET", timeout)
            return -signal.SIGKILL

    def killpg(pid, sig):
        events.append(("killpg", pid, sig))
        if group_missing:
            raise ProcessLookupError("SECRET")

    monkeypatch.setattr(runner.subprocess, "Popen", Process)
    monkeypatch.setattr(runner.os, "killpg", killpg)
    assert runner.run_analysis({}, timeout=0.25) == {
        "status": "unavailable",
        "error_class": "analysis_timeout",
    }
    assert events == [("wait", 0.25), ("killpg", 12345, signal.SIGKILL), ("wait", None)]


@pytest.mark.parametrize("failure", ["spawn", "exit", "missing", "json", "shape", "input"])
def test_boundary_failures_are_sanitized(monkeypatch, failure):
    from tradingagents.idx_strategies import ai_runner as runner

    class Process:
        pid = 12345
        returncode = 1 if failure == "exit" else 0

        def __init__(self, command, **kwargs):
            if failure == "spawn":
                raise OSError("SECRET")
            if failure not in ("missing", "spawn"):
                Path(command[-1]).write_text("[]" if failure == "shape" else "SECRET")

        def wait(self, timeout=None):
            return self.returncode

    monkeypatch.setattr(runner.subprocess, "Popen", Process)
    candidate = {"bad": object()} if failure == "input" else {}
    result = runner.run_analysis(candidate)
    assert result == {"status": "unavailable", "error_class": "analysis_unavailable"}


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), None, True])
def test_invalid_timeout_never_starts_paid_work(monkeypatch, timeout):
    from tradingagents.idx_strategies import ai_runner as runner

    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: pytest.fail("must not spawn"))
    assert runner.run_analysis({}, timeout) == {
        "status": "unavailable",
        "error_class": "invalid_timeout",
    }


def test_run_analysis_roundtrips_in_private_subprocess(monkeypatch):
    from tradingagents.idx_strategies import ai_runner as runner

    candidate = {"symbol": "BBCA.JK", "evidence": {"close": 9025}}
    expected = {"status": "completed", "reports": {"market_report": "observed"}}
    seen = {}

    class Process:
        returncode = 0
        pid = 12345

        def __init__(self, command, **kwargs):
            seen.update(command=command, kwargs=kwargs)
            assert command[:4] == [
                sys.executable,
                "-m",
                "tradingagents.idx_strategies.ai_runner",
                "--child",
            ]
            input_path, output_path = map(Path, command[4:])
            seen["directory"] = input_path.parent
            assert json.loads(input_path.read_text()) == candidate
            assert stat.S_IMODE(input_path.parent.stat().st_mode) == 0o700
            assert stat.S_IMODE(input_path.stat().st_mode) == 0o600
            for stream in (kwargs["stdout"], kwargs["stderr"]):
                assert stat.S_IMODE(Path(stream.name).stat().st_mode) == 0o600
            assert kwargs["start_new_session"] is True
            output_path.write_text(json.dumps(expected))

        def wait(self, timeout=None):
            seen["timeout"] = timeout
            return self.returncode

    monkeypatch.setattr(runner.subprocess, "Popen", Process)
    assert runner.run_analysis(candidate) == expected
    assert seen["timeout"] == 180
    assert not seen["directory"].exists()
    assert candidate == {"symbol": "BBCA.JK", "evidence": {"close": 9025}}
