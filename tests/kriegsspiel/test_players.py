from kriegsspiel.players import ROSTER


def test_roster_names_match_keys():
    for k, v in ROSTER.items():
        assert v.name == k


def test_jail_is_outside_home_and_empty():
    from pathlib import Path

    from kriegsspiel.players import jail

    with jail() as d:
        assert d.is_dir() and not any(d.iterdir())
        assert Path.home() not in d.resolve().parents
    assert not d.exists()


def test_context_room_from_an_overflow_error():
    from kriegsspiel.players import _context_room

    msg = (
        '{"message":"Requested token count exceeds the model\'s maximum context length of '
        "1048576 tokens. You requested a total of 1083425 tokens: 83425 tokens from the input "
        'messages and 1000000 tokens for the completion."}'
    )
    assert _context_room(msg) == 1048576 - 83425 - 64
    assert _context_room("HTTP 429: throttled") is None
