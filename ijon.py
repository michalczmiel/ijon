import argparse
import functools
import itertools
import json
import logging
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Optional, Sequence

logger = logging.getLogger("ijon")


@dataclass
class HttpTransport:
    """Makes HTTP requests, retrying 429/5xx and timeouts with exponential backoff."""

    request_max_attempts: int
    request_base_delay: float  # seconds; doubles each attempt
    timeout: int  # seconds

    def _retry(self, attempt: int, reason: str) -> bool:
        """Sleep with backoff before retrying; return False when attempts exhausted so caller gives up."""
        if attempt == self.request_max_attempts:
            logger.error(
                "giving up after %d attempts: %s", self.request_max_attempts, reason
            )
            return False
        delay = self.request_base_delay * 2 ** (attempt - 1)
        logger.warning(
            "%s, retrying in %.1fs (attempt %d/%d)",
            reason,
            delay,
            attempt,
            self.request_max_attempts,
        )
        time.sleep(delay)
        return True

    def request(
        self, url: str, headers: dict, body: dict
    ) -> Optional[tuple[str, dict]]:
        body_bytes = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body_bytes,
            headers=headers,
        )

        for attempt in range(1, self.request_max_attempts + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    data = response.read().decode("utf-8")
                    headers = response.headers
                return data, headers
            except socket.timeout:
                if self._retry(attempt, f"request timed out after {self.timeout}s"):
                    continue
                return None
            except urllib.error.HTTPError as e:
                error_body = e.read().decode("utf-8")
                if (
                    e.code == HTTPStatus.TOO_MANY_REQUESTS
                    or e.code >= HTTPStatus.INTERNAL_SERVER_ERROR
                ):
                    if self._retry(
                        attempt, f"request failed (HTTP {e.code} {e.reason})"
                    ):
                        continue
                    return None
                logger.error("HTTP %s %s: %s", e.code, e.reason, error_body)
                if e.code == HTTPStatus.UNAUTHORIZED:
                    # MCP's OAuth flow starts here, but ijon only does static-token auth.
                    challenge = e.headers.get("WWW-Authenticate")
                    logger.error(
                        "401 unauthorized for %s: ijon only supports static tokens "
                        "(set them in mcp.json headers). WWW-Authenticate: %s",
                        url,
                        challenge or "<none>",
                    )
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
    transport: HttpTransport
    api_key: Optional[str] = None

    def chat_completions(
        self,
        model: str,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        max_completion_tokens: Optional[int] = None,
    ) -> Optional[dict]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        body = {"model": model, "messages": messages}
        if tools:
            body["tools"] = tools
        if max_completion_tokens is not None:
            body["max_completion_tokens"] = max_completion_tokens

        response = self.transport.request(
            f"{self.base_url}/v1/chat/completions", headers, body
        )
        if response is None:
            return None
        data, _ = response
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            logger.error("non-JSON response body: %s", data[:200])
            return None


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got {raw!r}")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {raw!r}")


@dataclass
class Config:
    openai_base_url: str
    openai_api_key: Optional[str] = None
    bash_timeout: int = 120
    request_max_attempts: int = 3
    request_base_delay: float = 1.0
    http_timeout: int = 120

    @classmethod
    def from_env(cls) -> "Config":
        openai_base_url = os.environ.get("OPENAI_BASE_URL")
        if not openai_base_url:
            raise ValueError("OPENAI_BASE_URL not set")

        openai_api_key = os.environ.get("OPENAI_API_KEY")

        bash_timeout = _env_int("IJON_BASH_TIMEOUT", cls.bash_timeout)

        request_max_attempts = _env_int("IJON_MAX_ATTEMPTS", cls.request_max_attempts)
        if request_max_attempts < 1:
            raise ValueError(
                f"IJON_MAX_ATTEMPTS must be at least 1, got {request_max_attempts}"
            )

        request_base_delay = _env_float("IJON_RETRY_BASE_DELAY", cls.request_base_delay)
        if request_base_delay < 0:
            raise ValueError(
                f"IJON_RETRY_BASE_DELAY must not be negative, got {request_base_delay}"
            )

        http_timeout = _env_int("IJON_HTTP_TIMEOUT", cls.http_timeout)

        return cls(
            openai_base_url=openai_base_url,
            openai_api_key=openai_api_key,
            bash_timeout=bash_timeout,
            request_max_attempts=request_max_attempts,
            request_base_delay=request_base_delay,
            http_timeout=http_timeout,
        )


