"""A reply cut off mid-body becomes a RuntimeError, which the commander's retry loop catches."""

import http.client

import pytest

from kriegsspiel.players import ApiPlayer


class _Cut:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        raise http.client.IncompleteRead(b"")


@pytest.mark.parametrize("exc", [http.client.IncompleteRead(b""), ValueError("invalid literal")])
def test_truncated_reply_is_runtime_error(monkeypatch, exc):
    class Cut(_Cut):
        def read(self):
            raise exc

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Cut())
    p = ApiPlayer(
        name="t", model="m", base_url="http://x", key_env="T_KEY", env_file="/nonexistent"
    )
    monkeypatch.setenv("T_KEY", "k")
    with pytest.raises(RuntimeError, match="truncated reply"):
        p.act("s", "p")


def test_null_body_is_runtime_error(monkeypatch):
    class Null(_Cut):
        def read(self):
            return b"null"

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Null())
    p = ApiPlayer(
        name="t", model="m", base_url="http://x", key_env="T_KEY", env_file="/nonexistent"
    )
    monkeypatch.setenv("T_KEY", "k")
    with pytest.raises(RuntimeError, match="empty reply body"):
        p.act("s", "p")
