"""A general chat model standing in for Jev: the same `JevClient` surface (state + named
questions in, Jev-shaped answers out), answered by a language model instead of TypeSafe's
decision model.

Why: Jev is a paid external service (an account that runs dry answers 402 and stops a run),
while the Codex harness is already installed for the players. docs/staff-study.md compares the
two answerers.

The model is `codex/<slug>` (the string also keys fixtures and logs, so a game recorded with
one answerer never replays against another): a Codex model through `codex app-server`, from the
players' clean CODEX_HOME in an empty jail, the final message constrained to JSON of exactly the
asked shape by an output schema. Reasoning effort `LLM_JEV_REASONING` (default medium). By
default one `codex app-server` process per client lives for the whole game: every request is a
fresh ephemeral thread on it, so nothing accumulates and the start of a `codex exec` is paid
once. `LLM_JEV_PERSISTENT=0` falls back to one `codex exec --output-schema` per request.

The model is told what Jev is told: read the state, answer each question from it alone, never
compute. Probabilities come from the model's own estimate, so they are opinions, not Jev's
calibrated mass; the staff thresholds (`CONFIDENT` 0.5) read them the same way.
"""

from __future__ import annotations

import atexit
import contextlib
import json
import os
import queue
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .jev import DEFAULT_MODEL, JevClient, JevError
from .players import CodexPlayer, clean_env, default_codex_home, jail, resolve_binary

PREFIX = "codex/"  # the model strings this client answers for
DEFAULT_LLM_MODEL = "codex/gpt-6-luna"

PREAMBLE = """You are the decisions engine of a Kriegsspiel umpire. You receive a STATE (a JSON \
document) and a map of named QUESTIONS about it. Answer every question from the state alone: \
read what the words say, never compute, count or invent facts, and never assume the writer \
meant something the words do not say.

Question types and the answer each needs:
- choice: `criteria` maps option ids to descriptions. Answer {"c": <the option id that fits \
best>, "p": <your probability, 0 to 1, that it is the right reading>}.
- noul: `criteria.true` and `criteria.false` describe the two readings. Answer a number: the \
probability, 0 to 1, that the `true` reading holds.
- score: `criteria` is an ordered list of level descriptions, lowest first, level i at index i. \
Answer {"s": <the expected level, a number from 0 to the last index>, "p": <your probability \
that the nearest level is the right one>}.

Put p at 1 only when the words leave no doubt; a reading the words only suggest gets a p under \
0.5. Answer with JSON only, exactly the schema given: {"answers": {<question name>: <answer>}}, \
one entry per question, same names."""


def _schema(questions: dict[str, dict]) -> dict:
    """A strict JSON schema of the compact answer map: every question required, nothing else.
    Compact (one id and one probability per question, not Jev's probability per option)
    because the model's output tokens are what a request's time is spent on."""
    props: dict[str, Any] = {}
    for name, q in questions.items():
        t = q["type"]
        if t == "choice":
            props[name] = {
                "type": "object",
                "additionalProperties": False,
                "required": ["c", "p"],
                "properties": {
                    "c": {"type": "string", "enum": list(q["criteria"])},
                    "p": {"type": "number"},
                },
            }
        elif t == "noul":
            props[name] = {"type": "number"}
        elif t == "score":
            props[name] = {
                "type": "object",
                "additionalProperties": False,
                "required": ["s", "p"],
                "properties": {"s": {"type": "number"}, "p": {"type": "number"}},
            }
        else:
            raise JevError(f"unknown question type {t!r}")
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["answers"],
        "properties": {
            "answers": {
                "type": "object",
                "additionalProperties": False,
                "required": list(questions),
                "properties": props,
            }
        },
    }


def _clamp(x: Any, default: float) -> float:
    try:
        return min(1.0, max(0.0, float(x)))
    except (TypeError, ValueError):
        return default


