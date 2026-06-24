from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import uuid
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping

from dotenv import load_dotenv

from .codex_runner import get_codex_workspace_dir


SERVICE_NAME = "robopen-health-receiver"
SCHEMA_VERSION = 1
CONTENT_TYPE = "application/vnd.robopen.health.export+json"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DEFAULT_MAX_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024


class HealthUploadError(Exception):
    def __init__(self, code: str, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class HealthUploadConfig:
    host: str
    port: int
    token_hash: str
    root: Path
    max_bytes: int
    max_uncompressed_bytes: int


@dataclass(frozen=True)
class HealthImportResult:
    status: str
    schema_version: int
    import_id: str
    workspace_path: str
    received_at: str
    payload_sha256: str
    record_count: int
    deleted_object_count: int
    duplicate: bool = False

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "schemaVersion": self.schema_version,
            "importId": self.import_id,
            "workspacePath": self.workspace_path,
            "receivedAt": self.received_at,
            "recordCount": self.record_count,
            "deletedObjectCount": self.deleted_object_count,
            "payloadSha256": self.payload_sha256,
        }
        if self.duplicate:
            payload["duplicate"] = True
        return payload


def config_from_env() -> HealthUploadConfig:
    workspace = get_codex_workspace_dir()
    root_env = os.environ.get("HEALTH_UPLOAD_ROOT")
    if root_env:
        root_path = Path(root_env).expanduser()
        root = root_path.resolve() if root_path.is_absolute() else (workspace / root_path).resolve()
    else:
        root = (workspace / "healthcare").resolve()

    return HealthUploadConfig(
        host=os.environ.get("HEALTH_UPLOAD_HOST", DEFAULT_HOST),
        port=_env_int("HEALTH_UPLOAD_PORT", DEFAULT_PORT),
        token_hash=_required_token_hash(),
        root=root,
        max_bytes=_env_int("HEALTH_UPLOAD_MAX_BYTES", DEFAULT_MAX_BYTES),
        max_uncompressed_bytes=_env_int(
            "HEALTH_UPLOAD_MAX_UNCOMPRESSED_BYTES",
            DEFAULT_MAX_UNCOMPRESSED_BYTES,
        ),
    )


def receive_health_import(
    *,
    headers: Mapping[str, str],
    body: bytes,
    config: HealthUploadConfig,
    now: datetime | None = None,
) -> HealthImportResult:
    _validate_authorization(headers, config.token_hash)
    _validate_content_headers(headers)

    if len(body) > config.max_bytes:
        raise HealthUploadError(
            "payload_too_large",
            "Payload exceeds HEALTH_UPLOAD_MAX_BYTES.",
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        )

    export_id = _validated_export_id(_header_value(headers, "X-Robopen-Export-Id"))
    expected_hash = _validated_sha256(_header_value(headers, "X-Robopen-Payload-Sha256"))
    actual_hash = hashlib.sha256(body).hexdigest()
    if not hmac.compare_digest(expected_hash.lower(), actual_hash):
        raise HealthUploadError("payload_hash_mismatch", "Payload SHA-256 does not match request header.")

    decoded = _decompress_payload(body, config.max_uncompressed_bytes)
    payload = _load_payload(decoded)
    _validate_payload(payload, export_id)
    record_count = _list_count(payload.get("records"))
    deleted_object_count = _list_count(payload.get("deletedObjects"))

    received_at_dt = now or datetime.now(timezone.utc)
    received_at = _iso_z(received_at_dt)
    final_path = _final_import_path(config.root, received_at_dt, export_id)
    workspace_path = _workspace_relative_path(final_path)

    final_path.parent.mkdir(parents=True, exist_ok=True)
    if final_path.exists():
        existing_hash = hashlib.sha256(final_path.read_bytes()).hexdigest()
        if hmac.compare_digest(existing_hash, actual_hash):
            return HealthImportResult(
                status="accepted",
                schema_version=SCHEMA_VERSION,
                import_id=export_id,
                workspace_path=workspace_path,
                received_at=received_at,
                payload_sha256=actual_hash,
                record_count=record_count,
                deleted_object_count=deleted_object_count,
                duplicate=True,
            )
        raise HealthUploadError(
            "export_id_conflict",
            "An import with the same export id already exists with different content.",
            HTTPStatus.CONFLICT,
        )

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{export_id}.",
        suffix=".tmp",
        dir=final_path.parent,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(body)
            file.flush()
            os.fchmod(file.fileno(), 0o600)
        os.replace(temp_path, final_path)
        os.chmod(final_path, 0o600)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    return HealthImportResult(
        status="accepted",
        schema_version=SCHEMA_VERSION,
        import_id=export_id,
        workspace_path=workspace_path,
        received_at=received_at,
        payload_sha256=actual_hash,
        record_count=record_count,
        deleted_object_count=deleted_object_count,
    )


