from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from .codex_runner import run_codex
from .memory_store import MemoryStore, TaskRow
from .proactive import config_from_env, ensure_proactive_tasks, is_proactive_task
from .schedule_intent_parser import parse_schedule_intent_with_ai
from .scheduler import Scheduler


Reply = Callable[[str], None]


def required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def create_app() -> App:
    load_dotenv()
    memory_store = MemoryStore(os.environ.get("SQLITE_PATH", "data/agent.db"))
    proactive_config = config_from_env()
    seen_events: dict[str, float] = {}

    app = App(
        token=required("SLACK_BOT_TOKEN"),
        process_before_response=False,
        token_verification_enabled=False,
    )

    def run_scheduled_task(task: TaskRow) -> None:
        if is_proactive_task(task):
            try:
                result = run_codex(task.prompt or task.title)
            except Exception as exc:
                print(f"[proactive] Failed to generate message for task #{task.id}: {exc}")
                memory_store.mark_task_run(task.id)
                memory_store.complete_task(task.id)
                return

            memory_store.mark_task_run(task.id)
            memory_store.complete_task(task.id)

            channel = task.notify_channel or proactive_config.channel
            if not channel:
                print(f"[proactive] No Slack channel configured. Task #{task.id} result skipped.")
                return
            response = app.client.chat_postMessage(channel=channel, text=result.text)
            register_bot_started_conversation(
                memory_store=memory_store,
                channel=channel,
                post_response=response,
                text=result.text,
                session_id=result.session_id,
            )
            for proactive_task in ensure_proactive_tasks(memory_store, proactive_config):
                scheduler.schedule(proactive_task)
            return

        result = run_codex(task.prompt or task.title)
        memory_store.mark_task_run(task.id)
        if task.run_at:
            memory_store.complete_task(task.id)

        channel = task.notify_channel or os.environ.get("SLACK_LOG_CHANNEL")
        if not channel:
            print(f"[scheduler] SLACK_LOG_CHANNEL is not configured. Task #{task.id} result skipped.")
            return
        posted_text = f":spiral_calendar_pad: *Scheduled Task:* {task.title}\n\n{result.text}"
        response = app.client.chat_postMessage(
            channel=channel,
            text=posted_text,
        )
        register_bot_started_conversation(
            memory_store=memory_store,
            channel=channel,
            post_response=response,
            text=posted_text,
            session_id=result.session_id,
        )

    scheduler = Scheduler(run_scheduled_task)

    @app.event("app_mention")
    def handle_app_mention(event: dict[str, Any], body: dict[str, Any], say: Callable[..., Any]) -> None:
        if is_duplicate_event(body, seen_events):
            return
        thread_ts = event.get("thread_ts") or event.get("ts")
        conversation_key = build_conversation_key(event.get("channel"), thread_ts)
        source_key = build_source_key(event.get("channel"), event.get("ts"))

        def reply(text: str) -> None:
            say(text=text, thread_ts=thread_ts)

        handle_prompt(
            prompt=event.get("text"),
            reply=reply,
            memory_store=memory_store,
            scheduler=scheduler,
            user=event.get("user"),
            conversation_key=conversation_key,
            source_key=source_key,
        )

    @app.message(re.compile(".*", re.DOTALL))
    def handle_message(message: dict[str, Any], body: dict[str, Any], say: Callable[..., Any]) -> None:
        if is_duplicate_event(body, seen_events):
            return
        if message.get("subtype") or message.get("bot_id"):
            return

        is_direct_message = message.get("channel_type") == "im"
        text = message.get("text")
        is_mention = isinstance(text, str) and "<@" in text
        if is_mention and not is_direct_message:
            return

        if not is_direct_message:
            if not message.get("thread_ts"):
                return
            tracked = memory_store.find_conversation_by_thread(
                build_conversation_key(message.get("channel"), message["thread_ts"])
            )
            if not tracked:
                return

        thread_ts = message.get("thread_ts") or message.get("ts")
        reply_thread_ts = None if is_direct_message else thread_ts
        conversation_key = build_conversation_key(message.get("channel"), thread_ts)
        source_key = build_source_key(message.get("channel"), message.get("ts"))

        def reply(text: str) -> None:
            if reply_thread_ts:
                say(text=text, thread_ts=reply_thread_ts)
            else:
                say(text=text)

        handle_prompt(
            prompt=text,
            reply=reply,
            memory_store=memory_store,
            scheduler=scheduler,
            user=message.get("user"),
            conversation_key=conversation_key,
            source_key=source_key,
        )

    app.client.robopen_memory_store = memory_store  # type: ignore[attr-defined]
    app.client.robopen_scheduler = scheduler  # type: ignore[attr-defined]
    app.client.robopen_proactive_config = proactive_config  # type: ignore[attr-defined]
    return app


