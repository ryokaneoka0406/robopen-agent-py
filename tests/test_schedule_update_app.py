from robopen_agent import app as app_module
from robopen_agent.memory_store import MemoryStore, TaskRow
from robopen_agent.schedule_intent_parser import ParsedScheduleUpdateIntent


class RecordingScheduler:
    def __init__(self) -> None:
        self.scheduled: list[TaskRow] = []

    def schedule(self, task: TaskRow) -> None:
        self.scheduled.append(task)


def test_natural_language_update_uses_sqlite_and_reschedules(tmp_path, monkeypatch):
    store = MemoryStore(str(tmp_path / "agent.db"))
    scheduler = RecordingScheduler()
    replies: list[str] = []
    try:
        task = store.create_task(title="朝の要約", prompt="予定を要約する", schedule_cron="0 0 * * *")
        monkeypatch.setattr(
            app_module,
            "parse_schedule_intent_with_ai",
            lambda _text: ParsedScheduleUpdateIntent(
                kind="update",
                task_id=task.id,
                schedule_cron="0 23 * * *",
                confidence=0.9,
            ),
        )

        app_module.handle_prompt(
            prompt=f"#{task.id}を毎朝8時に変えて",
            reply=replies.append,
            memory_store=store,
            scheduler=scheduler,  # type: ignore[arg-type]
        )

        updated = store.list_tasks()[0]
        assert updated.schedule_cron == "0 23 * * *"
        assert [scheduled.schedule_cron for scheduled in scheduler.scheduled] == ["0 23 * * *"]
        assert replies == [
            f"タスクを更新しました: #{task.id} 朝の要約 (毎日 08:00 JST (cron: 0 23 * * * UTC))"
        ]
    finally:
        store.close()


def test_natural_language_update_with_ambiguous_target_does_not_update(tmp_path, monkeypatch):
    store = MemoryStore(str(tmp_path / "agent.db"))
    scheduler = RecordingScheduler()
    replies: list[str] = []
    try:
        first = store.create_task(title="朝の要約", prompt="予定を要約する", schedule_cron="0 0 * * *")
        second = store.create_task(title="朝の要約", prompt="ニュースを要約する", schedule_cron="0 1 * * *")
        monkeypatch.setattr(
            app_module,
            "parse_schedule_intent_with_ai",
            lambda _text: ParsedScheduleUpdateIntent(
                kind="update",
                target_query="朝の要約",
                schedule_cron="0 23 * * *",
                confidence=0.9,
            ),
        )

        app_module.handle_prompt(
            prompt="朝の要約を毎朝8時に変えて",
            reply=replies.append,
            memory_store=store,
            scheduler=scheduler,  # type: ignore[arg-type]
        )

        tasks = store.list_tasks()
        assert [task.schedule_cron for task in tasks] == ["0 0 * * *", "0 1 * * *"]
        assert scheduler.scheduled == []
        assert replies == ["更新対象が複数あります。schedule listでIDを確認して #ID を指定してください。"]
        assert {task.id for task in tasks} == {first.id, second.id}
    finally:
        store.close()


def test_fixed_schedule_update_command_updates_task(tmp_path):
    store = MemoryStore(str(tmp_path / "agent.db"))
    scheduler = RecordingScheduler()
    replies: list[str] = []
    try:
        task = store.create_task(title="daily", prompt="run", schedule_cron="0 0 * * *")

        app_module.handle_prompt(
            prompt=f"schedule update {task.id} | 0 23 * * *",
            reply=replies.append,
            memory_store=store,
            scheduler=scheduler,  # type: ignore[arg-type]
        )

        assert store.list_tasks()[0].schedule_cron == "0 23 * * *"
        assert [scheduled.id for scheduled in scheduler.scheduled] == [task.id]
        assert replies == [
            f"タスクを更新しました: #{task.id} daily (毎日 08:00 JST (cron: 0 23 * * * UTC))"
        ]
    finally:
        store.close()


def test_schedule_list_returns_task_ids(tmp_path):
    store = MemoryStore(str(tmp_path / "agent.db"))
    scheduler = RecordingScheduler()
    replies: list[str] = []
    try:
        task = store.create_task(title="daily", prompt="run", schedule_cron="0 0 * * *")
        done = store.create_task(title="old", prompt="run", schedule_cron="0 1 * * *")
        store.complete_task(done.id)

        app_module.handle_prompt(
            prompt="schedule list",
            reply=replies.append,
            memory_store=store,
            scheduler=scheduler,  # type: ignore[arg-type]
        )

        assert replies == [
            f"登録済みタスク:\n#{task.id} [active] daily - 毎日 09:00 JST (cron: 0 0 * * * UTC)"
        ]
    finally:
        store.close()