def build_healthz(config: HealthUploadConfig) -> dict[str, Any]:
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "schemaVersion": SCHEMA_VERSION,
        "maxBytes": config.max_bytes,
    }


def run_server(config: HealthUploadConfig) -> None:
    class Handler(BaseHTTPRequestHandler):
        server_version = SERVICE_NAME

        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/healthz":
                self._send_error("not_found", "Not found.", HTTPStatus.NOT_FOUND)
                return
            self._send_json(build_healthz(config), HTTPStatus.OK)

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/v1/health/imports":
                self._send_error("not_found", "Not found.", HTTPStatus.NOT_FOUND)
                return
            length = self.headers.get("Content-Length")
            if length is None:
                self._send_error("missing_content_length", "Content-Length is required.", HTTPStatus.LENGTH_REQUIRED)
                return
            try:
                content_length = int(length)
            except ValueError:
                self._send_error("invalid_content_length", "Content-Length must be an integer.")
                return
            if content_length > config.max_bytes:
                self._send_error(
                    "payload_too_large",
                    "Payload exceeds HEALTH_UPLOAD_MAX_BYTES.",
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                )
                return

            try:
                _validate_authorization(self.headers, config.token_hash)
                _validate_content_headers(self.headers)
                _validated_export_id(_header_value(self.headers, "X-Robopen-Export-Id"))
                _validated_sha256(_header_value(self.headers, "X-Robopen-Payload-Sha256"))
                body = self.rfile.read(content_length)
                result = receive_health_import(headers=self.headers, body=body, config=config)
            except HealthUploadError as exc:
                self._send_error(exc.code, exc.message, exc.status)
                return
            except Exception:
                self._send_error("internal_error", "Receiver failed to process upload.", HTTPStatus.INTERNAL_SERVER_ERROR)
                return

            print(
                "[health-receiver] accepted "
                f"export_id={result.import_id} bytes={len(body)} "
                f"records={result.record_count} deleted={result.deleted_object_count} "
                f"duplicate={result.duplicate}"
            )
            self._send_json(result.to_json(), HTTPStatus.OK)

        def log_message(self, format: str, *args: Any) -> None:
            print(f"[health-receiver] {self.address_string()} {format % args}")

        def _send_json(self, payload: Mapping[str, Any], status: HTTPStatus) -> None:
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_error(
            self,
            code: str,
            message: str,
            status: HTTPStatus = HTTPStatus.BAD_REQUEST,
        ) -> None:
            print(f"[health-receiver] rejected code={code}")
            self._send_json({"status": "rejected", "code": code, "message": message}, status)

    server = ThreadingHTTPServer((config.host, config.port), Handler)
    print(f"[health-receiver] listening host={config.host} port={config.port} root={config.root}")
    server.serve_forever()


def main() -> None:
    load_dotenv()
    if not _env_bool("HEALTH_UPLOAD_ENABLED", default=False):
        raise RuntimeError("HEALTH_UPLOAD_ENABLED=true is required to start the health receiver.")
    run_server(config_from_env())


def _validate_authorization(headers: Mapping[str, str], token_hash: str) -> None:
    authorization = _header_value(headers, "Authorization")
    if not authorization or not authorization.startswith("Bearer "):
        raise HealthUploadError("missing_token", "Bearer token is required.", HTTPStatus.UNAUTHORIZED)
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HealthUploadError("missing_token", "Bearer token is required.", HTTPStatus.UNAUTHORIZED)
    actual_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(actual_hash, token_hash.lower()):
        raise HealthUploadError("invalid_token", "Bearer token is invalid.", HTTPStatus.UNAUTHORIZED)


