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


def parse_schedule_intent_with_ai(input_text: str) -> ParsedScheduleIntent | None:
    parsing_prompt = "\n".join(
        [
            "あなたはスケジューラ登録の抽出器です。",
            "ユーザー入力から「実行時点」と「実行タスク」を抽出してください。",
            "出力はJSONのみ。余計な文章は禁止。",
            "フォーマット:",
            '{"kind":"cron|once","title":"...","prompt":"...","scheduleCron":"m h * * d"|null,"runAt":"ISO8601 UTC"|null,"confidence":0.0}',
            "ルール:",
            "- 「毎朝9時」「毎日21時」など反復は kind=cron, UTCの5フィールドcronに変換。",
            "- 「明日9時」「2026-05-11 09:00」など単発は kind=once, runAtはUTCのISO8601。",
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

