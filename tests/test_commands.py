import pytest

from robopen_agent.app import (
    build_conversation_key,
    convert_cron_utc_to_jst_label,
    format_schedule_for_jst,
    is_duplicate_event,
    parse_cron_command,
    parse_one_shot_command,
)


def test_parse_cron_command():
    assert parse_cron_command("title | 0 0 * * * | do | this") == {
        "title": "title",
        "schedule_cron": "0 0 * * *",
        "prompt": "do | this",
    }


def test_parse_one_shot_command():
    assert parse_one_shot_command("title | 2026-05-20T00:00:00Z | do it") == {
        "title": "title",
        "run_at": "2026-05-20T00:00:00Z",
        "prompt": "do it",
    }


def test_parse_command_rejects_missing_parts():
    with pytest.raises(ValueError):
        parse_cron_command("title | 0 0 * * *")


def test_format_schedule_for_jst():
    assert format_schedule_for_jst(None, "2026-05-20T00:00:00Z") == "2026/05/20 09:00:00 JST"


def test_convert_cron_utc_to_jst_label():
    assert convert_cron_utc_to_jst_label("0 0 * * *") == "毎日 09:00 JST (cron: 0 0 * * * UTC)"


def test_build_conversation_key_includes_channel():
    assert build_conversation_key("C123", "1710000000.000100") == "C123:1710000000.000100"


def test_duplicate_event_detection():
    seen = {}
    body = {"event_id": "Ev123"}

    assert is_duplicate_event(body, seen) is False
    assert is_duplicate_event(body, seen) is True
    assert is_duplicate_event({"event_id": "Ev456"}, seen) is False
