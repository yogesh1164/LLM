"""Inactive account foundations; does not claim deployed multi-user API isolation."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response

from app.auth_foundation import (
    COOKIE_NAME,
    Principal,
    Role,
    clear_session_cookie,
    hash_password,
    new_token,
    password_needs_rehash,
    require_admin,
    require_csrf,
    require_owner,
    session_valid,
    set_session_cookie,
    token_digest,
    verify_password,
)


def test_password_hashes_are_salted_and_do_not_accept_wrong_passwords():
    password = "offline long passphrase"
    first, second = hash_password(password), hash_password(password)
    assert first != second and first.startswith("$argon2id$")
    assert password not in first
    assert verify_password(first, password)
    assert not verify_password(first, "another long passphrase")
    assert not verify_password("invalid", password)
    assert not password_needs_rehash(first)


@pytest.mark.parametrize("password", ["short", "x" * 129])
def test_password_limits(password):
    with pytest.raises(ValueError):
        hash_password(password)
    assert not verify_password("unused", password)


def test_session_and_csrf_tokens_are_distinct_and_hashed():
    session, csrf = new_token(), new_token()
    assert len(session) == 43 and session != csrf
    assert session not in token_digest(session)
    require_csrf(origin="https://localhost:8443", allowed_origins={"https://localhost:8443"},
                 submitted=csrf, expected_digest=token_digest(csrf))


@pytest.mark.parametrize("origin,submitted", [
    (None, "valid"), ("https://evil.example", "valid"),
    ("https://localhost:8443.evil.example", "valid"),
    ("https://localhost:8443", None), ("https://localhost:8443", "wrong"),
])
def test_csrf_rejects_missing_cross_origin_and_wrong_tokens(origin, submitted):
    with pytest.raises(HTTPException) as error:
        require_csrf(origin=origin, allowed_origins={"https://localhost:8443"},
                     submitted=submitted, expected_digest=token_digest("valid"))
    assert error.value.status_code == 403


def test_cookie_flags_and_clearing():
    response = Response()
    set_session_cookie(response, new_token(), max_age=3600)
    cookie = response.headers["set-cookie"]
    assert COOKIE_NAME in cookie
    assert all(flag in cookie for flag in ("Secure", "HttpOnly", "SameSite=strict", "Path=/"))
    assert "Domain=" not in cookie
    assert response.headers["cache-control"] == "no-store"
    cleared = Response()
    clear_session_cookie(cleared)
    assert "Max-Age=0" in cleared.headers["set-cookie"]


@pytest.mark.parametrize("expired,idle,revoked,enabled,valid", [
    (False, False, False, True, True), (True, False, False, True, False),
    (False, True, False, True, False), (False, False, True, True, False),
    (False, False, False, False, False),
])
def test_session_expiration_and_revocation(expired, idle, revoked, enabled, valid):
    now = datetime.now(UTC)
    future = now + timedelta(hours=1)
    assert session_valid(expires_at=now if expired else future,
                         idle_expires_at=now if idle else future, now=now,
                         revoked=revoked, user_enabled=enabled) is valid


@pytest.mark.parametrize("role", [Role.ADMIN, Role.MEMBER])
def test_user_a_cannot_access_user_b_or_unassigned_resources(role):
    user_a = Principal(uuid4(), role)
    require_owner(user_a, user_a.user_id)
    for owner in (uuid4(), None):
        with pytest.raises(HTTPException) as error:
            require_owner(user_a, owner)
        assert error.value.status_code == 404
    with pytest.raises(HTTPException):
        require_owner(Principal(user_a.user_id, role, enabled=False), user_a.user_id)


def test_member_cannot_use_admin_operations():
    require_admin(Principal(uuid4(), Role.ADMIN))
    for principal in (Principal(uuid4(), Role.MEMBER), Principal(uuid4(), Role.ADMIN, False)):
        with pytest.raises(HTTPException) as error:
            require_admin(principal)
        assert error.value.status_code == 403
