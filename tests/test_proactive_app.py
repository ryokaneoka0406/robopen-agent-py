from __future__ import annotations

from robopen_agent import app as app_module
from robopen_agent.codex_runner import CodexResult
from robopen_agent.proactive import DEFAULT_PROMPT


def test_proactive_task_posts_natural_message_without_scheduled_heading(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "agent.db"))
    monkeypatch.setenv("PROACTIVE_ENABLED", "true")
    monkeypatch.setenv("PROACTIVE_CHANNEL", "CPRO")
    monkeypatch.setattr(app_module, "run_codex", lambda *_args, **_kwargs: CodexResult("そろそろ一息つく？"))

    slack_app = app_module.create_app()
    posted: list[dict[str, str]] = []
    monkeypatch.setattr(
        slack_app.client,
        "chat_postMessage",
        lambda **kwargs: posted.append(kwargs),
    )

    store = slack_app.client.robopen_memory_store  # type: ignore[attr-defined]
    scheduler = slack_app.client.robopen_scheduler  # type: ignore[attr-defined]
    task = store.create_task(
        title="proactive check-in",
        prompt=DEFAULT_PROMPT,
        run_at="2026-05-28T12:00:00Z",
        notify_channel="CPRO",
        source_key="proactive:2026-05-28:1",
    )

    scheduler.run_task(task)

    assert posted == [{"channel": "CPRO", "text": "そろそろ一息つく？"}]
    assert task.id not in {active.id for active in store.list_active_tasks()}
    store.close()


def test_proactive_task_registers_posted_thread_as_conversation(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "agent.db"))
    monkeypatch.setenv("PROACTIVE_ENABLED", "true")
    monkeypatch.setenv("PROACTIVE_CHANNEL", "CPRO")
    monkeypatch.setattr(
        app_module,
        "run_codex",
        lambda *_args, **_kwargs: CodexResult("そろそろ一息つく？", "thread-proactive"),
    )

    slack_app = app_module.create_app()
    posted: list[dict[str, str]] = []
    monkeypatch.setattr(
        slack_app.client,
        "chat_postMessage",
        lambda **kwargs: posted.append(kwargs) or {"ts": "1710000000.000100"},
    )

    store = slack_app.client.robopen_memory_store  # type: ignore[attr-defined]
    scheduler = slack_app.client.robopen_scheduler  # type: ignore[attr-defined]
    task = store.create_task(
        title="proactive check-in",
        prompt=DEFAULT_PROMPT,
        run_at="2026-05-28T12:00:00Z",
        notify_channel="CPRO",
        source_key="proactive:2026-05-28:1",
    )

    scheduler.run_task(task)

    conversation = store.find_conversation_by_thread("CPRO:1710000000.000100")
    assert conversation is not None
    assert conversation.codex_rollout_id == "thread-proactive"
    assert [row.content for row in store.get_recent_context(conversation.id)] == ["そろそろ一息つく？"]
    assert posted == [{"channel": "CPRO", "text": "そろそろ一息つく？"}]
    store.close()


def test_regular_scheduled_task_keeps_scheduled_heading(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "agent.db"))
    monkeypatch.setenv("SLACK_LOG_CHANNEL", "CLOG")
    monkeypatch.setenv("PROACTIVE_ENABLED", "false")
    monkeypatch.setattr(app_module, "run_codex", lambda *_args, **_kwargs: CodexResult("done"))

    slack_app = app_module.create_app()
    posted: list[dict[str, str]] = []
    monkeypatch.setattr(
        slack_app.client,
        "chat_postMessage",
        lambda **kwargs: posted.append(kwargs),
    )

    store = slack_app.client.robopen_memory_store  # type: ignore[attr-defined]
    scheduler = slack_app.client.robopen_scheduler  # type: ignore[attr-defined]
    task = store.create_task(title="daily", prompt="run", schedule_cron="0 0 * * *")

    scheduler.run_task(task)

    assert posted == [
        {
            "channel": "CLOG",
            "text": ":spiral_calendar_pad: *Scheduled Task:* daily\n\ndone",
        }
    ]
    store.close()


def test_regular_scheduled_task_registers_posted_thread_as_conversation(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "agent.db"))
    monkeypatch.setenv("SLACK_LOG_CHANNEL", "CLOG")
    monkeypatch.setenv("PROACTIVE_ENABLED", "false")
    monkeypatch.setattr(app_module, "run_codex", lambda *_args, **_kwargs: CodexResult("done", "thread-cron"))

    slack_app = app_module.create_app()
    posted: list[dict[str, str]] = []
    monkeypatch.setattr(
        slack_app.client,
        "chat_postMessage",
        lambda **kwargs: posted.append(kwargs) or {"ts": "1710000000.000200"},
    )

    store = slack_app.client.robopen_memory_store  # type: ignore[attr-defined]
    scheduler = slack_app.client.robopen_scheduler  # type: ignore[attr-defined]
    task = store.create_task(title="daily", prompt="run", schedule_cron="0 0 * * *")

    scheduler.run_task(task)

    posted_text = ":spiral_calendar_pad: *Scheduled Task:* daily\n\ndone"
    conversation = store.find_conversation_by_thread("CLOG:1710000000.000200")
    assert conversation is not None
    assert conversation.codex_rollout_id == "thread-cron"
    assert [row.content for row in store.get_recent_context(conversation.id)] == [posted_text]
    assert posted == [{"channel": "CLOG", "text": posted_text}]
    store.close()


def test_scheduled_task_without_post_ts_does_not_register_conversation(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "agent.db"))
    monkeypatch.setenv("SLACK_LOG_CHANNEL", "CLOG")
    monkeypatch.setenv("PROACTIVE_ENABLED", "false")
    monkeypatch.setattr(app_module, "run_codex", lambda *_args, **_kwargs: CodexResult("done", "thread-cron"))

    slack_app = app_module.create_app()
    monkeypatch.setattr(slack_app.client, "chat_postMessage", lambda **_kwargs: {})

    store = slack_app.client.robopen_memory_store  # type: ignore[attr-defined]
    scheduler = slack_app.client.robopen_scheduler  # type: ignore[attr-defined]
    task = store.create_task(title="daily", prompt="run", schedule_cron="0 0 * * *")

    scheduler.run_task(task)

    assert store.find_conversation_by_thread("CLOG:1710000000.000200") is None
    store.close()


def test_registered_bot_thread_reply_resumes_saved_codex_session(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "agent.db"))
    monkeypatch.setenv("SLACK_LOG_CHANNEL", "CLOG")
    monkeypatch.setenv("PROACTIVE_ENABLED", "false")

    calls: list[tuple[str, str | None]] = []

    def fake_run_codex(prompt: str, session_id: str | None = None) -> CodexResult:
        calls.append((prompt, session_id))
        return CodexResult("continued", session_id)

    monkeypatch.setattr(app_module, "run_codex", fake_run_codex)
    slack_app = app_module.create_app()
    store = slack_app.client.robopen_memory_store  # type: ignore[attr-defined]
    scheduler = slack_app.client.robopen_scheduler  # type: ignore[attr-defined]
    conversation = store.get_or_create_conversation("CLOG:1710000000.000300")
    store.set_codex_rollout_id(conversation.id, "thread-cron")
    replies: list[str] = []

    app_module.handle_prompt(
        prompt="この結果について続けて",
        reply=replies.append,
        memory_store=store,
        scheduler=scheduler,
        conversation_key="CLOG:1710000000.000300",
    )

    assert calls == [("この結果について続けて", "thread-cron")]
    assert replies == ["continued"]
    store.close()
