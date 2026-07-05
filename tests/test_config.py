import json

import pytest

from ijon import (
    Config,
    HttpTransport,
    expand_env_vars,
    load_mcp_clients_from_config,
)


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


def test_expand_env_vars_substitutes_set_variable(monkeypatch):
    monkeypatch.setenv("API_KEY", "secret")
    assert expand_env_vars("Bearer ${API_KEY}") == "Bearer secret"


def test_expand_env_vars_prefers_value_over_default_when_set(monkeypatch):
    monkeypatch.setenv("API_BASE_URL", "https://real.example.com")
    assert (
        expand_env_vars("${API_BASE_URL:-https://fallback.example.com}/mcp")
        == "https://real.example.com/mcp"
    )


def test_expand_env_vars_uses_default_when_unset(monkeypatch):
    monkeypatch.delenv("API_BASE_URL", raising=False)
    assert (
        expand_env_vars("${API_BASE_URL:-https://fallback.example.com}/mcp")
        == "https://fallback.example.com/mcp"
    )


def test_expand_env_vars_unset_without_default_becomes_empty(monkeypatch):
    monkeypatch.delenv("MISSING", raising=False)
    assert expand_env_vars("Bearer ${MISSING}") == "Bearer "


def test_expand_env_vars_handles_multiple_references(monkeypatch):
    monkeypatch.setenv("HOST", "api.example.com")
    monkeypatch.setenv("TOKEN", "abc")
    assert (
        expand_env_vars("https://${HOST}/mcp?t=${TOKEN}")
        == "https://api.example.com/mcp?t=abc"
    )


def test_load_mcp_clients_expands_url_and_headers(
    tmp_path, monkeypatch, transport: HttpTransport
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("API_KEY", "secret")
    monkeypatch.delenv("API_BASE_URL", raising=False)
    config = {
        "mcpServers": {
            "api": {
                "url": "${API_BASE_URL:-https://api.example.com}/mcp",
                "headers": {"Authorization": "Bearer ${API_KEY}"},
            }
        }
    }
    (tmp_path / "mcp.json").write_text(json.dumps(config))

    clients = load_mcp_clients_from_config(transport)

    assert len(clients) == 1
    assert clients[0].url == "https://api.example.com/mcp"
    assert clients[0].headers["Authorization"] == "Bearer secret"
