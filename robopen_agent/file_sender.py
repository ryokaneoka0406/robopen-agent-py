from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .codex_runner import get_codex_workspace_dir


DEFAULT_MAX_BYTES = 20 * 1024 * 1024
UPLOAD_MANIFEST_PREFIX = "ROBOPEN_FILE_UPLOAD "
FILE_TRIGGER_PATTERN = re.compile(r"(送って|送信|アップロード|貼って|共有)")
FILE_NAME_PATTERN = re.compile(r"[A-Za-z0-9_./ -]+\.[A-Za-z0-9]{1,12}")
URL_PATTERN = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+", re.IGNORECASE)


class FileSenderError(ValueError):
    pass


@dataclass(frozen=True)
class FileUploadRequest:
    path: str
    comment: str | None = None


@dataclass(frozen=True)
class FileUploadResult:
    path: str
    file_id: str | None = None
    permalink: str | None = None


@dataclass(frozen=True)
class ManifestExtraction:
    text: str
    requests: list[FileUploadRequest]


def get_slack_file_root() -> Path:
    configured = os.environ.get("SLACK_FILE_ROOT")
    if configured:
        configured_path = Path(configured).expanduser()
        if configured_path.is_absolute():
            return configured_path.resolve()
        return (get_codex_workspace_dir() / configured_path).resolve()
    return (get_codex_workspace_dir() / "share").resolve()


def get_slack_file_max_bytes() -> int:
    configured = (os.environ.get("SLACK_FILE_MAX_BYTES") or "").strip()
    if not configured:
        return DEFAULT_MAX_BYTES
    try:
        value = int(configured)
    except ValueError as exc:
        raise FileSenderError("SLACK_FILE_MAX_BYTESは整数で指定してください。") from exc
    if value <= 0:
        raise FileSenderError("SLACK_FILE_MAX_BYTESは1以上の整数で指定してください。")
    return value


def resolve_share_path(
    user_path: str,
    *,
    root: Path | None = None,
    max_bytes: int | None = None,
) -> Path:
    root = root or get_slack_file_root()
    max_bytes = max_bytes if max_bytes is not None else get_slack_file_max_bytes()
    relative = Path(user_path.strip())
    if not str(relative):
        raise FileSenderError("ファイルパスを指定してください。")
    if relative.is_absolute():
        raise FileSenderError("絶対パスは指定できません。share配下の相対パスを指定してください。")
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise FileSenderError("不正な相対パスです。")
    if any(part.startswith(".") for part in relative.parts):
        raise FileSenderError("隠しファイルは送信できません。")

    root_resolved = root.resolve()
    try:
        candidate = (root_resolved / relative).resolve(strict=True)
    except FileNotFoundError as exc:
        raise FileSenderError(f"ファイルが見つかりませんでした: {user_path}") from exc
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise FileSenderError("shareフォルダ外のファイルは送信できません。") from exc

    if not candidate.is_file():
        raise FileSenderError("ディレクトリは送信できません。ファイルを指定してください。")
    size = candidate.stat().st_size
    if size > max_bytes:
        raise FileSenderError(f"ファイルサイズが上限を超えています: {size} bytes / {max_bytes} bytes")
    return candidate


def list_share_files(*, root: Path | None = None, limit: int = 50) -> list[str]:
    root = root or get_slack_file_root()
    if not root.exists():
        return []
    root_resolved = root.resolve()
    files: list[Path] = []
    for path in root_resolved.rglob("*"):
        relative = path.relative_to(root_resolved)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if path.is_file():
            files.append(path)
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return [path.relative_to(root_resolved).as_posix() for path in files[:limit]]


def upload_file_to_slack(
    *,
    client: Any,
    channel: str,
    path: Path,
    thread_ts: str | None = None,
    initial_comment: str | None = None,
) -> FileUploadResult:
    kwargs: dict[str, Any] = {
        "channel": channel,
        "file": str(path),
        "filename": path.name,
        "title": path.name,
    }
    if thread_ts:
        kwargs["thread_ts"] = thread_ts
    if initial_comment:
        kwargs["initial_comment"] = initial_comment

    response = client.files_upload_v2(**kwargs)
    file_id, permalink = _extract_file_metadata(response)
    return FileUploadResult(path=path.name, file_id=file_id, permalink=permalink)


