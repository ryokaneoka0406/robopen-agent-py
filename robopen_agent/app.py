from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from .codex_runner import run_codex
from .file_sender import (
    FileSenderError,
    FileUploadRequest,
    build_file_list_message,
    build_upload_log,
    extract_upload_manifests,
    get_slack_file_root,
    list_share_files,
    parse_file_send_command,
    parse_natural_file_request,
    resolve_share_path,
    upload_file_to_slack,
)
from .memory_store import MemoryStore, TaskRow
from .proactive import config_from_env, ensure_proactive_tasks, is_proactive_task
from .schedule_intent_parser import (
    ParsedScheduleDeleteIntent,
    ParsedScheduleUpdateIntent,
    parse_schedule_intent_with_ai,
)
from .scheduler import CRON_PATTERN, Scheduler


Reply = Callable[[str], None]


@dataclass(frozen=True)
class PendingScheduleDelete:
    task_id: int


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
    pending_schedule_deletions: dict[str, PendingScheduleDelete] = {}

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
            pending_schedule_deletions=pending_schedule_deletions,
            slack_client=app.client,
            slack_channel=event.get("channel"),
            slack_thread_ts=thread_ts,
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
            pending_schedule_deletions=pending_schedule_deletions,
            slack_client=app.client,
            slack_channel=message.get("channel"),
            slack_thread_ts=reply_thread_ts,
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
    pending_schedule_deletions: dict[str, PendingScheduleDelete] | None = None,
    slack_client: Any | None = None,
    slack_channel: str | None = None,
    slack_thread_ts: str | None = None,
) -> None:
    trimmed = (prompt or "").strip()
    if not trimmed:
        reply("入力が空です。メッセージを送ってください。")
        return

    pending_delete = find_pending_schedule_delete(
        conversation_key=conversation_key,
        pending_schedule_deletions=pending_schedule_deletions,
    )
    if pending_delete and is_schedule_delete_denial(trimmed):
        if pending_schedule_deletions is not None and conversation_key:
            pending_schedule_deletions.pop(conversation_key, None)
        reply("タスク削除をキャンセルしました。")
        return
    if pending_delete and is_schedule_delete_confirmation(trimmed, pending_delete.task_id):
        confirm_schedule_delete(
            task_id=pending_delete.task_id,
            reply=reply,
            memory_store=memory_store,
            scheduler=scheduler,
            conversation_key=conversation_key,
            pending_schedule_deletions=pending_schedule_deletions,
        )
        return

    if trimmed == "schedule list":
        reply(build_task_list_message(memory_store.list_active_tasks()))
        return

    if trimmed == "file list":
        reply(build_file_list_message(list_share_files()))
        return

    try:
        file_send_request = parse_file_send_command(trimmed)
    except FileSenderError as exc:
        reply(str(exc))
        return
    if file_send_request:
        upload_file_request(
            request=file_send_request,
            reply=reply,
            memory_store=memory_store,
            conversation_key=conversation_key,
            slack_client=slack_client,
            slack_channel=slack_channel,
            slack_thread_ts=slack_thread_ts,
        )
        return

    if trimmed.startswith("schedule delete confirm "):
        try:
            task_id = parse_schedule_delete_confirm_command(
                trimmed.removeprefix("schedule delete confirm ")
            )
        except ValueError as exc:
            reply(str(exc))
            return
        confirm_schedule_delete(
            task_id=task_id,
            reply=reply,
            memory_store=memory_store,
            scheduler=scheduler,
            conversation_key=conversation_key,
            pending_schedule_deletions=pending_schedule_deletions,
        )
        return

    if trimmed.startswith("schedule delete "):
        try:
            task_id = parse_schedule_delete_command(trimmed.removeprefix("schedule delete "))
        except ValueError as exc:
            reply(str(exc))
            return
        task = find_active_task_by_id(task_id, memory_store.list_active_tasks())
        if not task:
            reply(f"削除対象が見つかりませんでした: #{task_id}")
            return
        request_schedule_delete_confirmation(
            task=task,
            reply=reply,
            memory_store=memory_store,
            conversation_key=conversation_key,
            pending_schedule_deletions=pending_schedule_deletions,
        )
        return

    if trimmed.startswith("schedule update "):
        try:
            task_id, schedule_cron = parse_schedule_update_command(
                trimmed.removeprefix("schedule update ")
            )
        except ValueError as exc:
            reply(str(exc))
            return
        update_cron_task_from_command(
            task_id=task_id,
            schedule_cron=schedule_cron,
            reply=reply,
            memory_store=memory_store,
            scheduler=scheduler,
        )
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

    ai_intent = None
    if looks_like_schedule_intent(trimmed):
        try:
            ai_intent = parse_schedule_intent_with_ai(trimmed)
        except Exception:
            ai_intent = None

    if ai_intent:
        if isinstance(ai_intent, ParsedScheduleUpdateIntent):
            update_cron_task_from_intent(
                intent=ai_intent,
                reply=reply,
                memory_store=memory_store,
                scheduler=scheduler,
            )
            return
        if isinstance(ai_intent, ParsedScheduleDeleteIntent):
            request_schedule_delete_from_intent(
                intent=ai_intent,
                reply=reply,
                memory_store=memory_store,
                conversation_key=conversation_key,
                pending_schedule_deletions=pending_schedule_deletions,
            )
            return
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

    natural_file_request = parse_natural_file_request(trimmed)
    if isinstance(natural_file_request, str):
        reply(natural_file_request)
        return
    if natural_file_request:
        upload_file_request(
            request=natural_file_request,
            reply=reply,
            memory_store=memory_store,
            conversation_key=conversation_key,
            slack_client=slack_client,
            slack_channel=slack_channel,
            slack_thread_ts=slack_thread_ts,
        )
        return

    conversation = memory_store.get_or_create_conversation(conversation_key or f"local-{datetime.now().timestamp()}")
    memory_store.append_message(conversation.id, "user", trimmed)

    try:
        result = run_codex(trimmed, conversation.codex_rollout_id)
        if result.session_id and result.session_id != conversation.codex_rollout_id:
            memory_store.set_codex_rollout_id(conversation.id, result.session_id)
        try:
            extraction = extract_upload_manifests(result.text)
        except FileSenderError as exc:
            memory_store.append_message(conversation.id, "assistant", result.text)
            user_prefix = f"<@{user}> " if user else ""
            reply(f"{user_prefix}{result.text}")
            reply(f"ファイル送信に失敗しました: {exc}")
            return

        assistant_text = extraction.text or "(ファイル送信を実行します)"
        memory_store.append_message(conversation.id, "assistant", assistant_text)
        user_prefix = f"<@{user}> " if user else ""
        reply(f"{user_prefix}{assistant_text}")
        for upload_request in extraction.requests:
            upload_file_request(
                request=upload_request,
                reply=reply,
                memory_store=memory_store,
                conversation_key=conversation_key,
                slack_client=slack_client,
                slack_channel=slack_channel,
                slack_thread_ts=slack_thread_ts,
                failure_prefix="ファイル送信に失敗しました",
            )
    except Exception as exc:
        reply(f"Codex実行でエラーが発生しました: {exc}")