def handle_prompt(
    *,
    prompt: str | None,
    reply: Reply,
    memory_store: MemoryStore,
    scheduler: Scheduler,
    user: str | None = None,
    conversation_key: str | None = None,
    source_key: str | None = None,
) -> None:
    trimmed = (prompt or "").strip()
    if not trimmed:
        reply("入力が空です。メッセージを送ってください。")
        return

    ai_intent = None
    if looks_like_schedule_intent(trimmed):
        try:
            ai_intent = parse_schedule_intent_with_ai(trimmed)
        except Exception:
            ai_intent = None

    if ai_intent:
        if source_key and memory_store.find_task_by_source_key(source_key):
            return
        if ai_intent.kind == "cron":
            task = memory_store.create_task(
                title=ai_intent.title,
                prompt=ai_intent.prompt,
                schedule_cron=ai_intent.schedule_cron,
                source_key=source_key,
            )
        else:
            task = memory_store.create_task(
                title=ai_intent.title,
                prompt=ai_intent.prompt,
                run_at=ai_intent.run_at,
                source_key=source_key,
            )
        scheduler.schedule(task)
        reply(build_task_registered_message(task))
        return

    if trimmed.startswith("schedule cron "):
        if source_key and memory_store.find_task_by_source_key(source_key):
            return
        parsed = parse_cron_command(trimmed.removeprefix("schedule cron "))
        task = memory_store.create_task(**parsed, source_key=source_key)
        scheduler.schedule(task)
        reply(build_task_registered_message(task))
        return

    if trimmed.startswith("schedule once "):
        if source_key and memory_store.find_task_by_source_key(source_key):
            return
        parsed = parse_one_shot_command(trimmed.removeprefix("schedule once "))
        task = memory_store.create_task(**parsed, source_key=source_key)
        scheduler.schedule(task)
        reply(build_task_registered_message(task))
        return

    conversation = memory_store.get_or_create_conversation(conversation_key or f"local-{datetime.now().timestamp()}")
    memory_store.append_message(conversation.id, "user", trimmed)

    try:
        result = run_codex(trimmed, conversation.codex_rollout_id)
        if result.session_id and result.session_id != conversation.codex_rollout_id:
            memory_store.set_codex_rollout_id(conversation.id, result.session_id)
        memory_store.append_message(conversation.id, "assistant", result.text)
        user_prefix = f"<@{user}> " if user else ""
        reply(f"{user_prefix}{result.text}")
    except Exception as exc:
        reply(f"Codex実行でエラーが発生しました: {exc}")


def build_task_registered_message(task: TaskRow) -> str:
    schedule = format_schedule_for_jst(task.schedule_cron, task.run_at)
    return f"タスクが登録できました: #{task.id} {task.title} ({schedule})"


def register_bot_started_conversation(
    *,
    memory_store: MemoryStore,
    channel: str,
    post_response: Any,
    text: str,
    session_id: str | None = None,
) -> None:
    post_ts = extract_slack_post_ts(post_response)
    if not post_ts:
        return

    conversation = memory_store.get_or_create_conversation(build_conversation_key(channel, post_ts))
    if session_id and session_id != conversation.codex_rollout_id:
        memory_store.set_codex_rollout_id(conversation.id, session_id)
    memory_store.append_message(conversation.id, "assistant", text)


