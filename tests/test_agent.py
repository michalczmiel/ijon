from conftest import completion_requests, events, tool_results
from factories import assistant_message, bash_call


def test_shows_the_models_answer_to_the_user(ijon, openai_endpoint):
    openai_endpoint(assistant_message("the answer is 42"))

    result = ijon.run("hi", "--model", "test-model")

    assert result.returncode == 0, result.stderr
    assert "the answer is 42" in result.stderr


def test_shows_the_models_thinking_to_the_user(ijon, openai_endpoint):
    openai_endpoint(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "reasoning_content": "let me work it out",
                        "content": "the answer is 42",
                    }
                }
            ]
        }
    )

    result = ijon.run("hi", "--model", "test-model")

    assert "let me work it out" in result.stderr


def test_stdout_stays_empty_without_jsonl(ijon, openai_endpoint):
    openai_endpoint(assistant_message("the answer is 42"))

    result = ijon.run("hi", "--model", "test-model")

    assert result.stdout == ""


def test_emits_the_whole_conversation_as_jsonl(ijon, openai_endpoint):
    tool_response = bash_call("echo hi")
    final_response = assistant_message("done")
    openai_endpoint(tool_response, final_response)

    result = ijon.run("hi", "--model", "test-model", "--bash", "--jsonl")

    assert result.returncode == 0, result.stderr
    assert events(result) == [
        {"type": "user", "message": {"role": "user", "content": "hi"}},
        {"type": "completion", "response": tool_response},
        {
            "type": "tool_result",
            "message": {
                "role": "tool",
                "content": "exit_code: 0\nstdout:\nhi\n",
                "tool_call_id": "call_1",
            },
        },
        {"type": "completion", "response": final_response},
    ]


def test_feeds_the_tool_result_back_to_the_model(ijon, httpserver, openai_endpoint):
    openai_endpoint(bash_call("echo hi"), assistant_message("done"))

    ijon.run("hi", "--model", "test-model", "--bash")

    # The model must receive the tool's output back, tagged to its call.
    messages = completion_requests(httpserver)[1].get_json()["messages"]
    tool_msg = next(m for m in messages if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == "call_1"
    assert "hi" in tool_msg["content"]


def test_keeps_the_assistant_turn_in_the_conversation(
    ijon, httpserver, openai_endpoint
):
    tool_response = bash_call("echo hi")
    openai_endpoint(tool_response, assistant_message("done"))

    ijon.run("hi", "--model", "test-model", "--bash")

    messages = completion_requests(httpserver)[1].get_json()["messages"]
    assert messages[0] == {"role": "user", "content": "hi"}
    assert messages[1] == tool_response["choices"][0]["message"]
    assert [m["role"] for m in messages] == ["user", "assistant", "tool"]


def test_survives_an_invalid_response(ijon, openai_endpoint):
    openai_endpoint({"unexpected": "shape"})

    result = ijon.run("hi", "--model", "test-model")

    # No crash; the failure is logged for the user and reported as a failure.
    assert result.returncode == 1
    assert "response" in result.stderr


def test_stops_instead_of_looping_forever(ijon, httpserver, openai_endpoint):
    # A model stuck always asking for another command must still terminate.
    openai_endpoint(*[bash_call("echo loop") for _ in range(10)])

    result = ijon.run(
        "hi", "--model", "test-model", "--bash", "--jsonl", "--max-iterations", "3"
    )

    assert result.returncode == 1
    assert len(completion_requests(httpserver)) == 3
    assert len(tool_results(result)) == 3
    assert "max iterations" in result.stderr


def test_reports_failure_when_the_request_fails(ijon, httpserver):
    httpserver.expect_request("/v1/chat/completions").respond_with_data(
        "boom", status=400
    )

    result = ijon.run("hi", "--model", "test-model")

    assert result.returncode == 1
    assert "failed to get response" in result.stderr
