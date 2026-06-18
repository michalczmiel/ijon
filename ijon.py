import argparse
import json
import logging
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

logger = logging.getLogger("ijon")


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
        logger.error("HTTP %s %s: %s", e.code, e.reason, error_body)
        return None
    except urllib.error.URLError as e:
        logger.error("cannot connect to %s: %s", url, e.reason)
        return None
    except Exception as e:
        logger.error("%s", e)
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
    openai_base_url: str
    openai_api_key: Optional[str] = None
    bash_timeout: int = 120

    @classmethod
    def from_env(cls) -> "Config":
        openai_base_url = os.environ.get("OPENAI_BASE_URL")
        if not openai_base_url:
            raise ValueError("OPENAI_BASE_URL not set")

        openai_api_key = os.environ.get("OPENAI_API_KEY")

        bash_timeout = int(os.environ.get("IJON_BASH_TIMEOUT", "120"))

        return cls(
            openai_base_url=openai_base_url,
            openai_api_key=openai_api_key,
            bash_timeout=bash_timeout,
        )


class HttpMCPClient:
    def __init__(self, url: str, headers: Optional[dict[str, str]] = None):
        self.url = url
        self.headers = {
            "Accept": "text/event-stream, application/json",
            "Content-Type": "application/json",
            **(headers or {}),
        }
        self._id = 0

    def _next_id(self) -> int:
        # MCP requires ids to be non-null and unique within a session.
        self._id += 1
        return self._id

    def _send(self, method: str, params: Optional[dict] = None) -> Optional[dict]:
        body = {"jsonrpc": "2.0", "id": self._next_id(), "method": method}
        if params is not None:
            body["params"] = params

        response = request(self.url, self.headers, body)
        if not response:
            return None
        data, _ = response
        parsed = self._extract_sse_data(data)
        if not parsed:
            return None
        return parsed.get("result")

    def connect(self) -> bool:
        body = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
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
        result = self._send("tools/list")
        return result.get("tools", []) if result else []

    def call_tool(self, name: str, arguments: dict) -> Optional[dict]:
        return self._send("tools/call", {"name": name, "arguments": arguments})


def execute_bash_script(script: str, timeout: int) -> str:
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


def make_bash_tool(timeout: int) -> dict:
    """Expose bash script execution as a tool."""
    return {
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
        "execute": lambda args: execute_bash_script(args["script"], timeout=timeout),
    }


def execute_tool_call(tool_call: dict, tools: list[dict]) -> dict:
    """Run one tool call, return the `role: tool` message to append."""
    try:
        tool_args = json.loads(tool_call["function"]["arguments"])
    except (json.JSONDecodeError, TypeError) as e:
        result = f"error: invalid tool arguments JSON: {e}"
    else:
        tool_name = tool_call["function"]["name"]
        tool = next((t for t in tools if t["name"] == tool_name), None)

        if tool is None:
            result = f"error: unknown tool '{tool_name}'"
        else:
            logger.info("executing tool: %s with args %s", tool_name, tool_args)
            result = tool["execute"](tool_args)

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
    jsonl: bool = False
    bash: bool = False
    mcp: bool = False
    skills: bool = False

    @classmethod
    def from_args(cls, argv: Optional[Sequence[str]] = None) -> "Arguments":
        parser = argparse.ArgumentParser(
            prog="ijon",
            description="Single-file zero-dependency AI harness",
        )

        parser.add_argument("prompt", type=str)
        parser.add_argument("--model", type=str, required=True)
        parser.add_argument("--bash", action="store_true", help="enable the bash tool")
        parser.add_argument(
            "--mcp",
            action="store_true",
            help="enable MCP tools from .mcp.json in the current directory",
        )
        parser.add_argument(
            "--skills",
            action="store_true",
            help="enable skills loaded from .agents/skills in the current directory",
        )
        parser.add_argument("--max-iterations", type=int, default=10)
        parser.add_argument(
            "--jsonl",
            action="store_true",
            help="emit the session as JSONL on stdout (pipe to a file to save it)",
        )

        args = parser.parse_args(argv)
        return cls(**vars(args))


