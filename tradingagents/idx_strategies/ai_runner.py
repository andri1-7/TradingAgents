"""Private, time-bounded subprocess boundary for paid candidate analysis."""

from __future__ import annotations

import json
import math
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _private_write(path: Path, value: dict) -> None:
    with open(path, "x", encoding="utf-8", opener=lambda p, f: os.open(p, f, 0o600)) as stream:
        json.dump(value, stream, allow_nan=False)


def _unavailable(error_class="analysis_unavailable") -> dict:
    return {"status": "unavailable", "error_class": error_class}


def _kill_and_reap(process) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    finally:
        process.wait()


def run_analysis(candidate, timeout: float = 180) -> dict:
    """Run the adapter out of process, returning JSON or a sanitized failure.

    ``timeout`` is a finite positive number of seconds. On timeout the entire
    child process group is killed and its leader reaped before returning.
    Private input/output/log files are deleted at completion. No graph or dotenv
    dependency is imported in the monitor process.
    """
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        return _unavailable("invalid_timeout")
    try:
        with tempfile.TemporaryDirectory(prefix="idx-ai-") as directory:
            root = Path(directory)
            input_path, output_path = root / "input.json", root / "output.json"
            _private_write(input_path, candidate)
            with (
                open(root / "stdout.log", "xb", opener=lambda p, f: os.open(p, f, 0o600)) as stdout,
                open(root / "stderr.log", "xb", opener=lambda p, f: os.open(p, f, 0o600)) as stderr,
            ):
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "tradingagents.idx_strategies.ai_runner",
                        "--child",
                        str(input_path),
                        str(output_path),
                    ],
                    cwd=str(REPO_ROOT),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    start_new_session=True,
                )
                try:
                    returncode = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    _kill_and_reap(process)
                    return _unavailable("analysis_timeout")
                except BaseException:
                    _kill_and_reap(process)
                    raise
            if returncode != 0:
                return _unavailable()
            result = json.loads(output_path.read_text(encoding="utf-8"))
            return result if isinstance(result, dict) else _unavailable()
    except Exception:
        # Never include exception messages, command lines or child logs: these
        # can contain credentials and upstream transport details.
        return _unavailable()


def main(argv=None) -> int:
    """Internal child entrypoint: load env, call adapter, publish atomically."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3 or args[0] != "--child":
        return 2
    input_path, output_path = map(Path, args[1:])
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env", override=False)
        from tradingagents.idx_strategies.ai_analysis import analyze_candidate

        candidate = json.loads(input_path.read_text(encoding="utf-8"))
        result = analyze_candidate(candidate)
        if not isinstance(result, dict):
            raise TypeError("Analysis must return an object")
        # Validate fully before creating the artifact, never stringify arbitrary
        # objects/exception reprs into output.
        json.dumps(result, allow_nan=False)
    except Exception:
        result = _unavailable()
    temporary = None
    try:
        fd, name = tempfile.mkstemp(prefix=".analysis-", suffix=".json", dir=output_path.parent)
        temporary = Path(name)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(result, stream, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output_path)
        return 0
    except Exception:
        return 1
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
