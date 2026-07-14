# sandbox-lambda

Runs [ijon](https://github.com/michalczmiel/ijon) inside a Lambda, with the bash tool
sandboxed by the function's own execution environment. Every JSONL event of a session is
written to DynamoDB.

`ijon.py` is not part of this project: `scripts/fetch-ijon.sh` curls it from GitHub into
`src/agent-runner/` before each synth, the same way `sandbox-e2b.py` pulls it into the
sandbox. Override the source with `IJON_URL`.

## Session table

| key | value                               |
| --- | ----------------------------------- |
| PK  | session uuid, minted per invocation |
| SK  | ISO-8601 timestamp of the event     |

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

Read a session back:

```sh
aws dynamodb query --endpoint-url http://localhost:8000 \
  --table-name AgentSession \
  --key-condition-expression 'PK = :pk' \
  --expression-attribute-values '{":pk": {"S": "<session-id>"}}'
```

## Useful commands

- `pnpm test` run the CDK unit tests
- `pnpm build` typecheck
- `pnpm fetch:ijon` vendor `ijon.py` (run before `pnpm cdk deploy`)
- `pnpm cdk deploy` deploy the stack. `OPENAI_BASE_URL` / `OPENAI_API_KEY` are read from
  your shell at synth time and land in the template as plain function env vars — fine for
  a sandbox, swap them for a Secrets Manager lookup before it is anything more
