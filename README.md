# ijon

A single-file zero-dependency agent harness in Python 3.9+.

- No sessions, no history
- Built-in bash tool, HTTP MCP, and skills
- Built-in retries on 429/5xx and timeouts with exponential backoff

A learning project, not for production. Tested with the OpenRouter API.

## Install

It's one file with no dependencies, so grab it and run it:

```bash
curl -fsSL https://raw.githubusercontent.com/michalczmiel/ijon/main/ijon.py -o ijon.py
python3 ijon.py "your prompt" --model <model>
```

Put it on your `PATH` to call it as `ijon`:

```bash
curl -fsSL https://raw.githubusercontent.com/michalczmiel/ijon/main/ijon.py -o ~/.local/bin/ijon
chmod +x ~/.local/bin/ijon
ijon "your prompt" --model <model>
```

Or, if you have [uv](https://docs.astral.sh/uv/), skip the download:

```bash
uvx --from git+https://github.com/michalczmiel/ijon ijon "your prompt" --model <model>
```

## Usage

| Option                      | Description                                     | Default  |
| --------------------------- | ----------------------------------------------- | -------- |
| `--model MODEL`             | Model id to use                                 | required |
| `--bash`                    | Enable the bash tool                            | off      |
| `--mcp`                     | Enable MCP tools from `mcp.json`                | off      |
| `--skills`                  | Enable skills from `.agents/skills`             | off      |
| `--max-iterations N`        | Max agent loop iterations                       | `10`     |
| `--max-completion-tokens N` | Cap output tokens per response, incl. reasoning | unset    |
| `--jsonl`                   | Emit the session as JSONL on stdout             | off      |

Let the model run shell commands:

```bash
ijon "explain what is this project" --model <model> --bash
```

Pipe stdin in and it's appended to the prompt:

```bash
cat file.py | ijon "explain this" --model <model>
```

With `--jsonl`, stdout is pure JSONL (logs go to stderr), so redirecting saves a clean session:

```bash
ijon "your prompt" --model <model> --jsonl > session.jsonl
```

## Configure

Set via environment variables (not auto-loaded from `.env`):

| Variable                | Description                                      | Default  |
| ----------------------- | ------------------------------------------------ | -------- |
| `OPENAI_BASE_URL`       | API base URL                                     | required |
| `OPENAI_API_KEY`        | Bearer token; header omitted if unset            | —        |
| `IJON_BASH_TIMEOUT`     | Bash tool timeout, seconds                       | `120`    |
| `IJON_MAX_ATTEMPTS`     | HTTP attempts, retrying 429/5xx and timeouts     | `3`      |
| `IJON_RETRY_BASE_DELAY` | Seconds before first retry, doubles each attempt | `1.0`    |
| `IJON_HTTP_TIMEOUT`     | HTTP timeout, seconds; retried on timeout        | `120`    |

## MCP

Drop a `mcp.json` next to where you run `ijon` and pass `--mcp` to enable it. Each server's tools are discovered over HTTP and exposed to the model:

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

`headers` is optional; values in `url` and `headers` expand `${VAR}` / `${VAR:-default}` from the environment, keeping secrets out of the file. HTTP transport only, static-token auth only (no OAuth); stateful and stateless servers both work.

## Skills

Pass `--skills` to load skills from `.agents/skills` next to where you run `ijon`. Each skill is a `<name>/SKILL.md` file; they're exposed to the model as a single `skill` tool it can call to pull a skill's instructions into context on demand.
