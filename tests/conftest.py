import pytest

import ijon


@pytest.fixture(autouse=True)
def no_retry_sleep(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ijon.time, "sleep", lambda _seconds: None)
