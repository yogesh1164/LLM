"""Explicit operator-only account tooling; never run against a live DB without approval.

Passwords are read from a terminal, never argv, environment variables or files.
"""
import argparse
import getpass
import json
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from app import accounts, legacy_ownership
from app import database as db
from app.auth_foundation import Role


def password():
    if not sys.stdin.isatty():
        raise ValueError("Password entry requires an interactive terminal")
    first = getpass.getpass("New password (15-128 characters): ")
    if first != getpass.getpass("Confirm new password: "):
        raise ValueError("Passwords do not match")
    return first


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--expect-database", required=True)
    commands = result.add_subparsers(dest="command", required=True)
    for command in ("bootstrap", "add-member"):
        sub = commands.add_parser(command)
        sub.add_argument("--login", required=True)
        sub.add_argument("--approval", required=True)
    for command in ("reset-password", "disable-user"):
        sub = commands.add_parser(command)
        sub.add_argument("--user-id", type=UUID, required=True)
        sub.add_argument("--confirm-login", required=True)
        sub.add_argument("--approval", required=True)
    sub = commands.add_parser("plan-ownership")
    sub.add_argument("--owner-id", type=UUID, required=True)
    sub.add_argument("--output", type=Path, required=True)
    sub = commands.add_parser("assign-ownership")
    sub.add_argument("--manifest", type=Path, required=True)
    sub.add_argument("--confirm-login", required=True)
    sub.add_argument("--approval", required=True)
    sub.add_argument("--apply", action="store_true")
    return result


def main():
    args = parser().parse_args()
    with db.engine.connect() as connection:
        if connection.dialect.name != "postgresql":
            raise ValueError("Operator commands require PostgreSQL")
        if connection.scalar(text("SELECT current_database()")) != args.expect_database:
            raise ValueError("Database identity confirmation failed")
        if connection.scalar(text("SELECT version_num FROM alembic_version")) != "0007_accounts_ownership":
            raise ValueError("Expected account migration 0007")
    if args.command in {"bootstrap", "add-member"}:
        identifier = accounts.create_user(args.login, password(), bootstrap=args.command == "bootstrap",
            role=Role.ADMIN if args.command == "bootstrap" else Role.MEMBER, approved_by=args.approval)
        print(json.dumps({"user_id": str(identifier), "action": args.command}))
    elif args.command in {"reset-password", "disable-user"}:
        accounts.recover_account(args.user_id, confirm_login=args.confirm_login, approved_by=args.approval,
            new_password=password() if args.command == "reset-password" else None,
            disable=args.command == "disable-user")
        print(json.dumps({"user_id": str(args.user_id), "action": args.command}))
    elif args.command == "plan-ownership":
        with db.engine.connect() as connection:
            manifest = legacy_ownership.plan(connection, args.owner_id)
        with args.output.open("x", encoding="utf-8") as destination:
            json.dump(manifest, destination, indent=2)
        print(json.dumps({"manifest_digest": manifest["manifest_digest"], "action": "plan-only"}))
    elif args.command == "assign-ownership":
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not args.apply:
            print("No changes made. Review the manifest and obtain ownership approval before --apply.")
            return
        with db.engine.begin() as connection:
            count = legacy_ownership.apply(connection, manifest, confirm_login=args.confirm_login,
                                           approved_by=args.approval)
        print(json.dumps({"assigned_rows": count, "manifest_digest": manifest["manifest_digest"]}))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - never echo connection strings or credential-bearing exceptions.
        print("Account operation failed; no credentials are printed. Inspect identity, schema and approval inputs.",
              file=sys.stderr)
        raise SystemExit(1) from None