def upload_file_request(
    *,
    request: FileUploadRequest,
    reply: Reply,
    memory_store: MemoryStore,
    conversation_key: str | None,
    slack_client: Any | None,
    slack_channel: str | None,
    slack_thread_ts: str | None,
    failure_prefix: str = "ファイル送信に失敗しました",
) -> None:
    if slack_client is None or not slack_channel:
        reply("Slack送信先が特定できないため、ファイルを送信できません。")
        return

    try:
        path = resolve_share_path(request.path)
        result = upload_file_to_slack(
            client=slack_client,
            channel=slack_channel,
            path=path,
            thread_ts=slack_thread_ts,
            initial_comment=request.comment,
        )
    except Exception as exc:
        reply(f"{failure_prefix}: {exc}")
        return

    if conversation_key:
        conversation = memory_store.get_or_create_conversation(conversation_key)
        root = get_slack_file_root()
        try:
            relative_path = path.relative_to(root).as_posix()
        except ValueError:
            relative_path = request.path
        memory_store.append_message(conversation.id, "assistant", build_upload_log(result, relative_path))
    reply(f"ファイルを送信しました: {request.path}")


def build_task_registered_message(task: TaskRow) -> str:
    schedule = format_schedule_for_jst(task.schedule_cron, task.run_at)
    return f"タスクが登録できました: #{task.id} {task.title} ({schedule})"


def build_task_updated_message(task: TaskRow) -> str:
    return f"タスクを更新しました: #{task.id} {task.title} ({format_schedule_for_jst(task.schedule_cron, task.run_at)})"


def build_task_delete_requested_message(task: TaskRow) -> str:
    schedule = format_schedule_for_jst(task.schedule_cron, task.run_at)
    return (
        f"削除確認: #{task.id} {task.title} ({schedule}) を削除します。\n"
        f"実行する場合は `schedule delete confirm {task.id}`、または `はい` / `削除して` と返信してください。"
    )


