from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from .codex_runner import run_codex


@dataclass(frozen=True)
class ParsedScheduleIntent:
    kind: Literal["cron", "once"]
    title: str
    prompt: str
    confidence: float
    schedule_cron: str | None = None
    run_at: str | None = None


@dataclass(frozen=True)
class ParsedScheduleUpdateIntent:
    kind: Literal["update"]
    schedule_cron: str
    confidence: float
    task_id: int | None = None
    target_query: str | None = None


@dataclass(frozen=True)
class ParsedScheduleDeleteIntent:
    kind: Literal["delete"]
    confidence: float
    task_id: int | None = None
    target_query: str | None = None


ScheduleIntent = ParsedScheduleIntent | ParsedScheduleUpdateIntent | ParsedScheduleDeleteIntent


def parse_schedule_intent_with_ai(input_text: str) -> ScheduleIntent | None:
    parsing_prompt = "\n".join(
        [
            "あなたはスケジューラ操作の抽出器です。",
            "ユーザー入力から「新規登録」「既存cronタスクの時刻変更」「既存タスクの削除依頼」を抽出してください。",
            "出力はJSONのみ。余計な文章は禁止。",
            "フォーマット:",
            '{"kind":"cron|once|update|delete","title":"...","prompt":"...","scheduleCron":"m h * * d"|null,"runAt":"ISO8601 UTC"|null,"taskId":123|null,"targetQuery":"..."|null,"confidence":0.0}',
            "ルール:",
            "- 「毎朝9時」「毎日21時」など反復は kind=cron, UTCの5フィールドcronに変換。",
            "- 「明日9時」「2026-05-11 09:00」など単発は kind=once, runAtはUTCのISO8601。",
            "- 「#12を毎朝8時に変えて」のような既存タスク変更は kind=update, taskId=12, scheduleCronを設定。",
            "- 「朝の要約を8時半にして」のような既存タスク変更は kind=update, targetQueryに対象名, scheduleCronを設定。",
            "- 「#12を削除して」のような既存タスク削除依頼は kind=delete, taskId=12 を設定。",
            "- 「朝の要約を消して」のような既存タスク削除依頼は kind=delete, targetQueryに対象名を設定。",
            "- updateではtitle/prompt/runAtはnullまたは空文字でよい。",
            "- deleteではtitle/prompt/scheduleCron/runAtはnullまたは空文字でよい。",
            "- titleは短い要約。promptは実行してほしい本文。",
            '- スケジュール意図が無ければ {"kind":"none","confidence":0} を返す。',
            f"入力: {input_text}",
        ]
    )

    text = run_codex(parsing_prompt).text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None

    parsed = json.loads(text[start : end + 1])
    if parsed.get("kind") in (None, "none"):
        return None
    confidence = parsed.get("confidence")
    if not isinstance(confidence, (int, float)) or confidence < 0.6:
        return None

    schedule_cron = parsed.get("scheduleCron")
    if parsed.get("kind") == "update" and isinstance(schedule_cron, str) and schedule_cron:
        task_id = parsed.get("taskId")
        target_query = parsed.get("targetQuery")
        if not isinstance(task_id, int):
            task_id = None
        if not isinstance(target_query, str) or not target_query.strip():
            target_query = None
        if task_id is None and target_query is None:
            return None
        return ParsedScheduleUpdateIntent(
            kind="update",
            task_id=task_id,
            target_query=target_query,
            schedule_cron=schedule_cron,
            confidence=float(confidence),
        )

    if parsed.get("kind") == "delete":
        task_id = parsed.get("taskId")
        target_query = parsed.get("targetQuery")
        if not isinstance(task_id, int):
            task_id = None
        if not isinstance(target_query, str) or not target_query.strip():
            target_query = None
        if task_id is None and target_query is None:
            return None
        return ParsedScheduleDeleteIntent(
            kind="delete",
            task_id=task_id,
            target_query=target_query,
            confidence=float(confidence),
        )

    if parsed.get("kind") == "cron" and parsed.get("title") and parsed.get("prompt") and parsed.get("scheduleCron"):
        return ParsedScheduleIntent(
            kind="cron",
            title=parsed["title"],
            prompt=parsed["prompt"],
            schedule_cron=parsed["scheduleCron"],
            confidence=float(confidence),
        )

    if parsed.get("kind") == "once" and parsed.get("title") and parsed.get("prompt") and parsed.get("runAt"):
        return ParsedScheduleIntent(
            kind="once",
            title=parsed["title"],
            prompt=parsed["prompt"],
            run_at=parsed["runAt"],
            confidence=float(confidence),
        )

    return None
