import json

from ijon import execute_tool_call


def call(name: str, arguments) -> dict:
    return {
        "id": "call_1",
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def tool(name: str, execute) -> dict:
    return {"name": name, "description": "", "parameters": {}, "execute": execute}


def test_runs_the_matching_tool_with_parsed_args():
    received = {}
    tools = {"echo": tool("echo", lambda args: received.update(args) or "ok")}

    msg = execute_tool_call(call("echo", json.dumps({"text": "hi"})), tools)

    assert received == {"text": "hi"}
    assert msg["tool_call_id"] == "call_1"
    assert "ok" in msg["content"]


def test_reports_unknown_tool():
    msg = execute_tool_call(call("nope", json.dumps({})), tools={})

    assert "unknown tool" in msg["content"]


def test_reports_invalid_arguments_json():
    tools = {"echo": tool("echo", lambda args: "ok")}

    msg = execute_tool_call(call("echo", "not json"), tools)

    assert "invalid tool arguments JSON" in msg["content"]