class HttpMCPClient:
    def __init__(
        self,
        url: str,
        transport: HttpTransport,
        headers: Optional[dict[str, str]] = None,
    ):
        self.url = url
        self.headers = {
            "Accept": "text/event-stream, application/json",
            "Content-Type": "application/json",
            **(headers or {}),
        }
        self.transport = transport
        # MCP requires ids to be non-null and unique within a session.
        self._ids = itertools.count(1)

    def _send(self, method: str, params: Optional[dict] = None) -> Optional[dict]:
        body = {"jsonrpc": "2.0", "id": next(self._ids), "method": method}
        if params is not None:
            body["params"] = params

        response = self.transport.request(self.url, self.headers, body)
        if not response:
            return None
        data, _ = response
        parsed = self._parse_response(data)
        if not parsed:
            return None
        return parsed.get("result")

    def connect(self) -> bool:
        body = {
            "jsonrpc": "2.0",
            "id": next(self._ids),
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"elicitation": {}},
                "clientInfo": {"name": "ijon", "version": "0.1.0"},
            },
        }
        response = self.transport.request(self.url, self.headers, body)
        if not response:
            return False
        _, headers = response
        # Session ids are optional: stateful servers issue one to carry on the
        # session, stateless ones omit it. Only echo it back when present.
        session_id = headers.get("mcp-session-id")
        if session_id:
            self.headers["mcp-session-id"] = session_id

        return True

    def _parse_response(self, raw: str) -> Optional[dict]:
        # try JSON response first, if not fallback to SSE
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        for line in raw.split("\n"):
            line = line.strip()
            if line.startswith("data:"):
                try:
                    return json.loads(line.removeprefix("data:"))
                except json.JSONDecodeError:
                    logger.error("non-JSON SSE data: %s", line[:200])
                    return None
        logger.error("unparseable MCP response: %s", raw[:200])
        return None

    def list_tools(self) -> list[dict]:
        result = self._send("tools/list")
        return result.get("tools", []) if result else []

    def call_tool(self, name: str, arguments: dict) -> Optional[dict]:
        return self._send("tools/call", {"name": name, "arguments": arguments})


def execute_bash_script(script: str, timeout: int) -> str:
    # start_new_session groups the shell and its children so a timeout can kill the whole group, not just the shell.
    with subprocess.Popen(
        script,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    ) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # shell is its own group leader (start_new_session), so pid == group id;
            # ProcessLookupError means the group already drained.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            return f"error: Bash script timed out after {timeout} seconds"

        parts = [f"exit_code: {process.returncode}"]
        if stdout:
            parts.append(f"stdout:\n{stdout}")
        if stderr:
            parts.append(f"stderr:\n{stderr}")
        return "\n".join(parts)


def make_bash_tool(timeout: int) -> dict:
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


def execute_tool_call(tool_call: dict, tools: dict[str, dict]) -> dict:
    """Run one tool call, return the `role: tool` message to append."""

    def reply(result) -> dict:
        # only serialize dicts (MCP); str passes through to avoid double-encoding.
        content = result if isinstance(result, str) else json.dumps(result)
        return {
            "role": "tool",
            "content": content,
            "tool_call_id": tool_call["id"],
        }

    try:
        tool_args = json.loads(tool_call["function"]["arguments"])
    except (json.JSONDecodeError, TypeError) as e:
        return reply(f"error: invalid tool arguments JSON: {e}")

    tool_name = tool_call["function"]["name"]
    tool = tools.get(tool_name)
    if tool is None:
        return reply(f"error: unknown tool '{tool_name}'")

    logger.info("executing tool: %s with args %s", tool_name, tool_args)
    try:
        return reply(tool["execute"](tool_args))
    except Exception as e:
        logger.error("tool %s failed: %s", tool_name, e)
        return reply(f"error: {e}")


def read_piped_stdin() -> str:
    """Return stdin's content when piped/redirected, else an empty string"""
    if sys.stdin.isatty():
        return ""
    try:
        return sys.stdin.read().strip()
    except (OSError, ValueError):
        return ""


@dataclass
class Arguments:
    prompt: str
    model: str
    max_iterations: int
    max_completion_tokens: Optional[int] = None
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
            help="enable MCP tools from mcp.json in the current directory",
        )
        parser.add_argument(
            "--skills",
            action="store_true",
            help="enable skills loaded from .agents/skills in the current directory",
        )
        parser.add_argument("--max-iterations", type=int, default=10)
        parser.add_argument(
            "--max-completion-tokens",
            type=int,
            default=None,
            help="cap output tokens (incl. reasoning)",
        )
        parser.add_argument(
            "--jsonl",
            action="store_true",
            help="emit the session as JSONL on stdout (pipe to a file to save it)",
        )

        args = parser.parse_args(argv)
        instance = cls(**vars(args))

        piped = read_piped_stdin()
        if piped:
            instance.prompt = f"{instance.prompt}\n\n{piped}"

        return instance


