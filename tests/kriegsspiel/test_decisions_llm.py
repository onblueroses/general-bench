"""`kriegsspiel.decisions_llm`: a chat model behind the JevClient surface. No network, no
codex: the schema, the normalisation of what a model returns, the prompt, the factory and the
client's fixture/record behaviour through a stubbed backend."""

from __future__ import annotations

import json

import pytest

from kriegsspiel import decisions_llm as dl
from kriegsspiel.jev import Answer, JevClient, choice, noul, score

QS = {
    "kind": choice("what kind", {"hold": "stay", "advance": "go"}),
    "sure": noul("is it so", "yes", "no"),
    "manner": score("how", ["slow", "measured", "fast"]),
}
STATE = {"document": "an order", "order": "Hold the ford."}


def test_schema_requires_every_question_and_nothing_else():
    s = dl._schema(QS)
    ans = s["properties"]["answers"]
    assert ans["required"] == ["kind", "sure", "manner"]
    assert ans["additionalProperties"] is False
    kind = ans["properties"]["kind"]
    assert kind["properties"]["c"]["enum"] == ["hold", "advance"] and kind["required"] == ["c", "p"]
    assert ans["properties"]["sure"] == {"type": "number"}
    assert ans["properties"]["manner"]["required"] == ["s", "p"]
    with pytest.raises(dl.JevError):
        dl._schema({"x": {"type": "essay", "criteria": {}}})


def test_normalise_builds_jevs_shape_from_compact_answers():
    raw = {"kind": {"c": "advance", "p": 0.8}, "sure": 1.7, "manner": {"s": 1.4, "p": 0.6}}
    out = dl._normalise(raw, QS)
    assert out["kind"]["choice"] == "advance" and out["kind"]["probabilities"] == {
        "hold": 0.2,
        "advance": 0.8,
    }
    assert out["kind"]["confidence"] == 0.8
    assert out["sure"]["noul"] == 1.0  # clamped
    m = out["manner"]
    assert m["score"] == 1.4 and m["probabilities"] == {"0": 0.2, "1": 0.6, "2": 0.2}
    assert m["legend"]["2"] == "fast"
    a = Answer.from_json(m)
    assert a.score == 1.4 and a.p_max == 0.6
    assert Answer.from_json(out["kind"]).p_max == 0.8
    # an end level spreads the rest on its one neighbour
    assert dl._normalise({"manner": {"s": 0, "p": 0.7}}, {"manner": QS["manner"]})["manner"][
        "probabilities"
    ] == {"0": 0.7, "1": 0.3, "2": 0.0}


def test_normalise_with_nothing_usable_is_flat_and_unconfident():
    out = dl._normalise({"kind": {"c": "fly"}, "manner": {}}, QS)
    assert out["kind"]["probabilities"] == {"hold": 0.5, "advance": 0.5}
    assert Answer.from_json(out["kind"]).p_max == 0.5  # under the staff's CONFIDENT line
    assert out["sure"]["noul"] == 0.5
    assert out["manner"]["score"] == 1.0 and Answer.from_json(out["manner"]).p_max < 0.5


def test_prompt_is_a_function_of_state_and_questions():
    p = dl.LlmDecisionsClient.prompt(STATE, QS)
    assert p.startswith(dl.PREAMBLE) and "Hold the ford." in p and '"manner"' in p
    assert dl.LlmDecisionsClient.body(STATE, QS) == p[len(dl.PREAMBLE) + 2 :]
    assert p == dl.LlmDecisionsClient.prompt(json.loads(json.dumps(STATE)), QS)


def test_factory_picks_the_client_by_model(monkeypatch):
    monkeypatch.delenv("JEV_MODEL", raising=False)
    assert type(dl.make_client("stub")) is JevClient
    c = dl.make_client("stub", model="codex/gpt-6-luna")
    assert (
        isinstance(c, dl.LlmDecisionsClient)
        and c.slug == "gpt-6-luna"
        and c.model == "codex/gpt-6-luna"
    )
    monkeypatch.setenv("JEV_MODEL", "codex/gpt-6-sol")
    assert dl.make_client("stub").slug == "gpt-6-sol"
    with pytest.raises(ValueError):
        dl.LlmDecisionsClient("gpt-6-luna")


def test_client_records_and_replays_through_the_fixture_machinery(tmp_path, monkeypatch):
    calls = []

    def fake(self, state, questions):
        calls.append(questions)
        return {
            "answers": dl._normalise(
                {"kind": {"c": "hold", "p": 1}, "sure": 0.2, "manner": {"s": 0, "p": 1}}, QS
            ),
            "usage": {"cost": 0.0, "input_tokens": 1234, "output_tokens": 0},
            "id": "codex-1",
        }

    monkeypatch.setattr(dl.LlmDecisionsClient, "_codex", fake)
    c = dl.LlmDecisionsClient("codex/gpt-6-luna", mode="record", fixture_dir=tmp_path)
    a = c.ask(STATE, QS)
    assert a["kind"].choice == "hold" and a["sure"].yes is False and a["manner"].score == 0.0
    assert (
        c.calls[-1].source == "live"
        and c.calls[-1].model == "codex/gpt-6-luna"
        and c.calls[-1].cost == 0.0
    )
    again = dl.LlmDecisionsClient("codex/gpt-6-luna", mode="replay", fixture_dir=tmp_path).ask(
        STATE, QS
    )
    assert again["kind"].choice == "hold" and len(calls) == 1
    # a Jev client never reads this fixture: the model is part of the key
    with pytest.raises(dl.JevError):
        JevClient(mode="replay", fixture_dir=tmp_path).ask(STATE, QS)


def test_split_keeps_groups_whole_and_cuts_only_oversized_ones():
    qs = {f"a{i}": noul("x", "y", "n") for i in range(5)}
    qs.update({f"a{i}_c0": noul("x", "y", "n") for i in range(5)})
    qs.update({f"q0_{k}": noul("x", "y", "n") for k in ("kind", "obj", "route", "state")})
    qs.update({f"q1_{k}": noul("x", "y", "n") for k in ("kind", "obj", "route", "state")})
    qs["k0"] = noul("x", "y", "n")
    chunks = dl.split_questions(qs, 12)
    assert sum(len(c) for c in chunks) == len(qs) and {n for c in chunks for n in c} == set(qs)
    assert all(len(c) <= 12 for c in chunks)
    # the ten addressing questions travel together; q0's details are never split
    assert any(all(n.startswith("a") for n in c) and len(c) == 10 for c in chunks)
    assert any({"q0_kind", "q0_obj", "q0_route", "q0_state"} <= set(c) for c in chunks)
    assert dl.split_questions(qs, 0) == [qs]
    big = {f"a{i}": noul("x", "y", "n") for i in range(30)}
    assert [len(c) for c in dl.split_questions(big, 12)] == [12, 12, 6]