def build_task_deleted_message(task: TaskRow) -> str:
    return f"タスクを削除しました: #{task.id} {task.title}"


def build_task_list_message(tasks: list[TaskRow]) -> str:
    if not tasks:
        return "登録済みタスクはありません。"
    lines = ["登録済みタスク:"]
    for task in tasks:
        lines.append(
            f"#{task.id} [{task.status}] {task.title} - {format_schedule_for_jst(task.schedule_cron, task.run_at)}"
        )
    return "\n".join(lines)


def update_cron_task_from_command(
    *,
    task_id: int,
    schedule_cron: str,
    reply: Reply,
    memory_store: MemoryStore,
    scheduler: Scheduler,
) -> None:
    if not is_supported_cron(schedule_cron):
        reply('cron形式が不正です。形式: "m h * * d"')
        return

    task = memory_store.update_cron_task(task_id, schedule_cron)
    if not task:
        reply(f"更新できませんでした: #{task_id} はactiveなcronタスクではありません。")
        return

    scheduler.schedule(task)
    reply(build_task_updated_message(task))


def update_cron_task_from_intent(
    *,
    intent: ParsedScheduleUpdateIntent,
    reply: Reply,
    memory_store: MemoryStore,
    scheduler: Scheduler,
) -> None:
    if not is_supported_cron(intent.schedule_cron):
        reply('cron形式が不正です。形式: "m h * * d"')
        return

    target = find_update_target(intent, memory_store.list_active_tasks())
    if isinstance(target, str):
        reply(target)
        return

    update_cron_task_from_command(
        task_id=target.id,
        schedule_cron=intent.schedule_cron,
        reply=reply,
        memory_store=memory_store,
        scheduler=scheduler,
    )


def request_schedule_delete_from_intent(
    *,
    intent: ParsedScheduleDeleteIntent,
    reply: Reply,
    memory_store: MemoryStore,
    conversation_key: str | None,
    pending_schedule_deletions: dict[str, PendingScheduleDelete] | None = None,
) -> None:
    target = find_delete_target(intent, memory_store.list_active_tasks())
    if isinstance(target, str):
        reply(target)
        return
    request_schedule_delete_confirmation(
        task=target,
        reply=reply,
        memory_store=memory_store,
        conversation_key=conversation_key,
        pending_schedule_deletions=pending_schedule_deletions,
    )


def request_schedule_delete_confirmation(
    *,
    task: TaskRow,
    reply: Reply,
    memory_store: MemoryStore,
    conversation_key: str | None,
    pending_schedule_deletions: dict[str, PendingScheduleDelete] | None = None,
) -> None:
    if pending_schedule_deletions is not None and conversation_key:
        pending_schedule_deletions[conversation_key] = PendingScheduleDelete(task_id=task.id)
    if conversation_key:
        memory_store.get_or_create_conversation(conversation_key)
    reply(build_task_delete_requested_message(task))


def confirm_schedule_delete(
    *,
    task_id: int,
    reply: Reply,
    memory_store: MemoryStore,
    scheduler: Scheduler,
    conversation_key: str | None,
    pending_schedule_deletions: dict[str, PendingScheduleDelete] | None = None,
) -> None:
    if pending_schedule_deletions is not None and conversation_key:
        pending = pending_schedule_deletions.get(conversation_key)
        if pending is None or pending.task_id != task_id:
            reply("削除確認が見つかりませんでした。先に `schedule delete <task_id>` を送ってください。")
            return

    task = find_active_task_by_id(task_id, memory_store.list_active_tasks())
    if not task:
        if pending_schedule_deletions is not None and conversation_key:
            pending_schedule_deletions.pop(conversation_key, None)
        reply(f"削除対象が見つかりませんでした: #{task_id}")
        return

    memory_store.cancel_task(task.id)
    scheduler.unschedule(task.id)
    if pending_schedule_deletions is not None and conversation_key:
        pending_schedule_deletions.pop(conversation_key, None)
    reply(build_task_deleted_message(task))


def find_pending_schedule_delete(
    *,
    conversation_key: str | None,
    pending_schedule_deletions: dict[str, PendingScheduleDelete] | None = None,
) -> PendingScheduleDelete | None:
    if pending_schedule_deletions is None or not conversation_key:
        return None
    return pending_schedule_deletions.get(conversation_key)


