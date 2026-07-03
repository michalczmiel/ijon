import json


def assistant_message(content: str) -> dict:
    """A plain chat-completions answer carrying assistant text."""
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def tool_call(
    script: str, *, name: str = "execute_bash_script", call_id: str = "call_1"
) -> dict:
    """A chat-completions answer asking to run a tool."""
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
                                "arguments": json.dumps({"script": script}),
                            },
                        }
                    ],
                }
            }
        ]
    }
