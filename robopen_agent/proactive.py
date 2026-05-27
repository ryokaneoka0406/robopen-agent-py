from __future__ import annotations

import os
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .memory_store import MemoryStore, TaskRow


SOURCE_PREFIX = "proactive:"
DEFAULT_PROMPT = (
    "あなたは個人用エージェントです。短く自然に、状況確認・作業再開・休憩・"
    "今日の予定確認のどれかを促すSlackメッセージを日本語で1〜3文だけ書いてください。"
    "押しつけず、親しみはあるが過度に馴れ馴れしくしないでください。"
)


@dataclass(frozen=True)
class ProactiveConfig:
    enabled: bool
    channel: str | None
    times_per_day: int
    window_start: time
    window_end: time
    min_gap_minutes: int
    timezone_name: str

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)


def config_from_env(env: dict[str, str] | None = None) -> ProactiveConfig:
    source = env if env is not None else os.environ
    return ProactiveConfig(
        enabled=_parse_bool(source.get("PROACTIVE_ENABLED")),
        channel=_empty_to_none(source.get("PROACTIVE_CHANNEL"))
        or _empty_to_none(source.get("SLACK_LOG_CHANNEL")),
        times_per_day=_parse_int(source.get("PROACTIVE_TIMES_PER_DAY"), 4),
        window_start=_parse_hhmm(source.get("PROACTIVE_WINDOW_START"), time(9, 0)),
        window_end=_parse_hhmm(source.get("PROACTIVE_WINDOW_END"), time(22, 0)),
        min_gap_minutes=_parse_int(source.get("PROACTIVE_MIN_GAP_MINUTES"), 120),
        timezone_name=source.get("PROACTIVE_TIMEZONE") or "Asia/Tokyo",
    )


def is_proactive_task(task: TaskRow) -> bool:
    return bool(task.source_key and task.source_key.startswith(SOURCE_PREFIX))


def ensure_proactive_tasks(
    store: MemoryStore,
    config: ProactiveConfig,
    *,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> list[TaskRow]:
    if not config.enabled:
        return []
    if not config.channel:
        print("[proactive] PROACTIVE_CHANNEL or SLACK_LOG_CHANNEL is not configured. Skipping.")
        return []
    if config.times_per_day <= 0:
        return []

    current = (now or datetime.now(timezone.utc)).astimezone(config.tzinfo)
    created_or_existing: list[TaskRow] = []
    random_source = rng or random.Random()
    for offset in (0, 1):
        target_date = current.date() + timedelta(days=offset)
        created_or_existing.extend(
            ensure_proactive_tasks_for_date(
                store,
                config,
                target_date,
                now=current,
                rng=random_source,
            )
        )
    return created_or_existing


def ensure_proactive_tasks_for_date(
    store: MemoryStore,
    config: ProactiveConfig,
    target_date: date,
    *,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> list[TaskRow]:
    if not config.enabled or not config.channel or config.times_per_day <= 0:
        return []

    random_source = rng or random.Random()
    current = (now or datetime.now(timezone.utc)).astimezone(config.tzinfo)
    run_times = generate_daily_run_times(target_date, config, rng=random_source)
    tasks: list[TaskRow] = []
    for index, local_run_at in enumerate(run_times, start=1):
        if local_run_at <= current:
            continue
        run_at_utc = local_run_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        task = store.create_task(
            title="proactive check-in",
            prompt=DEFAULT_PROMPT,
            run_at=run_at_utc,
            notify_channel=config.channel,
            source_key=build_source_key(target_date, index),
        )
        tasks.append(task)
    return tasks


def generate_daily_run_times(
    target_date: date,
    config: ProactiveConfig,
    *,
    rng: random.Random | None = None,
) -> list[datetime]:
    if config.times_per_day <= 0:
        return []

    start_minute = _minute_of_day(config.window_start)
    end_minute = _minute_of_day(config.window_end)
    if end_minute <= start_minute:
        raise ValueError("PROACTIVE_WINDOW_END must be later than PROACTIVE_WINDOW_START")

    random_source = rng or random.Random()
    window_minutes = end_minute - start_minute
    count = config.times_per_day
    min_gap = max(config.min_gap_minutes, 0)

    if count == 1:
        selected = [random_source.randrange(start_minute, end_minute)]
    else:
        selected = _sample_minutes_with_gap(
            start_minute=start_minute,
            end_minute=end_minute,
            count=count,
            min_gap=min_gap,
            rng=random_source,
        )
        if selected is None:
            step = window_minutes / count
            selected = [int(start_minute + step * index + step / 2) for index in range(count)]

    tzinfo = config.tzinfo
    return [
        datetime.combine(target_date, time(minute // 60, minute % 60), tzinfo=tzinfo)
        for minute in sorted(selected)
    ]


def build_source_key(target_date: date, index: int) -> str:
    return f"{SOURCE_PREFIX}{target_date.isoformat()}:{index}"


def _sample_minutes_with_gap(
    *,
    start_minute: int,
    end_minute: int,
    count: int,
    min_gap: int,
    rng: random.Random,
) -> list[int] | None:
    for _ in range(2000):
        candidates = sorted(rng.sample(range(start_minute, end_minute), count))
        if all(second - first >= min_gap for first, second in zip(candidates, candidates[1:])):
            return candidates
    return None


def _parse_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _parse_int(value: str | None, default: int) -> int:
    if value is None or not value.strip():
        return default
    return int(value)


def _parse_hhmm(value: str | None, default: time) -> time:
    if value is None or not value.strip():
        return default
    hour, minute = value.split(":", 1)
    return time(int(hour), int(minute))


def _minute_of_day(value: time) -> int:
    return value.hour * 60 + value.minute
