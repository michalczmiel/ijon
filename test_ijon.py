import json
from dataclasses import dataclass

import pytest

from ijon import Arguments, run_agent


@dataclass
class FakeClient:
    """A scripted model: hands back canned responses turn by turn."""

    responses: list
    turns: int = 0

    def chat_completions(self, body: dict):
        self.turns += 1
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

    def _run(client, *, prompt="hi", max_iterations=10, bash_timeout=5, jsonl=False):
        args = Arguments(
            prompt=prompt,
            model="test-model",
            max_iterations=max_iterations,
            jsonl=jsonl,
        )
        run_agent(args, client, bash_timeout=bash_timeout)

    return _run


def test_shows_the_models_answer_to_the_user(run, capsys):
    run(FakeClient([message("the answer is 42")]))

    assert "the answer is 42" in capsys.readouterr().out


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


def test_survives_an_invalid_response(run, caplog):
    run(FakeClient([{"unexpected": "shape"}]))

    # No crash; the failure is logged for the user.
    assert "response" in caplog.text.lower()


def test_stops_instead_of_looping_forever(run, caplog):
    # A model stuck always asking for another command must still terminate.
    client = FakeClient([tool("echo loop") for _ in range(10)])

    run(client, max_iterations=3)

    assert client.turns == 3
    assert "max iterations" in caplog.text.lower()
