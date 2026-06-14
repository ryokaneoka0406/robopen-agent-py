from __future__ import annotations

from pathlib import Path

import pytest

from robopen_agent import app as app_module
from robopen_agent.codex_runner import CodexResult
from robopen_agent.file_sender import (
    FileSenderError,
    extract_upload_manifests,
    parse_natural_file_request,
    resolve_share_path,
)
from robopen_agent.memory_store import MemoryStore
from robopen_agent.scheduler import Scheduler


class FakeSlackClient:
    def __init__(self) -> None:
        self.uploads: list[dict[str, object]] = []

    def files_upload_v2(self, **kwargs):
        self.uploads.append(kwargs)
        return {"file": {"id": "F123", "permalink": "https://example.slack.com/files/F123"}}


def test_resolve_share_path_allows_regular_relative_file(tmp_path):
    root = tmp_path / "share"
    root.mkdir()
    file_path = root / "report.md"
    file_path.write_text("ok", encoding="utf-8")

    assert resolve_share_path("report.md", root=root) == file_path.resolve()


@pytest.mark.parametrize("requested", ["../secret.txt", "/tmp/secret.txt", ".secret"])
def test_resolve_share_path_rejects_unsafe_paths(tmp_path, requested):
    root = tmp_path / "share"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    (root / ".secret").write_text("secret", encoding="utf-8")

    with pytest.raises(FileSenderError):
        resolve_share_path(requested, root=root)


def test_resolve_share_path_rejects_symlink_escape(tmp_path):
    root = tmp_path / "share"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    (root / "link.txt").symlink_to(secret)

    with pytest.raises(FileSenderError):
        resolve_share_path("link.txt", root=root)


def test_resolve_share_path_rejects_directory_and_size_limit(tmp_path):
    root = tmp_path / "share"
    root.mkdir()
    (root / "dir").mkdir()
    (root / "large.txt").write_text("12345", encoding="utf-8")

    with pytest.raises(FileSenderError):
        resolve_share_path("dir", root=root)
    with pytest.raises(FileSenderError):
        resolve_share_path("large.txt", root=root, max_bytes=1)


def test_parse_natural_file_request_resolves_unique_filename(tmp_path):
    root = tmp_path / "share"
    (root / "images").mkdir(parents=True)
    (root / "images" / "chart.png").write_bytes(b"png")

    request = parse_natural_file_request("さっき作ったchart.pngをこのスレッドに貼って", root=root)

    assert request is not None
    assert not isinstance(request, str)
    assert request.path == "images/chart.png"


def test_parse_natural_file_request_reports_ambiguous_filename(tmp_path):
    root = tmp_path / "share"
    (root / "a").mkdir(parents=True)
    (root / "b").mkdir(parents=True)
    (root / "a" / "report.md").write_text("a", encoding="utf-8")
    (root / "b" / "report.md").write_text("b", encoding="utf-8")

    result = parse_natural_file_request("report.mdを送って", root=root)

    assert isinstance(result, str)
    assert "送信対象が複数あります" in result


def test_parse_natural_file_request_ignores_url():
    result = parse_natural_file_request(
        "https://huggingface.co/rhasspy/piper-voices\n"
        "これつかってローカルでTTSして、音声ファイルを貼ってもらう運用にできる？"
    )

    assert result is None


def test_parse_natural_file_request_ignores_url_but_finds_separate_file(tmp_path):
    root = tmp_path / "share"
    root.mkdir()
    (root / "report.md").write_text("report", encoding="utf-8")

    request = parse_natural_file_request(
        "https://example.com/docs/readme.md を参考に report.mdを送って",
        root=root,
    )

    assert request is not None
    assert not isinstance(request, str)
    assert request.path == "report.md"


def test_extract_upload_manifests_removes_manifest_line():
    extraction = extract_upload_manifests(
        'できました。\nROBOPEN_FILE_UPLOAD {"path":"report.md","comment":"レポートです"}'
    )

    assert extraction.text == "できました。"
    assert extraction.requests[0].path == "report.md"
    assert extraction.requests[0].comment == "レポートです"


def test_extract_upload_manifests_rejects_invalid_json():
    with pytest.raises(FileSenderError):
        extract_upload_manifests("ROBOPEN_FILE_UPLOAD {bad json")


