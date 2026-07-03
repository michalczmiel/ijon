import json
from collections.abc import Iterator

import pytest
from fastmcp import FastMCP
from fastmcp.utilities.tests import run_server_in_process

from ijon import (
    HttpMCPClient,
    HttpTransport,
    expand_env_vars,
    load_mcp_clients_from_config,
)


def _run_server(host: str, port: int, json_response: bool = False) -> None:
    server = FastMCP("test")

    @server.tool
    def add(a: int, b: int) -> int:
        "Add two numbers"
        return a + b

    server.run(
        transport="http",
        host=host,
        port=port,
        show_banner=False,
        json_response=json_response,
    )


@pytest.fixture(scope="session")
def mcp_url() -> Iterator[str]:
    """A real MCP server over HTTP; tests talk to it like production does."""
    with run_server_in_process(_run_server) as url:
        yield f"{url}/mcp"


@pytest.fixture(scope="session")
def json_mcp_url() -> Iterator[str]:
    """A real MCP server that answers with plain JSON rather than SSE."""
    with run_server_in_process(_run_server, json_response=True) as url:
        yield f"{url}/mcp"


@pytest.fixture
def client(mcp_url, transport: HttpTransport) -> HttpMCPClient:
    return HttpMCPClient(mcp_url, transport)


@pytest.fixture
def json_client(json_mcp_url, transport: HttpTransport) -> HttpMCPClient:
    return HttpMCPClient(json_mcp_url, transport)


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


def test_call_tool_works_against_a_plain_json_server(json_client):
    # The spec allows a plain application/json response, not just SSE.
    json_client.connect()
    result = json_client.call_tool("add", {"a": 6, "b": 7})

    assert result["content"][0]["text"] == "13"


def test_unparseable_body_degrades_gracefully(httpserver, transport: HttpTransport):
    # A garbage body (e.g. proxy HTML) must not crash the client.
    httpserver.expect_request("/mcp").respond_with_data("<html>oops</html>")

    client = HttpMCPClient(httpserver.url_for("/mcp"), transport)
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
