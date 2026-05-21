import sqlite3

from robopen_agent.memory_store import MemoryStore


def test_conversation_and_messages_round_trip(tmp_path):
    store = MemoryStore(str(tmp_path / "agent.db"))
    try:
        conversation = store.get_or_create_conversation("123.456")
        same = store.get_or_create_conversation("123.456")

        assert same.id == conversation.id

        store.append_message(conversation.id, "user", "hello")
        store.append_message(conversation.id, "assistant", "world")
        recent = store.get_recent_context(conversation.id)

        assert [row.content for row in recent] == ["world", "hello"]
    finally:
        store.close()


def test_agent_session_prefers_matching_engine(tmp_path):
    store = MemoryStore(str(tmp_path / "agent.db"))
    try:
        conversation = store.get_or_create_conversation("123.456")
        store.set_agent_session(conversation.id, "claude", "claude-session")

        updated = store.get_or_create_conversation("123.456")

        assert store.get_agent_session_id(updated, "claude") == "claude-session"
        assert store.get_agent_session_id(updated, "codex") is None
    finally:
        store.close()


def test_existing_codex_rollout_migrates_to_agent_session(tmp_path):
    db_path = tmp_path / "agent.db"
    db = sqlite3.connect(db_path)
    db.execute(
        """
        CREATE TABLE conversations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          slack_thread_ts TEXT NOT NULL UNIQUE,
          codex_rollout_id TEXT,
          parent_conversation_id INTEGER,
          started_at TEXT NOT NULL,
          summary TEXT,
          token_usage_estimate INTEGER NOT NULL DEFAULT 0,
          last_active_at TEXT NOT NULL
        )
        """
    )
    db.execute(
        """
        INSERT INTO conversations
          (slack_thread_ts, codex_rollout_id, parent_conversation_id, started_at,
           summary, token_usage_estimate, last_active_at)
        VALUES ('123.456', 'codex-thread', NULL, '2026-05-20T00:00:00Z', NULL, 0,
                '2026-05-20T00:00:00Z')
        """
    )
    db.commit()
    db.close()

    store = MemoryStore(str(db_path))
    try:
        migrated = store.get_or_create_conversation("123.456")

        assert migrated.agent_engine == "codex"
        assert migrated.agent_session_id == "codex-thread"
        assert store.get_agent_session_id(migrated, "codex") == "codex-thread"
    finally:
        store.close()


def test_task_lifecycle(tmp_path):
    store = MemoryStore(str(tmp_path / "agent.db"))
    try:
        task = store.create_task(title="daily", prompt="run", schedule_cron="0 0 * * *")

        assert task.id > 0
        assert store.list_active_tasks()[0].title == "daily"

        store.mark_task_run(task.id)
        store.complete_task(task.id)

        assert store.list_active_tasks() == []
    finally:
        store.close()


def test_task_source_key_is_idempotent(tmp_path):
    store = MemoryStore(str(tmp_path / "agent.db"))
    try:
        first = store.create_task(
            title="say hello",
            prompt="hello",
            run_at="2026-05-20T12:00:00Z",
            source_key="C123:1710000000.000100",
        )
        second = store.create_task(
            title="say hello again",
            prompt="hello again",
            run_at="2026-05-20T12:01:00Z",
            source_key="C123:1710000000.000100",
        )

        assert second.id == first.id
        assert second.title == first.title
        assert store.find_task_by_source_key("C123:1710000000.000100") == first
    finally:
        store.close()


def test_complete_expired_one_shot_tasks(tmp_path):
    store = MemoryStore(str(tmp_path / "agent.db"))
    try:
        expired = store.create_task(title="expired", prompt="run", run_at="2026-05-20T12:00:00Z")
        future = store.create_task(title="future", prompt="run", run_at="2026-05-20T12:10:00Z")
        cron = store.create_task(title="cron", prompt="run", schedule_cron="0 0 * * *")

        store.complete_expired_one_shot_tasks("2026-05-20T12:05:00Z")
        active_ids = {task.id for task in store.list_active_tasks()}

        assert expired.id not in active_ids
        assert future.id in active_ids
        assert cron.id in active_ids
    finally:
        store.close()
