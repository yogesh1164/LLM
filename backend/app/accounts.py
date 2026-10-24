"""Account persistence and session service. No public registration or bootstrap API.

HTTP integration is deliberately separate from these transactional primitives.
Only digests of bearer session/CSRF tokens are persisted.
"""
from datetime import UTC, datetime, timedelta
from functools import wraps
from threading import BoundedSemaphore
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Uuid,
    select,
    update,
)
from sqlalchemy.orm import Mapped, mapped_column

from app import database as db
from app.auth_foundation import (
    Principal,
    Role,
    hash_password,
    new_token,
    password_needs_rehash,
    require_csrf,
    session_valid,
    token_digest,
    verify_password,
)

_hash_slots = BoundedSemaphore(2)


def bounded_hashing(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if not _hash_slots.acquire(blocking=False):
            raise HTTPException(503, "Authentication busy", headers={"Retry-After": "5"})
        try:
            return function(*args, **kwargs)
        finally:
            _hash_slots.release()
    return wrapped


class User(db.Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('admin', 'member')", name="ck_user_role"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    login: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    role: Mapped[str] = mapped_column(String(16), default="member")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    credential_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AccountSession(db.Base):
    __tablename__ = "account_sessions"
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    csrf_digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LoginBucket(db.Base):
    __tablename__ = "login_buckets"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer)


class OwnershipAssignment(db.Base):
    """Append-only operator manifest evidence, never passwords or content."""
    __tablename__ = "ownership_assignments"
    manifest_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    approved_by: Mapped[str] = mapped_column(String(254))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    row_count: Mapped[int] = mapped_column(Integer)


class AccountAudit(db.Base):
    __tablename__ = "account_audit"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    event: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str] = mapped_column(String(254))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def audit(session, user_id, event, actor):
    session.add(AccountAudit(user_id=user_id, event=event, actor=actor, created_at=datetime.now(UTC)))


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def normalize_login(value: str) -> str:
    value = value.strip().casefold()
    if not 3 <= len(value) <= 254 or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError("Login must contain 3-254 non-whitespace characters")
    return value


@bounded_hashing
def create_user(login: str, password: str, *, role: Role = Role.MEMBER,
                bootstrap: bool = False, approved_by: str = "offline-operator") -> UUID:
    """Offline operator operation. Bootstrap serialized on PostgreSQL."""
    login, encoded = normalize_login(login), hash_password(password)
    with db.SessionLocal.begin() as session:
        if session.bind.dialect.name == "postgresql":
            from sqlalchemy import text
            session.execute(text("SELECT pg_advisory_xact_lock(714329001)"))
        if bootstrap and session.scalar(select(User.id).limit(1)) is not None:
            raise ValueError("Bootstrap requires an empty account table")
        if bootstrap and role != Role.ADMIN:
            raise ValueError("Bootstrap requires an administrator")
        now = datetime.now(UTC)
        user = User(login=login, password_hash=encoded, role=role.value, enabled=True,
                    created_at=now, credential_changed_at=now)
        session.add(user)
        session.flush()
        audit(session, user.id, "bootstrap" if bootstrap else "create_user", approved_by)
        return user.id


