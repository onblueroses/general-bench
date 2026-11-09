"""The API route keeps the conversation as a message list (no harness session)."""

from dataclasses import dataclass

from kriegsspiel.commander import HarnessSession, LLMCommander
from kriegsspiel.players import Reply


@dataclass
class FakeApi:
    harness = "api"
    name: str = "fake-api"
    model: str = "fake"
    calls: list | None = None

    def chat(self, messages):
        self.calls = (self.calls or []) + [list(messages)]
        return Reply(
            text=f"turn {len(self.calls)}: {len(messages)} messages",
            latency_s=0.01,
            meta={"harness": "api"},
        )

    def act(self, system, prompt):
        return self.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        )


def test_api_session_resends_whole_conversation():
    s = HarnessSession(FakeApi())
    r1 = s.send("SYS", "first brief")
    r2 = s.send("SYS", "second brief")
    assert r1.text == "turn 1: 2 messages"
    assert r2.text == "turn 2: 4 messages"
    assert r2.meta["resumed"] is True and r2.meta["session_id"] == r1.meta["session_id"]
    roles = [m["role"] for m in s.player.calls[-1]]
    assert roles == ["system", "user", "assistant", "user"]


def test_llm_commander_memory_switch():
    with_memory = LLMCommander(FakeApi(), persona="PERSONA")
    assert with_memory.orders("PERSONA\nbrief 1", 0).startswith("turn 1")
    assert with_memory.orders("brief 2", 15).startswith("turn 2: 4")
    one_shot = LLMCommander(FakeApi(), persona="PERSONA", memory=False)
    one_shot.orders("brief 1", 0)
    assert one_shot.orders("brief 2", 15).startswith("turn 2: 2")


def test_session_retries_a_lost_turn_and_then_gives_up(monkeypatch):
    """A harness failure (HTTP error, non-zero exit, is_error) is retried with waits; the
    general is unreachable only after every retry, and the game must not go on without it."""
    import pytest

    from kriegsspiel import commander as cm

    naps: list[float] = []
    monkeypatch.setattr(cm.time, "sleep", naps.append)

    @dataclass
    class Flaky(FakeApi):
        fail: int = 2

        def chat(self, messages):
            if self.fail:
                self.fail -= 1
                raise RuntimeError("HTTP 429: throttled")
            return super().chat(messages)

    r = HarnessSession(Flaky()).send("SYS", "brief")
    assert r.text.startswith("turn 1") and r.meta["attempts"] == 3 and naps == [15.0, 30.0]

    @dataclass
    class Dead(FakeApi):
        def chat(self, messages):
            return Reply(text="", latency_s=0.0, meta={"exit": 1, "stderr": "ERROR: 429"})

    naps.clear()
    with pytest.raises(cm.GeneralUnreachable, match="13 attempts"):
        HarnessSession(Dead()).send("SYS", "brief")
    assert len(naps) == 12 and max(naps) == 300.0
    with pytest.raises(cm.GeneralUnreachable):  # orders() must not swallow it
        LLMCommander(Dead(), persona="").orders("brief", 0)
