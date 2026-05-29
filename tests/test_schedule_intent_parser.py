from robopen_agent.codex_runner import CodexResult
from robopen_agent.schedule_intent_parser import (
    ParsedScheduleIntent,
    ParsedScheduleUpdateIntent,
    parse_schedule_intent_with_ai,
)
from robopen_agent import schedule_intent_parser


def test_parse_update_intent_with_task_id(monkeypatch):
    monkeypatch.setattr(
        schedule_intent_parser,
        "run_codex",
        lambda _prompt: CodexResult(
            '{"kind":"update","taskId":12,"targetQuery":null,'
            '"scheduleCron":"0 23 * * *","confidence":0.9}'
        ),
    )

    intent = parse_schedule_intent_with_ai("#12を毎朝8時に変えて")

    assert isinstance(intent, ParsedScheduleUpdateIntent)
    assert intent.task_id == 12
    assert intent.target_query is None
    assert intent.schedule_cron == "0 23 * * *"


def test_parse_update_intent_with_target_query(monkeypatch):
    monkeypatch.setattr(
        schedule_intent_parser,
        "run_codex",
        lambda _prompt: CodexResult(
            '{"kind":"update","taskId":null,"targetQuery":"朝の要約",'
            '"scheduleCron":"30 23 * * *","confidence":0.9}'
        ),
    )

    intent = parse_schedule_intent_with_ai("朝の要約を8時半にして")

    assert isinstance(intent, ParsedScheduleUpdateIntent)
    assert intent.task_id is None
    assert intent.target_query == "朝の要約"
    assert intent.schedule_cron == "30 23 * * *"


def test_parse_create_intent_still_returns_create_intent(monkeypatch):
    monkeypatch.setattr(
        schedule_intent_parser,
        "run_codex",
        lambda _prompt: CodexResult(
            '{"kind":"cron","title":"朝の要約","prompt":"予定を要約する",'
            '"scheduleCron":"0 0 * * *","runAt":null,"confidence":0.9}'
        ),
    )

    intent = parse_schedule_intent_with_ai("毎朝9時に予定を要約して")

    assert isinstance(intent, ParsedScheduleIntent)
    assert intent.kind == "cron"
    assert intent.title == "朝の要約"
    assert intent.schedule_cron == "0 0 * * *"
