# Players

How each model is run as a general. All players sit behind one interface in
`src/kriegsspiel/players.py` (`Player.act(system, prompt) -> Reply`); a general in a game runs
through `commander.HarnessSession`, one persistent conversation per general per game.

| model | route | roster name |
|---|---|---|
| Claude Opus 5.5, Claude Fable 5.1, Claude Sonnet 5.5 | Claude Code, `claude -p` | `opus`, `fable`, `sonnet` |
| GPT-6 Astra, GPT-6 Sol, GPT-6 Luna | Codex CLI, `codex exec` | `astra`, `sol`, `luna` |
| DeepSeek V4.1 Flash | DeepSeek's OpenAI-compatible chat API | `deepseek` |

To add a model, add an entry to `players.ROSTER`.

## The requirement

Every player receives the same system text and the same prompt bytes, with no tools, no
instruction files, no hooks and no memory beyond the game's own conversation. Anything a harness
adds on its own is a measured asymmetry, listed below.

## Claude Code

```
claude -p --model <model> --effort high --tools "" --strict-mcp-config \
  --setting-sources "" --system-prompt <system> --output-format json \
  (--session-id <uuid> | --resume <uuid>) <prompt>
```

- `--tools ""` removes the built-in tools. `--strict-mcp-config` with no `--mcp-config` starts no
  MCP server; without it the user's MCP servers start and their tool definitions become a
  cached prefix of tens of thousands of tokens on every call.
- `--setting-sources ""` loads no user or project settings, so no `CLAUDE.md` and no hooks.
- `--bare` cannot be used: it skips credential reads and the harness is then not logged in.
- The first turn of a game opens a session with `--session-id`; later turns `--resume` it. Claude
  Code finds its sessions by working directory, so every turn of a game runs in the same jail
  directory.

## Codex CLI

```
codex exec --model <model> --skip-git-repo-check -s read-only -o <out> \
  -c model_reasoning_effort="high" "<system>\n\n---\n\n<prompt>"
codex exec resume <session-id> --model <model> ... <prompt>
```

- Codex has no system-prompt flag, so the system text heads the first message, separated by a
  rule. Codex's own system prompt is not replaceable.
- `codex exec` reads `AGENTS.md` from every ancestor of its working directory and from
  `$CODEX_HOME`, and loads the user's hooks and config from `$CODEX_HOME`.
  `--ignore-user-config` removes the hooks but not the instruction files, and
  `-c project_doc_max_bytes=0` does not stop them either. What works is a clean `CODEX_HOME`
  and an empty working directory outside the home tree.
- The clean `CODEX_HOME` (`.local/codex-home`, or `$GB_CODEX_HOME`) holds only a symlink to the
  real `~/.codex/auth.json`. It must be a link, never a copy: two copies of one login invalidate
  each other's refresh token. Set it up once per machine:

  ```
  mkdir -p .local/codex-home && ln -sfn ~/.codex/auth.json .local/codex-home/auth.json
  ```

- Reasoning effort must be pinned: in a clean `CODEX_HOME` the provider default is no reasoning.
- The first turn's output names the session id; later turns run `codex exec resume <id>`.

## The API route

`ApiPlayer` is a standard-library client for OpenAI-compatible chat completions. DeepSeek runs on
DeepSeek's own API (`DEEPSEEK_BASE_URL`, `DEEPSEEK_API_KEY`, from the environment or
`.local/.env`) with `reasoning_effort` high. The conversation is the message list, resent whole
each turn. The output ceiling is the model's own (393,216 tokens for DeepSeek, the largest the
API accepts); if ceiling plus conversation would overflow the context window, the request is
retried with the room that is left. A grid refuses API players unless `--allow-api` is given,
since they are billed per token.

## Isolation, measured

