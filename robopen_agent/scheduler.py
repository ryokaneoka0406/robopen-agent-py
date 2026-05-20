from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from .memory_store import TaskRow


RunTask = Callable[[TaskRow], None]


@dataclass
class ScheduledHandle:
    key: str
    cancel: Callable[[], None]


CRON_PATTERN = re.compile(r"^(\*|[0-5]?\d)\s+(\*|[01]?\d|2[0-3])\s+\*\s+\*\s+(\*|[0-6])$")


class Scheduler:
    def __init__(self, run_task: RunTask) -> None:
        self.run_task = run_task
        self.handles: dict[int, ScheduledHandle] = {}

    def restore(self, tasks: list[TaskRow]) -> None:
        for task in tasks:
            if task.status == "active":
                self.schedule(task)

    def schedule(self, task: TaskRow) -> None:
        self.unschedule(task.id)
        if task.run_at:
            self._schedule_one_shot(task)
            return
        if task.schedule_cron:
            self._schedule_cron(task)

    def unschedule(self, task_id: int) -> None:
        existing = self.handles.get(task_id)
        if not existing:
            return
        existing.cancel()
        del self.handles[task_id]

    def _schedule_one_shot(self, task: TaskRow) -> None:
        target = _parse_iso_datetime(task.run_at or "")
        if not target:
            return
        delay = (target - datetime.now(timezone.utc)).total_seconds()
        if delay <= 0:
            return

        def run_and_remove() -> None:
            try:
                self.run_task(task)
            finally:
                self.unschedule(task.id)

        timer = threading.Timer(delay, run_and_remove)
        timer.daemon = True
        timer.start()
        self.handles[task.id] = ScheduledHandle(
            key=str(uuid.uuid4()),
            cancel=timer.cancel,
        )

    def _schedule_cron(self, task: TaskRow) -> None:
        cron = task.schedule_cron or ""
        match = CRON_PATTERN.match(cron)
        if not match:
            raise ValueError(f'Unsupported cron format: {cron}. Use "m h * * d".')

        minute, hour, day_of_week = match.groups()
        cancelled = threading.Event()

        def tick_loop() -> None:
            self._run_if_due(task, minute, hour, day_of_week)
            while not cancelled.wait(60):
                self._run_if_due(task, minute, hour, day_of_week)

        thread = threading.Thread(target=tick_loop, daemon=True)
        thread.start()
        self.handles[task.id] = ScheduledHandle(
            key=str(uuid.uuid4()),
            cancel=cancelled.set,
        )

    def _run_if_due(self, task: TaskRow, minute: str, hour: str, day_of_week: str) -> None:
        now = datetime.now(timezone.utc)
        minute_ok = minute == "*" or now.minute == int(minute)
        hour_ok = hour == "*" or now.hour == int(hour)
        day_ok = day_of_week == "*" or _js_day_of_week(now) == int(day_of_week)
        if minute_ok and hour_ok and day_ok:
            try:
                self.run_task(task)
            except Exception as exc:
                print(f"[scheduler] Failed task {task.id}: {exc}")


def _parse_iso_datetime(value: str) -> datetime | None:
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _js_day_of_week(value: datetime) -> int:
    return (value.weekday() + 1) % 7

