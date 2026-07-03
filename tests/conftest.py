import pytest

import ijon
from ijon import HttpTransport


@pytest.fixture(autouse=True)
def no_retry_sleep(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ijon.time, "sleep", lambda _seconds: None)


@pytest.fixture
def transport() -> HttpTransport:
    return HttpTransport(request_max_attempts=3, request_base_delay=1.0, timeout=30)