def _normalise(answers: dict[str, Any], questions: dict[str, dict]) -> dict[str, Any]:
    """Compact answers to Jev's shape, so `Answer.from_json` and every caller see one thing:
    a choice gets `probabilities` with p on the chosen option and the rest spread over the
    others; a score gets `probabilities` with p on the nearest level and the rest on its
    neighbours, plus the `legend`; `confidence` is p. Missing or unusable answers become the
    unsure reading (a flat distribution, 0.5), under the staff's CONFIDENT line."""
    out: dict[str, Any] = {}
    for name, q in questions.items():
        a = answers.get(name)
        t = q["type"]
        if t == "noul":
            out[name] = {
                "type": t,
                "noul": _clamp(a if not isinstance(a, dict) else a.get("noul"), 0.5),
            }
            continue
        if t == "choice":
            ids = list(q["criteria"])
            c = (a.get("c") or a.get("choice")) if isinstance(a, dict) else None
            if c not in ids:
                probs = {i: round(1.0 / len(ids), 4) for i in ids}
                c = ids[0]
            else:
                p = _clamp(a.get("p", a.get("confidence")), 0.5) if len(ids) > 1 else 1.0
                rest = (1.0 - p) / (len(ids) - 1) if len(ids) > 1 else 0.0
                probs = {i: round(p if i == c else rest, 4) for i in ids}
            out[name] = {"type": t, "choice": c, "probabilities": probs, "confidence": probs[c]}
            continue
        n = len(q["criteria"])
        ids = [str(i) for i in range(n)]
        sc = a.get("s", a.get("score")) if isinstance(a, dict) else None
        try:
            sc = min(float(n - 1), max(0.0, float(sc)))
        except (TypeError, ValueError):
            sc = None
        if sc is None:
            probs = {i: round(1.0 / n, 4) for i in ids}
            sc = (n - 1) / 2
        else:
            p = _clamp(a.get("p"), 0.5)
            near = round(sc)
            neigh = [j for j in (near - 1, near + 1) if 0 <= j < n]
            probs = dict.fromkeys(ids, 0.0)
            probs[str(near)] = p
            for j in neigh:
                probs[str(j)] += (1.0 - p) / len(neigh)
            probs = {i: round(v, 4) for i, v in probs.items()}
        out[name] = {
            "type": t,
            "score": round(sc, 4),
            "probabilities": probs,
            "legend": {i: q["criteria"][int(i)] for i in ids},
            "confidence": max(probs.values()),
        }
    return out


def _parse_answers(text: str) -> dict[str, Any]:
    try:
        return json.loads(text).get("answers") or {}
    except (json.JSONDecodeError, AttributeError):
        m = re.search(r"\{.*\}", text, re.S)
        try:
            return (json.loads(m.group(0)).get("answers") or {}) if m else {}
        except (json.JSONDecodeError, AttributeError):
            return {}


def split_questions(questions: dict[str, dict], chunk: int) -> list[dict[str, dict]]:
    """Chunks of at most `chunk` questions, groups kept whole when they fit (a group larger
    than `chunk` is cut); `chunk` <= 0 means one chunk."""
    if chunk <= 0 or len(questions) <= chunk:
        return [dict(questions)]
    groups: dict[str, dict[str, dict]] = {}
    for n, q in questions.items():
        groups.setdefault(_group(n), {})[n] = q
    out: list[dict[str, dict]] = []
    cur: dict[str, dict] = {}
    for g in groups.values():
        items = list(g.items())
        while len(items) > chunk:
            if cur:
                out.append(cur)
                cur = {}
            out.append(dict(items[:chunk]))
            items = items[chunk:]
        if cur and len(cur) + len(items) > chunk:
            out.append(cur)
            cur = {}
        cur.update(items)
    if cur:
        out.append(cur)
    return out


def _group(name: str) -> str:
    """Questions that belong together: a plan's details (`q0_*`), a clause's reading (`c1_*`),
    the addressing nouls (`a<i>`, `a<i>_c<k>`), the checks."""
    head = name.split("_", maxsplit=1)[0]
    if head[:1] == "a" and head[1:].isdigit():
        return "a"
    return head


