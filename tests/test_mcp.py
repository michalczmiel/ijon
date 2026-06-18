import json
from collections.abc import Iterator

import pytest
from fastmcp import FastMCP
from fastmcp.utilities.tests import run_server_in_process

from ijon import HttpMCPClient, expand_env_vars, load_mcp_clients_from_config


def _run_server(host: str, port: int) -> None:
    server = FastMCP("test")

    @server.tool
    def add(a: int, b: int) -> int:
        "Add two numbers"
        return a + b

    server.run(transport="http", host=host, port=port, show_banner=False)


@pytest.fixture(scope="session")
def mcp_url() -> Iterator[str]:
    """A real MCP server over HTTP; tests talk to it like production does."""
    with run_server_in_process(_run_server) as url:
        yield f"{url}/mcp"


@pytest.fixture
def client(mcp_url) -> HttpMCPClient:
    return HttpMCPClient(mcp_url)


def test_connect_establishes_a_session(client):
    assert client.connect() is True
    assert "mcp-session-id" in client.headers


def test_list_tools_returns_the_servers_tools(client):
    client.connect()
    tools = client.list_tools()

    assert [t["name"] for t in tools] == ["add"]
    assert "inputSchema" in tools[0]


def test_call_tool_runs_it_and_returns_the_result(client):
    client.connect()
    result = client.call_tool("add", {"a": 6, "b": 7})

    assert result["content"][0]["text"] == "13"


def test_calls_fail_without_connecting_first(client):
    # No session handshake -> the server rejects, client degrades gracefully.
    assert client.list_tools() == []


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


def test_load_mcp_clients_expands_url_and_headers(tmp_path, monkeypatch):
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
    (tmp_path / ".mcp.json").write_text(json.dumps(config))

    clients = load_mcp_clients_from_config()

    assert len(clients) == 1
    assert clients[0].url == "https://api.example.com/mcp"
    assert clients[0].headers["Authorization"] == "Bearer secret"
