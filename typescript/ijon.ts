#!/usr/bin/env node
// Runs directly on Node 22.18+ / 24+ via built-in type stripping: `node ijon.ts ...`
import { spawn } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { parseArgs } from "node:util";

// Mirrors python's logging with the "%(message)s" format: bare messages on stderr.
const log = (message: string): void => {
  process.stderr.write(`${message}\n`);
};
const logger = { info: log, warning: log, error: log };

const sleep = (seconds: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, seconds * 1000));

const errorMessage = (e: unknown): string =>
  e instanceof Error ? e.message : String(e);

// biome-ignore lint/suspicious/noExplicitAny: mirrors python's dict[str, Any]; JSON payloads are indexed freely
type Json = Record<string, any>;

type Tool = {
  name: string;
  description: string;
  parameters: Json;
  execute: (args: Json) => unknown | Promise<unknown>;
};

/**
 * Makes HTTP requests, retrying 429/5xx and timeouts with exponential backoff.
 *
 * The timeout is a stall timeout, not a total deadline: it restarts at each phase
 * (connecting and waiting for headers, then every body chunk), so a slow but
 * progressing response is not cut off.
 */
class HttpTransport {
  #request_max_attempts: number;
  #request_base_delay: number; // seconds; doubles each attempt
  #timeout: number; // seconds per phase

  constructor(fields: {
    request_max_attempts: number;
    request_base_delay: number;
    timeout: number;
  }) {
    this.#request_max_attempts = fields.request_max_attempts;
    this.#request_base_delay = fields.request_base_delay;
    this.#timeout = fields.timeout;
  }

  /** Sleep with backoff before retrying; return false when attempts exhausted so caller gives up. */
  async #retry(attempt: number, reason: string): Promise<boolean> {
    if (attempt === this.#request_max_attempts) {
      logger.error(
        `giving up after ${this.#request_max_attempts} attempts: ${reason}`,
      );
      return false;
    }
    const delay = this.#request_base_delay * 2 ** (attempt - 1);
    logger.warning(
      `${reason}, retrying in ${delay.toFixed(1)}s (attempt ${attempt}/${this.#request_max_attempts})`,
    );
    await sleep(delay);
    return true;
  }

  /** POST and read the whole body, re-arming the stall timer on every chunk. */
  async #fetch(
    url: string,
    headers: Record<string, string>,
    body: string,
  ): Promise<[Response, string]> {
    const controller = new AbortController();
    const abort = (): void =>
      controller.abort(new DOMException("stalled", "TimeoutError"));
    let timer = setTimeout(abort, this.#timeout * 1000);
    try {
      const response = await fetch(url, {
        method: "POST",
        headers,
        body,
        signal: controller.signal,
      });
      const decoder = new TextDecoder();
      let data = "";
      for await (const chunk of response.body ?? []) {
        clearTimeout(timer);
        timer = setTimeout(abort, this.#timeout * 1000);
        data += decoder.decode(chunk, { stream: true });
      }
      return [response, data + decoder.decode()];
    } finally {
      clearTimeout(timer);
    }
  }

  async request(
    url: string,
    headers: Record<string, string>,
    body: Json,
  ): Promise<[string, Headers] | null> {
    const body_bytes = JSON.stringify(body);

    for (let attempt = 1; attempt <= this.#request_max_attempts; attempt++) {
      try {
        const [response, data] = await this.#fetch(url, headers, body_bytes);
        if (response.ok) {
          return [data, response.headers];
        }
        if (response.status === 429 || response.status >= 500) {
          if (
            await this.#retry(
              attempt,
              `request failed (HTTP ${response.status} ${response.statusText})`,
            )
          ) {
            continue;
          }
          return null;
        }
        logger.error(`HTTP ${response.status} ${response.statusText}: ${data}`);
        if (response.status === 401) {
          // MCP's OAuth flow starts here, but ijon only does static-token auth.
          const challenge = response.headers.get("WWW-Authenticate");
          logger.error(
            `401 unauthorized for ${url}: ijon only supports static tokens ` +
              `(set them in mcp.json headers). WWW-Authenticate: ${challenge || "<none>"}`,
          );
        }
        return null;
      } catch (e) {
        if ((e as { name?: string })?.name === "TimeoutError") {
          if (
            await this.#retry(
              attempt,
              `request timed out after ${this.#timeout}s`,
            )
          ) {
            continue;
          }
          return null;
        }
        if (e instanceof TypeError && e.cause !== undefined) {
          logger.error(`cannot connect to ${url}: ${errorMessage(e.cause)}`);
          return null;
        }
        logger.error(errorMessage(e));
        return null;
      }
    }
    return null;
  }
}