def run_agent(
    args: Arguments,
    client: OpenAICompatibleClient,
    tools: list[dict],
) -> None:
    """
    Run the agent loop, handling tool calls and session storage.
    """
    iteration_count = 0
    messages = [{"role": "user", "content": args.prompt}]

    tool_schemas = [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["parameters"],
            },
        }
        for tool in tools
    ]

    if args.jsonl:
        print(json.dumps({"type": "user", "message": messages[0]}), flush=True)

    while iteration_count < args.max_iterations:
        iteration_count += 1

        response = client.chat_completions(
            {
                "model": args.model,
                "messages": messages,
                "tools": tool_schemas,
            }
        )

        if not response:
            logger.error("failed to get response")
            return

        if args.jsonl:
            print(json.dumps({"type": "completion", "response": response}), flush=True)

        try:
            message = response["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as e:
            logger.error("%s, response: %s", e, json.dumps(response))
            return

        if message.get("content"):
            logger.info("%s", message["content"])

        messages.append(message)

        tool_calls = message.get("tool_calls")
        if not tool_calls:
            break

        for tool_call in tool_calls:
            messages.append(execute_tool_call(tool_call, tools))
    else:
        logger.error("reached max iterations (%s)", args.max_iterations)


def load_mcp_clients_from_config() -> list[HttpMCPClient]:
    file_name = ".mcp.json"
    try:
        with open(file_name) as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as e:
        logger.error("malformed %s: %s", file_name, e)
        return []
    except Exception as e:
        logger.error("unexpected error while loading %s: %s", file_name, e)
        return []

    return [
        HttpMCPClient(server["url"], server.get("headers"))
        for server in data.get("mcpServers", {}).values()
    ]


def parse_skill_metadata(content: str, default_name: str) -> tuple[str, str]:
    """Pull name/description from optional YAML frontmatter, with fallbacks."""
    name = default_name
    description = ""
    body = content

    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            frontmatter = content[3:end]
            body = content[end + 4 :]
            for line in frontmatter.splitlines():
                key, sep, value = line.partition(":")
                if not sep:
                    continue
                key = key.strip().lower()
                value = value.strip()
                if key == "name" and value:
                    name = value
                elif key == "description" and value:
                    description = value

    if not description:
        for line in body.splitlines():
            line = line.strip().lstrip("#").strip()
            if line:
                description = line
                break

    return name, description


def load_skills_from_directory(directory: str = ".agents/skills") -> list[dict]:
    """Discover skills stored as <directory>/<name>/SKILL.md."""
    skills = []
    for skill_file in sorted(Path(directory).glob("*/SKILL.md")):
        try:
            content = skill_file.read_text()
        except OSError as e:
            logger.error("cannot read %s: %s", skill_file, e)
            continue

        name, description = parse_skill_metadata(
            content, default_name=skill_file.parent.name
        )
        skills.append({"name": name, "description": description, "content": content})

    return skills


def make_skill_tool(skills: list[dict]) -> dict:
    """Expose discovered skills as a single tool that loads a skill into context."""
    by_name = {skill["name"]: skill for skill in skills}
    available = "\n".join(f"- {s['name']}: {s['description']}" for s in skills)

    def execute(args: dict) -> str:
        skill = by_name.get(args.get("name"))
        if skill is None:
            return f"error: unknown skill '{args.get('name')}'"
        return skill["content"]

    return {
        "name": "skill",
        "description": (
            "Load a skill's instructions into context. Available skills:\n" + available
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "enum": list(by_name.keys()),
                    "description": "The name of the skill to load",
                }
            },
            "required": ["name"],
        },
        "execute": execute,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

    arguments = Arguments.from_args()

    try:
        config = Config.from_env()
    except ValueError as e:
        logger.error("%s", e)
        return

    tools = []

    if arguments.bash:
        tools.append(make_bash_tool(config.bash_timeout))

    mcp_clients = load_mcp_clients_from_config() if arguments.mcp else []
    for mcp_client in mcp_clients:
        connected = mcp_client.connect()
        if not connected:
            continue
        mcp_tools = mcp_client.list_tools()

        for mcp_tool in mcp_tools:
            name = mcp_tool["name"]
            tools.append(
                {
                    "name": name,
                    "description": mcp_tool["description"],
                    "parameters": mcp_tool["inputSchema"],
                    "execute": lambda args, client=mcp_client, name=name: (
                        client.call_tool(name, args)
                    ),
                }
            )

    if arguments.skills:
        skills = load_skills_from_directory()
        if skills:
            tools.append(make_skill_tool(skills))

    client = OpenAICompatibleClient(config.openai_base_url, config.openai_api_key)

    run_agent(
        arguments,
        client,
        tools,
    )


if __name__ == "__main__":
    main()
