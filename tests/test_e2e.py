import json
import subprocess
import sys
from pathlib import Path

from pytest_httpserver import HTTPServer

IJON = Path(__file__).resolve().parent.parent / "ijon.py"


def run_ijon(*args: str, env: dict) -> subprocess.CompletedProcess:
    # DEVNULL keeps read_piped_stdin from swallowing the runner's stdin.
    return subprocess.run(
        [sys.executable, str(IJON), *args],
        capture_output=True,
        text=True,
        env=env,
        stdin=subprocess.DEVNULL,
    )


def test_runs_the_prompt_against_the_configured_endpoint(httpserver: HTTPServer):
    answer = {"choices": [{"message": {"role": "assistant", "content": "42"}}]}
    httpserver.expect_request("/v1/chat/completions", method="POST").respond_with_json(
        answer
    )

    result = run_ijon(
        "hello",
        "--model",
        "test-model",
        "--jsonl",
        env={"OPENAI_BASE_URL": httpserver.url_for("")},
    )

    assert result.returncode == 0, result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert {"type": "user", "message": {"role": "user", "content": "hello"}} in events


def test_missing_base_url_exits_nonzero():
    result = run_ijon("hello", "--model", "test-model", env={})

    assert result.returncode == 1
    assert "OPENAI_BASE_URL" in result.stderr
