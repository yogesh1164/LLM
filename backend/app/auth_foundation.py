"""Inactive V2 security primitives. Not wired into the MVP authentication path.

Do not expose account endpoints until the ownership migration/cutover is approved.
Session persistence, login admission control and transaction boundaries belong in
the approved account service; these functions alone do not implement login.
"""
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException, Response

_hasher = PasswordHasher()
COOKIE_NAME = "__Host-agentflow_session"


class Role(StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    role: Role
    enabled: bool = True


def hash_password(password: str) -> str:
    # Do not trim or silently truncate passwords. Bound hashing input/DoS cost.
    if not 15 <= len(password) <= 128:
        raise ValueError("Password must contain between 15 and 128 characters")
    return _hasher.hash(password)


def verify_password(encoded: str, password: str) -> bool:
    if not 15 <= len(password) <= 128:
        return False
    try:
        return _hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(encoded: str) -> bool:
    return _hasher.check_needs_rehash(encoded)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_valid(*, expires_at: datetime, idle_expires_at: datetime,
                  now: datetime, revoked: bool, user_enabled: bool) -> bool:
    if any(value.tzinfo is None for value in (expires_at, idle_expires_at, now)):
        raise ValueError("Session timestamps must be timezone aware")
    return not revoked and user_enabled and now < min(expires_at, idle_expires_at)


def set_session_cookie(response: Response, token: str, *, max_age: int) -> None:
    if max_age <= 0:
        raise ValueError("Session lifetime must be positive")
    response.set_cookie(COOKIE_NAME, token, max_age=max_age, secure=True,
                        httponly=True, samesite="strict", path="/")
    response.headers["Cache-Control"] = "no-store"


def clear_session_cookie(response: Response) -> None:
    # The account service must revoke the database session before clearing this cookie.
    response.delete_cookie(COOKIE_NAME, secure=True, httponly=True, samesite="strict", path="/")
    response.headers["Cache-Control"] = "no-store"


def require_csrf(*, origin: str | None, allowed_origins: set[str],
                 submitted: str | None, expected_digest: str) -> None:
    # Bind the CSRF token to a server-side session. Cookies alone are never proof.
    if (origin not in allowed_origins or not submitted or len(submitted) > 128
            or not hmac.compare_digest(token_digest(submitted), expected_digest)):
        raise HTTPException(status_code=403, detail="Request verification failed")


def require_owner(principal: Principal, owner_id: UUID | None) -> None:
    # Admin is not an implicit cross-user content reader; separate audited admin
    # operations will be designed at cutover. Null legacy ownership fails closed.
    if not principal.enabled or owner_id is None or owner_id != principal.user_id:
        raise HTTPException(status_code=404, detail="Resource not found")


def require_admin(principal: Principal) -> None:
    if not principal.enabled or principal.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Administrator access required")