def parse_file_send_command(text: str) -> FileUploadRequest | None:
    if not text.startswith("file send "):
        return None
    raw = text.removeprefix("file send ").strip()
    path, separator, comment = raw.partition("|")
    path = path.strip()
    if not path:
        raise FileSenderError("形式: file send <relative_path> | <comment>")
    return FileUploadRequest(path=path, comment=comment.strip() if separator else None)


def parse_natural_file_request(text: str, *, root: Path | None = None) -> FileUploadRequest | str | None:
    if not FILE_TRIGGER_PATTERN.search(text):
        return None
    url_spans = [match.span() for match in URL_PATTERN.finditer(text)]
    candidates = [
        match.group(0).strip(" .。`'\"")
        for match in FILE_NAME_PATTERN.finditer(text)
        if not any(_spans_overlap(match.span(), url_span) for url_span in url_spans)
    ]
    candidates = [candidate.removeprefix("share/") for candidate in candidates]
    if not candidates:
        return None

    requested = candidates[-1]
    matches = find_matching_files(requested, root=root)
    if len(matches) == 1:
        return FileUploadRequest(path=matches[0], comment=None)
    if not matches:
        return f"送信対象のファイルが見つかりませんでした: {requested}"
    return "送信対象が複数あります。相対パスを指定してください:\n" + "\n".join(f"- {match}" for match in matches[:10])


def find_matching_files(requested: str, *, root: Path | None = None) -> list[str]:
    requested = requested.strip().removeprefix("share/")
    files = list_share_files(root=root, limit=500)
    exact = [path for path in files if path == requested]
    if exact:
        return exact
    basename_matches = [path for path in files if Path(path).name == requested]
    if basename_matches:
        return basename_matches
    suffix_matches = [path for path in files if path.endswith("/" + requested)]
    return suffix_matches


def _spans_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def extract_upload_manifests(text: str) -> ManifestExtraction:
    display_lines: list[str] = []
    requests: list[FileUploadRequest] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(UPLOAD_MANIFEST_PREFIX):
            display_lines.append(line)
            continue
        payload = stripped.removeprefix(UPLOAD_MANIFEST_PREFIX).strip()
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise FileSenderError("Codexのファイル送信マニフェストが不正なJSONです。") from exc
        if not isinstance(data, dict):
            raise FileSenderError("Codexのファイル送信マニフェストはJSON objectである必要があります。")
        path = data.get("path")
        comment = data.get("comment")
        if not isinstance(path, str) or not path.strip():
            raise FileSenderError("Codexのファイル送信マニフェストにpathがありません。")
        if comment is not None and not isinstance(comment, str):
            raise FileSenderError("Codexのファイル送信マニフェストのcommentは文字列で指定してください。")
        requests.append(FileUploadRequest(path=path.strip(), comment=comment.strip() if comment else None))
    return ManifestExtraction(text="\n".join(display_lines).strip(), requests=requests)


def build_file_list_message(files: list[str]) -> str:
    if not files:
        return "送信可能なファイルはありません。"
    return "送信可能なファイル:\n" + "\n".join(f"- {path}" for path in files)


def build_upload_log(result: FileUploadResult, relative_path: str) -> str:
    parts = [f"[file_uploaded] {relative_path}"]
    if result.file_id:
        parts.append(f"id={result.file_id}")
    if result.permalink:
        parts.append(f"permalink={result.permalink}")
    return " ".join(parts)


def _extract_file_metadata(response: Any) -> tuple[str | None, str | None]:
    data = response.data if hasattr(response, "data") and isinstance(response.data, dict) else response
    if not isinstance(data, dict):
        return None, None
    file_data = data.get("file")
    if isinstance(file_data, dict):
        file_id = file_data.get("id")
        permalink = file_data.get("permalink")
        return (
            file_id if isinstance(file_id, str) else None,
            permalink if isinstance(permalink, str) else None,
        )
    files_data = data.get("files")
    if isinstance(files_data, list) and files_data and isinstance(files_data[0], dict):
        file_id = files_data[0].get("id")
        permalink = files_data[0].get("permalink")
        return (
            file_id if isinstance(file_id, str) else None,
            permalink if isinstance(permalink, str) else None,
        )
    return None, None