def extract_slack_post_ts(post_response: Any) -> str | None:
    if post_response is None:
        return None
    if isinstance(post_response, dict):
        ts = post_response.get("ts")
        return ts if isinstance(ts, str) and ts else None

    getter = getattr(post_response, "get", None)
    if callable(getter):
        ts = getter("ts")
        if isinstance(ts, str) and ts:
            return ts

    data = getattr(post_response, "data", None)
    if isinstance(data, dict):
        ts = data.get("ts")
        return ts if isinstance(ts, str) and ts else None

    return None


def format_schedule_for_jst(schedule_cron: str | None, run_at: str | None) -> str:
    if run_at:
        parsed = _parse_iso_datetime(run_at)
        if parsed:
            jst = parsed.astimezone(ZoneInfo("Asia/Tokyo"))
            return f"{jst:%Y/%m/%d %H:%M:%S} JST"

    if schedule_cron:
        converted = convert_cron_utc_to_jst_label(schedule_cron)
        return converted or f"cron: {schedule_cron} (UTC基準)"

    return "時刻未設定"


def convert_cron_utc_to_jst_label(cron: str) -> str | None:
    parts = cron.strip().split()
    if len(parts) != 5:
        return None
    minute, hour, day_of_month, month, day_of_week = parts
    if not minute.isdigit() or not hour.isdigit():
        return None
    base = datetime(2026, 1, 1, int(hour), int(minute), tzinfo=timezone.utc)
    jst = base.astimezone(ZoneInfo("Asia/Tokyo"))
    return f"毎日 {jst:%H:%M} JST (cron: {minute} {hour} {day_of_month} {month} {day_of_week} UTC)"


def looks_like_schedule_intent(text: str) -> bool:
    return any(hint in text for hint in ["毎", "明日", "明後日", "時", "分", "schedule", "cron", "once", "定期", "実行"])


def build_conversation_key(channel: str | None, thread_ts: str | None) -> str:
    if channel and thread_ts:
        return f"{channel}:{thread_ts}"
    return thread_ts or f"local-{datetime.now().timestamp()}"


def build_source_key(channel: str | None, message_ts: str | None) -> str | None:
    if channel and message_ts:
        return f"{channel}:{message_ts}"
    return None


def is_duplicate_event(body: dict[str, Any], seen_events: dict[str, float], ttl_seconds: int = 300) -> bool:
    event_id = body.get("event_id")
    if not isinstance(event_id, str) or not event_id:
        return False

    now = time.monotonic()
    expired = [key for key, seen_at in seen_events.items() if now - seen_at > ttl_seconds]
    for key in expired:
        del seen_events[key]

    if event_id in seen_events:
        return True
    seen_events[event_id] = now
    return False


def parse_cron_command(raw: str) -> dict[str, str]:
    title, schedule_cron, prompt = _parse_pipe_command(raw, "形式: schedule cron <title> | <m h * * d> | <prompt>")
    return {"title": title, "schedule_cron": schedule_cron, "prompt": prompt}


def parse_one_shot_command(raw: str) -> dict[str, str]:
    title, run_at, prompt = _parse_pipe_command(raw, "形式: schedule once <title> | <ISO8601 UTC> | <prompt>")
    return {"title": title, "run_at": run_at, "prompt": prompt}


def _parse_pipe_command(raw: str, error_message: str) -> tuple[str, str, str]:
    parts = [part.strip() for part in raw.split("|")]
    if len(parts) < 3 or not parts[0] or not parts[1] or not parts[2]:
        raise ValueError(error_message)
    return parts[0], parts[1], " | ".join(parts[2:])


def _parse_iso_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def main() -> None:
    app = create_app()
    scheduler = app.client.robopen_scheduler  # type: ignore[attr-defined]
    memory_store = app.client.robopen_memory_store  # type: ignore[attr-defined]
    proactive_config = app.client.robopen_proactive_config  # type: ignore[attr-defined]
    memory_store.complete_expired_one_shot_tasks()
    ensure_proactive_tasks(memory_store, proactive_config)
    scheduler.restore(memory_store.list_active_tasks())
    SocketModeHandler(app, required("SLACK_APP_TOKEN")).start()
