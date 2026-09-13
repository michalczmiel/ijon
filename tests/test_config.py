import json

import pytest

from conftest import completion_requests, requests_to, tool_names_offered
from factories import assistant_message

MCP_INITIALIZED = {"jsonrpc": "2.0", "id": 1, "result": {}}
MCP_NO_TOOLS = {"jsonrpc": "2.0", "id": 2, "result": {"tools": []}}


def fake_mcp_server(httpserver, path: str = "/mcp") -> None:
    """A minimal MCP endpoint: answers initialize and an empty tools/list."""
    httpserver.expect_ordered_request(path, method="POST").respond_with_json(
        MCP_INITIALIZED
    )
    httpserver.expect_ordered_request(path, method="POST").respond_with_json(
        MCP_NO_TOOLS
    )


def test_missing_base_url_exits_nonzero(ijon, httpserver):
    result = ijon.run("hi", "--model", "test-model", env={"OPENAI_BASE_URL": None})

    assert result.returncode == 1
    assert "OPENAI_BASE_URL" in result.stderr
    assert not httpserver.log


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("IJON_BASH_TIMEOUT", "abc"),
        ("IJON_HTTP_TIMEOUT", "1.5"),
        ("IJON_MAX_ATTEMPTS", "0"),
        ("IJON_RETRY_BASE_DELAY", "fast"),
        ("IJON_RETRY_BASE_DELAY", "-1"),
    ],
)
def test_invalid_setting_is_an_error(ijon, httpserver, name, value):
    result = ijon.run("hi", "--model", "test-model", env={name: value})

    assert result.returncode == 1
    assert name in result.stderr
    assert not httpserver.log


def test_max_attempts_is_read_from_the_environment(ijon, httpserver):
    httpserver.expect_request("/v1/chat/completions").respond_with_data(
        "boom", status=500
    )

    ijon.run("hi", "--model", "test-model", env={"IJON_MAX_ATTEMPTS": "2"})

    assert len(completion_requests(httpserver)) == 2


def test_mcp_config_expands_env_vars_in_url_and_headers(
    ijon, httpserver, openai_endpoint, tmp_path
):
    fake_mcp_server(httpserver)
    openai_endpoint(assistant_message("done"))
    config = {
        "mcpServers": {
            "api": {
                "url": "${MCP_BASE_URL:-" + httpserver.url_for("") + "}/mcp",
                "headers": {"Authorization": "Bearer ${API_KEY}"},
            }
        }
    }
    (tmp_path / "mcp.json").write_text(json.dumps(config))

    result = ijon.run(
        "hi", "--model", "test-model", "--mcp", env={"API_KEY": "secret"}, cwd=tmp_path
    )

    assert result.returncode == 0, result.stderr
    mcp_request = requests_to(httpserver, "/mcp")[0]
    assert mcp_request.headers["Authorization"] == "Bearer secret"


def test_mcp_config_prefers_env_value_over_default(
    ijon, httpserver, openai_endpoint, tmp_path
):
    fake_mcp_server(httpserver, "/real")
    openai_endpoint(assistant_message("done"))
    config = {"mcpServers": {"api": {"url": "${MCP_URL:-http://fallback.test/mcp}"}}}
    (tmp_path / "mcp.json").write_text(json.dumps(config))

    ijon.run(
        "hi",
        "--model",
        "test-model",
        "--mcp",
        env={"MCP_URL": httpserver.url_for("/real")},
        cwd=tmp_path,
    )

    assert len(requests_to(httpserver, "/real")) == 2


def test_mcp_config_unset_var_without_default_becomes_empty(
    ijon, httpserver, openai_endpoint, tmp_path
):
    fake_mcp_server(httpserver)
    openai_endpoint(assistant_message("done"))
    config = {
        "mcpServers": {
            "api": {
                "url": httpserver.url_for("/mcp"),
                "headers": {"X-Token": "prefix-${MISSING_TOKEN}"},
            }
        }
    }
    (tmp_path / "mcp.json").write_text(json.dumps(config))

    result = ijon.run("hi", "--model", "test-model", "--mcp", cwd=tmp_path)

    assert requests_to(httpserver, "/mcp")[0].headers["X-Token"] == "prefix-"
    assert "MISSING_TOKEN" in result.stderr


def test_mcp_config_skips_server_missing_url(
    ijon, httpserver, openai_endpoint, tmp_path
):
    fake_mcp_server(httpserver)
    openai_endpoint(assistant_message("done"))
    config = {
        "mcpServers": {
            "broken": {"headers": {"Authorization": "Bearer x"}},
            "ok": {"url": httpserver.url_for("/mcp")},
        }
    }
    (tmp_path / "mcp.json").write_text(json.dumps(config))

    result = ijon.run("hi", "--model", "test-model", "--mcp", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert "broken" in result.stderr
    assert len(requests_to(httpserver, "/mcp")) == 2


def test_missing_mcp_config_warns_and_continues(
    ijon, httpserver, openai_endpoint, tmp_path
):
    openai_endpoint(assistant_message("done"))

    result = ijon.run("hi", "--model", "test-model", "--mcp", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert "mcp.json not found" in result.stderr
    assert tool_names_offered(httpserver) == []


def test_malformed_mcp_config_is_reported_and_skipped(
    ijon, httpserver, openai_endpoint, tmp_path
):
    openai_endpoint(assistant_message("done"))
    (tmp_path / "mcp.json").write_text("{not json")

    result = ijon.run("hi", "--model", "test-model", "--mcp", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert "malformed mcp.json" in result.stderr
    assert tool_names_offered(httpserver) == []
