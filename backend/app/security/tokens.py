"""Opaque API-token issuance and verification helpers.

Tokens are generated from 256 bits of entropy. The raw value is returned once;
only a SHA-256 digest is stored, so a database read does not reveal credentials.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import ApiToken, AuditLog, Principal

TOKEN_PREFIX = "afs_pat_"
DEFAULT_TTL_DAYS = 30
MAX_TTL_DAYS = 365


class AuthenticationError(ValueError):
    pass


def token_digest(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def issue_api_token(
    db: Session,
    *,
    principal_id: UUID,
    ttl_days: int = DEFAULT_TTL_DAYS,
) -> tuple[ApiToken, str]:
    if not 1 <= ttl_days <= MAX_TTL_DAYS:
        raise ValueError(f"ttl_days must be between 1 and {MAX_TTL_DAYS}")
    principal = db.get(Principal, principal_id)
    if principal is None or not principal.is_active:
        raise ValueError("active principal not found")
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    row = ApiToken(
        principal_id=principal_id,
        token_prefix=raw[:20],
        token_hash=token_digest(raw),
        expires_at=now + timedelta(days=ttl_days),
    )
    db.add(row)
    db.flush()
    db.add(AuditLog(
        project_id=None, actor_id=principal_id, actor_kind=principal.principal_kind,
        action="api_token.issued", object_type="api_token", object_id=row.id,
        details={"expires_at": row.expires_at.isoformat(), "token_prefix": row.token_prefix},
    ))
    return row, raw


def authenticate_api_token(db: Session, raw_token: str) -> Principal:
    if not raw_token.startswith(TOKEN_PREFIX) or len(raw_token) > 128:
        raise AuthenticationError("invalid bearer token")
    row = db.scalar(select(ApiToken).where(ApiToken.token_hash == token_digest(raw_token)))
    now = datetime.now(timezone.utc)
    if row is None or row.revoked_at is not None:
        raise AuthenticationError("invalid bearer token")
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= now:
        raise AuthenticationError("expired bearer token")
    principal = db.get(Principal, row.principal_id)
    if principal is None or not principal.is_active:
        raise AuthenticationError("inactive principal")
    return principal
