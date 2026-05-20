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

