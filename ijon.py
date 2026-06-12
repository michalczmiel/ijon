import argparse
import json
import os
import subprocess
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass
class OpenAICompatibleClient:
    base_url: str
    api_key: Optional[str] = None

    def chat_completions(self, body: dict) -> Optional[dict]:
        request = urllib.request.Request(f"{self.base_url}/v1/chat/completions")
        request.add_header("Content-Type", "application/json")
        if self.api_key:
            request.add_header("Authorization", f"Bearer {self.api_key}")
        body_bytes = json.dumps(body).encode("utf-8")
        request.add_header("Content-Length", str(len(body_bytes)))

        try:
            with urllib.request.urlopen(request, body_bytes, timeout=60) as response:
                data = response.read().decode("utf-8")
            return json.loads(data)
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            print(f"HTTP {e.code} {e.reason}: {error_body}")
            return None
        except Exception as e:
            print(e)
            return None


@dataclass
class Config:
    config_dir: str
    openai_base_url: str
    openai_api_key: Optional[str] = None
    bash_timeout: int = 120

    @classmethod
    def from_env(cls) -> "Config":
        openai_base_url = os.environ.get("OPENAI_BASE_URL")
        if not openai_base_url:
            raise ValueError("OPENAI_BASE_URL not set")

        openai_api_key = os.environ.get("OPENAI_API_KEY")

        config_dir = os.environ.get("IJON_CONFIG_DIR", "~/.ijon")
        config_dir = os.path.expanduser(config_dir)

        bash_timeout = int(os.environ.get("IJON_BASH_TIMEOUT", "120"))

        return cls(
            openai_base_url=openai_base_url,
            openai_api_key=openai_api_key,
            config_dir=config_dir,
            bash_timeout=bash_timeout,
        )


class FileSessionStore:
    def __init__(self, config_dir: str):
        self.config_dir = config_dir
        self.session_id = uuid.uuid4()

    def save(self, response: dict) -> None:
        sessions_dir = os.path.join(self.config_dir, "sessions")
        os.makedirs(sessions_dir, exist_ok=True)

        session_path = os.path.join(
            sessions_dir,
            f"{self.session_id}.jsonl",
        )
        with open(session_path, "a") as f:
            f.write(json.dumps(response) + "\n")


BASH_SCRIPT_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "execute_bash_script",
        "description": "Execute a bash script and return the output",
        "parameters": {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "The bash script to execute",
                }
            },
            "required": ["script"],
        },
    },
}


def execute_bash_script(script: str, timeout: int) -> str:
    print(f"Executing bash script: {script}")
    try:
        result = subprocess.run(
            script, shell=True, capture_output=True, text=True, timeout=timeout
        )
        parts = [f"exit_code: {result.returncode}"]
        if result.stdout:
            parts.append(f"stdout:\n{result.stdout}")
        if result.stderr:
            parts.append(f"stderr:\n{result.stderr}")
        return "\n".join(parts)
    except subprocess.TimeoutExpired:
        return f"error: Bash script timed out after {timeout} seconds"


def execute_tool_call(tool_call: dict, bash_timeout: int) -> dict:
    """Run one tool call, return the `role: tool` message to append."""
    try:
        tool_args = json.loads(tool_call["function"]["arguments"])
    except (json.JSONDecodeError, TypeError) as e:
        result = f"error: invalid tool arguments JSON: {e}"
    else:
        tool_name = tool_call["function"]["name"]
        if tool_name != BASH_SCRIPT_TOOL_SCHEMA["function"]["name"]:
            result = f"error: unknown tool '{tool_name}'"
        elif not isinstance(tool_args, dict) or "script" not in tool_args:
            result = "error: missing required argument 'script'"
        else:
            result = execute_bash_script(tool_args["script"], bash_timeout)

    return {
        "role": "tool",
        "content": json.dumps(result),
        "tool_call_id": tool_call["id"],
    }


@dataclass
class Arguments:
    prompt: str
    model: str
    max_iterations: int

    @classmethod
    def from_args(cls, argv: Optional[Sequence[str]] = None) -> "Arguments":
        parser = argparse.ArgumentParser(
            prog="ijon", description="Zero dependency AI harness with bash tool"
        )
        parser.add_argument("prompt", type=str)
        parser.add_argument("--model", type=str, required=True)
        parser.add_argument("--max-iterations", type=int, default=10)

        args = parser.parse_args(argv)
        return cls(**vars(args))


def run_agent(
    args: Arguments,
    session_store: FileSessionStore,
    client: OpenAICompatibleClient,
    bash_timeout: int,
) -> None:
    """
    Run the agent loop, handling tool calls and session storage.
    """
    iteration_count = 0
    messages = [{"role": "user", "content": args.prompt}]

    while iteration_count < args.max_iterations:
        iteration_count += 1

        response = client.chat_completions(
            {
                "model": args.model,
                "messages": messages,
                "tools": [BASH_SCRIPT_TOOL_SCHEMA],
            }
        )

        if not response:
            print("error: failed to get response")
            return

        session_store.save(response)

        try:
            message = response["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            print(f"error: unexpected response shape: {json.dumps(response)}")
            return

        if message.get("content"):
            print(message["content"])

        messages.append(message)

        tool_calls = message.get("tool_calls")
        if not tool_calls:
            break

        for tool_call in tool_calls:
            messages.append(execute_tool_call(tool_call, bash_timeout))
    else:
        print(f"error: reached max iterations ({args.max_iterations})")


def main() -> None:
    arguments = Arguments.from_args()

    try:
        config = Config.from_env()
    except ValueError as e:
        print(e)
        return

    client = OpenAICompatibleClient(config.openai_base_url, config.openai_api_key)
    session_store = FileSessionStore(config.config_dir)

    run_agent(arguments, session_store, client, config.bash_timeout)


if __name__ == "__main__":
    main()