def run_agent(
    args: Arguments,
    client: OpenAICompatibleClient,
    tools: list[dict],
) -> bool:
    """Run the agent loop; return False on any error so callers exit non-zero."""
    iteration_count = 0
    messages = [{"role": "user", "content": args.prompt}]

    def emit(event_type: str, **fields) -> None:
        """Print one JSONL event to stdout, a no-op unless --jsonl is set."""
        if args.jsonl:
            print(json.dumps({"type": event_type, **fields}), flush=True)

    tools_by_name = {tool["name"]: tool for tool in tools}
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

    emit("user", message=messages[0])

    while iteration_count < args.max_iterations:
        iteration_count += 1

        response = client.chat_completions(
            args.model,
            messages,
            tool_schemas,
            args.max_completion_tokens,
        )

        if not response:
            logger.error("failed to get response")
            return False

        emit("completion", response=response)

        try:
            message = response["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as e:
            logger.error("%s, response: %s", e, json.dumps(response))
            return False

        reasoning = message.get("reasoning_content") or message.get("reasoning")
        if reasoning:
            logger.info("reasoning:\n%s", reasoning)

        if message.get("content"):
            logger.info("%s", message["content"])

        messages.append(message)

        tool_calls = message.get("tool_calls")
        if not tool_calls:
            return True

        for tool_call in tool_calls:
            tool_result = execute_tool_call(tool_call, tools_by_name)
            messages.append(tool_result)
            emit("tool_result", message=tool_result)

    logger.error("reached max iterations (%s)", args.max_iterations)
    return False


# os.path.expandvars lacks ${VAR:-default}, so roll our own to match the
# mcp.json convention (Claude Code, Cursor, VS Code).
_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def expand_env_vars(value: str) -> str:
    """Expand ${VAR} / ${VAR:-default}; unset without default → empty string."""

    def replace(match: re.Match) -> str:
        name, default = match.group(1), match.group(2)
        env_value = os.environ.get(name)
        if env_value is not None:
            return env_value
        if default is not None:
            return default
        logger.warning("env var %s referenced in mcp.json is unset", name)
        return ""

    return _ENV_VAR_RE.sub(replace, value)


def load_mcp_clients_from_config(
    transport: HttpTransport,
) -> list[HttpMCPClient]:
    file_name = "mcp.json"
    try:
        with open(file_name) as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.warning("mcp.json not found, add it or remove the --mcp flag")
        return []
    except json.JSONDecodeError as e:
        logger.error("malformed %s: %s", file_name, e)
        return []
    except Exception as e:
        logger.error("unexpected error while loading %s: %s", file_name, e)
        return []

    clients = []
    for server in data.get("mcpServers", {}).values():
        url = expand_env_vars(server["url"])
        headers = server.get("headers")
        if headers is not None:
            headers = {k: expand_env_vars(v) for k, v in headers.items()}
        clients.append(HttpMCPClient(url, transport, headers))
    return clients


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    content: str

    @classmethod
    def from_text(cls, content: str, default_name: str) -> "Skill":
        """Build a skill, reading name/description from optional YAML frontmatter."""
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

        return cls(name=name, description=description, content=content)


def load_skills_from_directory(directory: str = ".agents/skills") -> list[Skill]:
    """Discover skills stored as <directory>/<name>/SKILL.md."""
    skills = []
    for skill_file in sorted(Path(directory).glob("*/SKILL.md")):
        try:
            content = skill_file.read_text()
        except OSError as e:
            logger.error("cannot read %s: %s", skill_file, e)
            continue

        skills.append(Skill.from_text(content, default_name=skill_file.parent.name))

    return skills


def make_skill_tool(skills: list[Skill]) -> dict:
    """Expose discovered skills as a single tool that loads a skill into context."""
    by_name = {skill.name: skill for skill in skills}
    available = "\n".join(f"- {s.name}: {s.description}" for s in skills)

    def execute(args: dict) -> str:
        name = args.get("name")
        if name is None:
            return "error: no skill name provided"
        skill = by_name.get(name)
        if skill is None:
            return f"error: unknown skill '{name}'"
        return skill.content

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
        sys.exit(1)

    transport = HttpTransport(
        request_max_attempts=config.request_max_attempts,
        request_base_delay=config.request_base_delay,
        timeout=config.http_timeout,
    )

    tools = []

    if arguments.bash:
        tools.append(make_bash_tool(config.bash_timeout))

    mcp_clients = load_mcp_clients_from_config(transport) if arguments.mcp else []
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
                    "execute": functools.partial(mcp_client.call_tool, name),
                }
            )

    if arguments.skills:
        skills = load_skills_from_directory()
        if skills:
            tools.append(make_skill_tool(skills))

    client = OpenAICompatibleClient(
        config.openai_base_url, transport, config.openai_api_key
    )

    succeeded = run_agent(
        arguments,
        client,
        tools,
    )
    if not succeeded:
        sys.exit(1)


if __name__ == "__main__":
    main()
