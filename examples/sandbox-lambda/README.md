# sandbox-lambda

Runs [ijon](https://github.com/michalczmiel/ijon) inside a Lambda, with the bash tool
sandboxed by the function's own execution environment. Every JSONL event of a session is
written to DynamoDB.

`ijon.py` is not part of this project: `scripts/fetch-ijon.sh` curls it from GitHub into
`src/agent-runner/` before each synth, the same way `sandbox-e2b.py` pulls it into the
sandbox. Override the source with `IJON_URL`.

## Session table

| key | value                                                 |
| --- | ----------------------------------------------------- |
| PK  | session uuid, minted per invocation                   |
| SK  | `2026-07-14T19:21:34.197691Z`, when the event arrived |

The sort key is always UTC and always fixed width — microseconds padded to six digits, `Z`
rather than `+00:00`. DynamoDB sorts it as a string, so anything that varies the width or
the offset would sort out of event order.

The function can only write to the table, never read it — the CDK test enforces that.

## Run it locally

Needs Docker, the AWS SAM CLI and the AWS CLI.

```sh
pnpm install
cp env.local.example.json env.local.json   # then put your OPENAI_API_KEY in it
docker compose up -d                       # DynamoDB Local on :8000
pnpm db:create                             # CDK does not create the local table
pnpm local:invoke                          # fetches ijon.py, synths, invokes
```

`local:invoke` sends `event.local.json` as the request body (`prompt` and `model`), and
joins the function container to the compose network so `AWS_ENDPOINT_URL_DYNAMODB` can
address DynamoDB Local as `http://dynamodb:8000`.

List what is stored, one row per event:

```sh
pnpm db:scan
```

Read events back, `event` holding the raw JSONL line:

```sh
pnpm db:query --session <uuid>                        # one session, in order
pnpm db:query --session <uuid> --timestamp 2026-07-14 # that session, from a point in time
pnpm db:query --timestamp 2026-07-14T19:21            # all sessions, from a point in time
```

`--timestamp` is an ISO-8601 prefix. With a session it narrows the sort key, without one
it falls back to a scan, since the partition key is what makes the read cheap.

## Useful commands

- `pnpm test` run the CDK unit tests
- `pnpm build` typecheck
- `pnpm fetch:ijon` vendor `ijon.py` (run before `pnpm cdk deploy`)
- `pnpm cdk deploy` deploy the stack. `OPENAI_BASE_URL` / `OPENAI_API_KEY` are read from
  your shell at synth time and land in the template as plain function env vars — fine for
  a sandbox, swap them for a Secrets Manager lookup before it is anything more