class OpenAICompatibleClient {
  #base_url: string;
  #transport: HttpTransport;
  #api_key: string | null;

  constructor(
    base_url: string,
    transport: HttpTransport,
    api_key: string | null = null,
  ) {
    this.#base_url = base_url;
    this.#transport = transport;
    this.#api_key = api_key;
  }

  async chat_completions(
    model: string,
    messages: Json[],
    tools: Json[] | null = null,
    max_completion_tokens: number | null = null,
  ): Promise<Json | null> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (this.#api_key) {
      headers["Authorization"] = `Bearer ${this.#api_key}`;
    }

    const body: Json = { model, messages };
    if (tools && tools.length > 0) {
      body["tools"] = tools;
    }
    if (max_completion_tokens !== null) {
      body["max_completion_tokens"] = max_completion_tokens;
    }

    const response = await this.#transport.request(
      `${this.#base_url}/v1/chat/completions`,
      headers,
      body,
    );
    if (response === null) {
      return null;
    }
    const [data] = response;
    try {
      return JSON.parse(data);
    } catch {
      logger.error(`non-JSON response body: ${data.slice(0, 200)}`);
      return null;
    }
  }
}

function _env_int(name: string, fallback: number): number {
  const raw = process.env[name];
  if (raw === undefined) {
    return fallback;
  }
  if (!/^\s*[+-]?\d+\s*$/.test(raw)) {
    throw new Error(`${name} must be an integer, got ${JSON.stringify(raw)}`);
  }
  return Number.parseInt(raw, 10);
}

function _env_float(name: string, fallback: number): number {
  const raw = process.env[name];
  if (raw === undefined) {
    return fallback;
  }
  const value = Number(raw);
  if (raw.trim() === "" || Number.isNaN(value)) {
    throw new Error(`${name} must be a number, got ${JSON.stringify(raw)}`);
  }
  return value;
}

type Config = {
  openai_base_url: string;
  openai_api_key: string | null;
  bash_timeout: number;
  request_max_attempts: number;
  request_base_delay: number;
  http_timeout: number;
};

const Config = {
  defaults: {
    bash_timeout: 120,
    request_max_attempts: 3,
    request_base_delay: 1.0,
    http_timeout: 120,
  },

  from_env(): Config {
    const defaults = Config.defaults;

    const openai_base_url = process.env["OPENAI_BASE_URL"];
    if (!openai_base_url) {
      throw new Error("OPENAI_BASE_URL not set");
    }

    const openai_api_key = process.env["OPENAI_API_KEY"] ?? null;

    const bash_timeout = _env_int("IJON_BASH_TIMEOUT", defaults.bash_timeout);

    const request_max_attempts = _env_int(
      "IJON_MAX_ATTEMPTS",
      defaults.request_max_attempts,
    );
    if (request_max_attempts < 1) {
      throw new Error(
        `IJON_MAX_ATTEMPTS must be at least 1, got ${request_max_attempts}`,
      );
    }

    const request_base_delay = _env_float(
      "IJON_RETRY_BASE_DELAY",
      defaults.request_base_delay,
    );
    if (request_base_delay < 0) {
      throw new Error(
        `IJON_RETRY_BASE_DELAY must not be negative, got ${request_base_delay}`,
      );
    }

    const http_timeout = _env_int("IJON_HTTP_TIMEOUT", defaults.http_timeout);

    return {
      openai_base_url,
      openai_api_key,
      bash_timeout,
      request_max_attempts,
      request_base_delay,
      http_timeout,
    };
  },
};

