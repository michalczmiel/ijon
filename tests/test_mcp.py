from collections.abc import Iterator

import pytest
from fastmcp import FastMCP
from fastmcp.utilities.tests import run_server_in_process

from ijon import HttpMCPClient, HttpTransport


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


def test_send_surfaces_jsonrpc_error_instead_of_swallowing_it_into_none(
    client, caplog
):
    client.connect()

    with caplog.at_level("ERROR"):
        result = client._send("resources/read", {"uri": "file:///nope"})

    assert result is not None, "JSON-RPC error swallowed into None"
    assert caplog.text, "JSON-RPC error not logged"