def is_schedule_delete_confirmation(text: str, pending_task_id: int) -> bool:
    task_id = extract_task_id_reference(text)
    if task_id is not None and task_id != pending_task_id:
        return False

    normalized = text.strip().lower()
    confirmations = {
        "yes",
        "y",
        "ok",
        "okay",
        "confirm",
        "はい",
        "うん",
        "お願い",
        "お願いします",
        "実行",
        "実行して",
        "削除",
        "削除して",
        "消して",
        "確定",
        "確定して",
    }
    if normalized in confirmations:
        return True

    return any(
        phrase in text
        for phrase in [
            "削除していい",
            "削除を実行",
            "削除を確定",
            "消していい",
            "実行していい",
            "そのまま実行",
            "それでお願い",
        ]
    )


def is_schedule_delete_denial(text: str) -> bool:
    normalized = text.strip().lower()
    denials = {
        "no",
        "n",
        "cancel",
        "deny",
        "いいえ",
        "いや",
        "キャンセル",
        "やめて",
        "中止",
        "取り消し",
        "取消",
    }
    if normalized in denials:
        return True
    return any(phrase in text for phrase in ["削除しない", "やっぱりやめ", "取り消して", "中止して"])


def extract_task_id_reference(text: str) -> int | None:
    match = re.search(r"#?(\d+)", text)
    if not match:
        return None
    return int(match.group(1))


def find_update_target(
    intent: ParsedScheduleUpdateIntent, tasks: list[TaskRow]
) -> TaskRow | str:
    cron_tasks = [task for task in tasks if task.schedule_cron]
    if intent.task_id is not None:
        for task in cron_tasks:
            if task.id == intent.task_id:
                return task
        return f"更新できませんでした: #{intent.task_id} はactiveなcronタスクではありません。"

    query = (intent.target_query or "").strip()
    if not query:
        return "更新対象のタスクを特定できませんでした。schedule listでIDを確認してください。"

    matches = [
        task for task in cron_tasks if query in task.title or query in task.prompt
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        return f"更新対象のタスクが見つかりませんでした: {query}"
    return "更新対象が複数あります。schedule listでIDを確認して #ID を指定してください。"


def find_delete_target(
    intent: ParsedScheduleDeleteIntent, tasks: list[TaskRow]
) -> TaskRow | str:
    if intent.task_id is not None:
        for task in tasks:
            if task.id == intent.task_id:
                return task
        return f"削除対象が見つかりませんでした: #{intent.task_id}"

    query = (intent.target_query or "").strip()
    if not query:
        return "削除対象のタスクを特定できませんでした。schedule listでIDを確認してください。"

    matches = [
        task for task in tasks if query in task.title or query in task.prompt
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        return f"削除対象のタスクが見つかりませんでした: {query}"
    return "削除対象が複数あります。schedule listでIDを確認して #ID を指定してください。"


def find_active_task_by_id(task_id: int, tasks: list[TaskRow]) -> TaskRow | None:
    for task in tasks:
        if task.id == task_id:
            return task
    return None


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
    return any(
        hint in text
        for hint in [
            "毎",
            "明日",
            "明後日",
            "時",
            "分",
            "schedule",
            "cron",
            "once",
            "定期",
            "実行",
            "削除",
            "消して",
            "解除",
            "キャンセル",
            "delete",
        ]
    )


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


def parse_schedule_update_command(raw: str) -> tuple[int, str]:
    parts = [part.strip() for part in raw.split("|", 1)]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("形式: schedule update <task_id> | <m h * * d>")
    try:
        task_id = int(parts[0])
    except ValueError as exc:
        raise ValueError("task_idは数値で指定してください。") from exc
    if task_id <= 0:
        raise ValueError("task_idは1以上の数値で指定してください。")
    return task_id, parts[1]


def parse_schedule_delete_command(raw: str) -> int:
    stripped = raw.strip()
    if not stripped:
        raise ValueError("形式: schedule delete <task_id>")
    try:
        task_id = int(stripped.removeprefix("#"))
    except ValueError as exc:
        raise ValueError("task_idは数値で指定してください。") from exc
    if task_id <= 0:
        raise ValueError("task_idは1以上の数値で指定してください。")
    return task_id


def parse_schedule_delete_confirm_command(raw: str) -> int:
    stripped = raw.strip()
    if not stripped:
        raise ValueError("形式: schedule delete confirm <task_id>")
    return parse_schedule_delete_command(stripped)


def is_supported_cron(cron: str) -> bool:
    return bool(CRON_PATTERN.match(cron))


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