class HttpMCPClient {
  #url: string;
  #headers: Record<string, string>;
  #transport: HttpTransport;
  // MCP requires ids to be non-null and unique within a session.
  #ids: number;

  constructor(
    url: string,
    transport: HttpTransport,
    headers: Record<string, string> | null = null,
  ) {
    this.#url = url;
    this.#headers = {
      Accept: "text/event-stream, application/json",
      "Content-Type": "application/json",
      ...(headers ?? {}),
    };
    this.#transport = transport;
    this.#ids = 0;
  }

  #next_id(): number {
    this.#ids += 1;
    return this.#ids;
  }

  async #send(
    method: string,
    params: Json | null = null,
  ): Promise<Json | null> {
    const body: Json = { jsonrpc: "2.0", id: this.#next_id(), method };
    if (params !== null) {
      body["params"] = params;
    }

    const response = await this.#transport.request(
      this.#url,
      this.#headers,
      body,
    );
    if (!response) {
      return null;
    }
    const [data, headers] = response;
    // Session ids are optional: stateful servers issue one on initialize to
    // carry on the session, stateless ones omit it. Only echo it back when present.
    const session_id = headers.get("mcp-session-id");
    if (session_id) {
      this.#headers["mcp-session-id"] = session_id;
    }
    const parsed = this.#parse_response(data);
    if (!parsed) {
      return null;
    }
    const error = parsed["error"];
    if (error !== undefined && error !== null) {
      logger.error(`MCP ${method} failed: ${JSON.stringify(error)}`);
      return { error };
    }
    return parsed["result"] ?? null;
  }

  async connect(): Promise<boolean> {
    const result = await this.#send("initialize", {
      protocolVersion: "2025-11-25",
      capabilities: {},
      clientInfo: { name: "ijon", version: "0.1.0" },
    });
    return result !== null && !("error" in result);
  }

  #parse_response(raw: string): Json | null {
    // try JSON response first, if not fallback to SSE
    try {
      return JSON.parse(raw);
    } catch {
      // not JSON
    }
    for (let line of raw.split("\n")) {
      line = line.trim();
      if (line.startsWith("data:")) {
        try {
          return JSON.parse(line.slice("data:".length));
        } catch {
          logger.error(`non-JSON SSE data: ${line.slice(0, 200)}`);
          return null;
        }
      }
    }
    logger.error(`unparseable MCP response: ${raw.slice(0, 200)}`);
    return null;
  }

  async list_tools(): Promise<Json[]> {
    const result = await this.#send("tools/list");
    return result ? (result["tools"] ?? []) : [];
  }

  async call_tool(name: string, args: Json): Promise<Json | null> {
    return this.#send("tools/call", { name, arguments: args });
  }
}

