import json
from typing import Optional


def assistant_message(content: str) -> dict:
    """A plain chat-completions answer carrying assistant text."""
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def tool_call(
    arguments: Optional[dict] = None,
    *,
    name: str = "execute_bash_script",
    call_id: str = "call_1",
    raw_arguments: Optional[str] = None,
) -> dict:
    """A chat-completions answer asking to run a tool."""
    return tool_calls(
        (name, arguments if arguments is not None else {}, call_id),
        raw_arguments=raw_arguments,
    )


def tool_calls(*calls: tuple, raw_arguments: Optional[str] = None) -> dict:
    """A chat-completions answer asking to run several tools; calls are (name, args, id)."""
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": (
                                    raw_arguments
                                    if raw_arguments is not None
                                    else json.dumps(arguments)
                                ),
                            },
                        }
                        for name, arguments, call_id in calls
                    ],
                }
            }
        ]
    }


def bash_call(script: str, call_id: str = "call_1") -> dict:
    return tool_call({"script": script}, call_id=call_id)