class LlmDecisionsClient(JevClient):
    """`JevClient` whose live answers come from a chat model (see the module docstring).

    `model` is `codex/<model id>`; the logical name is kept as is in fixtures and logs."""

    def __init__(
        self,
        model: str = DEFAULT_LLM_MODEL,
        mode: str = "live",
        reasoning: str | None = None,
        timeout_s: float = 600.0,
        **kw: Any,
    ) -> None:
        slug = model.removeprefix(PREFIX)
        if not model.startswith(PREFIX) or not slug:
            raise ValueError(f"model must be {PREFIX}<id>: {model!r}")
        # Codex throttles a fleet (429 after the app-server's own reconnects): wait it out, up
        # to about an hour, rather than lose a game hours in.
        kw.setdefault("max_retries", 20)
        kw.setdefault("max_backoff_s", 300.0)
        super().__init__(model=model, mode=mode, timeout_s=timeout_s, **kw)
        self.slug = slug
        self.reasoning = reasoning or os.environ.get("LLM_JEV_REASONING", "medium")
        self.provider = "llm:codex"
        # Questions per model request; 0 (the default) sends a staff call whole: the account is
        # throttled by input tokens, and every chunk resends the whole state.
        self.chunk = int(os.environ.get("LLM_JEV_CHUNK", "0"))
        self.parallel = int(os.environ.get("LLM_JEV_PARALLEL", "6"))  # requests in flight per ask
        self.persistent = os.environ.get("LLM_JEV_PERSISTENT", "1") not in ("0", "false", "no")
        self._server: CodexAppServer | None = None
        self._server_lock = threading.Lock()

    def close(self) -> None:
        """Stop the app-server, if one runs. Safe to call twice."""
        with self._server_lock:
            if self._server is not None:
                self._server.close()
                self._server = None

    def _app_server(self) -> CodexAppServer:
        with self._server_lock:
            if self._server is None or not self._server.alive():
                self._server = CodexAppServer(self.slug, self.reasoning, timeout_s=self.timeout_s)
            return self._server

    # The request body Jev sees is the prompt the model sees, so the prompt is one function
    # of (state, questions) and the fixture key (model + state + questions) covers it.
    @staticmethod
    def body(state: Any, questions: dict[str, dict]) -> str:
        st = state if isinstance(state, str) else json.dumps(state, ensure_ascii=False, indent=1)
        qs = json.dumps(questions, ensure_ascii=False, indent=1)
        return f"STATE:\n{st}\n\nQUESTIONS:\n{qs}\n"

    @classmethod
    def prompt(cls, state: Any, questions: dict[str, dict]) -> str:
        """The one-shot form: the preamble heads the message (the app-server carries it as the
        thread's base instructions instead, and gets `body`)."""
        return f"{PREAMBLE}\n\n{cls.body(state, questions)}"

    def _post(self, state: Any, questions: dict) -> dict[str, Any]:
        """One request to the model per chunk of questions, the chunks in parallel, merged
        into one Jev-shaped response (one call record, one fixture)."""
        chunks = split_questions(questions, self.chunk)
        t0 = time.monotonic()
        if len(chunks) == 1:
            parts = [self._codex(state, chunks[0])]
        else:
            with ThreadPoolExecutor(max_workers=min(len(chunks), self.parallel)) as ex:
                parts = list(ex.map(lambda c: self._codex(state, c), chunks))
        answers: dict[str, Any] = {}
        tokens = 0
        for r in parts:
            answers.update(r["answers"])
            tokens += int(r["usage"].get("input_tokens") or 0)
        return {
            "answers": answers,
            "usage": {
                "cost": 0.0,
                "input_tokens": tokens,
                "output_tokens": 0,
                "latency_s": round(time.monotonic() - t0, 3),
                "requests": len(parts),
            },
            "id": parts[0].get("id", ""),
        }

    def _codex(self, state: Any, questions: dict) -> dict[str, Any]:
        if self.persistent:
            return self._ask_with_retry(questions, lambda: self._server_turn(state, questions))
        home = default_codex_home()
        if not (home / "auth.json").exists():
            raise JevError(f"no auth.json in {home}; see docs/players.md")
        player = CodexPlayer(
            name=self.model,
            model=self.slug,
            reasoning=self.reasoning,
            timeout_s=self.timeout_s,
            binary=resolve_binary("codex"),
            codex_home=home,
        )
        return self._ask_with_retry(questions, lambda: self._exec_turn(player, state, questions))

    def _ask_with_retry(self, questions: dict, runner) -> dict[str, Any]:
        """`runner()` -> (answer text, usage) for one model request, retried up to
        `max_retries` times: after a lost turn (`_LostTurn`, with the backoff wait when it asks
        for one) and after an answer that leaves a question out."""
        last: JevError | None = None
        for attempt in range(self.max_retries + 1):
            t0 = time.monotonic()
            try:
                text, usage = runner()
            except _LostTurn as e:
                last = e
                if e.backoff:
                    time.sleep(min(self.backoff_s * 2**attempt, self.max_backoff_s))
                continue
            answers = _parse_answers(text)
            missing = set(questions) - set(answers)
            if missing:
                last = JevError(f"model left questions unanswered: {sorted(missing)[:5]}")
                continue
            return {
                "answers": _normalise(answers, questions),
                "usage": {
                    "cost": 0.0,
                    **usage,
                    "latency_s": round(time.monotonic() - t0, 3),
                },
                "id": f"codex-{int(t0)}",
            }
        raise last or JevError("model request failed")

    def _server_turn(self, state: Any, questions: dict) -> tuple[str, dict]:
        """One thread on the app-server (the preamble is its base instructions)."""
        try:
            text, usage = self._app_server().turn(self.body(state, questions), _schema(questions))
        except JevError as e:
            raise _LostTurn(str(e), backoff=True) from e
        return text, {
            "input_tokens": int(usage.get("input") or 0),
            "cached_input_tokens": int(usage.get("cached") or 0),
            "output_tokens": int(usage.get("output") or 0),
        }

    def _exec_turn(self, player: CodexPlayer, state: Any, questions: dict) -> tuple[str, dict]:
        """One `codex exec --output-schema` in a fresh jail; a throttled one waits."""
        with jail() as cwd:
            schema = cwd / "schema.json"
            schema.write_text(json.dumps(_schema(questions)))
            try:
                r = player.call(
                    self.prompt(state, questions),
                    cwd,
                    out_name="last.json",
                    flags=("--ignore-user-config", "--output-schema", str(schema)),
                )
            except subprocess.TimeoutExpired:
                raise _LostTurn(
                    f"codex exec timed out after {self.timeout_s}s", backoff=False
                ) from None
        stderr = r.meta["stderr"]
        if r.meta["exit"] != 0 or not r.text:
            raise _LostTurn(
                f"codex exec exit {r.meta['exit']}: {stderr[-400:]}",
                backoff="429" in stderr or "rate limit" in stderr.lower(),
            )
        return r.text, {"input_tokens": r.meta.get("tokens_used") or 0, "output_tokens": 0}