function execute_bash_script(script: string, timeout: number): Promise<string> {
  return new Promise((resolve, reject) => {
    // detached groups the shell and its children so a timeout can kill the whole group, not just the shell.
    // shell: true alone would run /bin/sh (dash on Debian); the tool promises bash.
    const child = spawn(script, {
      shell: "/bin/bash",
      stdio: ["inherit", "pipe", "pipe"],
      detached: true,
    });

    let stdout = "";
    let stderr = "";
    let timed_out = false;
    child.stdout.setEncoding("utf-8");
    child.stderr.setEncoding("utf-8");
    child.stdout.on("data", (chunk: string) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk: string) => {
      stderr += chunk;
    });

    const timer = setTimeout(() => {
      timed_out = true;
      // shell is its own group leader (detached), so pid == group id;
      // ESRCH means the group already drained. pid is only unset when spawn
      // itself failed, and the "error" handler clears this timer in that case.
      try {
        if (child.pid !== undefined) {
          process.kill(-child.pid, "SIGKILL");
        }
      } catch (e) {
        if ((e as NodeJS.ErrnoException).code !== "ESRCH") {
          reject(e);
        }
      }
    }, timeout * 1000);

    child.on("error", (e) => {
      clearTimeout(timer);
      reject(e);
    });
    child.on("close", (code, signal) => {
      clearTimeout(timer);
      if (timed_out) {
        resolve(`error: Bash script timed out after ${timeout} seconds`);
        return;
      }
      // exactly one of code/signal is set; python reports a signal death as
      // the negated signal number
      const exit_code = signal === null ? code : -os.constants.signals[signal];
      const parts = [`exit_code: ${exit_code}`];
      if (stdout) {
        parts.push(`stdout:\n${stdout}`);
      }
      if (stderr) {
        parts.push(`stderr:\n${stderr}`);
      }
      resolve(parts.join("\n"));
    });
  });
}

function make_bash_tool(timeout: number): Tool {
  return {
    name: "execute_bash_script",
    description: "Execute a bash script and return the output",
    parameters: {
      type: "object",
      properties: {
        script: {
          type: "string",
          description: "The bash script to execute",
        },
      },
      required: ["script"],
    },
    execute: (args) => execute_bash_script(args["script"], timeout),
  };
}

/** Run one tool call, return the `role: tool` message to append. */
async function execute_tool_call(
  tool_call: Json,
  tools: Map<string, Tool>,
): Promise<Json> {
  const reply = (result: unknown): Json => {
    // only serialize objects (MCP); string passes through to avoid double-encoding.
    const content =
      typeof result === "string" ? result : JSON.stringify(result ?? null);
    return {
      role: "tool",
      content,
      tool_call_id: tool_call["id"],
    };
  };

  let tool_args: Json;
  try {
    const raw = tool_call["function"]["arguments"];
    if (typeof raw !== "string") {
      throw new TypeError(`expected string, got ${typeof raw}`);
    }
    tool_args = JSON.parse(raw);
  } catch (e) {
    return reply(`error: invalid tool arguments JSON: ${errorMessage(e)}`);
  }

  const tool_name = tool_call["function"]["name"];
  const tool = tools.get(tool_name);
  if (tool === undefined) {
    return reply(`error: unknown tool '${tool_name}'`);
  }

  logger.info(
    `executing tool: ${tool_name} with args ${JSON.stringify(tool_args)}`,
  );
  try {
    return reply(await tool.execute(tool_args));
  } catch (e) {
    logger.error(`tool ${tool_name} failed: ${errorMessage(e)}`);
    return reply(`error: ${errorMessage(e)}`);
  }
}

/** Return stdin's content when piped/redirected, else an empty string */
function read_piped_stdin(): string {
  if (process.stdin.isTTY) {
    return "";
  }
  try {
    return fs.readFileSync(0, "utf-8").trim();
  } catch {
    return "";
  }
}

// One table drives parseArgs, the usage line and --help, so they cannot drift.
const OPTIONS = {
  help: {
    type: "boolean",
    short: "h",
    help: "show this help message and exit",
  },
  model: { type: "string", required: true },
  bash: { type: "boolean", help: "enable the bash tool" },
  mcp: {
    type: "boolean",
    help: "enable MCP tools from mcp.json in the current directory",
  },
  skills: {
    type: "boolean",
    help: "enable skills loaded from .agents/skills in the current directory",
  },
  "max-iterations": { type: "string", default: "10" },
  "max-completion-tokens": {
    type: "string",
    help: "cap output tokens (incl. reasoning)",
  },
  jsonl: {
    type: "boolean",
    help: "emit the session as JSONL on stdout (pipe to a file to save it)",
  },
} as const;

// argparse-style rendering: `--model MODEL`, `[--bash]`, `[--max-iterations MAX_ITERATIONS]`
const option_flag = (name: string, type: string): string =>
  type === "string"
    ? `--${name} ${name.toUpperCase().replaceAll("-", "_")}`
    : `--${name}`;

