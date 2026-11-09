"""Players: anything that turns a prompt into a reply.

The Claude and GPT-6 players run through the vendors' own command-line harnesses, each a
subprocess with no tools, no instruction files, the same system prompt and the same user prompt
bytes; other models go through `ApiPlayer`, an OpenAI-compatible client. `act` is one-shot; a
general in a game runs through `HarnessSession` (`kriegsspiel.commander`), one persistent
session per general per game, briefed in full once and with updates after. Both kinds of call
go through one function per harness: `ClaudePlayer.call` (`claude -p`, optionally under
`--session-id`/`--resume`) and `CodexPlayer.call` (`codex exec`, optionally `codex exec
resume`).

Isolation: ``claude -p --setting-sources "" --tools "" --system-prompt ...`` loads no CLAUDE.md
and no hooks; ``codex exec`` reads AGENTS.md from every ancestor of its cwd and from
``$CODEX_HOME``, so it runs from a clean ``CODEX_HOME`` holding only a symlink to ``auth.json``.
Both run in a fresh temporary directory outside the home tree (`jail`). The probes that
established this are in docs/players.md.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Protocol


@dataclass(frozen=True)
class Reply:
    text: str
    latency_s: float
    meta: dict = field(default_factory=dict)  # tokens, cost, exit code, raw stderr tail
    session_id: str | None = None  # the harness session the reply came from, if it names one


class Player(Protocol):
    name: str
    harness: str  # "claude", "codex" or "api": the concurrency pool and the session kind

    def act(self, system: str, prompt: str) -> Reply: ...


# ---------------------------------------------------------------------------
# Isolation of the harnesses


@contextmanager
def jail() -> Iterator[Path]:
    """A fresh empty directory outside the home tree, so no AGENTS.md or CLAUDE.md is an
    ancestor. Removed afterwards."""
    base = Path(os.environ.get("GB_JAIL_BASE", "/tmp"))
    if Path.home() in base.resolve().parents or base.resolve() == Path.home():
        raise RuntimeError("GB_JAIL_BASE must lie outside the home directory")
    with tempfile.TemporaryDirectory(prefix="gb-jail-", dir=base) as td:
        yield Path(td)


def default_codex_home() -> Path:
    """``$GB_CODEX_HOME`` or ``<repo>/.local/codex-home``: a directory holding only a symlink to
    the real ``~/.codex/auth.json`` (same file, never a copy: two copies of one login invalidate
    each other's refresh token). No config.toml, no AGENTS.md, no hooks."""
    env = os.environ.get("GB_CODEX_HOME")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / ".local" / "codex-home"


_STEERING_PREFIXES = ("CLAUDE", "ANTHROPIC", "CODEX", "OPENAI")


def clean_env() -> dict[str, str]:
    """Drop variables that steer a player harness: nested-session markers (``CLAUDECODE``,
    ``CLAUDE_CODE_*``), API keys that would switch the harness to another account, Codex
    overrides. Everything else stays, because the ``mise`` shims behind ``claude``/``codex``
    hang under a bare environment."""
    return {
        k: v for k, v in os.environ.items() if not k.startswith(_STEERING_PREFIXES) and k != "PWD"
    }


def resolve_binary(name: str) -> str:
    """The real executable behind a mise-managed tool, bypassing any bash wrapper on the PATH
    (``$GB_<NAME>_BIN`` overrides)."""
    env = os.environ.get(f"GB_{name.upper()}_BIN")
    if env:
        return env
    try:
        out = subprocess.run(
            ["mise", "which", name], capture_output=True, text=True, timeout=30, check=False
        ).stdout.strip()
        if out:
            return out
    except (OSError, subprocess.TimeoutExpired):
        pass
    return name


def tokens_used(output: str) -> int | None:
    """The count `codex exec` prints on the line after "tokens used" (on stderr), or None."""
    lines = output.splitlines()
    count = None
    for i, line in enumerate(lines[:-1]):
        if line.strip().lower() == "tokens used":
            with contextlib.suppress(ValueError):
                count = int(lines[i + 1].strip().replace(",", ""))
    return count


def _run(cmd: list[str], cwd: Path, timeout_s: float, env: dict[str, str]):
    """A harness subprocess: captured text output, no stdin, the exit code left to the caller."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        stdin=subprocess.DEVNULL,
        env=env,
        check=False,
    )


# ---------------------------------------------------------------------------
# Players


@dataclass
class ApiPlayer:
    """OpenAI-compatible chat completions over HTTPS (stdlib only), for models the
    command-line harnesses do not serve. Usage is billed per token, so a grid refuses API
    players unless `--allow-api` is given. The endpoint is `$<base_url_env>` or `base_url`, the
    key `$<key_env>`; both may also come from `env_file`. `tokens_param` names the output
    ceiling ("max_tokens", or "max_completion_tokens" for endpoints that count hidden reasoning
    against it). `max_tokens` is sent as given, so that the model's own ceiling is what binds:
    no player's output is capped below what its endpoint allows. None omits it."""

    name: str
    model: str
    base_url: str = ""
    base_url_env: str = "API_BASE_URL"
    key_env: str = "API_KEY"
    env_file: str = ".local/.env"
    tokens_param: str = "max_tokens"
    max_tokens: int | None = 1_000_000
    reasoning: str | None = None  # sent as reasoning_effort
    timeout_s: float = 600
    harness: ClassVar[str] = "api"

    def _creds(self) -> tuple[str, str]:
        env = dict(os.environ)
        f = Path(self.env_file).expanduser()
        if f.exists():
            for raw in f.read_text().splitlines():
                line = raw.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        base, key = env.get(self.base_url_env) or self.base_url, env.get(self.key_env)
        if not base or not key:
            raise RuntimeError(f"{self.base_url_env}/{self.key_env} not set ({self.env_file})")
        return base.rstrip("/"), key

    def act(self, system: str, prompt: str) -> Reply:
        return self.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        )

    def chat(self, messages: list[dict]) -> Reply:
        base, key = self._creds()
        body: dict = {"model": self.model, "messages": messages}
        if self.max_tokens is not None:
            body[self.tokens_param] = self.max_tokens
        if self.reasoning:
            body["reasoning_effort"] = self.reasoning
        t0 = time.monotonic()
        for attempt in (0, 1):
            req = urllib.request.Request(
                f"{base}/chat/completions",
                data=json.dumps(body).encode(),
                headers={
                    "Content-Type": "application/json",
                    "api-key": key,
                    "Authorization": f"Bearer {key}",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                    d = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")[:500]
                # The output ceiling is the model's own: when the ceiling plus the conversation
                # overflows the context window (for example "maximum context length
                # of 1048576 tokens. You requested a total of 1083425 tokens: 83425 tokens
                # from the input messages"), send what room is left.
                room = _context_room(detail)
                if attempt == 0 and room is not None and self.tokens_param in body:
                    body[self.tokens_param] = room
                    continue
                raise RuntimeError(f"{self.name}: HTTP {e.code}: {detail}") from e
            except (http.client.HTTPException, ValueError) as e:
                # A long chunked reply can be cut off mid-body (IncompleteRead, or a bad chunk
                # size). Raised as RuntimeError, so the commander's retry loop takes the turn
                # again instead of the game dying.
                raise RuntimeError(f"{self.name}: truncated reply: {type(e).__name__}: {e}") from e
        if not isinstance(d, dict):  # a 200 whose body is `null`: retried likewise
            raise RuntimeError(f"{self.name}: empty reply body: {str(d)[:100]}")
        dt = time.monotonic() - t0
        choice = (d.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        text = msg.get("content") or ""
        usage = d.get("usage") or {}
        meta = {
            "harness": "api",
            "model": d.get("model", self.model),
            "finish_reason": choice.get("finish_reason"),
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
            "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get(
                "reasoning_tokens"
            ),
            "reasoning": self.reasoning,
            "has_reasoning_content": "reasoning_content" in msg,
        }
        return Reply(text=text, latency_s=dt, meta=meta)


def _context_room(detail: str) -> int | None:
    """Output tokens left in the window, from a context-overflow error, or None."""
    m = re.search(r"maximum context length of (\d+) tokens.*?(\d+) tokens from the input", detail)
    if not m:
        return None
    return max(int(m.group(1)) - int(m.group(2)) - 64, 1)


@dataclass
class ClaudePlayer:
    """``claude -p``. ``model`` is a Claude Code alias or full id."""

    name: str
    model: str = "opus"
    effort: str = "high"  # pinned; provider defaults differ across harnesses (docs/players.md)
    timeout_s: float = 600
    binary: str = field(default_factory=lambda: resolve_binary("claude"))
    harness: ClassVar[str] = "claude"

    def act(self, system: str, prompt: str) -> Reply:
        with jail() as cwd:
            return self.call(system, prompt, cwd)

    def call(
        self,
        system: str,
        prompt: str,
        cwd: Path,
        session_id: str | None = None,
        resume: bool = False,
    ) -> Reply:
        """One turn in `cwd`: without `session_id` a one-shot call that persists nothing, with
        it the first turn of that session (`--session-id`) or, `resume`, a later one."""
        if session_id is None:
            session = ["--no-session-persistence"]
            tail: list[str] = []
        else:
            session = []
            tail = ["--resume" if resume else "--session-id", session_id]
        cmd = [
            self.binary,
            "-p",
            "--model",
            self.model,
            "--effort",
            self.effort,
            "--tools",
            "",
            "--strict-mcp-config",
            *session,
            "--setting-sources",
            "",
            "--system-prompt",
            system,
            "--output-format",
            "json",
            *tail,
            prompt,
        ]
        t0 = time.monotonic()
        p = _run(cmd, cwd, self.timeout_s, clean_env())
        dt = time.monotonic() - t0
        meta: dict = {"exit": p.returncode, "stderr": p.stderr[-2000:], "harness": "claude -p"}
        try:
            d = json.loads(p.stdout)
        except json.JSONDecodeError:
            meta["parse_error"] = True
            return Reply(text=p.stdout.strip(), latency_s=dt, meta=meta)
        u = d.get("usage", {})
        meta.update(
            input_tokens=u.get("input_tokens"),
            cache_read=u.get("cache_read_input_tokens"),
            cache_create=u.get("cache_creation_input_tokens"),
            output_tokens=u.get("output_tokens"),
            cost_usd=d.get("total_cost_usd"),
            is_error=d.get("is_error", False),
        )
        text = d.get("result", "") or ""
        return Reply(text=text.strip(), latency_s=dt, meta=meta, session_id=d.get("session_id"))


@dataclass
class CodexPlayer:
    """``codex exec`` from a clean CODEX_HOME. Codex has no system-prompt flag: the system
    text heads the first user message, separated by a rule (an asymmetry docs/players.md
    reports)."""

    name: str
    model: str = "gpt-6-luna"
    # low | medium | high | xhigh; None is the provider default, which in a clean CODEX_HOME
    # is "none", so it is always pinned
    reasoning: str | None = "high"
    timeout_s: float = 900
    binary: str = field(default_factory=lambda: resolve_binary("codex"))
    codex_home: Path = field(default_factory=default_codex_home)
    harness: ClassVar[str] = "codex"

    @staticmethod
    def first_message(system: str, prompt: str) -> str:
        return f"{system}\n\n---\n\n{prompt}"

    def act(self, system: str, prompt: str) -> Reply:
        with jail() as cwd:
            return self.call(self.first_message(system, prompt), cwd)

    def call(
        self,
        message: str,
        cwd: Path,
        out_name: str = "last.txt",
        resume_id: str | None = None,
        ephemeral: bool = True,
        flags: tuple[str, ...] = (),
    ) -> Reply:
        """One `codex exec` in `cwd`, the final message read from `cwd/out_name`; with
        `resume_id`, a later turn of that session (`codex exec resume <id>`). `ephemeral`
        keeps no session on disk; `flags` go before the sandbox flag."""
        if not (self.codex_home / "auth.json").exists():
            raise RuntimeError(f"no auth.json in {self.codex_home}; see docs/players.md")
        out = cwd / out_name
        # `exec resume` takes no -s: its sandbox is set by config
        sandbox = ["-c", 'sandbox_mode="read-only"'] if resume_id else ["-s", "read-only"]
        effort = ["-c", f'model_reasoning_effort="{self.reasoning}"'] if self.reasoning else []
        cmd = [
            self.binary,
            "exec",
            *(["resume", resume_id] if resume_id else []),
            "--model",
            self.model,
            *(["--ephemeral"] if ephemeral else []),
            "--skip-git-repo-check",
            *flags,
            *sandbox,
            "-o",
            str(out),
            *effort,
            message,
        ]
        t0 = time.monotonic()
        p = _run(cmd, cwd, self.timeout_s, {**clean_env(), "CODEX_HOME": str(self.codex_home)})
        dt = time.monotonic() - t0
        text = out.read_text() if out.exists() else ""
        meta: dict = {
            "exit": p.returncode,
            "stderr": p.stderr[-2000:],
            "harness": "codex exec",
            "reasoning": self.reasoning,
        }
        m = re.search(r"reasoning effort: (\w+)", p.stderr)
        if m:
            meta["reasoning_reported"] = m.group(1)
        tokens = tokens_used(p.stdout + "\n" + p.stderr)
        if tokens is not None:
            meta["tokens_used"] = tokens
        sid = re.search(r"session id:\s*([0-9a-fA-F-]{36})", p.stdout + "\n" + p.stderr)
        return Reply(
            text=text.strip(), latency_s=dt, meta=meta, session_id=sid.group(1) if sid else None
        )


ROSTER: dict[str, Player] = {
    "opus": ClaudePlayer(name="opus", model="opus"),
    # Fable also wrote much of the engine and the harness (README, "What to keep in mind").
    "fable": ClaudePlayer(name="fable", model="claude-fable-5-1"),
    "sonnet": ClaudePlayer(name="sonnet", model="claude-sonnet-5-5"),
    "astra": CodexPlayer(name="astra", model="gpt-6-astra"),
    "sol": CodexPlayer(name="sol", model="gpt-6-sol"),
    "luna": CodexPlayer(name="luna", model="gpt-6-luna"),
    # DeepSeek V4.1 Flash on DeepSeek's API. Its output ceiling is 393,216 tokens and the API
    # refuses a larger max_tokens, so the ceiling itself is sent.
    "deepseek": ApiPlayer(
        name="deepseek",
        model="deepseek-flash",
        base_url="https://api.deepseek.com",
        base_url_env="DEEPSEEK_BASE_URL",
        key_env="DEEPSEEK_API_KEY",
        max_tokens=393_216,
        reasoning="high",
    ),
}
