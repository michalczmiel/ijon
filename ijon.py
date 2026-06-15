import argparse
import json
import os
import subprocess
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Optional, Sequence


def request(url: str, headers: dict, body: dict) -> Optional[tuple[str, dict]]:
    body_bytes = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body_bytes,
        headers=headers,
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            data = response.read().decode("utf-8")
            headers = response.headers
        return data, headers
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"HTTP {e.code} {e.reason}: {error_body}")
        return None
    except Exception as e:
        print(e)
        return None


@dataclass
class OpenAICompatibleClient:
    base_url: str
    api_key: Optional[str] = None

    def chat_completions(self, body: dict) -> Optional[dict]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        response = request(f"{self.base_url}/v1/chat/completions", headers, body)
        if response is None:
            return None
        data, _ = response
        return json.loads(data)


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

    def save_user(self, message: dict) -> None:
        self._save({"type": "user", "message": message})

    def save_completion(self, response: dict) -> None:
        self._save({"type": "completion", "response": response})

    def _save(self, response: dict) -> None:
        sessions_dir = os.path.join(self.config_dir, "sessions")
        os.makedirs(sessions_dir, exist_ok=True)

        session_path = os.path.join(
            sessions_dir,
            f"{self.session_id}.jsonl",
        )
        with open(session_path, "a") as f:
            f.write(json.dumps(response) + "\n")


class HttpMCPClient:
    def __init__(self, url: str, headers: Optional[dict[str, str]] = None):
        self.url = url
        self.headers = {
            "Accept": "text/event-stream, application/json",
            "Content-Type": "application/json",
            **(headers or {}),
        }

    def connect(self) -> bool:
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"elicitation": {}},
                "clientInfo": {"name": "ijon", "version": "1.0.0"},
            },
        }
        response = request(self.url, self.headers, body)
        if not response:
            return False
        _, headers = response
        session_id = headers.get("mcp-session-id")
        if not session_id:
            return False

        self.headers["mcp-session-id"] = session_id

        return True

    def _extract_sse_data(self, raw: str) -> Optional[dict]:
        for line in raw.split("\n"):
            line = line.strip()
            if line.startswith("data:"):
                return json.loads(line[5:])

    def list_tools(self) -> list[dict]:
        body = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
        }
        response = request(self.url, self.headers, body)
        if not response:
            return []

        data, _ = response

        parsed = self._extract_sse_data(data)
        if not parsed:
            return []

        result = parsed.get("result", {})
        return result.get("tools", [])

    def call_tool(self, name: str, arguments: dict) -> Optional[dict]:
        body = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments,
            },
        }

        response = request(self.url, self.headers, body)
        if not response:
            return None
        data, _ = response
        parsed = self._extract_sse_data(data)
        if not parsed:
            return None
        return parsed.get("result")


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


def execute_tool_call(
    tool_call: dict, bash_timeout: int, mcp_tools_client_map: dict
) -> dict:
    """Run one tool call, return the `role: tool` message to append."""
    try:
        tool_args = json.loads(tool_call["function"]["arguments"])
    except (json.JSONDecodeError, TypeError) as e:
        result = f"error: invalid tool arguments JSON: {e}"
    else:
        tool_name = tool_call["function"]["name"]
        if tool_name in mcp_tools_client_map:
            print(f"executing MCP tool: {tool_name} with args {tool_args}")
            mcp_tool_result = mcp_tools_client_map[tool_name].call_tool(
                tool_name, tool_args
            )
            result = (
                mcp_tool_result
                if mcp_tool_result is not None
                else "error: tool call failed"
            )
        elif tool_name != BASH_SCRIPT_TOOL_SCHEMA["function"]["name"]:
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
    mcp_clients: Optional[list[HttpMCPClient]] = None,
) -> None:
    """
    Run the agent loop, handling tool calls and session storage.
    """
    iteration_count = 0
    messages = [{"role": "user", "content": args.prompt}]

    session_store.save_user(messages[0])

    mcp_tools_client_map = {}

    tools = [BASH_SCRIPT_TOOL_SCHEMA]
    if mcp_clients:
        for mcp_client in mcp_clients:
            connected = mcp_client.connect()
            if not connected:
                continue
            mcp_tools = mcp_client.list_tools()
            for mcp_tool in mcp_tools:
                mcp_tool_name = mcp_tool["name"]
                mcp_tools_client_map[mcp_tool_name] = mcp_client
                tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": mcp_tool["name"],
                            "description": mcp_tool["description"],
                            "parameters": mcp_tool["inputSchema"],
                        },
                    }
                )

    while iteration_count < args.max_iterations:
        iteration_count += 1

        response = client.chat_completions(
            {
                "model": args.model,
                "messages": messages,
                "tools": tools,
            }
        )

        if not response:
            print("error: failed to get response")
            return

        session_store.save_completion(response)

        try:
            message = response["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as e:
            print(f"error: {e}, response: {json.dumps(response)}")
            return

        if message.get("content"):
            print(message["content"])

        messages.append(message)

        tool_calls = message.get("tool_calls")
        if not tool_calls:
            break

        for tool_call in tool_calls:
            messages.append(
                execute_tool_call(tool_call, bash_timeout, mcp_tools_client_map)
            )
    else:
        print(f"error: reached max iterations ({args.max_iterations})")


def load_mcp_clients_from_config() -> list[HttpMCPClient]:
    file_name = ".mcp.json"
    try:
        with open(file_name) as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as e:
        print(f"error: malformed {file_name}: {e}")
        return []
    except Exception as e:
        print(f"error: unexpected error while loading {file_name}: {e}")
        return []

    if "mcpServers" not in data:
        return []

    return [
        HttpMCPClient(server["url"], server.get("headers"))
        for server in data["mcpServers"].values()
    ]


def main() -> None:
    arguments = Arguments.from_args()
    mcp_clients = load_mcp_clients_from_config()

    try:
        config = Config.from_env()
    except ValueError as e:
        print(e)
        return

    client = OpenAICompatibleClient(config.openai_base_url, config.openai_api_key)
    session_store = FileSessionStore(config.config_dir)

    run_agent(
        arguments, session_store, client, config.bash_timeout, mcp_clients=mcp_clients
    )


if __name__ == "__main__":
    main()
