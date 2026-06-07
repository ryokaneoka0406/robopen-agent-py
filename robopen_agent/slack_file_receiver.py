from __future__ import annotations

import os
import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .codex_runner import get_codex_workspace_dir
from .file_sender import DEFAULT_MAX_BYTES, FileSenderError


DownloadFn = Callable[[str, str, int], bytes]

SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class InboundSlackFile:
    path: Path
    relative_path: str
    title: str
    mimetype: str | None
    size: int
    file_id: str | None


def get_slack_inbound_file_root() -> Path:
    configured = os.environ.get("SLACK_INBOUND_FILE_ROOT")
    if configured:
        configured_path = Path(configured).expanduser()
        if configured_path.is_absolute():
            return configured_path.resolve()
        return (get_codex_workspace_dir() / configured_path).resolve()
    return (get_codex_workspace_dir() / "inbox" / "slack").resolve()


def get_slack_inbound_file_max_bytes() -> int:
    configured = (os.environ.get("SLACK_INBOUND_FILE_MAX_BYTES") or "").strip()
    if not configured:
        return DEFAULT_MAX_BYTES
    try:
        value = int(configured)
    except ValueError as exc:
        raise FileSenderError("SLACK_INBOUND_FILE_MAX_BYTESは整数で指定してください。") from exc
    if value <= 0:
        raise FileSenderError("SLACK_INBOUND_FILE_MAX_BYTESは1以上の整数で指定してください。")
    return value


def build_prompt_with_slack_files(
    *,
    text: str | None,
    files: list[dict[str, Any]] | None,
    token: str | None = None,
    root: Path | None = None,
    max_bytes: int | None = None,
    download_fn: DownloadFn | None = None,
) -> str | None:
    trimmed = (text or "").strip()
    if not files:
        return trimmed or None

    downloaded = download_slack_files(
        files=files,
        token=token,
        root=root,
        max_bytes=max_bytes,
        download_fn=download_fn,
    )
    file_lines = ["Slack添付ファイル:"]
    for file in downloaded:
        metadata = [f"path={file.relative_path}", f"title={file.title}", f"size={file.size} bytes"]
        if file.mimetype:
            metadata.append(f"mimetype={file.mimetype}")
        if file.file_id:
            metadata.append(f"id={file.file_id}")
        file_lines.append("- " + ", ".join(metadata))

    if trimmed:
        return trimmed + "\n\n" + "\n".join(file_lines)
    return "\n".join(file_lines)


def download_slack_files(
    *,
    files: list[dict[str, Any]],
    token: str | None = None,
    root: Path | None = None,
    max_bytes: int | None = None,
    download_fn: DownloadFn | None = None,
) -> list[InboundSlackFile]:
    token = token or os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        raise FileSenderError("Slack添付ファイルの取得にSLACK_BOT_TOKENが必要です。")
    root = root or get_slack_inbound_file_root()
    max_bytes = max_bytes if max_bytes is not None else get_slack_inbound_file_max_bytes()
    download_fn = download_fn or download_private_url

    root.mkdir(parents=True, exist_ok=True)
    day_dir = root / datetime.now(timezone.utc).strftime("%Y%m%d")
    day_dir.mkdir(parents=True, exist_ok=True)

    downloaded: list[InboundSlackFile] = []
    for file_data in files:
        if not isinstance(file_data, dict):
            continue
        url = _file_download_url(file_data)
        if not url:
            raise FileSenderError("Slack添付ファイルのダウンロードURLが見つかりません。")

        size = _file_size(file_data)
        if size is not None and size > max_bytes:
            raise FileSenderError(f"Slack添付ファイルのサイズが上限を超えています: {size} bytes / {max_bytes} bytes")

        content = download_fn(url, token, max_bytes)
        if len(content) > max_bytes:
            raise FileSenderError(
                f"Slack添付ファイルのサイズが上限を超えています: {len(content)} bytes / {max_bytes} bytes"
            )

        file_id = _string_value(file_data.get("id"))
        title = _file_title(file_data)
        filename = safe_inbound_filename(file_id=file_id, title=title)
        path = unique_path(day_dir / filename)
        path.write_bytes(content)
        try:
            relative_path = path.relative_to(get_codex_workspace_dir()).as_posix()
        except ValueError:
            relative_path = path.as_posix()
        downloaded.append(
            InboundSlackFile(
                path=path,
                relative_path=relative_path,
                title=title,
                mimetype=_string_value(file_data.get("mimetype")),
                size=len(content),
                file_id=file_id,
            )
        )

    return downloaded


def download_private_url(url: str, token: str, max_bytes: int) -> bytes:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=30) as response:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise FileSenderError(
                    f"Slack添付ファイルのサイズが上限を超えています: {total} bytes / {max_bytes} bytes"
                )
            chunks.append(chunk)
    return b"".join(chunks)


def safe_inbound_filename(*, file_id: str | None, title: str) -> str:
    cleaned = SAFE_FILENAME_PATTERN.sub("_", title.strip()).strip("._-")
    if not cleaned:
        cleaned = "slack-file"
    prefix = SAFE_FILENAME_PATTERN.sub("_", file_id).strip("._-") if file_id else None
    if len(cleaned) > 120:
        suffix = Path(cleaned).suffix[:20]
        stem = Path(cleaned).stem[: 120 - len(suffix)]
        cleaned = stem + suffix
    if prefix:
        return f"{prefix}-{cleaned}"
    return cleaned


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _file_download_url(file_data: dict[str, Any]) -> str | None:
    return _string_value(file_data.get("url_private_download")) or _string_value(file_data.get("url_private"))


def _file_title(file_data: dict[str, Any]) -> str:
    return (
        _string_value(file_data.get("name"))
        or _string_value(file_data.get("title"))
        or _string_value(file_data.get("id"))
        or "slack-file"
    )


def _file_size(file_data: dict[str, Any]) -> int | None:
    value = file_data.get("size")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _string_value(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None
