"""Cloudflare R2 (S3-compatible). Meta fetches videos from a public URL, so renders live here."""

from __future__ import annotations

import mimetypes
from functools import lru_cache
from pathlib import Path

import boto3

from engine.config import Settings, get_settings


@lru_cache
def _client(account_id: str, key_id: str, secret: str):
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
        region_name="auto",
    )


def client(settings: Settings | None = None):
    s = settings or get_settings()
    if not (s.r2_account_id and s.r2_access_key_id and s.r2_secret_access_key):
        raise RuntimeError("R2 credentials are not configured")
    return _client(
        s.r2_account_id,
        s.r2_access_key_id.get_secret_value(),
        s.r2_secret_access_key.get_secret_value(),
    )


def object_key(run_date: str, filename: str) -> str:
    return f"runs/{run_date}/{filename}"


def upload(path: Path, key: str, settings: Settings | None = None) -> str:
    s = settings or get_settings()
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    client(s).upload_file(str(path), s.r2_bucket, key, ExtraArgs={"ContentType": content_type})
    return f"s3://{s.r2_bucket}/{key}"


def public_url(key: str, settings: Settings | None = None) -> str:
    s = settings or get_settings()
    if not s.r2_public_base_url:
        raise RuntimeError("R2_PUBLIC_BASE_URL is not set; Meta needs a public video URL")
    return f"{s.r2_public_base_url.rstrip('/')}/{key}"


def download(key: str, dest: Path, settings: Settings | None = None) -> Path:
    s = settings or get_settings()
    dest.parent.mkdir(parents=True, exist_ok=True)
    client(s).download_file(s.r2_bucket, key, str(dest))
    return dest