def test_file_send_command_uploads_to_slack_and_logs(tmp_path, monkeypatch):
    share = tmp_path / "share"
    share.mkdir()
    (share / "report.md").write_text("hello", encoding="utf-8")
    monkeypatch.setenv("SLACK_FILE_ROOT", str(share))

    store = MemoryStore(str(tmp_path / "agent.db"))
    scheduler = Scheduler(lambda _task: None)
    client = FakeSlackClient()
    replies: list[str] = []

    app_module.handle_prompt(
        prompt="file send report.md | レポートです",
        reply=replies.append,
        memory_store=store,
        scheduler=scheduler,
        conversation_key="C123:1710000000.000100",
        slack_client=client,
        slack_channel="C123",
        slack_thread_ts="1710000000.000100",
    )

    assert replies == ["ファイルを送信しました: report.md"]
    assert client.uploads == [
        {
            "channel": "C123",
            "file": str((share / "report.md").resolve()),
            "filename": "report.md",
            "title": "report.md",
            "thread_ts": "1710000000.000100",
            "initial_comment": "レポートです",
        }
    ]
    conversation = store.find_conversation_by_thread("C123:1710000000.000100")
    assert conversation is not None
    assert store.get_recent_context(conversation.id)[0].content.startswith("[file_uploaded] report.md")
    store.close()


def test_natural_file_request_uploads_to_slack(tmp_path, monkeypatch):
    share = tmp_path / "share"
    share.mkdir()
    (share / "report.md").write_text("hello", encoding="utf-8")
    monkeypatch.setenv("SLACK_FILE_ROOT", str(share))

    store = MemoryStore(str(tmp_path / "agent.db"))
    scheduler = Scheduler(lambda _task: None)
    client = FakeSlackClient()
    replies: list[str] = []

    app_module.handle_prompt(
        prompt="shareのreport.mdをSlackに送って",
        reply=replies.append,
        memory_store=store,
        scheduler=scheduler,
        conversation_key="D123:1710000000.000100",
        slack_client=client,
        slack_channel="D123",
    )

    assert replies == ["ファイルを送信しました: report.md"]
    assert client.uploads[0]["channel"] == "D123"
    assert "thread_ts" not in client.uploads[0]
    store.close()


def test_url_request_reaches_codex_without_being_treated_as_file(tmp_path, monkeypatch):
    prompt = (
        "https://huggingface.co/rhasspy/piper-voices\n"
        "これつかってローカルでTTSして、音声ファイルを貼ってもらう運用にできる？"
    )
    calls: list[tuple[str, str | None]] = []

    def fake_run_codex(prompt_text: str, session_id: str | None = None) -> CodexResult:
        calls.append((prompt_text, session_id))
        return CodexResult("できます。", "thread-url")

    monkeypatch.setattr(app_module, "run_codex", fake_run_codex)

    store = MemoryStore(str(tmp_path / "agent.db"))
    scheduler = Scheduler(lambda _task: None)
    client = FakeSlackClient()
    replies: list[str] = []

    app_module.handle_prompt(
        prompt=prompt,
        reply=replies.append,
        memory_store=store,
        scheduler=scheduler,
        conversation_key="D123:1710000000.000300",
        slack_client=client,
        slack_channel="D123",
    )

    assert calls == [(prompt, None)]
    assert replies == ["できます。"]
    assert client.uploads == []
    store.close()


def test_codex_manifest_uploads_file_and_hides_manifest(tmp_path, monkeypatch):
    share = tmp_path / "share"
    share.mkdir()
    (share / "report.md").write_text("hello", encoding="utf-8")
    monkeypatch.setenv("SLACK_FILE_ROOT", str(share))
    monkeypatch.setattr(
        app_module,
        "run_codex",
        lambda *_args, **_kwargs: CodexResult(
            'レポートを作成しました。\nROBOPEN_FILE_UPLOAD {"path":"report.md","comment":"レポートです"}',
            "thread-1",
        ),
    )

    store = MemoryStore(str(tmp_path / "agent.db"))
    scheduler = Scheduler(lambda _task: None)
    client = FakeSlackClient()
    replies: list[str] = []

    app_module.handle_prompt(
        prompt="レポートを作って送って",
        reply=replies.append,
        memory_store=store,
        scheduler=scheduler,
        conversation_key="C123:1710000000.000200",
        slack_client=client,
        slack_channel="C123",
        slack_thread_ts="1710000000.000200",
    )

    assert replies == ["レポートを作成しました。", "ファイルを送信しました: report.md"]
    assert client.uploads[0]["initial_comment"] == "レポートです"
    conversation = store.find_conversation_by_thread("C123:1710000000.000200")
    assert conversation is not None
    contents = [row.content for row in store.get_recent_context(conversation.id)]
    assert all("ROBOPEN_FILE_UPLOAD" not in content for content in contents)
    assert any(content.startswith("[file_uploaded] report.md") for content in contents)
    store.close()
