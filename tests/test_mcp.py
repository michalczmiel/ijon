import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastmcp import FastMCP
from fastmcp.utilities.tests import run_server_in_process

from conftest import tool_names_offered, tool_results, tools_offered
from factories import assistant_message, tool_call


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


def write_mcp_config(directory: Path, url: str) -> None:
    config = {"mcpServers": {"test": {"url": url}}}
    (directory / "mcp.json").write_text(json.dumps(config))


def test_offers_the_servers_tools_to_the_model(
    ijon, httpserver, openai_endpoint, tmp_path, mcp_url
):
    write_mcp_config(tmp_path, mcp_url)
    openai_endpoint(assistant_message("done"))

    result = ijon.run("hi", "--model", "test-model", "--mcp", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    (add,) = tools_offered(httpserver)
    assert add["name"] == "add"
    assert add["description"] == "Add two numbers"
    assert set(add["parameters"]["properties"]) == {"a", "b"}


def test_runs_the_tool_and_feeds_back_the_result(
    ijon, openai_endpoint, tmp_path, mcp_url
):
    write_mcp_config(tmp_path, mcp_url)
    openai_endpoint(tool_call({"a": 6, "b": 7}, name="add"), assistant_message("done"))

    result = ijon.run("hi", "--model", "test-model", "--mcp", "--jsonl", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    (tool_msg,) = tool_results(result)
    assert tool_msg["tool_call_id"] == "call_1"
    # MCP results are dicts, serialized as JSON for the model.
    assert json.loads(tool_msg["content"])["content"][0]["text"] == "13"


def test_works_against_a_plain_json_server(
    ijon, openai_endpoint, tmp_path, json_mcp_url
):
    # The spec allows a plain application/json response, not just SSE.
    write_mcp_config(tmp_path, json_mcp_url)
    openai_endpoint(tool_call({"a": 6, "b": 7}, name="add"), assistant_message("done"))

    result = ijon.run("hi", "--model", "test-model", "--mcp", "--jsonl", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    (tool_msg,) = tool_results(result)
    assert json.loads(tool_msg["content"])["content"][0]["text"] == "13"


def test_unparseable_body_degrades_gracefully(
    ijon, httpserver, openai_endpoint, tmp_path
):
    # A garbage body (e.g. proxy HTML) must not crash the client.
    # Handlers are ordered because the OpenAI endpoint is too: initialize succeeds,
    # tools/list then fails to parse.
    httpserver.expect_ordered_request("/mcp").respond_with_json(
        {"jsonrpc": "2.0", "id": 1, "result": {}}
    )
    httpserver.expect_ordered_request("/mcp").respond_with_data("<html>oops</html>")
    openai_endpoint(assistant_message("done"))
    write_mcp_config(tmp_path, httpserver.url_for("/mcp"))

    result = ijon.run("hi", "--model", "test-model", "--mcp", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert "unparseable MCP response" in result.stderr
    assert tool_names_offered(httpserver) == []


def test_unreachable_server_is_skipped(ijon, httpserver, openai_endpoint, tmp_path):
    openai_endpoint(assistant_message("done"))
    write_mcp_config(tmp_path, "http://127.0.0.1:9/mcp")

    result = ijon.run("hi", "--model", "test-model", "--mcp", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert "cannot connect" in result.stderr
    assert tool_names_offered(httpserver) == []


def test_unauthorized_server_explains_static_token_auth(
    ijon, httpserver, openai_endpoint, tmp_path
):
    httpserver.expect_ordered_request("/mcp").respond_with_data(
        "", status=401, headers={"WWW-Authenticate": 'Bearer realm="mcp"'}
    )
    openai_endpoint(assistant_message("done"))
    write_mcp_config(tmp_path, httpserver.url_for("/mcp"))

    result = ijon.run("hi", "--model", "test-model", "--mcp", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert "static tokens" in result.stderr
    assert 'Bearer realm="mcp"' in result.stderr
    assert tool_names_offered(httpserver) == []


def jsonrpc(id: int, **fields) -> dict:
    return {"jsonrpc": "2.0", "id": id, **fields}


ADD_TOOL = {
    "name": "add",
    "description": "Add two numbers",
    "inputSchema": {"type": "object", "properties": {}},
}


def test_jsonrpc_error_on_list_is_logged_not_swallowed(
    ijon, httpserver, openai_endpoint, tmp_path
):
    httpserver.expect_ordered_request("/mcp").respond_with_json(jsonrpc(1, result={}))
    httpserver.expect_ordered_request("/mcp").respond_with_json(
        jsonrpc(2, error={"code": -32601, "message": "Method not found"})
    )
    openai_endpoint(assistant_message("done"))
    write_mcp_config(tmp_path, httpserver.url_for("/mcp"))

    result = ijon.run("hi", "--model", "test-model", "--mcp", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert "MCP tools/list failed" in result.stderr
    assert "Method not found" in result.stderr
    assert tool_names_offered(httpserver) == []


def test_jsonrpc_error_on_call_is_fed_back_to_the_model(ijon, httpserver, tmp_path):
    # registered in the order the harness talks: handshake, list, model, call, model
    mcp = lambda body: httpserver.expect_ordered_request("/mcp").respond_with_json(body)  # noqa: E731
    model = lambda body: httpserver.expect_ordered_request(  # noqa: E731
        "/v1/chat/completions"
    ).respond_with_json(body)
    mcp(jsonrpc(1, result={}))
    mcp(jsonrpc(2, result={"tools": [ADD_TOOL]}))
    model(tool_call({"a": "x"}, name="add"))
    mcp(jsonrpc(3, error={"code": -32602, "message": "Invalid params"}))
    model(assistant_message("done"))
    write_mcp_config(tmp_path, httpserver.url_for("/mcp"))

    result = ijon.run("hi", "--model", "test-model", "--mcp", "--jsonl", cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert "MCP tools/call failed" in result.stderr
    (tool_msg,) = tool_results(result)
    # the error reaches the model as JSON, not as the string "null"
    assert json.loads(tool_msg["content"])["error"]["message"] == "Invalid params"
