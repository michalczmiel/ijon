import json
import logging
from dataclasses import dataclass, field

import pytest

from ijon import Arguments, run_agent


@dataclass
class FakeClient:
    """A scripted model: hands back canned responses turn by turn."""

    responses: list
    turns: int = 0
    bodies: list = field(default_factory=list)

    def chat_completions(self, body: dict):
        self.turns += 1
        self.bodies.append(body)
        return self.responses.pop(0)


def message(content: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def tool(script: str) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "execute_bash_script",
                                "arguments": json.dumps({"script": script}),
                            },
                        }
                    ],
                }
            }
        ]
    }


@pytest.fixture
def run():
    """Drive run_agent with sensible defaults; pass the scripted client in."""

    def _run(client, *, prompt="hi", max_iterations=10, jsonl=False):
        args = Arguments(
            prompt=prompt,
            model="test-model",
            max_iterations=max_iterations,
            jsonl=jsonl,
        )
        tools = [
            {
                "name": "execute_bash_script",
                "description": "a fake tool",
                "parameters": {},
                "execute": lambda args: "fake output",
            }
        ]
        run_agent(args, client, tools)

    return _run


def test_shows_the_models_answer_to_the_user(run, caplog):
    caplog.set_level(logging.INFO, logger="ijon")
    run(FakeClient([message("the answer is 42")]))

    assert "the answer is 42" in caplog.text


def test_shows_the_models_thinking_to_the_user(run, caplog):
    caplog.set_level(logging.INFO, logger="ijon")
    response = {
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
    run(FakeClient([response]))

    assert "let me work it out" in caplog.text


def test_emits_the_whole_conversation_as_jsonl(run, capsys):
    tool_response = tool("echo hi")
    final_response = message("done")
    run(FakeClient([tool_response, final_response]), prompt="hi", jsonl=True)

    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert records == [
        {"type": "user", "message": {"role": "user", "content": "hi"}},
        {"type": "completion", "response": tool_response},
        {"type": "completion", "response": final_response},
    ]


def test_feeds_the_tool_result_back_to_the_model(run):
    client = FakeClient([tool("echo hi"), message("done")])
    run(client)

    # The model must receive the tool's output back, tagged to its call.
    messages = client.bodies[1]["messages"]
    tool_msg = next(m for m in messages if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == "call_1"
    assert "fake output" in tool_msg["content"]


def test_survives_an_invalid_response(run, caplog):
    run(FakeClient([{"unexpected": "shape"}]))

    # No crash; the failure is logged for the user.
    assert "response" in caplog.text


def test_stops_instead_of_looping_forever(run, caplog):
    # A model stuck always asking for another command must still terminate.
    client = FakeClient([tool("echo loop") for _ in range(10)])

    run(client, max_iterations=3)

    assert client.turns == 3
    assert "max iterations" in caplog.text
