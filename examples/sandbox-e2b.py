import json
import os

from e2b import Sandbox

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")

if not OPENAI_API_KEY or not OPENAI_BASE_URL:
    raise ValueError("OPENAI_API_KEY and OPENAI_BASE_URL must be set")

IJON_URL = "https://raw.githubusercontent.com/michalczmiel/ijon/main/ijon.py"

MCP_CONFIG = {
    "mcpServers": {
        "exa": {
            "url": "https://mcp.exa.ai/mcp",
        }
    }
}

sandbox = Sandbox.create(
    envs={
        "OPENAI_API_KEY": OPENAI_API_KEY,
        "OPENAI_BASE_URL": OPENAI_BASE_URL,
    }
)

REPORT_FILE = "report.md"

try:
    sandbox.commands.run(f"curl -fsSL -o ijon.py {IJON_URL}")
    sandbox.files.write("mcp.json", json.dumps(MCP_CONFIG))

    handle = sandbox.commands.run(
        f'python ijon.py "Search the web for LLM harnesses trends in 2026, then write a markdown report of the top 3 findings to {REPORT_FILE}" --model "anthropic/claude-sonnet-4.6" --bash --mcp',
        background=True,
        # no timeout, the agent decides when it's done
        timeout=0,
    )

    handle.wait(on_stderr=lambda line: print(line, end=""))

    print(sandbox.files.read(REPORT_FILE))
finally:
    sandbox.kill()
