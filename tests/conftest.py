from pathlib import Path
from typing import Callable

import pytest

import ijon
from ijon import HttpTransport


@pytest.fixture(autouse=True)
def no_retry_sleep(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ijon.time, "sleep", lambda _seconds: None)


@pytest.fixture
def write_skill() -> Callable[[Path, str, str], Path]:
    """Lay out a skill on disk the way load_skills_from_directory expects it."""

    def _write(root: Path, name: str, content: str = "# Skill\n\nbody") -> Path:
        skill_dir = root / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(content)
        return skill_dir

    return _write


@pytest.fixture
def transport() -> HttpTransport:
    return HttpTransport(request_max_attempts=3, request_base_delay=1.0, timeout=30)
