"""JevClient mechanics: stub, record/replay, retries, limits. No network."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from kriegsspiel import jev
from kriegsspiel.jev import FixtureMissing, JevClient, JevError, choice, noul, request_key, score

QS = {
    "k": choice("Which?", {"a": "first", "b": "second"}),
    "n": noul("Yes?", "yes", "no"),
    "s": score("How much?", ["low", "mid", "high"]),
}
RESP = {
    "model": "typesafe/jev-1.14",
    "answers": {
        "k": {
            "type": "choice",
            "choice": "b",
            "probabilities": {"a": 0.2, "b": 0.8},
            "confidence": 0.8,
        },
        "n": {"type": "noul", "noul": 0.9},
        "s": {
            "type": "score",
            "score": 1.7,
            "legend": {},
            "probabilities": {"2": 0.7},
            "confidence": 0.7,
        },
    },
    "usage": {"input_tokens": 100, "output_tokens": 3, "cost": 0.00001},
    "id": "gen-dec-test",
}


def test_stub_answers():
    a = JevClient(mode="stub").ask("s", QS)
    assert a["k"].choice == "a" and a["n"].noul == 0.5 and a["s"].score == 1.0


def test_replay_missing_fixture_raises(tmp_path):
    with pytest.raises(FixtureMissing):
        JevClient(mode="replay", fixture_dir=tmp_path).ask("s", QS)


def test_record_then_replay(tmp_path, monkeypatch):
    rec = JevClient(mode="record", fixture_dir=tmp_path)
    monkeypatch.setattr(rec, "_post", lambda state, qs: RESP)
    a = rec.ask({"x": "y"}, QS)
    assert a["k"].choice == "b" and a["k"].p_max == 0.8 and a["n"].yes
    assert rec.live_cost == pytest.approx(0.00001)
    rep = JevClient(mode="replay", fixture_dir=tmp_path)
    b = rep.ask({"x": "y"}, QS)
    assert b["s"].score == 1.7 and rep.calls[0].source == "fixture" and rep.live_cost == 0
    assert rep.total_cost == pytest.approx(0.00001)
    assert [c.key for c in rep.drain()] == [request_key(rep.model, {"x": "y"}, QS)]
    assert rep.calls == []


def test_key_depends_on_everything():
    k = request_key("m", "s", QS)
    assert k != request_key("m2", "s", QS)
    assert k != request_key("m", "t", QS)
    assert k != request_key("m", "s", {"k": QS["k"]})


def test_retries_on_429_then_succeeds(monkeypatch):
    calls = {"n": 0}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.HTTPError(req.full_url, 429, "busy", {}, io.BytesIO(b"slow down"))
        return Resp(json.dumps(RESP).encode())

    monkeypatch.setattr(jev.urllib.request, "urlopen", fake_urlopen)
    c = JevClient(api_key="k", mode="live", backoff_s=0.0)
    assert c.ask("s", QS)["k"].choice == "b"
    assert calls["n"] == 3


def test_network_errors_retry_nine_times_then_raise(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(req, timeout):
        calls["n"] += 1
        raise ConnectionResetError(104, "Connection reset by peer")

    monkeypatch.setattr(jev.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(JevError, match="network error"):
        JevClient(api_key="k", mode="live", backoff_s=0.0).ask("s", QS)
    assert calls["n"] == 9


def test_no_retry_on_400(monkeypatch):
    def fake_urlopen(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, io.BytesIO(b"bad request"))

    monkeypatch.setattr(jev.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(JevError, match="HTTP 400"):
        JevClient(api_key="k", mode="live", backoff_s=0.0).ask("s", QS)


def test_state_size_limit():
    with pytest.raises(JevError, match="bytes"):
        JevClient(mode="stub").ask("x" * 40_000, QS)


def test_load_key_from_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("OTHER=1\nexport OPENROUTER_API_KEY='sk-test'\n")
    assert jev.load_key(env, provider="openrouter") == "sk-test"
    assert jev.load_key(tmp_path / "missing", provider="openrouter") is None


def test_vercel_provider_maps_the_model_and_reads_cost_from_gateway_metadata(monkeypatch):
    import io
    import urllib.request

    seen = {}

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0):
        seen["url"] = req.full_url
        seen["body"] = json.loads(req.data.decode())
        seen["auth"] = req.get_header("Authorization")
        return _Resp(
            json.dumps(
                {
                    "model": "typesafe-ai/jev-1.14.0",
                    "answers": {"q": {"type": "noul", "noul": 0.9}},
                    "usage": {"input_tokens": 275, "output_tokens": 20},
                    "provider_metadata": {
                        "gateway": {"cost": "0.00001155", "generationId": "gen_x"}
                    },
                }
            ).encode()
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    c = jev.JevClient(api_key="k", mode="live", provider="vercel")
    ans = c.ask("s", {"q": jev.noul("Is it so?", "yes", "no")})
    assert seen["url"] == "https://ai-gateway.vercel.sh/typesafe/v1/systemone"
    assert seen["body"]["model"] == "typesafe-ai/jev-1.14.0"
    assert seen["auth"] == "Bearer k"
    assert ans["q"].yes
    rec = c.calls[-1]
    assert rec.model == jev.DEFAULT_MODEL  # logical name keys the log and the fixtures
    assert rec.cost == 0.00001155 and rec.input_tokens == 275 and rec.id == "gen_x"
    assert rec.key == jev.request_key(
        jev.DEFAULT_MODEL, "s", {"q": jev.noul("Is it so?", "yes", "no")}
    )


def test_provider_choice_follows_env_then_key_presence(monkeypatch, tmp_path):
    monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)
    monkeypatch.setenv("JEV_PROVIDER", "openrouter")
    assert jev.current_provider() == "openrouter"
    monkeypatch.setenv("JEV_PROVIDER", "vercel")
    assert jev.current_provider() == "vercel"
    monkeypatch.delenv("JEV_PROVIDER")
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "x")
    assert jev.current_provider() == "vercel"
    env = tmp_path / "v.env"
    env.write_text("AI_GATEWAY_API_KEY=vck_test\n")
    assert jev.load_key(env, provider="vercel") == "x"  # environment wins
    monkeypatch.delenv("AI_GATEWAY_API_KEY")
    assert jev.load_key(env, provider="vercel") == "vck_test"
