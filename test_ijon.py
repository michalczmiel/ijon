import json
from dataclasses import dataclass, field

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


@dataclass
class FakeStore:
    """Records the conversation the way the real store persists it."""

    saved: list = field(default_factory=list)

    def save_user(self, message: dict) -> None:
        self.saved.append({"type": "user", "message": message})

    def save_completion(self, response: dict) -> None:
        self.saved.append({"type": "completion", "response": response})


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
def store():
    return FakeStore()


@pytest.fixture
def run(store):
    """Drive run_agent with sensible defaults; pass the scripted client in."""

    def _run(client, *, prompt="hi", max_iterations=10, bash_timeout=5):
        args = Arguments(
            prompt=prompt, model="test-model", max_iterations=max_iterations
        )
        run_agent(args, store, client, bash_timeout=bash_timeout)

    return _run


def test_shows_the_models_answer_to_the_user(run, capsys):
    run(FakeClient([message("the answer is 42")]))

    assert "the answer is 42" in capsys.readouterr().out


def test_records_the_whole_conversation(run, store):
    run(FakeClient([tool("echo hi"), message("done")]), prompt="hi")

    # The user prompt plus every backend response is persisted so the session can be replayed.
    assert [entry["type"] for entry in store.saved] == [
        "user",
        "completion",
        "completion",
    ]
    assert store.saved[0]["message"] == {"role": "user", "content": "hi"}


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
