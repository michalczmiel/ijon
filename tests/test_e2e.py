import json
import subprocess
import sys
from pathlib import Path

from factories import assistant_message, tool_call
from pytest_httpserver import HTTPServer

IJON = Path(__file__).resolve().parent.parent / "ijon.py"


def run_ijon(
    *args: str, env: dict, cwd: str | None = None
) -> subprocess.CompletedProcess:
    # DEVNULL keeps read_piped_stdin from swallowing the runner's stdin.
    return subprocess.run(
        [sys.executable, str(IJON), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
    )


def tool_names_offered(httpserver: HTTPServer) -> list[str]:
    """The tool names main() advertised to the model on the first request."""
    request, _ = httpserver.log[0]
    return [t["function"]["name"] for t in request.get_json().get("tools", [])]


def test_runs_the_prompt_against_the_configured_endpoint(
    httpserver: HTTPServer, openai_endpoint
):
    openai_endpoint(assistant_message("42"))

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


def test_bash_flag_wires_the_tool_and_runs_it(httpserver: HTTPServer, openai_endpoint):
    # --bash must both advertise the tool to the model and execute its calls.
    openai_endpoint(tool_call("echo wired"), assistant_message("done"))

    result = run_ijon(
        "hi",
        "--model",
        "test-model",
        "--bash",
        "--jsonl",
        env={"OPENAI_BASE_URL": httpserver.url_for("")},
    )

    assert result.returncode == 0, result.stderr
    assert "execute_bash_script" in tool_names_offered(httpserver)

    events = [json.loads(line) for line in result.stdout.splitlines()]
    tool_results = [e for e in events if e["type"] == "tool_result"]
    assert "wired" in tool_results[0]["message"]["content"]


def test_skills_flag_discovers_and_offers_skills(
    httpserver: HTTPServer, tmp_path: Path, write_skill, openai_endpoint
):
    # main() must load .agents/skills from the cwd and register the skill tool.
    write_skill(tmp_path / ".agents" / "skills", "greet", "# Greet\n\nsay hi")

    openai_endpoint(assistant_message("done"))

    result = run_ijon(
        "hi",
        "--model",
        "test-model",
        "--skills",
        env={"OPENAI_BASE_URL": httpserver.url_for("")},
        cwd=str(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    assert "skill" in tool_names_offered(httpserver)