def admit_login(login: str, *, limit: int = 5, global_limit: int = 60) -> None:
    """Atomic shared 5-minute buckets; admission commits even on bad credentials.

    Global admission precedes expensive Argon2 and bounds arbitrary-name attacks.
    Do not trust caller-supplied forwarded addresses as a throttling identity.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    now = datetime.now(UTC)
    denied = False
    with db.SessionLocal.begin() as session:
        insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
        for label, ceiling in (("global", global_limit), ("account:" + login, limit)):
            key = token_digest(label)
            session.execute(insert(LoginBucket).values(key=key, window_start=now, attempts=0)
                            .on_conflict_do_nothing(index_elements=["key"]))
            bucket = session.scalar(select(LoginBucket).where(LoginBucket.key == key).with_for_update())
            if utc(bucket.window_start) <= now - timedelta(minutes=5):
                bucket.window_start, bucket.attempts = now, 0
            if bucket.attempts >= ceiling:
                denied = True
                break
            bucket.attempts += 1
            session.flush()
        # Keep attacker-controlled login cardinality bounded across windows.
        from sqlalchemy import delete
        session.execute(delete(LoginBucket).where(LoginBucket.window_start < now - timedelta(minutes=10))
                        .execution_options(synchronize_session=False))
    if denied:
        raise HTTPException(429, "Too many login attempts", headers={"Retry-After": "300"})


# Same algorithm/cost for unknown accounts; never derived from user input.
_dummy_hash = hash_password("inactive-dummy-account-password")


@bounded_hashing
def login(login_name: str, password: str) -> tuple[str, str, Principal]:
    try:
        normalized = normalize_login(login_name)
        valid_login = True
    except ValueError:
        normalized = "invalid-login"
        valid_login = False
    admit_login(normalized)
    with db.SessionLocal.begin() as session:
        user = session.scalar(select(User).where(User.login == normalized).with_for_update())
        if not valid_login:
            user = None
        valid = verify_password(user.password_hash if user else _dummy_hash, password)
        if user is None or not user.enabled or not valid:
            raise HTTPException(401, "Invalid credentials")
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        token = new_token()
        csrf = token_digest("csrf:" + token)
        now = datetime.now(UTC)
        session.add(AccountSession(digest=token_digest(token), user_id=user.id,
            csrf_digest=token_digest(csrf), created_at=now,
            expires_at=now + timedelta(hours=12), idle_expires_at=now + timedelta(minutes=30)))
        return token, csrf, Principal(user.id, Role(user.role))


def authenticate(token: str | None, *, origin: str | None = None, csrf: str | None = None,
                 allowed_origins: set[str] | None = None, mutation: bool = False) -> Principal:
    if not token or len(token) > 128:
        raise HTTPException(401, "Authentication required")
    with db.SessionLocal.begin() as session:
        # Lock user before session, matching password changes and login ordering.
        row = session.get(AccountSession, token_digest(token))
        if row is None:
            raise HTTPException(401, "Authentication required")
        user = session.scalar(select(User).where(User.id == row.user_id).with_for_update())
        session.refresh(row, with_for_update=True)
        now = datetime.now(UTC)
        if not user or not session_valid(expires_at=utc(row.expires_at),
                idle_expires_at=utc(row.idle_expires_at), now=now,
                revoked=row.revoked_at is not None, user_enabled=user.enabled):
            raise HTTPException(401, "Authentication required")
        if mutation:
            require_csrf(origin=origin, allowed_origins=allowed_origins or set(),
                         submitted=csrf, expected_digest=row.csrf_digest)
        row.idle_expires_at = min(utc(row.expires_at), now + timedelta(minutes=30))
        return Principal(user.id, Role(user.role))


def revoke(token: str) -> None:
    with db.SessionLocal.begin() as session:
        session.execute(update(AccountSession).where(AccountSession.digest == token_digest(token))
                        .values(revoked_at=datetime.now(UTC)))


@bounded_hashing
def change_password(principal: Principal, old_password: str, new_password: str) -> None:
    # Validate policy before locking; hashing stays serialized with credential changes.
    if not 15 <= len(new_password) <= 128:
        raise ValueError("Password must contain between 15 and 128 characters")
    admit_login("password-change:" + str(principal.user_id))
    with db.SessionLocal.begin() as session:
        user = session.scalar(select(User).where(User.id == principal.user_id).with_for_update())
        if not user or not user.enabled or not verify_password(user.password_hash, old_password):
            raise HTTPException(401, "Invalid credentials")
        user.password_hash = hash_password(new_password)
        user.credential_changed_at = datetime.now(UTC)
        session.execute(update(AccountSession).where(AccountSession.user_id == user.id)
                        .values(revoked_at=user.credential_changed_at))
        audit(session, user.id, "password_changed", str(principal.user_id))


@bounded_hashing
def recover_account(user_id: UUID, *, confirm_login: str, approved_by: str,
                    new_password: str | None = None, disable: bool = False):
    """Offline operator recovery; no email reset or content-access override."""
    if not approved_by.strip() or len(approved_by) > 254 or (new_password is None and not disable):
        raise ValueError("An approval reference and recovery action are required")
    encoded = hash_password(new_password) if new_password is not None else None
    with db.SessionLocal.begin() as session:
        if session.bind.dialect.name == "postgresql":
            from sqlalchemy import text
            session.execute(text("SELECT pg_advisory_xact_lock(714329001)"))
        user = session.scalar(select(User).where(User.id == user_id).with_for_update())
        if not user or user.login != confirm_login:
            raise ValueError("Account identity confirmation failed")
        if disable and user.enabled and user.role == "admin":
            other_admin = session.scalar(select(User.id).where(User.role == "admin", User.enabled.is_(True),
                                                                User.id != user.id).limit(1))
            if other_admin is None:
                raise ValueError("Cannot disable the last enabled administrator")
        now = datetime.now(UTC)
        if encoded:
            user.password_hash, user.credential_changed_at = encoded, now
        if disable:
            user.enabled = False
        session.execute(update(AccountSession).where(AccountSession.user_id == user.id).values(revoked_at=now))
        audit(session, user.id, "account_disabled" if disable else "operator_password_reset", approved_by)
