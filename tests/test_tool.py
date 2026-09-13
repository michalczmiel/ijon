from conftest import tool_results
from factories import assistant_message, tool_call, tool_calls


def test_string_result_is_not_double_encoded(ijon, openai_endpoint):
    openai_endpoint(tool_call({"script": "echo hi"}), assistant_message("done"))

    result = ijon.run("hi", "--model", "test-model", "--bash", "--jsonl")

    # A bash result is raw text, not a JSON-quoted string.
    assert tool_results(result)[0]["content"] == "exit_code: 0\nstdout:\nhi\n"


def test_reports_unknown_tool(ijon, openai_endpoint):
    openai_endpoint(tool_call({}, name="nope"), assistant_message("done"))

    result = ijon.run("hi", "--model", "test-model", "--bash", "--jsonl")

    assert result.returncode == 0, result.stderr
    (tool_msg,) = tool_results(result)
    assert tool_msg["tool_call_id"] == "call_1"
    assert "unknown tool 'nope'" in tool_msg["content"]


def test_reports_invalid_arguments_json(ijon, openai_endpoint):
    openai_endpoint(tool_call(raw_arguments="not json"), assistant_message("done"))

    result = ijon.run("hi", "--model", "test-model", "--bash", "--jsonl")

    assert result.returncode == 0, result.stderr
    assert "invalid tool arguments JSON" in tool_results(result)[0]["content"]


def test_runs_every_tool_call_in_order(ijon, openai_endpoint):
    openai_endpoint(
        tool_calls(
            ("execute_bash_script", {"script": "echo one"}, "call_1"),
            ("execute_bash_script", {"script": "echo two"}, "call_2"),
        ),
        assistant_message("done"),
    )

    result = ijon.run("hi", "--model", "test-model", "--bash", "--jsonl")

    results = tool_results(result)
    assert [r["tool_call_id"] for r in results] == ["call_1", "call_2"]
    assert "one" in results[0]["content"]
    assert "two" in results[1]["content"]


def test_reports_tool_failure_instead_of_crashing(ijon, openai_endpoint):
    # The model omitted the required argument; the tool blows up on lookup.
    openai_endpoint(tool_call({}), assistant_message("done"))

    result = ijon.run("hi", "--model", "test-model", "--bash", "--jsonl")

    assert result.returncode == 0, result.stderr
    (tool_msg,) = tool_results(result)
    assert tool_msg["tool_call_id"] == "call_1"
    assert tool_msg["content"].startswith("error:")
