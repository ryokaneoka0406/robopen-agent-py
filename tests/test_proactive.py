from __future__ import annotations

import random
from datetime import date, datetime
from zoneinfo import ZoneInfo

from robopen_agent.memory_store import MemoryStore
from robopen_agent.proactive import (
    ProactiveConfig,
    build_source_key,
    config_from_env,
    ensure_proactive_tasks,
    ensure_proactive_tasks_for_date,
    generate_daily_run_times,
    is_proactive_task,
)


def test_generate_daily_run_times_uses_jst_window_and_utc_storage_inputs():
    config = ProactiveConfig(
        enabled=True,
        channel="C123",
        times_per_day=4,
        window_start=datetime.strptime("09:00", "%H:%M").time(),
        window_end=datetime.strptime("22:00", "%H:%M").time(),
        min_gap_minutes=120,
        timezone_name="Asia/Tokyo",
    )

    run_times = generate_daily_run_times(date(2026, 5, 28), config, rng=random.Random(1))

    assert len(run_times) == 4
    assert all(run_at.tzinfo == ZoneInfo("Asia/Tokyo") for run_at in run_times)
    assert all(9 <= run_at.hour < 22 for run_at in run_times)
    gaps = [
        int((second - first).total_seconds() / 60)
        for first, second in zip(run_times, run_times[1:])
    ]
    assert all(gap >= 120 for gap in gaps)


def test_ensure_proactive_tasks_is_idempotent_by_source_key(tmp_path):
    store = MemoryStore(str(tmp_path / "agent.db"))
    try:
        config = ProactiveConfig(
            enabled=True,
            channel="C123",
            times_per_day=4,
            window_start=datetime.strptime("09:00", "%H:%M").time(),
            window_end=datetime.strptime("22:00", "%H:%M").time(),
            min_gap_minutes=120,
            timezone_name="Asia/Tokyo",
        )
        now = datetime(2026, 5, 28, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo"))

        first = ensure_proactive_tasks_for_date(
            store, config, date(2026, 5, 28), now=now, rng=random.Random(2)
        )
        second = ensure_proactive_tasks_for_date(
            store, config, date(2026, 5, 28), now=now, rng=random.Random(2)
        )

        assert len(first) == 4
        assert [task.id for task in second] == [task.id for task in first]
        assert {task.source_key for task in first} == {
            build_source_key(date(2026, 5, 28), index) for index in range(1, 5)
        }
        assert all(is_proactive_task(task) for task in first)
        assert all(task.notify_channel == "C123" for task in first)
        assert all(task.run_at and task.run_at.endswith("Z") for task in first)
    finally:
        store.close()


def test_ensure_proactive_tasks_respects_enabled_flag(tmp_path):
    store = MemoryStore(str(tmp_path / "agent.db"))
    try:
        config = ProactiveConfig(
            enabled=False,
            channel="C123",
            times_per_day=4,
            window_start=datetime.strptime("09:00", "%H:%M").time(),
            window_end=datetime.strptime("22:00", "%H:%M").time(),
            min_gap_minutes=120,
            timezone_name="Asia/Tokyo",
        )

        assert ensure_proactive_tasks(store, config) == []
        assert store.list_active_tasks() == []
    finally:
        store.close()


def test_config_from_env_uses_channel_fallback():
    config = config_from_env(
        {
            "PROACTIVE_ENABLED": "true",
            "SLACK_LOG_CHANNEL": "CLOG",
        }
    )

    assert config.enabled is True
    assert config.channel == "CLOG"
    assert config.times_per_day == 4
    assert config.timezone_name == "Asia/Tokyo"


def test_config_from_env_prefers_proactive_channel():
    config = config_from_env(
        {
            "PROACTIVE_ENABLED": "true",
            "PROACTIVE_CHANNEL": "CPRO",
            "SLACK_LOG_CHANNEL": "CLOG",
        }
    )

    assert config.channel == "CPRO"
