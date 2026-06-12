# ijon

Zero dependency AI harness with bash tool written in Python. Sessions are stored in `~/.ijon/sessions` as JSONL files.

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
usage: ijon [-h] --model MODEL [--max-iterations MAX_ITERATIONS] prompt

Zero dependency AI harness with bash tool

positional arguments:
prompt

options:
-h, --help show this help message and exit
--model MODEL
--max-iterations MAX_ITERATIONS

```

## Configure

Set via environment variables (not auto-loaded from `.env`):

- `OPENAI_BASE_URL` (required)
- `OPENAI_API_KEY`
- `IJON_CONFIG_DIR` (default `~/.ijon`)
- `IJON_BASH_TIMEOUT` (default `120`)
