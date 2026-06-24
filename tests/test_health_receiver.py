from __future__ import annotations

import hashlib
import json
import stat
import zlib
from datetime import datetime, timezone

import pytest

from robopen_agent.health_receiver import (
    CONTENT_TYPE,
    HealthUploadConfig,
    HealthUploadError,
    build_healthz,
    receive_health_import,
)


EXPORT_ID = "8D8A2E31-3D8F-4C6A-8F99-BB8290F8D4DE"
TOKEN = "local-test-token"


def test_receive_health_import_writes_deflate_payload_to_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("CODEX_WORKSPACE_DIR", str(workspace))
    config = _config(workspace)
    body = _compressed_payload(records=[{"uuid": "sample-1"}], deleted=[{"uuid": "deleted-1"}])

    result = receive_health_import(
        headers=_headers(body),
        body=body,
        config=config,
        now=datetime(2026, 6, 16, 10, 15, tzinfo=timezone.utc),
    )

    assert result.to_json() == {
        "status": "accepted",
        "schemaVersion": 1,
        "importId": EXPORT_ID,
        "workspacePath": f"healthcare/inbox/2026/06/16/{EXPORT_ID}.json.deflate",
        "receivedAt": "2026-06-16T10:15:00Z",
        "recordCount": 1,
        "deletedObjectCount": 1,
        "payloadSha256": hashlib.sha256(body).hexdigest(),
    }
    saved = workspace / "healthcare" / "inbox" / "2026" / "06" / "16" / f"{EXPORT_ID}.json.deflate"
    assert saved.read_bytes() == body
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600


def test_receive_health_import_accepts_duplicate_same_hash(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("CODEX_WORKSPACE_DIR", str(workspace))
    config = _config(workspace)
    body = _compressed_payload()
    now = datetime(2026, 6, 16, 10, 15, tzinfo=timezone.utc)

    receive_health_import(headers=_headers(body), body=body, config=config, now=now)
    duplicate = receive_health_import(headers=_headers(body), body=body, config=config, now=now)

    assert duplicate.duplicate is True
    assert duplicate.to_json()["duplicate"] is True


def test_receive_health_import_rejects_duplicate_different_hash(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("CODEX_WORKSPACE_DIR", str(workspace))
    config = _config(workspace)
    now = datetime(2026, 6, 16, 10, 15, tzinfo=timezone.utc)
    original = _compressed_payload()

    receive_health_import(headers=_headers(original), body=original, config=config, now=now)
    different = _compressed_payload(records=[{"uuid": "different"}])

    with pytest.raises(HealthUploadError) as exc:
        receive_health_import(headers=_headers(different), body=different, config=config, now=now)

    assert exc.value.code == "export_id_conflict"


def test_receive_health_import_rejects_missing_token(tmp_path):
    body = _compressed_payload()
    headers = _headers(body)
    headers.pop("Authorization")

    with pytest.raises(HealthUploadError) as exc:
        receive_health_import(headers=headers, body=body, config=_config(tmp_path))

    assert exc.value.code == "missing_token"


def test_receive_health_import_rejects_invalid_token(tmp_path):
    body = _compressed_payload()
    headers = _headers(body)
    headers["Authorization"] = "Bearer wrong"

    with pytest.raises(HealthUploadError) as exc:
        receive_health_import(headers=headers, body=body, config=_config(tmp_path))

    assert exc.value.code == "invalid_token"


def test_receive_health_import_rejects_oversized_compressed_payload(tmp_path):
    body = _compressed_payload()
    config = _config(tmp_path, max_bytes=len(body) - 1)

    with pytest.raises(HealthUploadError) as exc:
        receive_health_import(headers=_headers(body), body=body, config=config)

    assert exc.value.code == "payload_too_large"


def test_receive_health_import_rejects_bad_deflate(tmp_path):
    body = b"not-deflate"
    headers = _headers(body)

    with pytest.raises(HealthUploadError) as exc:
        receive_health_import(headers=headers, body=body, config=_config(tmp_path))

    assert exc.value.code == "bad_deflate"


def test_receive_health_import_rejects_bad_hash(tmp_path):
    body = _compressed_payload()
    headers = _headers(body)
    headers["X-Robopen-Payload-Sha256"] = "0" * 64

    with pytest.raises(HealthUploadError) as exc:
        receive_health_import(headers=headers, body=body, config=_config(tmp_path))

    assert exc.value.code == "payload_hash_mismatch"


def test_receive_health_import_rejects_export_id_path_traversal(tmp_path):
    body = _compressed_payload()
    headers = _headers(body)
    headers["X-Robopen-Export-Id"] = "../../secret"

    with pytest.raises(HealthUploadError) as exc:
        receive_health_import(headers=headers, body=body, config=_config(tmp_path))

    assert exc.value.code == "invalid_export_id"


def test_receive_health_import_rejects_invalid_json(tmp_path):
    body = zlib.compress(b"{")

    with pytest.raises(HealthUploadError) as exc:
        receive_health_import(headers=_headers(body), body=body, config=_config(tmp_path))

    assert exc.value.code == "invalid_json"


def test_receive_health_import_rejects_missing_schema_version(tmp_path):
    body = _compressed_payload({"exportId": EXPORT_ID, "records": [], "deletedObjects": []})

    with pytest.raises(HealthUploadError) as exc:
        receive_health_import(headers=_headers(body), body=body, config=_config(tmp_path))

    assert exc.value.code == "unsupported_schema_version"


def test_healthz_reports_receiver_contract(tmp_path):
    config = _config(tmp_path, max_bytes=1234)

    assert build_healthz(config) == {
        "status": "ok",
        "service": "robopen-health-receiver",
        "schemaVersion": 1,
        "maxBytes": 1234,
    }


def _config(root, *, max_bytes=20 * 1024 * 1024) -> HealthUploadConfig:
    return HealthUploadConfig(
        host="127.0.0.1",
        port=8787,
        token_hash=hashlib.sha256(TOKEN.encode("utf-8")).hexdigest(),
        root=root / "healthcare",
        max_bytes=max_bytes,
        max_uncompressed_bytes=100 * 1024 * 1024,
    )


def _headers(body: bytes) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": CONTENT_TYPE,
        "Content-Encoding": "deflate",
        "X-Robopen-Export-Id": EXPORT_ID,
        "X-Robopen-Payload-Sha256": hashlib.sha256(body).hexdigest(),
    }


def _compressed_payload(payload=None, *, records=None, deleted=None) -> bytes:
    if payload is None:
        payload = {
            "schemaVersion": 1,
            "exportId": EXPORT_ID,
            "generatedAt": "2026-06-16T10:14:52Z",
            "mode": "incremental",
            "records": records or [],
            "deletedObjects": deleted or [],
        }
    return zlib.compress(json.dumps(payload).encode("utf-8"))
