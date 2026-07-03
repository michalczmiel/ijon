import pytest

from ijon import Config


def test_reads_settings_from_the_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("IJON_BASH_TIMEOUT", "30")

    config = Config.from_env()

    assert config.openai_base_url == "https://api.example.com"
    assert config.openai_api_key == "secret"
    assert config.bash_timeout == 30


def test_missing_base_url_is_an_error(monkeypatch):
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    with pytest.raises(ValueError, match="OPENAI_BASE_URL"):
        Config.from_env()


def test_api_key_is_optional(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.example.com")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert Config.from_env().openai_api_key is None


def test_bash_timeout_defaults_when_unset(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.example.com")
    monkeypatch.delenv("IJON_BASH_TIMEOUT", raising=False)

    assert Config.from_env().bash_timeout == 120


def test_non_integer_env_is_an_error(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("IJON_BASH_TIMEOUT", "abc")

    with pytest.raises(ValueError, match="IJON_BASH_TIMEOUT"):
        Config.from_env()


def test_non_number_env_is_an_error(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("IJON_RETRY_BASE_DELAY", "fast")

    with pytest.raises(ValueError, match="IJON_RETRY_BASE_DELAY"):
        Config.from_env()


def test_max_attempts_below_one_is_an_error(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("IJON_MAX_ATTEMPTS", "0")

    with pytest.raises(ValueError, match="IJON_MAX_ATTEMPTS"):
        Config.from_env()


def test_negative_retry_base_delay_is_an_error(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("IJON_RETRY_BASE_DELAY", "-1")

    with pytest.raises(ValueError, match="IJON_RETRY_BASE_DELAY"):
        Config.from_env()