const USAGE =
  "usage: ijon " +
  Object.entries(OPTIONS)
    .map(([name, option]) => {
      const flag = name === "help" ? "-h" : option_flag(name, option.type);
      return "required" in option ? flag : `[${flag}]`;
    })
    .join(" ") +
  " prompt";

const HELP = `${USAGE}

Single-file zero-dependency AI harness

positional arguments:
  prompt

options:
${Object.entries(OPTIONS)
  .map(([name, option]) => {
    const flag =
      name === "help" ? "-h, --help" : option_flag(name, option.type);
    if (!("help" in option)) {
      return `  ${flag}`;
    }
    // argparse puts the help on the same line when the flag fits in 22 columns
    return flag.length <= 20
      ? `  ${flag.padEnd(22)}${option.help}`
      : `  ${flag}\n${" ".repeat(24)}${option.help}`;
  })
  .join("\n")}
`;

type Arguments = {
  prompt: string;
  model: string;
  max_iterations: number;
  max_completion_tokens: number | null;
  jsonl: boolean;
  bash: boolean;
  mcp: boolean;
  skills: boolean;
};

const Arguments = {
  from_args(argv: string[] = process.argv.slice(2)): Arguments {
    // argparse-style: usage + error on stderr, exit status 2
    const fail = (message: string): never => {
      process.stderr.write(`${USAGE}\nijon: error: ${message}\n`);
      process.exit(2);
    };
    const int = (option: string, raw: string): number => {
      if (!/^[+-]?\d+$/.test(raw)) {
        fail(`argument ${option}: invalid int value: '${raw}'`);
      }
      return Number.parseInt(raw, 10);
    };

    let values: Record<string, string | boolean | undefined>;
    let positionals: string[];
    try {
      ({ values, positionals } = parseArgs({
        args: argv,
        allowPositionals: true,
        options: OPTIONS,
      }));
    } catch (e) {
      return fail(errorMessage(e));
    }

    if (values["help"]) {
      process.stdout.write(HELP);
      process.exit(0);
    }
    if (positionals.length === 0) {
      fail("the following arguments are required: prompt");
    }
    if (positionals.length > 1) {
      fail(`unrecognized arguments: ${positionals.slice(1).join(" ")}`);
    }
    if (values["model"] === undefined) {
      fail("the following arguments are required: --model");
    }

    const max_completion_tokens = values["max-completion-tokens"];
    const instance: Arguments = {
      prompt: positionals[0],
      model: values["model"] as string,
      max_iterations: int(
        "--max-iterations",
        values["max-iterations"] as string,
      ),
      max_completion_tokens:
        max_completion_tokens === undefined
          ? null
          : int("--max-completion-tokens", max_completion_tokens as string),
      jsonl: (values["jsonl"] as boolean | undefined) ?? false,
      bash: (values["bash"] as boolean | undefined) ?? false,
      mcp: (values["mcp"] as boolean | undefined) ?? false,
      skills: (values["skills"] as boolean | undefined) ?? false,
    };

    const piped = read_piped_stdin();
    if (piped) {
      instance.prompt = `${instance.prompt}\n\n${piped}`;
    }

    return instance;
  },
};

