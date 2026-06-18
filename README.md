# ijon

A single-file zero-dependency agent harness written in Python.

- Zero runtime dependencies
- Everything lives in `ijon.py`
- No sessions, no history
- Built-in bash tool
- Built-in HTTP MCP support

A learning project, not for production. Tested with the OpenRouter API.

## Install

Run without installing:

```bash
uvx --from git+https://github.com/michalczmiel/ijon ijon "your prompt" --model <model>
```

Or just copy `ijon.py` wherever you want and run it with Python — it's a single file with zero dependencies:

```bash
python ijon.py "your prompt" --model <model>
```

## Usage

```bash
usage: ijon [-h] --model MODEL [--bash] [--max-iterations MAX_ITERATIONS] [--jsonl] prompt
```

| Option               | Description                              |
| -------------------- | ---------------------------------------- |
| `--model MODEL`      | Model id to use (required)               |
| `--bash`             | Enable the bash tool                     |
| `--max-iterations N` | Max agent loop iterations (default `10`) |
| `--jsonl`            | Emit the session as JSONL on stdout      |

Let the model run shell commands:

```bash
ijon "explain what is this project" --model <model> --bash
```

With `--jsonl`, stdout carries only the JSONL session and human-readable logs go to stderr, so this stays a clean save:

```bash
ijon "your prompt" --model <model> --jsonl > session.jsonl
```

## Configure

Set via environment variables (not auto-loaded from `.env`):

- `OPENAI_BASE_URL` (required)
- `OPENAI_API_KEY`
- `IJON_BASH_TIMEOUT` (default `120`)

## MCP

Drop a `.mcp.json` next to where you run `ijon`. Each server's tools are discovered over HTTP and exposed to the model:

```json
{
  "mcpServers": {
    "example": {
      "url": "https://example.com/mcp",
      "headers": { "Authorization": "Bearer <token>" }
    }
  }
}
```

`headers` is optional. Only the HTTP transport is supported.
