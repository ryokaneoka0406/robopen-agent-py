from datetime import datetime, timezone

from robopen_agent.memory_store import TaskRow
from robopen_agent import scheduler as scheduler_module
from robopen_agent.scheduler import Scheduler, parse_supported_cron


def make_task(schedule_cron: str) -> TaskRow:
    return TaskRow(
        id=1,
        title="monthly",
        prompt="remind me",
        schedule_cron=schedule_cron,
        run_at=None,
        last_run_at=None,
        status="active",
        notify_channel=None,
    )


def test_parse_supported_cron_accepts_monthly_day_of_month():
    assert parse_supported_cron("0 0 15 * *") == ("0", "0", "15", "*")


def test_parse_supported_cron_rejects_invalid_or_ambiguous_day_fields():
    assert parse_supported_cron("0 0 0 * *") is None
    assert parse_supported_cron("0 0 32 * *") is None
    assert parse_supported_cron("0 0 15 * 1") is None


def test_monthly_cron_runs_only_on_matching_day(monkeypatch):
    calls = []
    task = make_task("0 0 15 * *")
    scheduler = Scheduler(calls.append)

    class FixedDateTime(datetime):
        current = datetime(2026, 6, 14, 0, 0, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(scheduler_module, "datetime", FixedDateTime)
    scheduler._run_if_due(task, "0", "0", "15", "*")
    assert calls == []

    FixedDateTime.current = datetime(2026, 6, 15, 0, 0, tzinfo=timezone.utc)
    scheduler._run_if_due(task, "0", "0", "15", "*")
    assert calls == [task]