/** Run the agent loop; return false on any error so callers exit non-zero. */
async function run_agent(
  args: Arguments,
  client: OpenAICompatibleClient,
  tools: Tool[],
): Promise<boolean> {
  let iteration_count = 0;
  const messages: Json[] = [{ role: "user", content: args.prompt }];

  /** Print one JSONL event to stdout, a no-op unless --jsonl is set. */
  const emit = (event_type: string, fields: Json): void => {
    if (args.jsonl) {
      process.stdout.write(
        `${JSON.stringify({ type: event_type, ...fields })}\n`,
      );
    }
  };

  const tools_by_name = new Map(tools.map((tool) => [tool.name, tool]));
  const tool_schemas = tools.map((tool) => ({
    type: "function",
    function: {
      name: tool.name,
      description: tool.description,
      parameters: tool.parameters,
    },
  }));

  emit("user", { message: messages[0] });

  while (iteration_count < args.max_iterations) {
    iteration_count += 1;

    const response = await client.chat_completions(
      args.model,
      messages,
      tool_schemas,
      args.max_completion_tokens,
    );

    if (!response) {
      logger.error("failed to get response");
      return false;
    }

    emit("completion", { response });

    const message = response["choices"]?.[0]?.["message"];
    if (
      message === undefined ||
      message === null ||
      typeof message !== "object"
    ) {
      logger.error(
        `missing choices[0].message, response: ${JSON.stringify(response)}`,
      );
      return false;
    }

    const reasoning = message["reasoning_content"] || message["reasoning"];
    if (reasoning) {
      logger.info(`reasoning:\n${reasoning}`);
    }

    if (message["content"]) {
      logger.info(`${message["content"]}`);
    }

    messages.push(message);

    const tool_calls = message["tool_calls"];
    if (!tool_calls || tool_calls.length === 0) {
      return true;
    }

    for (const tool_call of tool_calls) {
      const tool_result = await execute_tool_call(tool_call, tools_by_name);
      messages.push(tool_result);
      emit("tool_result", { message: tool_result });
    }
  }

  logger.error(`reached max iterations (${args.max_iterations})`);
  return false;
}

// Matches the mcp.json convention (Claude Code, Cursor, VS Code): ${VAR} / ${VAR:-default}.
const _ENV_VAR_RE = /\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}/g;

/** Expand ${VAR} / ${VAR:-default}; unset without default → empty string. */
function expand_env_vars(value: string): string {
  return value.replace(
    _ENV_VAR_RE,
    (_match: string, name: string, fallback: string | undefined): string => {
      const env_value = process.env[name];
      if (env_value !== undefined) {
        return env_value;
      }
      if (fallback !== undefined) {
        return fallback;
      }
      logger.warning(`env var ${name} referenced in mcp.json is unset`);
      return "";
    },
  );
}

function load_mcp_clients_from_config(
  transport: HttpTransport,
): HttpMCPClient[] {
  const file_name = "mcp.json";
  let data: Json;
  try {
    data = JSON.parse(fs.readFileSync(file_name, "utf-8"));
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") {
      logger.warning("mcp.json not found, add it or remove the --mcp flag");
      return [];
    }
    if (e instanceof SyntaxError) {
      logger.error(`malformed ${file_name}: ${e.message}`);
      return [];
    }
    logger.error(
      `unexpected error while loading ${file_name}: ${errorMessage(e)}`,
    );
    return [];
  }

  const clients: HttpMCPClient[] = [];
  for (const [name, server] of Object.entries<Json>(data["mcpServers"] ?? {})) {
    if (!("url" in server)) {
      logger.error(`mcp server '${name}' missing required 'url', skipping`);
      continue;
    }
    const url = expand_env_vars(server["url"]);
    let headers: Record<string, string> | null = server["headers"] ?? null;
    if (headers !== null) {
      headers = Object.fromEntries(
        Object.entries(headers).map(([k, v]) => [k, expand_env_vars(v)]),
      );
    }
    clients.push(new HttpMCPClient(url, transport, headers));
  }
  return clients;
}

type Skill = {
  readonly name: string;
  readonly description: string;
  readonly content: string;
};

