# ijon

Zero dependency AI harness with bash tool written in Python. Pass `--jsonl` to stream the session as JSONL on stdout; pipe it to a file if you want to keep it.

This is a learning project should not be used for production work. Tested with OpenRouter API.

## Install

Run without installing:

```bash
uvx --from git+https://github.com/michalczmiel/ijon ijon "your prompt" --model <model>
```

Persistent install (puts `ijon` on PATH via `~/.local/bin`):

```bash
uv tool install git+https://github.com/michalczmiel/ijon
```

## Usage

```bash
usage: ijon [-h] --model MODEL [--max-iterations MAX_ITERATIONS] [--jsonl] prompt

Zero dependency AI harness with bash tool

positional arguments:
prompt

options:
-h, --help show this help message and exit
--model MODEL
--max-iterations MAX_ITERATIONS
--jsonl                emit the session as JSONL on stdout (pipe to a file to save it)

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
