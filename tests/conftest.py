"""Black-box tests shared by both implementations.

Every test runs the CLI as a subprocess against a fake OpenAI endpoint, once per
implementation, so the Python and TypeScript versions are held to the same
behaviour.
"""

import json
import os
import pty
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import pytest
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request

ROOT = Path(__file__).resolve().parent.parent

IMPLEMENTATIONS = {
    "python": [sys.executable, str(ROOT / "python" / "ijon.py")],
    "typescript": [
        shutil.which("node") or "node",
        str(ROOT / "typescript" / "ijon.ts"),
    ],
}


@dataclass
class Ijon:
    """Runs one implementation's CLI with a controlled environment."""

    command: list
    base_url: str
    env: dict = field(default_factory=dict)

    def run(
        self,
        *args: str,
        env: Optional[dict] = None,
        cwd: Optional[Path] = None,
        stdin: Optional[str] = None,
        tty: bool = False,
    ) -> subprocess.CompletedProcess:
        full_env = {
            "PATH": os.environ["PATH"],
            "HOME": os.environ.get("HOME", ""),
            "OPENAI_BASE_URL": self.base_url,
            # keep retry tests fast; a test can override it
            "IJON_RETRY_BASE_DELAY": "0",
            **self.env,
            **(env or {}),
        }
        # unset OPENAI_BASE_URL by passing None
        full_env = {k: v for k, v in full_env.items() if v is not None}
        if tty:
            # a real pty so the CLI sees an interactive stdin, like a terminal user
            master, slave = pty.openpty()
            stdin_fd = slave
        else:
            master = None
            # DEVNULL keeps read_piped_stdin from swallowing the runner's stdin.
            stdin_fd = None if stdin is not None else subprocess.DEVNULL
        try:
            return subprocess.run(
                [*self.command, *args],
                capture_output=True,
                text=True,
                env=full_env,
                cwd=cwd,
                input=stdin,
                stdin=stdin_fd,
                timeout=60,
            )
        finally:
            if master is not None:
                os.close(master)
                os.close(slave)


@pytest.fixture(params=IMPLEMENTATIONS, ids=list(IMPLEMENTATIONS))
def ijon(request, httpserver: HTTPServer) -> Ijon:
    return Ijon(IMPLEMENTATIONS[request.param], httpserver.url_for(""))


@pytest.fixture
def openai_endpoint(httpserver: HTTPServer) -> Callable[..., HTTPServer]:
    """Register canned chat-completions responses, served in call order."""

    def _register(*responses: dict) -> HTTPServer:
        for response in responses:
            httpserver.expect_ordered_request(
                "/v1/chat/completions", method="POST"
            ).respond_with_json(response)
        return httpserver

    return _register


@pytest.fixture
def write_skill() -> Callable[[Path, str, str], Path]:
    """Lay out a skill on disk the way load_skills_from_directory expects it."""

    def _write(root: Path, name: str, content: str = "# Skill\n\nbody") -> Path:
        skill_dir = root / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(content)
        return skill_dir

    return _write


def events(result: subprocess.CompletedProcess) -> list:
    """Decode the --jsonl stdout into a list of event dicts."""
    return [json.loads(line) for line in result.stdout.splitlines()]


def tool_results(result: subprocess.CompletedProcess) -> list:
    """The `role: tool` messages the harness fed back, in order."""
    return [e["message"] for e in events(result) if e["type"] == "tool_result"]


def requests_to(httpserver: HTTPServer, path: str) -> list:
    return [request for request, _ in httpserver.log if request.path == path]


def completion_requests(httpserver: HTTPServer) -> list[Request]:
    return requests_to(httpserver, "/v1/chat/completions")


def tools_offered(httpserver: HTTPServer) -> list[dict]:
    """The tool schemas advertised to the model on the first request."""
    request = completion_requests(httpserver)[0]
    return [t["function"] for t in request.get_json().get("tools", [])]


def tool_names_offered(httpserver: HTTPServer) -> list[str]:
    return [t["name"] for t in tools_offered(httpserver)]
