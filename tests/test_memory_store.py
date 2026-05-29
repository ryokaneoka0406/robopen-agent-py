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


def test_update_cron_task_only_updates_active_cron_tasks(tmp_path):
    store = MemoryStore(str(tmp_path / "agent.db"))
    try:
        cron = store.create_task(title="daily", prompt="run", schedule_cron="0 0 * * *")
        once = store.create_task(title="once", prompt="run", run_at="2026-05-20T12:00:00Z")
        cancelled = store.create_task(title="old", prompt="run", schedule_cron="0 1 * * *")
        store.cancel_task(cancelled.id)

        updated = store.update_cron_task(cron.id, "0 23 * * *")

        assert updated is not None
        assert updated.schedule_cron == "0 23 * * *"
        assert store.update_cron_task(once.id, "0 23 * * *") is None
        assert store.update_cron_task(cancelled.id, "0 23 * * *") is None
        assert store.update_cron_task(999, "0 23 * * *") is None
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


def test_deprecated_preferences_and_audit_logs_tables_are_removed(tmp_path):
    db_path = tmp_path / "agent.db"
    db = sqlite3.connect(db_path)
    try:
        db.executescript(
            """
            CREATE TABLE preferences (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE audit_logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              action TEXT NOT NULL,
              target TEXT,
              approved_by TEXT,
              created_at TEXT NOT NULL
            );
            """
        )
        db.commit()
    finally:
        db.close()

    store = MemoryStore(str(db_path))
    try:
        table_names = {
            row["name"]
            for row in store.db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

        assert "preferences" not in table_names
        assert "audit_logs" not in table_names
    finally:
        store.close()
