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
