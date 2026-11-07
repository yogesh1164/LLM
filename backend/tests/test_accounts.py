"""Offline account service tests; these do not certify route ownership isolation."""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import accounts
from app import database as db
from app.auth_foundation import Role, token_digest

PASSWORD = "synthetic-test-password-only"


def member(name="test-member"):
    return accounts.create_user(name, PASSWORD)


def test_bootstrap_is_explicit_and_one_time():
    identifier = accounts.create_user("Administrator", PASSWORD, role=Role.ADMIN, bootstrap=True)
    with db.SessionLocal() as session:
        user = session.get(accounts.User, identifier)
        assert user.login == "administrator"
        assert user.password_hash.startswith("$argon2id$") and PASSWORD not in user.password_hash
    with pytest.raises(ValueError, match="empty"):
        accounts.create_user("another-admin", PASSWORD, role=Role.ADMIN, bootstrap=True)


def test_login_session_csrf_and_revocation():
    identifier = member()
    token, csrf, principal = accounts.login("TEST-MEMBER", PASSWORD)
    assert principal.user_id == identifier
    assert accounts.authenticate(token) == principal
    with db.SessionLocal() as session:
        row = session.get(accounts.AccountSession, token_digest(token))
        assert row.csrf_digest == token_digest(csrf)
        assert token != row.digest and csrf != row.csrf_digest
    origins = {"https://localhost:8443"}
    assert accounts.authenticate(token, origin=next(iter(origins)), csrf=csrf,
                                 allowed_origins=origins, mutation=True) == principal
    for origin, submitted in ((None, csrf), ("https://evil.invalid", csrf),
                               (next(iter(origins)), "wrong"), (next(iter(origins)), None)):
        with pytest.raises(HTTPException) as rejected:
            accounts.authenticate(token, origin=origin, csrf=submitted,
                                  allowed_origins=origins, mutation=True)
        assert rejected.value.status_code == 403
    accounts.revoke(token)
    with pytest.raises(HTTPException) as rejected:
        accounts.authenticate(token)
    assert rejected.value.status_code == 401


@pytest.mark.parametrize("login,password", [("unknown", PASSWORD),
                          ("test-member", "incorrect-password-long"), ("test-member", ""), ("", PASSWORD)])
def test_login_errors_are_generic(login, password):
    member()
    with pytest.raises(HTTPException) as rejected:
        accounts.login(login, password)
    assert (rejected.value.status_code, rejected.value.detail) == (401, "Invalid credentials")


@pytest.mark.parametrize("field", ["expires_at", "idle_expires_at", "revoked_at", "disabled"])
def test_expiration_and_disabled_account(field):
    identifier = member()
    token, _, _ = accounts.login("test-member", PASSWORD)
    with db.SessionLocal.begin() as session:
        if field == "disabled":
            session.get(accounts.User, identifier).enabled = False
        else:
            setattr(session.get(accounts.AccountSession, token_digest(token)), field,
                    datetime.now(UTC) - timedelta(seconds=1))
    with pytest.raises(HTTPException) as rejected:
        accounts.authenticate(token)
    assert rejected.value.status_code == 401


def test_password_change_revokes_all_sessions():
    member()
    first, _, principal = accounts.login("test-member", PASSWORD)
    second, _, _ = accounts.login("test-member", PASSWORD)
    assert accounts.authenticate(first) == accounts.authenticate(second)
    accounts.change_password(principal, PASSWORD, "changed-synthetic-password")
    for token in (first, second):
        with pytest.raises(HTTPException):
            accounts.authenticate(token)
    with pytest.raises(HTTPException):
        accounts.login("test-member", PASSWORD)
    token, _, _ = accounts.login("test-member", "changed-synthetic-password")
    assert accounts.authenticate(token) == principal


def test_failed_password_change_preserves_session():
    member()
    token, _, principal = accounts.login("test-member", PASSWORD)
    with pytest.raises(HTTPException):
        accounts.change_password(principal, "incorrect-password-long", "changed-synthetic-password")
    with pytest.raises(ValueError):
        accounts.change_password(principal, PASSWORD, "short")
    assert accounts.authenticate(token) == principal


def test_login_throttle_persists_failed_attempts():
    member()
    for _ in range(5):
        with pytest.raises(HTTPException) as rejected:
            accounts.login("test-member", "incorrect-password-long")
        assert rejected.value.status_code == 401
    with pytest.raises(HTTPException) as rejected:
        accounts.login("test-member", PASSWORD)
    assert rejected.value.status_code == 429
    with db.SessionLocal.begin() as session:
        for bucket in session.scalars(select(accounts.LoginBucket)):
            bucket.window_start = datetime.now(UTC) - timedelta(minutes=6)
    assert accounts.login("test-member", PASSWORD)


def test_global_throttle_limits_unknown_account_cardinality():
    for i in range(3):
        accounts.admit_login(f"unknown-{i}", global_limit=3)
    with pytest.raises(HTTPException) as rejected:
        accounts.admit_login("unknown-4", global_limit=3)
    assert rejected.value.status_code == 429
    with db.SessionLocal() as session:
        assert len(session.scalars(select(accounts.LoginBucket)).all()) == 4


def test_missing_and_oversized_session_rejected():
    for token in (None, "", "x" * 129, "unknown"):
        with pytest.raises(HTTPException) as rejected:
            accounts.authenticate(token)
        assert rejected.value.status_code == 401


def test_operator_recovery_is_confirmed_revokes_sessions_and_audits():
    identifier = member()
    token, _, _ = accounts.login("test-member", PASSWORD)
    with pytest.raises(ValueError, match="identity"):
        accounts.recover_account(identifier, confirm_login="wrong", approved_by="offline-test",
                                 new_password="new-synthetic-password")
    assert accounts.authenticate(token)
    accounts.recover_account(identifier, confirm_login="test-member", approved_by="offline-test",
                             new_password="new-synthetic-password")
    with pytest.raises(HTTPException):
        accounts.authenticate(token)
    token, _, _ = accounts.login("test-member", "new-synthetic-password")
    accounts.recover_account(identifier, confirm_login="test-member", approved_by="offline-test", disable=True)
    with pytest.raises(HTTPException):
        accounts.authenticate(token)
    with db.SessionLocal() as session:
        events = session.scalars(select(accounts.AccountAudit.event)).all()
        assert set(events) == {"create_user", "operator_password_reset", "account_disabled"}


def test_last_admin_disable_is_refused():
    identifier = accounts.create_user("only-admin", PASSWORD, role=Role.ADMIN, bootstrap=True)
    with pytest.raises(ValueError, match="last enabled"):
        accounts.recover_account(identifier, confirm_login="only-admin", approved_by="offline-test", disable=True)


def test_invalid_login_cannot_alias_a_real_account():
    member("invalid-login")
    with pytest.raises(HTTPException) as rejected:
        accounts.login("", PASSWORD)
    assert rejected.value.status_code == 401
