"""Object storage adapter.

Primary target: Cloudflare R2 (S3-compatible). Falls back to local disk under the configured shard-local training export root when R2 env vars are unset — so the exporter
works out-of-the-box in dev without external credentials. The `.url` returned
in fallback mode points at our own backend, which streams the file via
`GET /api/training/datasets/{id}/download`.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from config import settings

# --- Configuration ----------------------------------------------------------

R2_ACCOUNT_ID   = os.environ.get("R2_ACCOUNT_ID", "").strip()
R2_ACCESS_KEY   = os.environ.get("R2_ACCESS_KEY_ID", "").strip()
R2_SECRET_KEY   = os.environ.get("R2_SECRET_ACCESS_KEY", "").strip()
R2_BUCKET       = os.environ.get("R2_BUCKET", "").strip()
R2_PUBLIC_URL   = os.environ.get("R2_PUBLIC_URL", "").strip()  # optional public.r2.dev URL

LOCAL_ROOT = settings.training_local_root
LOCAL_ROOT.mkdir(parents=True, exist_ok=True)

# Public backend URL used to build fallback URLs. Same env var the webhook
# receiver will use for its Modal callback URL.
PUBLIC_BACKEND_URL = os.environ.get(
    "PUBLIC_BACKEND_URL", ""
).rstrip("/")


def r2_configured() -> bool:
    return bool(R2_ACCOUNT_ID and R2_ACCESS_KEY and R2_SECRET_KEY and R2_BUCKET)


_client = None


def _r2_client():
    global _client
    if _client is None:
        import boto3
        from botocore.client import Config
        _client = boto3.client(
            "s3",
            endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=R2_ACCESS_KEY,
            aws_secret_access_key=R2_SECRET_KEY,
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )
    return _client


# --- Public API -------------------------------------------------------------

def put_bytes(key: str, data: bytes,
              content_type: str = "application/octet-stream") -> str:
    """Upload data. Returns a publicly-fetchable URL."""
    if r2_configured():
        _r2_client().put_object(
            Bucket=R2_BUCKET, Key=key, Body=data, ContentType=content_type,
        )
        if R2_PUBLIC_URL:
            return f"{R2_PUBLIC_URL.rstrip('/')}/{key}"
        # No public bucket URL — return a 24h presigned GET as the "public" URL.
        return presign_get(key, expires=86400)
    # Local fallback.
    path = LOCAL_ROOT / key.replace("/", "_")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    # Build a self-served URL. The dataset route exposes /datasets/{id}/download.
    # Callers (exporter) will overwrite this with the proper route URL after
    # the DB row is created.
    if PUBLIC_BACKEND_URL:
        return f"{PUBLIC_BACKEND_URL}/api/training/exports/{path.name}"
    return f"local://{path.name}"


def presign_get(key: str, expires: int = 3600) -> str:
    """Time-limited GET URL for R2. Raises if R2 not configured."""
    if not r2_configured():
        raise RuntimeError("R2 not configured — cannot presign")
    return _r2_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": R2_BUCKET, "Key": key},
        ExpiresIn=expires,
    )


def get_bytes(key: str) -> Optional[bytes]:
    """Download an object by key. Returns None if the object is missing.
    Raises for any other error so callers can distinguish 404 from failure.
    """
    if r2_configured():
        from botocore.exceptions import ClientError
        try:
            obj = _r2_client().get_object(Bucket=R2_BUCKET, Key=key)
            return obj["Body"].read()
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404", "NoSuchBucket"):
                return None
            raise
    # Local fallback — mirror the key-mangling from put_bytes
    path = LOCAL_ROOT / key.replace("/", "_")
    if not path.exists():
        return None
    return path.read_bytes()


def delete_key(key: str) -> bool:
    """Delete an object by key. Returns True if it existed."""
    if r2_configured():
        try:
            _r2_client().delete_object(Bucket=R2_BUCKET, Key=key)
            return True
        except RuntimeError:
            return False
    path = LOCAL_ROOT / key.replace("/", "_")
    if path.exists():
        path.unlink()
        return True
    return False


def local_path(filename: str) -> Path:
    """Resolve a local-stored artifact by its stored filename."""
    return LOCAL_ROOT / filename


def is_local_url(url: str) -> bool:
    return url.startswith("local://") or "/api/training/exports/" in url
