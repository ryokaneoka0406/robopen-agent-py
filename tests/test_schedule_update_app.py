from robopen_agent import app as app_module
from robopen_agent.memory_store import MemoryStore, TaskRow
from robopen_agent.schedule_intent_parser import ParsedScheduleDeleteIntent, ParsedScheduleUpdateIntent


class RecordingScheduler:
    def __init__(self) -> None:
        self.scheduled: list[TaskRow] = []
        self.unscheduled: list[int] = []

    def schedule(self, task: TaskRow) -> None:
        self.scheduled.append(task)

    def unschedule(self, task_id: int) -> None:
        self.unscheduled.append(task_id)


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


def test_schedule_delete_command_requires_confirmation_and_cancels_task(tmp_path):
    store = MemoryStore(str(tmp_path / "agent.db"))
    scheduler = RecordingScheduler()
    replies: list[str] = []
    pending: dict[str, app_module.PendingScheduleDelete] = {}
    try:
        task = store.create_task(title="daily", prompt="run", schedule_cron="0 0 * * *")

        app_module.handle_prompt(
            prompt=f"schedule delete {task.id}",
            reply=replies.append,
            memory_store=store,
            scheduler=scheduler,  # type: ignore[arg-type]
            conversation_key="C123:111.222",
            pending_schedule_deletions=pending,
        )
        app_module.handle_prompt(
            prompt=f"schedule delete confirm {task.id}",
            reply=replies.append,
            memory_store=store,
            scheduler=scheduler,  # type: ignore[arg-type]
            conversation_key="C123:111.222",
            pending_schedule_deletions=pending,
        )

        assert replies == [
            (
                f"削除確認: #{task.id} daily (毎日 09:00 JST (cron: 0 0 * * * UTC)) を削除します。\n"
                f"実行する場合は `schedule delete confirm {task.id}`、または `はい` / `削除して` と返信してください。"
            ),
            f"タスクを削除しました: #{task.id} daily",
        ]
        assert store.find_task(task.id).status == "cancelled"  # type: ignore[union-attr]
        assert scheduler.unscheduled == [task.id]
        assert pending == {}
    finally:
        store.close()


def test_schedule_delete_confirm_without_pending_request_does_not_cancel(tmp_path):
    store = MemoryStore(str(tmp_path / "agent.db"))
    scheduler = RecordingScheduler()
    replies: list[str] = []
    pending: dict[str, app_module.PendingScheduleDelete] = {}
    try:
        task = store.create_task(title="daily", prompt="run", schedule_cron="0 0 * * *")

        app_module.handle_prompt(
            prompt=f"schedule delete confirm {task.id}",
            reply=replies.append,
            memory_store=store,
            scheduler=scheduler,  # type: ignore[arg-type]
            conversation_key="C123:111.222",
            pending_schedule_deletions=pending,
        )

        assert replies == ["削除確認が見つかりませんでした。先に `schedule delete <task_id>` を送ってください。"]
        assert store.find_task(task.id).status == "active"  # type: ignore[union-attr]
        assert scheduler.unscheduled == []
    finally:
        store.close()


def test_natural_language_delete_requests_confirmation(tmp_path, monkeypatch):
    store = MemoryStore(str(tmp_path / "agent.db"))
    scheduler = RecordingScheduler()
    replies: list[str] = []
    pending: dict[str, app_module.PendingScheduleDelete] = {}
    try:
        task = store.create_task(title="朝の要約", prompt="予定を要約する", schedule_cron="0 0 * * *")
        monkeypatch.setattr(
            app_module,
            "parse_schedule_intent_with_ai",
            lambda _text: ParsedScheduleDeleteIntent(
                kind="delete",
                task_id=task.id,
                confidence=0.9,
            ),
        )

        app_module.handle_prompt(
            prompt=f"#{task.id}を削除して",
            reply=replies.append,
            memory_store=store,
            scheduler=scheduler,  # type: ignore[arg-type]
            conversation_key="C123:111.222",
            pending_schedule_deletions=pending,
        )

        assert replies == [
            (
                f"削除確認: #{task.id} 朝の要約 (毎日 09:00 JST (cron: 0 0 * * * UTC)) を削除します。\n"
                f"実行する場合は `schedule delete confirm {task.id}`、または `はい` / `削除して` と返信してください。"
            )
        ]
        assert pending == {"C123:111.222": app_module.PendingScheduleDelete(task_id=task.id)}
        assert store.find_task(task.id).status == "active"  # type: ignore[union-attr]
    finally:
        store.close()


