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
    sub.add_argument("--confirm-manifest-digest", required=True)
    sub = commands.add_parser("inventory-ownership")
    sub.add_argument("--output", type=Path, required=True)
    sub = commands.add_parser("plan-mapping")
    sub.add_argument("--selection", type=Path, required=True)
    sub.add_argument("--output", type=Path, required=True)
    for command in ("apply-mapping", "verify-mapping"):
        sub = commands.add_parser(command)
        sub.add_argument("--manifest", type=Path, required=True)
        sub.add_argument("--confirm-manifest-digest", required=True)
        if command == "apply-mapping":
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
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        if (revision != "0007_accounts_ownership" and not (args.command == "inventory-ownership"
                and revision in {"0005_custom_workflows", "0006_durable_executions"})):
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
        if args.confirm_manifest_digest != manifest["manifest_digest"]:
            raise ValueError("Confirm the exact approved manifest digest")
        if not args.apply:
            print("No changes made. Review the manifest and obtain ownership approval before --apply.")
            return
        with db.engine.begin() as connection:
            count = legacy_ownership.apply(connection, manifest, confirm_login=args.confirm_login,
                                           approved_by=args.approval)
        print(json.dumps({"assigned_rows": count, "manifest_digest": manifest["manifest_digest"]}))
    elif args.command in {"inventory-ownership", "plan-mapping", "verify-mapping"}:
        with db.engine.connect() as connection, connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            if args.command == "inventory-ownership":
                result = (legacy_ownership.inventory(connection) if revision == "0007_accounts_ownership"
                          else legacy_ownership.inventory_before_accounts(connection))
            elif args.command == "plan-mapping":
                result = legacy_ownership.plan_mapping(connection, json.loads(args.selection.read_text(encoding="utf-8")))
            else:
                manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
                if args.confirm_manifest_digest != manifest["manifest_digest"]:
                    raise ValueError("Confirm the exact approved manifest digest")
                result = legacy_ownership.verify_mapping(connection, manifest)
        if args.command == "verify-mapping":
            print(json.dumps(result))
        else:
            with args.output.open("x", encoding="utf-8") as destination:
                json.dump(result, destination, indent=2)
            print(json.dumps({"action": args.command, "changes": False,
                              "digest": result.get("inventory_digest") if args.command == "inventory-ownership" else result["manifest_digest"]}))
    elif args.command == "apply-mapping":
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if args.confirm_manifest_digest != manifest["manifest_digest"]:
            raise ValueError("Confirm the exact approved manifest digest")
        if not args.apply:
            print("No changes made. Review the complete mapping and obtain approval before --apply.")
            return
        with db.engine.begin() as connection:
            count = legacy_ownership.apply_mapping(connection, manifest,
                confirm_digest=args.confirm_manifest_digest, approved_by=args.approval)
        print(json.dumps({"assigned_rows": count, "manifest_digest": manifest["manifest_digest"]}))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - never echo connection strings or credential-bearing exceptions.
        print("Account operation failed; no credentials are printed. Inspect identity, schema and approval inputs.",
              file=sys.stderr)
        raise SystemExit(1) from None
