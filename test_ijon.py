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

    def save(self, response: dict) -> None:
        self.saved.append(response)


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
    run(FakeClient([tool("echo hi"), message("done")]))

    # Every backend response is persisted so the session can be replayed.
    assert len(store.saved) == 2


def test_survives_an_invalid_response(run, capsys):
    run(FakeClient([{"unexpected": "shape"}]))

    # No crash; the user is told something went wrong.
    assert "error" in capsys.readouterr().out.lower()


def test_stops_instead_of_looping_forever(run, capsys):
    # A model stuck always asking for another command must still terminate.
    client = FakeClient([tool("echo loop") for _ in range(10)])

    run(client, max_iterations=3)

    assert client.turns == 3
    assert "max iterations" in capsys.readouterr().out.lower()
