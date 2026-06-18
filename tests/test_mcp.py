from collections.abc import Iterator

import pytest
from fastmcp import FastMCP
from fastmcp.utilities.tests import run_server_in_process

from ijon import HttpMCPClient


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