class _LostTurn(JevError):
    """A model request that brought no answer (an app-server error, a failed or timed-out
    `codex exec`); `backoff` asks for the growing wait before the next attempt."""

    def __init__(self, message: str, backoff: bool):
        super().__init__(message)
        self.backoff = backoff


class CodexAppServer:
    """One `codex app-server` process (JSON-RPC 2.0 over stdio, newline-delimited), many
    concurrent ephemeral threads. `turn(prompt, schema)` starts a fresh thread, runs one turn
    constrained by `schema`, returns the final agent message and that turn's token usage, and
    unsubscribes the thread. Thread-safe: one writer lock, one reader thread dispatching
    responses by id and notifications by thread id."""

    def __init__(self, model: str, reasoning: str, timeout_s: float = 600.0) -> None:
        self.model = model
        self.reasoning = reasoning
        self.timeout_s = timeout_s
        home = default_codex_home()
        if not (home / "auth.json").exists():
            raise JevError(f"no auth.json in {home}; see docs/players.md")
        self._jail = contextlib.ExitStack()
        self.cwd = self._jail.enter_context(jail())
        self._proc = subprocess.Popen(
            [resolve_binary("codex"), "app-server"],
            cwd=self.cwd,
            text=True,
            bufsize=1,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={**clean_env(), "CODEX_HOME": str(home)},
        )
        self._write_lock = threading.Lock()
        self._next_id = 0
        self._responses: dict[int, queue.Queue] = {}
        self._threads: dict[str, queue.Queue] = {}
        self._usage: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._reader = threading.Thread(target=self._read, daemon=True, name="codex-app-server")
        self._reader.start()
        atexit.register(self.close)
        self._request("initialize", {"clientInfo": {"name": "general-bench", "version": "0"}})

    def alive(self) -> bool:
        return self._proc.poll() is None

    def close(self) -> None:
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        with contextlib.suppress(OSError):
            self._jail.close()

    # -- wire ------------------------------------------------------------------

    def _read(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "method" not in m and "id" in m:
                with self._lock:
                    q = self._responses.get(m["id"])
                if q is not None:
                    q.put(m)
                continue
            params = m.get("params") or {}
            tid = params.get("threadId")
            if m.get("method") == "thread/tokenUsage/updated" and tid:
                with self._lock:
                    self._usage[tid] = params.get("tokenUsage") or {}
            if tid:
                with self._lock:
                    q = self._threads.get(tid)
                if q is not None:
                    q.put(m)
        # the process ended: wake every waiter
        with self._lock:
            waiters = list(self._responses.values()) + list(self._threads.values())
        for q in waiters:
            q.put({"method": "server/exited"})

    def _request(self, method: str, params: dict, timeout: float | None = None) -> dict:
        if self._proc.poll() is not None:
            raise JevError("codex app-server is not running")
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._next_id += 1
            rid = self._next_id
            self._responses[rid] = q
        line = json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}) + "\n"
        try:
            with self._write_lock:
                assert self._proc.stdin is not None
                self._proc.stdin.write(line)
                self._proc.stdin.flush()
            try:
                m = q.get(timeout=timeout or self.timeout_s)
            except queue.Empty:
                raise JevError(
                    f"app-server {method}: no response in {timeout or self.timeout_s}s"
                ) from None
        finally:
            with self._lock:
                self._responses.pop(rid, None)
        if m.get("method") == "server/exited":
            raise JevError("codex app-server exited")
        if "error" in m:
            raise JevError(f"app-server {method}: {json.dumps(m['error'])[:300]}")
        return m.get("result") or {}

    # -- one question set -------------------------------------------------------

    def turn(self, prompt: str, schema: dict) -> tuple[str, dict]:
        r = self._request(
            "thread/start",
            {
                "model": self.model,
                "ephemeral": True,
                "sandbox": "read-only",
                "approvalPolicy": "never",
                "cwd": str(self.cwd),
                "baseInstructions": PREAMBLE,
            },
            timeout=60,
        )
        tid = r["thread"]["id"]
        events: queue.Queue = queue.Queue()
        with self._lock:
            self._threads[tid] = events
        text = ""
        try:
            self._request(
                "turn/start",
                {
                    "threadId": tid,
                    "input": [{"type": "text", "text": prompt}],
                    "outputSchema": schema,
                    "effort": self.reasoning,
                },
                timeout=60,
            )
            deadline = time.monotonic() + self.timeout_s
            while True:
                try:
                    ev = events.get(timeout=max(0.1, deadline - time.monotonic()))
                except queue.Empty:
                    raise JevError(f"app-server turn: no completion in {self.timeout_s}s") from None
                method = ev.get("method")
                if method == "server/exited":
                    raise JevError("codex app-server exited mid-turn")
                p = ev.get("params") or {}
                if (
                    method == "item/completed"
                    and (p.get("item") or {}).get("type") == "agentMessage"
                ):
                    text = p["item"].get("text") or text
                if method == "turn/completed":
                    turn = p.get("turn") or {}
                    for it in turn.get("items") or []:
                        if it.get("type") == "agentMessage" and it.get("text"):
                            text = it["text"]
                    if turn.get("status") != "completed":
                        err = (turn.get("error") or {}).get("message", turn.get("status"))
                        raise JevError(f"app-server turn {turn.get('status')}: {err}")
                    break
                if time.monotonic() > deadline:
                    raise JevError(f"app-server turn: no completion in {self.timeout_s}s")
        finally:
            with self._lock:
                self._threads.pop(tid, None)
                usage = self._usage.pop(tid, {})
            with contextlib.suppress(JevError):
                self._request("thread/unsubscribe", {"threadId": tid}, timeout=10)
        last = usage.get("last") or {}
        return text, {
            "input": last.get("inputTokens") or last.get("input_tokens"),
            "cached": last.get("cachedInputTokens") or last.get("cached_input_tokens"),
            "output": last.get("outputTokens") or last.get("output_tokens"),
        }


def make_client(
    mode: str, fixture_dir: Path | str | None = None, model: str | None = None
) -> JevClient:
    """The decisions client a game runs on: `JEV_MODEL` (or `model`) `codex/<slug>` gives an
    `LlmDecisionsClient`; anything else (default `typesafe/jev-1.14`) the Jev client."""
    model = model or os.environ.get("JEV_MODEL") or DEFAULT_MODEL
    if model.startswith(PREFIX):
        return LlmDecisionsClient(model=model, mode=mode, fixture_dir=fixture_dir)
    return JevClient(model=model, mode=mode, fixture_dir=fixture_dir)