const Skill = {
  /** Build a skill, reading name/description from optional YAML frontmatter. */
  from_text(content: string, default_name: string): Skill {
    let name = default_name;
    let description = "";
    let body = content;

    if (content.startsWith("---")) {
      const end = content.indexOf("\n---", 3);
      if (end !== -1) {
        const frontmatter = content.slice(3, end);
        body = content.slice(end + 4);
        for (const line of frontmatter.split(/\r?\n/)) {
          const separator = line.indexOf(":");
          if (separator === -1) {
            continue;
          }
          const key = line.slice(0, separator).trim().toLowerCase();
          const value = line.slice(separator + 1).trim();
          if (key === "name" && value) {
            name = value;
          } else if (key === "description" && value) {
            description = value;
          }
        }
      }
    }

    if (!description) {
      for (let line of body.split(/\r?\n/)) {
        line = line.trim().replace(/^#+/, "").trim();
        if (line) {
          description = line;
          break;
        }
      }
    }

    return { name, description, content };
  },
};

/** Discover skills stored as <directory>/<name>/SKILL.md. */
function load_skills_from_directory(
  directory: string = ".agents/skills",
): Skill[] {
  const skills: Skill[] = [];
  let entries: string[];
  try {
    entries = fs.readdirSync(directory);
  } catch {
    return skills;
  }
  for (const entry of entries.sort()) {
    const skill_file = path.join(directory, entry, "SKILL.md");
    let content: string;
    try {
      content = fs.readFileSync(skill_file, "utf-8");
    } catch (e) {
      const code = (e as NodeJS.ErrnoException).code;
      if (code === "ENOENT" || code === "ENOTDIR") {
        continue;
      }
      logger.error(`cannot read ${skill_file}: ${errorMessage(e)}`);
      continue;
    }

    skills.push(Skill.from_text(content, entry));
  }

  return skills;
}

/** Expose discovered skills as a single tool that loads a skill into context. */
function make_skill_tool(skills: Skill[]): Tool {
  const by_name = new Map(skills.map((skill) => [skill.name, skill]));
  const available = skills
    .map((s) => `- ${s.name}: ${s.description}`)
    .join("\n");

  const execute = (args: Json): string => {
    const name = args["name"];
    if (name === undefined || name === null) {
      return "error: no skill name provided";
    }
    const skill = by_name.get(name);
    if (skill === undefined) {
      return `error: unknown skill '${name}'`;
    }
    return skill.content;
  };

  return {
    name: "skill",
    description:
      "Load a skill's instructions into context. Available skills:\n" +
      available,
    parameters: {
      type: "object",
      properties: {
        name: {
          type: "string",
          enum: [...by_name.keys()],
          description: "The name of the skill to load",
        },
      },
      required: ["name"],
    },
    execute,
  };
}

async function main(): Promise<void> {
  const cli_args = Arguments.from_args();

  let config: Config;
  try {
    config = Config.from_env();
  } catch (e) {
    logger.error(errorMessage(e));
    process.exitCode = 1;
    return;
  }

  const transport = new HttpTransport({
    request_max_attempts: config.request_max_attempts,
    request_base_delay: config.request_base_delay,
    timeout: config.http_timeout,
  });

  const tools: Tool[] = [];

  if (cli_args.bash) {
    tools.push(make_bash_tool(config.bash_timeout));
  }

  const mcp_clients = cli_args.mcp
    ? load_mcp_clients_from_config(transport)
    : [];
  for (const mcp_client of mcp_clients) {
    const connected = await mcp_client.connect();
    if (!connected) {
      continue;
    }
    const mcp_tools = await mcp_client.list_tools();

    for (const mcp_tool of mcp_tools) {
      const name = mcp_tool["name"];
      tools.push({
        name,
        description: mcp_tool["description"],
        parameters: mcp_tool["inputSchema"],
        execute: (args) => mcp_client.call_tool(name, args),
      });
    }
  }

  if (cli_args.skills) {
    const skills = load_skills_from_directory();
    if (skills.length > 0) {
      tools.push(make_skill_tool(skills));
    }
  }

  const client = new OpenAICompatibleClient(
    config.openai_base_url,
    transport,
    config.openai_api_key,
  );

  const succeeded = await run_agent(cli_args, client, tools);
  if (!succeeded) {
    process.exitCode = 1;
  }
}

if (import.meta.main) {
  await main();
}
