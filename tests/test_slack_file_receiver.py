from __future__ import annotations

from robopen_agent import app as app_module
from robopen_agent.codex_runner import CodexResult
from robopen_agent.file_sender import FileSenderError
from robopen_agent.memory_store import MemoryStore
from robopen_agent.scheduler import Scheduler
from robopen_agent.slack_file_receiver import build_prompt_with_slack_files, safe_inbound_filename


def test_build_prompt_with_slack_files_downloads_to_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("CODEX_WORKSPACE_DIR", str(workspace))

    prompt = build_prompt_with_slack_files(
        text="このファイルを確認して",
        token="xoxb-test",
        files=[
            {
                "id": "F123",
                "name": "report.md",
                "mimetype": "text/markdown",
                "size": 5,
                "url_private_download": "https://files.slack.com/report.md",
            }
        ],
        download_fn=lambda _url, _token, _max_bytes: b"hello",
    )

    saved = workspace / "inbox" / "slack"
    saved_files = list(saved.rglob("F123-report.md"))
    assert len(saved_files) == 1
    assert saved_files[0].read_bytes() == b"hello"
    assert prompt is not None
    assert prompt.startswith("このファイルを確認して\n\nSlack添付ファイル:")
    assert "path=inbox/slack/" in prompt
    assert "F123-report.md" in prompt
    assert "mimetype=text/markdown" in prompt


def test_build_prompt_with_only_slack_file_creates_non_empty_prompt(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("CODEX_WORKSPACE_DIR", str(workspace))

    prompt = build_prompt_with_slack_files(
        text="",
        token="xoxb-test",
        files=[
            {
                "id": "FIMG",
                "name": "image.png",
                "size": 3,
                "url_private_download": "https://files.slack.com/image.png",
            }
        ],
        download_fn=lambda _url, _token, _max_bytes: b"png",
    )

    assert prompt is not None
    assert prompt.startswith("Slack添付ファイル:")
    assert "FIMG-image.png" in prompt


def test_build_prompt_with_slack_file_rejects_size_over_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_WORKSPACE_DIR", str(tmp_path / "workspace"))

    try:
        build_prompt_with_slack_files(
            text="確認して",
            token="xoxb-test",
            max_bytes=2,
            files=[
                {
                    "id": "F123",
                    "name": "large.txt",
                    "size": 3,
                    "url_private_download": "https://files.slack.com/large.txt",
                }
            ],
            download_fn=lambda _url, _token, _max_bytes: b"xxx",
        )
    except FileSenderError as exc:
        assert "サイズが上限を超えています" in str(exc)
    else:
        raise AssertionError("Expected oversized Slack file to raise FileSenderError")


def test_safe_inbound_filename_removes_path_segments():
    assert safe_inbound_filename(file_id="F123", title="../secret report.md") == "F123-secret_report.md"


def test_slack_file_prompt_reaches_codex(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("CODEX_WORKSPACE_DIR", str(workspace))
    prompt = build_prompt_with_slack_files(
        text="",
        token="xoxb-test",
        files=[
            {
                "id": "F123",
                "name": "report.md",
                "size": 5,
                "url_private_download": "https://files.slack.com/report.md",
            }
        ],
        download_fn=lambda _url, _token, _max_bytes: b"hello",
    )
    calls: list[tuple[str, str | None]] = []

    def fake_run_codex(prompt_text: str, session_id: str | None = None) -> CodexResult:
        calls.append((prompt_text, session_id))
        return CodexResult("読み込みました", "thread-1")

    monkeypatch.setattr(app_module, "run_codex", fake_run_codex)
    store = MemoryStore(str(tmp_path / "agent.db"))
    scheduler = Scheduler(lambda _task: None)
    replies: list[str] = []

    app_module.handle_prompt(
        prompt=prompt,
        reply=replies.append,
        memory_store=store,
        scheduler=scheduler,
        conversation_key="D123:1710000000.000100",
    )

    assert len(calls) == 1
    assert calls[0][0].startswith("Slack添付ファイル:")
    assert "F123-report.md" in calls[0][0]
    assert replies == ["読み込みました"]
    store.close()


def test_inbound_slack_file_prompt_does_not_trigger_outbound_natural_file_send(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    share = workspace / "share"
    share.mkdir(parents=True)
    (share / "mobile-app-designdoc.pdf").write_bytes(b"existing outbound file")
    monkeypatch.setenv("CODEX_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("SLACK_FILE_ROOT", str(share))

    prompt = build_prompt_with_slack_files(
        text="このPDFを確認して、必要なら修正案を送って",
        token="xoxb-test",
        files=[
            {
                "id": "F123",
                "name": "mobile-app-designdoc.pdf",
                "size": 5,
                "url_private_download": "https://files.slack.com/mobile-app-designdoc.pdf",
            }
        ],
        download_fn=lambda _url, _token, _max_bytes: b"hello",
    )
    calls: list[tuple[str, str | None]] = []

    def fake_run_codex(prompt_text: str, session_id: str | None = None) -> CodexResult:
        calls.append((prompt_text, session_id))
        return CodexResult("確認します", "thread-1")

    monkeypatch.setattr(app_module, "run_codex", fake_run_codex)
    store = MemoryStore(str(tmp_path / "agent.db"))
    scheduler = Scheduler(lambda _task: None)
    replies: list[str] = []

    app_module.handle_prompt(
        prompt=prompt,
        reply=replies.append,
        memory_store=store,
        scheduler=scheduler,
        conversation_key="D123:1710000000.000200",
        slack_client=object(),
        slack_channel="D123",
        allow_natural_file_request=False,
    )

    assert len(calls) == 1
    assert "Slack添付ファイル:" in calls[0][0]
    assert replies == ["確認します"]
    store.close()
