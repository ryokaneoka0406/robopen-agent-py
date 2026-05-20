from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Conversation:
    id: int
    slack_thread_ts: str
    codex_rollout_id: str | None
    parent_conversation_id: int | None
    started_at: str
    summary: str | None
    token_usage_estimate: int
    last_active_at: str


@dataclass(frozen=True)
class MessageRow:
    role: str
    content: str


@dataclass(frozen=True)
class TaskRow:
    id: int
    title: str
    prompt: str
    schedule_cron: str | None
    run_at: str | None
    last_run_at: str | None
    status: str
    notify_channel: str | None
    source_key: str | None = None


class MemoryStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self.db.close()

    def _init_schema(self) -> None:
        self.db.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS conversations (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              slack_thread_ts TEXT NOT NULL UNIQUE,
              codex_rollout_id TEXT,
              parent_conversation_id INTEGER,
              started_at TEXT NOT NULL,
              summary TEXT,
              token_usage_estimate INTEGER NOT NULL DEFAULT 0,
              last_active_at TEXT NOT NULL,
              FOREIGN KEY(parent_conversation_id) REFERENCES conversations(id)
            );
            CREATE TABLE IF NOT EXISTS messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              conversation_id INTEGER NOT NULL,
              role TEXT NOT NULL,
              content TEXT NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY(conversation_id) REFERENCES conversations(id)
            );
            CREATE TABLE IF NOT EXISTS tasks (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              title TEXT NOT NULL,
              prompt TEXT NOT NULL DEFAULT '',
              schedule_cron TEXT,
              run_at TEXT,
              last_run_at TEXT,
              status TEXT NOT NULL,
              notify_channel TEXT,
              source_key TEXT UNIQUE
            );
            CREATE TABLE IF NOT EXISTS preferences (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              action TEXT NOT NULL,
              target TEXT,
              approved_by TEXT,
              created_at TEXT NOT NULL
            );
            """
        )
        self._add_column_if_missing("tasks", "prompt", "TEXT NOT NULL DEFAULT ''")
        self._add_column_if_missing("tasks", "run_at", "TEXT")
        self._add_column_if_missing("tasks", "notify_channel", "TEXT")
        self._add_column_if_missing("tasks", "source_key", "TEXT")
        self.db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_source_key ON tasks(source_key) WHERE source_key IS NOT NULL"
        )
        self.db.commit()

    def _add_column_if_missing(self, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in self.db.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def get_or_create_conversation(self, slack_thread_ts: str) -> Conversation:
        existing = self.find_conversation_by_thread(slack_thread_ts)
        if existing:
            return existing
        now = utc_now_iso()
        self.db.execute(
            """
            INSERT INTO conversations
              (slack_thread_ts, codex_rollout_id, parent_conversation_id, started_at,
               summary, token_usage_estimate, last_active_at)
            VALUES (?, NULL, NULL, ?, NULL, 0, ?)
            """,
            (slack_thread_ts, now, now),
        )
        self.db.commit()
        return self.find_conversation_by_thread(slack_thread_ts)  # type: ignore[return-value]

    def find_conversation_by_thread(self, slack_thread_ts: str) -> Conversation | None:
        row = self.db.execute(
            "SELECT * FROM conversations WHERE slack_thread_ts = ?", (slack_thread_ts,)
        ).fetchone()
        return _conversation(row) if row else None

    def set_codex_rollout_id(self, conversation_id: int, rollout_id: str) -> None:
        self.db.execute(
            "UPDATE conversations SET codex_rollout_id = ? WHERE id = ?",
            (rollout_id, conversation_id),
        )
        self.db.commit()

    def append_message(
        self, conversation_id: int, role: Literal["user", "assistant"], content: str
    ) -> None:
        now = utc_now_iso()
        self.db.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (conversation_id, role, content, now),
        )
        self.db.execute(
            "UPDATE conversations SET last_active_at = ? WHERE id = ?",
            (now, conversation_id),
        )
        self.db.commit()

    def get_recent_context(self, conversation_id: int, limit: int = 8) -> list[MessageRow]:
        rows = self.db.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
        return [MessageRow(role=row["role"], content=row["content"]) for row in rows]

    def get_summary(self, conversation_id: int) -> str | None:
        row = self.db.execute(
            "SELECT summary FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        return row["summary"] if row else None

    def list_active_tasks(self) -> list[TaskRow]:
        rows = self.db.execute("SELECT * FROM tasks WHERE status = 'active'").fetchall()
        return [_task(row) for row in rows]

    def find_task_by_source_key(self, source_key: str) -> TaskRow | None:
        row = self.db.execute("SELECT * FROM tasks WHERE source_key = ?", (source_key,)).fetchone()
        return _task(row) if row else None

    def create_task(
        self,
        *,
        title: str,
        prompt: str,
        schedule_cron: str | None = None,
        run_at: str | None = None,
        notify_channel: str | None = None,
        source_key: str | None = None,
    ) -> TaskRow:
        try:
            self.db.execute(
                """
                INSERT INTO tasks (title, prompt, schedule_cron, run_at, status, notify_channel, source_key)
                VALUES (?, ?, ?, ?, 'active', ?, ?)
                """,
                (title, prompt, schedule_cron, run_at, notify_channel, source_key),
            )
            self.db.commit()
        except sqlite3.IntegrityError:
            if not source_key:
                raise
            self.db.rollback()

        if source_key:
            row = self.db.execute("SELECT * FROM tasks WHERE source_key = ?", (source_key,)).fetchone()
        else:
            row = self.db.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT 1").fetchone()
        return _task(row)

    def cancel_task(self, task_id: int) -> None:
        self.db.execute("UPDATE tasks SET status = 'cancelled' WHERE id = ?", (task_id,))
        self.db.commit()

    def mark_task_run(self, task_id: int) -> None:
        self.db.execute(
            "UPDATE tasks SET last_run_at = ? WHERE id = ?", (utc_now_iso(), task_id)
        )
        self.db.commit()

    def complete_task(self, task_id: int) -> None:
        self.db.execute("UPDATE tasks SET status = 'done' WHERE id = ?", (task_id,))
        self.db.commit()

    def complete_expired_one_shot_tasks(self, now_iso: str | None = None) -> None:
        now = now_iso or utc_now_iso()
        self.db.execute(
            """
            UPDATE tasks
               SET status = 'done'
             WHERE status = 'active'
               AND run_at IS NOT NULL
               AND run_at <= ?
            """,
            (now,),
        )
        self.db.commit()


def _conversation(row: sqlite3.Row) -> Conversation:
    return Conversation(
        id=row["id"],
        slack_thread_ts=row["slack_thread_ts"],
        codex_rollout_id=row["codex_rollout_id"],
        parent_conversation_id=row["parent_conversation_id"],
        started_at=row["started_at"],
        summary=row["summary"],
        token_usage_estimate=row["token_usage_estimate"],
        last_active_at=row["last_active_at"],
    )


def _task(row: sqlite3.Row) -> TaskRow:
    return TaskRow(
        id=row["id"],
        title=row["title"],
        prompt=row["prompt"],
        schedule_cron=row["schedule_cron"],
        run_at=row["run_at"],
        last_run_at=row["last_run_at"],
        status=row["status"],
        notify_channel=row["notify_channel"],
        source_key=row["source_key"] if "source_key" in row.keys() else None,
    )
