import pytest

from robopen_agent.agent_runner import AgentResult
from robopen_agent.app import (
    build_conversation_key,
    build_source_key,
    convert_cron_utc_to_jst_label,
    format_schedule_for_jst,
    handle_prompt,
    is_duplicate_event,
    parse_cron_command,
    parse_one_shot_command,
)
from robopen_agent.memory_store import MemoryStore
from robopen_agent.scheduler import Scheduler


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


def test_build_source_key_requires_channel_and_message_ts():
    assert build_source_key("C123", "1710000000.000100") == "C123:1710000000.000100"
    assert build_source_key("C123", None) is None
    assert build_source_key(None, "1710000000.000100") is None


def test_duplicate_event_detection():
    seen = {}
    body = {"event_id": "Ev123"}

    assert is_duplicate_event(body, seen) is False
    assert is_duplicate_event(body, seen) is True
    assert is_duplicate_event({"event_id": "Ev456"}, seen) is False


def test_handle_prompt_saves_agent_session(monkeypatch, tmp_path):
    store = MemoryStore(str(tmp_path / "agent.db"))
    replies = []

    def fake_run_agent(prompt, session_id=None):
        assert prompt == "hello"
        assert session_id is None
        return AgentResult("world", "claude-session")

    monkeypatch.setenv("AGENT_ENGINE", "claude")
    monkeypatch.setattr("robopen_agent.app.run_agent", fake_run_agent)
    monkeypatch.setattr("robopen_agent.app.looks_like_schedule_intent", lambda text: False)

    try:
        handle_prompt(
            prompt="hello",
            reply=replies.append,
            memory_store=store,
            scheduler=Scheduler(lambda task: None),
            conversation_key="C123:1",
        )

        conversation = store.get_or_create_conversation("C123:1")
        assert replies == ["処理中です...", "world"]
        assert conversation.agent_engine == "claude"
        assert conversation.agent_session_id == "claude-session"
    finally:
        store.close()
