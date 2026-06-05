from __future__ import annotations

import hashlib
import re


def content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = re.sub(r"\s+", " ", value.strip().lower())
    return normalized


def normalize_url(value: str | None) -> str:
    if not value:
        return ""
    return normalize_text(value).rstrip("/")