Both command-line players run in a fresh empty directory under `/tmp` (or `$GB_JAIL_BASE`, which
must lie outside the home directory), removed when the game ends, so no `AGENTS.md` or `CLAUDE.md`
is an ancestor. They get the full environment minus variables that steer a harness (`CLAUDE*`,
`ANTHROPIC*`, `CODEX*`, `OPENAI*`) and `PWD`. A stripped environment is not an option: the shims
behind the binaries hang without it. The players call the resolved binaries, bypassing any shell
wrapper (`$GB_CLAUDE_BIN`, `$GB_CODEX_BIN` override).

The probe: an empty directory holding an `AGENTS.md` and a `CLAUDE.md` with a canary word, the
prompt asking whether the model can see that word, a word that occurs only in the user's own
instruction files, and a phrase injected by a user-level hook. Self-reports turned out to be
unreliable (one run answered yes to all three from a context the token count showed was clean),
so the deciding signals are the harness's token counts and an instruction canary: an `AGENTS.md`
saying "begin every reply with" the canary word.

| command | tokens | canary | reading |
|---|---|---|---|
| `claude -p --setting-sources "" --tools "" --system-prompt S --no-session-persistence`, jail holding a `CLAUDE.md` | 587 system | absent | clean; the system prompt still carries the user's email, cwd, platform and a safety note |
| `codex exec`, plain, jail inside the repository | 15,988 | present | user hooks and the `AGENTS.md` chain load |
| `codex exec --ignore-user-config -c project_doc_max_bytes=0` | 11,276 | present | hooks gone, instruction files still load |
| `codex exec`, clean `CODEX_HOME`, jail inside the repository | 2,867 | (confabulated) | clean by token count |
| `codex exec`, clean `CODEX_HOME`, empty directory under `/tmp` | 2,853 to 2,934 | absent | clean; the reply was the clean answer twice through the module |
| the same with a canary `AGENTS.md` in that directory (positive control) | 2,862 | present | the reply begins with the canary |

Measured with Claude Code 2.1.x and codex-cli 0.15x. A clean `CODEX_HOME` is what removes the
hooks and the instruction chain; the empty directory outside the home tree is the second wall,
against any `AGENTS.md` next to the run. Memory was checked the same way: a code word given in
turn 1 and asked for in turn 2 is recalled under the same session id, and the second turn reads
only the conversation's own tokens from cache.

## Known asymmetries

- Codex's system text is the head of the first user message, not a system prompt.
- `claude -p --system-prompt` replaces Claude Code's prompt, but the harness still appends the
  user's email, working directory, platform, date and a safety note (587 tokens).
- Reasoning effort is pinned high for every player (`ClaudePlayer.effort`,
  `CodexPlayer.reasoning`, `ApiPlayer.reasoning`), since provider defaults differ. There is no
  output-token cap below each model's own.
- Latency for a one-word reply: Opus 8.8 s, Luna 8.5 s, Sol 9.8 s. Latency costs nothing in the
  game, since the battle waits for every reply ([engine](engine.md#the-play-loop)); it is
  logged and reported on its own.

## Prompt caching

Both harnesses cache the conversation prefix themselves. What the game controls is keeping that
prefix stable: system prompt and persona first, briefs appended, nothing edited in place. On the
first seed of the published games:

- `claude -p --resume` (1,229 general calls): 94.5% of all input was read from cache.
- `codex exec resume`: a three-turn probe on a real general's conversation served 11.5k of 25.7k
  input tokens from cache on the first turn (the harness's own prefix), 37k of 53k on the second
  and 64k of 83k on the third, 70 to 77% of a resumed turn. Each turn resends the whole
  conversation, so a late turn of a long game runs well over 100k input tokens.
- The decisions API has no caching; the staff resend the state (about 20k characters) with each
  request.

## Failures

A turn the harness loses (a non-zero exit, a reply flagged as an error, an empty reply under a
rate limit, a timeout, an HTTP error on the API route) is retried up to 12 times with waits
doubling from 15 s to at most 300 s. A general still unreachable after that stops the game
(`GeneralUnreachable`); the grid marks the cell failed and `--resume` runs it again. A lost reply
is never passed to the game as "No orders.".