def test_natural_language_delete_can_be_confirmed_with_yes(tmp_path):
    store = MemoryStore(str(tmp_path / "agent.db"))
    scheduler = RecordingScheduler()
    replies: list[str] = []
    pending: dict[str, app_module.PendingScheduleDelete] = {}
    try:
        task = store.create_task(title="daily", prompt="run", schedule_cron="0 0 * * *")

        app_module.handle_prompt(
            prompt=f"schedule delete {task.id}",
            reply=replies.append,
            memory_store=store,
            scheduler=scheduler,  # type: ignore[arg-type]
            conversation_key="C123:111.222",
            pending_schedule_deletions=pending,
        )
        app_module.handle_prompt(
            prompt="はい",
            reply=replies.append,
            memory_store=store,
            scheduler=scheduler,  # type: ignore[arg-type]
            conversation_key="C123:111.222",
            pending_schedule_deletions=pending,
        )

        assert replies[-1] == f"タスクを削除しました: #{task.id} daily"
        assert store.find_task(task.id).status == "cancelled"  # type: ignore[union-attr]
        assert scheduler.unscheduled == [task.id]
        assert pending == {}
    finally:
        store.close()


def test_pending_delete_can_be_denied_with_natural_language(tmp_path):
    store = MemoryStore(str(tmp_path / "agent.db"))
    scheduler = RecordingScheduler()
    replies: list[str] = []
    pending: dict[str, app_module.PendingScheduleDelete] = {}
    try:
        task = store.create_task(title="daily", prompt="run", schedule_cron="0 0 * * *")

        app_module.handle_prompt(
            prompt=f"schedule delete {task.id}",
            reply=replies.append,
            memory_store=store,
            scheduler=scheduler,  # type: ignore[arg-type]
            conversation_key="C123:111.222",
            pending_schedule_deletions=pending,
        )
        app_module.handle_prompt(
            prompt="やっぱりやめて",
            reply=replies.append,
            memory_store=store,
            scheduler=scheduler,  # type: ignore[arg-type]
            conversation_key="C123:111.222",
            pending_schedule_deletions=pending,
        )

        assert replies[-1] == "タスク削除をキャンセルしました。"
        assert store.find_task(task.id).status == "active"  # type: ignore[union-attr]
        assert scheduler.unscheduled == []
        assert pending == {}
    finally:
        store.close()


def test_pending_delete_confirmation_does_not_confirm_different_task_id(tmp_path, monkeypatch):
    store = MemoryStore(str(tmp_path / "agent.db"))
    scheduler = RecordingScheduler()
    replies: list[str] = []
    pending: dict[str, app_module.PendingScheduleDelete] = {}
    try:
        first = store.create_task(title="daily", prompt="run", schedule_cron="0 0 * * *")
        second = store.create_task(title="weekly", prompt="run", schedule_cron="0 0 * * *")
        monkeypatch.setattr(
            app_module,
            "parse_schedule_intent_with_ai",
            lambda _text: ParsedScheduleDeleteIntent(
                kind="delete",
                task_id=second.id,
                confidence=0.9,
            ),
        )

        app_module.handle_prompt(
            prompt=f"schedule delete {first.id}",
            reply=replies.append,
            memory_store=store,
            scheduler=scheduler,  # type: ignore[arg-type]
            conversation_key="C123:111.222",
            pending_schedule_deletions=pending,
        )
        app_module.handle_prompt(
            prompt=f"#{second.id}を削除して",
            reply=replies.append,
            memory_store=store,
            scheduler=scheduler,  # type: ignore[arg-type]
            conversation_key="C123:111.222",
            pending_schedule_deletions=pending,
        )

        assert store.find_task(first.id).status == "active"  # type: ignore[union-attr]
        assert store.find_task(second.id).status == "active"  # type: ignore[union-attr]
        assert pending == {"C123:111.222": app_module.PendingScheduleDelete(task_id=second.id)}
        assert scheduler.unscheduled == []
    finally:
        store.close()
