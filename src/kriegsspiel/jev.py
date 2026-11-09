"""Decisions client for Jev (TypeSafe's decision model); OpenRouter or the
Vercel AI Gateway (`PROVIDERS`, chosen by `JEV_PROVIDER` or by which key is on the machine).

Jev answers a map of named questions (choice, noul, score) against one state, all in parallel.
It returns no text and must never be asked to compute; callers present clean states.

Modes:
- live: call the API.
- record: replay a fixture when one exists, otherwise call live and write the fixture.
- replay: fixtures only; a missing fixture raises `FixtureMissing` (offline tests).
- stub: no network; first option / 0.5 / middle level, so engine tests run without Jev.
- log (`LogReplayClient`): answers served from a run log's call records in order; a request
  that differs from the logged one, or one too many, raises `ReplayMismatch`.

Every call appends a `CallRecord` to `client.calls`; `drain()` hands them to the run log.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_MODEL = "typesafe/jev-1.14"
# Providers that serve Jev with TypeSafe's request and response shapes. The logical model name
# (`DEFAULT_MODEL`) keys fixtures and logs; each provider maps it to its own model id, so a
# recorded game replays whichever gateway answered it.
PROVIDERS: dict[str, dict[str, Any]] = {
    "openrouter": {
        "endpoint": ENDPOINT,
        "key_env": "OPENROUTER_API_KEY",
        "key_files": (".local/.env",),
        "models": {},
    },
    "vercel": {
        "endpoint": "https://ai-gateway.vercel.sh/typesafe/v1/systemone",
        "key_env": "AI_GATEWAY_API_KEY",
        "key_files": (".local/.env",),
        "models": {
            "typesafe/jev-1.14": "typesafe-ai/jev-1.14.0",
            "typesafe/jev": "typesafe-ai/jev",
        },
    },
}
MAX_STATE_BYTES = 32_000
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURES = REPO_ROOT / "tests" / "kriegsspiel" / "fixtures" / "jev"
MODES = ("live", "record", "replay", "stub")  # a JevClient's; LogReplayClient's is "log"


class JevError(RuntimeError):
    pass


class FixtureMissing(JevError):
    pass


class ReplayMismatch(JevError):
    pass


# ---------------------------------------------------------------------------
# Question builders


def choice(instructions: str, options: dict[str, str]) -> dict[str, Any]:
    """A choice question: options maps option id -> description."""
    if not options:
        raise ValueError("choice needs at least one option")
    return {"type": "choice", "instructions": instructions, "criteria": dict(options)}


def noul(instructions: str, true: str, false: str) -> dict[str, Any]:
    """A yes/no question; the answer is the probability of `true`."""
    return {
        "type": "noul",
        "instructions": instructions,
        "criteria": {"true": true, "false": false},
    }


def score(instructions: str, levels: list[str]) -> dict[str, Any]:
    """A score question over ordered level descriptions (lowest first).

    Jev answers `score` as the expected level index in [0, len(levels) - 1]: the mean of the
    level indices weighted by its probabilities."""
    if len(levels) < 2:
        raise ValueError("score needs at least two levels")
    return {"type": "score", "instructions": instructions, "criteria": list(levels)}


# ---------------------------------------------------------------------------
# Answers


@dataclass
class Answer:
    type: str
    choice: str | None = None
    noul: float | None = None
    score: float | None = None
    probabilities: dict[str, float] = field(default_factory=dict)
    confidence: float | None = None
    legend: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Answer:
        return cls(
            type=d.get("type", ""),
            choice=d.get("choice"),
            noul=d.get("noul"),
            score=d.get("score"),
            probabilities=dict(d.get("probabilities") or {}),
            confidence=d.get("confidence"),
            legend=dict(d.get("legend") or {}),
            raw=d,
        )

    @property
    def p_max(self) -> float:
        """Largest option probability (choice/score); for noul, max(p, 1 - p)."""
        if self.type == "noul" and self.noul is not None:
            return max(self.noul, 1.0 - self.noul)
        if self.probabilities:
            return max(self.probabilities.values())
        return self.confidence if self.confidence is not None else 0.0

    @property
    def yes(self) -> bool:
        return bool(self.noul is not None and self.noul >= 0.5)


Answers = dict[str, Answer]


@dataclass
class CallRecord:
    key: str
    model: str
    mode: str
    source: str  # live, fixture, stub
    questions: list[str]
    answers: dict[str, Any]
    cost: float
    input_tokens: int
    output_tokens: int
    latency_s: float
    id: str = ""

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Client


def request_key(model: str, state: Any, questions: dict[str, Any]) -> str:
    blob = json.dumps(
        {"model": model, "state": state, "questions": questions},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def load_key(env_file: Path | None = None, provider: str | None = None) -> str | None:
    """The provider's API key from the environment, else from its key files (never printed).

    `provider` defaults to `current_provider()`; `env_file` overrides the first key file."""
    provider = provider or current_provider()
    spec = PROVIDERS[provider]
    key = os.environ.get(spec["key_env"])
    if key:
        return key.strip()
    files = [env_file] if env_file else [_key_path(f) for f in spec["key_files"]]
    for path in files:
        try:
            lines = path.read_text().splitlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.strip().removeprefix("export ")
            if line.startswith(spec["key_env"] + "="):
                return line.split("=", 1)[1].strip().strip("'\"") or None
    return None


def _key_path(name: str) -> Path:
    return Path(name).expanduser() if name.startswith("~") else REPO_ROOT / name


def current_provider() -> str:
    """`JEV_PROVIDER` when set; else vercel when its key can be found, else openrouter."""
    env = os.environ.get("JEV_PROVIDER")
    if env:
        if env not in PROVIDERS:
            raise JevError(f"JEV_PROVIDER must be one of {tuple(PROVIDERS)}")
        return env
    if os.environ.get("AI_GATEWAY_API_KEY"):
        return "vercel"
    for f in PROVIDERS["vercel"]["key_files"]:
        try:
            if "AI_GATEWAY_API_KEY=" in _key_path(f).read_text():
                return "vercel"
        except OSError:
            pass
    return "openrouter"


def normalise_response(resp: dict[str, Any]) -> dict[str, Any]:
    """Bring a gateway response to the shape the client reads: `usage.cost` in dollars,
    `usage.input_tokens`/`output_tokens`, `id`. OpenRouter already answers so; the Vercel
    gateway puts the cost under `provider_metadata.gateway.cost` as a string."""
    usage = dict(resp.get("usage") or {})
    meta = (resp.get("provider_metadata") or resp.get("providerMetadata") or {}).get(
        "gateway"
    ) or {}
    if "cost" not in usage and meta.get("cost") is not None:
        usage["cost"] = float(meta["cost"])
    if "input_tokens" not in usage and "inputTokens" in usage:
        usage["input_tokens"] = usage["inputTokens"]
        usage["output_tokens"] = usage.get("outputTokens", 0)
    out = dict(resp)
    out["usage"] = usage
    if not out.get("id") and meta.get("generationId"):
        out["id"] = meta["generationId"]
    return out


def _stub_answer(q: dict[str, Any]) -> dict[str, Any]:
    t = q["type"]
    if t == "choice":
        first = next(iter(q["criteria"]))
        probs = {k: (1.0 if k == first else 0.0) for k in q["criteria"]}
        return {"type": "choice", "choice": first, "probabilities": probs, "confidence": 1.0}
    if t == "noul":
        return {"type": "noul", "noul": 0.5}
    if t == "score":
        n = len(q["criteria"])
        mid = (n - 1) // 2
        return {
            "type": "score",
            "score": float(mid),
            "legend": {str(i): lvl for i, lvl in enumerate(q["criteria"])},
            "probabilities": {str(i): (1.0 if i == mid else 0.0) for i in range(n)},
            "confidence": 1.0,
        }
    raise JevError(f"unknown question type {t!r}")


class JevClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        mode: str = "live",
        fixture_dir: Path | str | None = None,
        timeout_s: float = 60.0,
        max_retries: int = 8,
        backoff_s: float = 1.0,
        max_backoff_s: float = 60.0,
        provider: str | None = None,
    ) -> None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.model = model
        self.mode = mode
        self.fixture_dir = Path(fixture_dir) if fixture_dir else DEFAULT_FIXTURES
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.backoff_s = backoff_s
        # The default retry budget, about three minutes, outlasts a link blip (a VPN exit
        # reset, a handshake timeout), which would otherwise stop a game hours in.
        self.max_backoff_s = max_backoff_s
        self._api_key = api_key
        self.provider = provider or current_provider()
        if self.provider not in PROVIDERS:
            raise ValueError(f"provider must be one of {tuple(PROVIDERS)}")
        self.calls: list[CallRecord] = []
        self.total_cost = 0.0
        self.live_cost = 0.0

    # -- public ------------------------------------------------------------

    def ask(self, state: str | dict[str, Any], questions: dict[str, dict[str, Any]]) -> Answers:
        if not questions:
            return {}
        state_bytes = len(
            (state if isinstance(state, str) else json.dumps(state, ensure_ascii=False)).encode()
        )
        if state_bytes > MAX_STATE_BYTES:
            raise JevError(f"state is {state_bytes} bytes, above {MAX_STATE_BYTES}")
        key = request_key(self.model, state, questions)
        t0 = time.monotonic()
        if self.mode == "stub":
            resp = {"answers": {n: _stub_answer(q) for n, q in questions.items()}, "usage": {}}
            source = "stub"
        else:
            resp = self._load_fixture(key) if self.mode in ("record", "replay") else None
            source = "fixture"
            if resp is None:
                if self.mode == "replay":
                    raise FixtureMissing(f"no fixture {key[:16]} in {self.fixture_dir}")
                resp = self._post(state, questions)
                source = "live"
                if self.mode == "record":
                    self._save_fixture(key, state, questions, resp)
        answers_json = resp.get("answers") or {}
        missing = set(questions) - set(answers_json)
        if missing:
            raise JevError(f"Jev left questions unanswered: {sorted(missing)}")
        usage = resp.get("usage") or {}
        cost = float(usage.get("cost") or 0.0)
        rec = CallRecord(
            key=key,
            model=self.model,
            mode=self.mode,
            source=source,
            questions=list(questions),
            answers=answers_json,
            cost=cost,
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            latency_s=round(time.monotonic() - t0, 3),
            id=str(resp.get("id") or ""),
        )
        self.calls.append(rec)
        self.total_cost += cost
        if source == "live":
            self.live_cost += cost
        return {n: Answer.from_json(answers_json[n]) for n in questions}

    def drain(self) -> list[CallRecord]:
        out, self.calls = self.calls, []
        return out

    # -- fixtures ----------------------------------------------------------

    def _fixture_path(self, key: str) -> Path:
        return self.fixture_dir / f"{key[:24]}.json"

    def _load_fixture(self, key: str) -> dict[str, Any] | None:
        path = self._fixture_path(key)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        if data.get("key") != key:
            raise JevError(f"fixture {path.name} key mismatch")
        return data["response"]

    def _save_fixture(self, key: str, state: Any, questions: dict, resp: dict) -> None:
        self.fixture_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "key": key,
            "model": self.model,
            "recorded": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "state": state,
            "questions": questions,
            "response": resp,
        }
        self._fixture_path(key).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")

    # -- network -----------------------------------------------------------

    def _post(self, state: Any, questions: dict) -> dict[str, Any]:
        spec = PROVIDERS[self.provider]
        api_key = self._api_key or load_key(provider=self.provider)
        if not api_key:
            raise JevError(f"{spec['key_env']} not set (environment or {spec['key_files']})")
        model_id = spec["models"].get(self.model, self.model)
        body = json.dumps(
            {"model": model_id, "state": state, "questions": questions}, ensure_ascii=False
        ).encode("utf-8")
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            req = urllib.request.Request(
                spec["endpoint"],
                data=body,
                method="POST",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                    return normalise_response(json.loads(r.read().decode("utf-8")))
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:500]
                last = JevError(f"HTTP {e.code}: {detail}")
                if e.code != 429 and e.code < 500:
                    raise last from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = JevError(f"network error: {e}")
            if attempt < self.max_retries:
                time.sleep(min(self.backoff_s * 2**attempt, self.max_backoff_s))
        raise last or JevError("request failed")


class LogReplayClient(JevClient):
    """Serves the Jev answers of a run log, in order, without network (run replay).

    Each request must equal the logged one (same request key: model, state and questions);
    otherwise, or when the log has no call left, it raises `ReplayMismatch`."""

    def __init__(self, records: list[dict[str, Any]], model: str = DEFAULT_MODEL) -> None:
        super().__init__(model=model, mode="stub")
        self.mode = "log"
        self._records = list(records)
        self._next = 0

    @property
    def remaining(self) -> int:
        return len(self._records) - self._next

    def ask(self, state: str | dict[str, Any], questions: dict[str, dict[str, Any]]) -> Answers:
        if not questions:
            return {}
        key = request_key(self.model, state, questions)
        if self._next >= len(self._records):
            raise ReplayMismatch(f"Jev call {self._next} ({key[:16]}) is not in the log")
        rec = self._records[self._next]
        if rec.get("key") != key:
            raise ReplayMismatch(
                f"Jev call {self._next}: request {key[:16]} differs from the logged "
                f"{str(rec.get('key'))[:16]} (questions {sorted(questions)[:4]}...)"
            )
        self._next += 1
        answers_json = rec["answers"]
        self.calls.append(
            CallRecord(
                key=key,
                model=self.model,
                mode="log",
                source="log",
                questions=list(questions),
                answers=answers_json,
                cost=0.0,
                input_tokens=0,
                output_tokens=0,
                latency_s=0.0,
                id=str(rec.get("id") or ""),
            )
        )
        return {n: Answer.from_json(answers_json[n]) for n in questions}