def _validate_content_headers(headers: Mapping[str, str]) -> None:
    content_type = (_header_value(headers, "Content-Type") or "").split(";", 1)[0].strip().lower()
    if content_type != CONTENT_TYPE:
        raise HealthUploadError("invalid_content_type", f"Content-Type must be {CONTENT_TYPE}.")
    content_encoding = (_header_value(headers, "Content-Encoding") or "").strip().lower()
    if content_encoding != "deflate":
        raise HealthUploadError("invalid_content_encoding", "Content-Encoding must be deflate.")


def _decompress_payload(body: bytes, max_uncompressed_bytes: int) -> bytes:
    for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
        try:
            decompressor = zlib.decompressobj(wbits)
            decoded = decompressor.decompress(body, max_uncompressed_bytes + 1)
            decoded += decompressor.flush()
        except zlib.error:
            continue
        if len(decoded) > max_uncompressed_bytes or decompressor.unconsumed_tail:
            raise HealthUploadError(
                "uncompressed_payload_too_large",
                "Payload exceeds HEALTH_UPLOAD_MAX_UNCOMPRESSED_BYTES.",
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
        if not decompressor.eof:
            raise HealthUploadError("bad_deflate", "Payload is not valid deflate data.")
        return decoded
    raise HealthUploadError("bad_deflate", "Payload is not valid deflate data.")


def _load_payload(decoded: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(decoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HealthUploadError("invalid_json", "Payload must be valid UTF-8 JSON.") from exc
    if not isinstance(payload, dict):
        raise HealthUploadError("invalid_json", "Payload JSON root must be an object.")
    return payload


def _validate_payload(payload: Mapping[str, Any], export_id: str) -> None:
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        raise HealthUploadError("unsupported_schema_version", "Payload schemaVersion must be 1.")
    if payload.get("exportId") != export_id:
        raise HealthUploadError("export_id_mismatch", "Payload exportId must match X-Robopen-Export-Id.")
    if not isinstance(payload.get("records", []), list):
        raise HealthUploadError("invalid_records", "Payload records must be an array.")
    if not isinstance(payload.get("deletedObjects", []), list):
        raise HealthUploadError("invalid_deleted_objects", "Payload deletedObjects must be an array.")


def _final_import_path(root: Path, received_at: datetime, export_id: str) -> Path:
    day_dir = root / "inbox" / received_at.strftime("%Y") / received_at.strftime("%m") / received_at.strftime("%d")
    final_path = (day_dir / f"{export_id}.json.deflate").resolve()
    resolved_root = root.resolve()
    if not final_path.is_relative_to(resolved_root):
        raise HealthUploadError("invalid_import_path", "Resolved import path escapes upload root.")
    return final_path


def _workspace_relative_path(path: Path) -> str:
    workspace = get_codex_workspace_dir().resolve()
    try:
        return path.resolve().relative_to(workspace).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _validated_export_id(value: str | None) -> str:
    if not value:
        raise HealthUploadError("missing_export_id", "X-Robopen-Export-Id is required.")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise HealthUploadError("invalid_export_id", "X-Robopen-Export-Id must be a UUID.") from exc
    return str(parsed).upper()


def _validated_sha256(value: str | None) -> str:
    if not value:
        raise HealthUploadError("missing_payload_sha256", "X-Robopen-Payload-Sha256 is required.")
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise HealthUploadError("invalid_payload_sha256", "X-Robopen-Payload-Sha256 must be a SHA-256 hex digest.")
    return normalized


def _header_value(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None


def _list_count(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _required_token_hash() -> str:
    value = (os.environ.get("HEALTH_UPLOAD_TOKEN_HASH") or "").strip().lower()
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise RuntimeError("HEALTH_UPLOAD_TOKEN_HASH must be a SHA-256 hex digest.")
    return value


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than 0.")
    return value


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
