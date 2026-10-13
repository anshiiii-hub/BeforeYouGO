"""Operational commands: ``python -m app.cli <command>``."""

from __future__ import annotations

import argparse
import getpass
import json
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import session_scope
from app.core.logging import configure_logging
from app.core.security import hash_password, validate_password_strength
from app.models import User
from app.services.sources.registry import seed_sources
from app.services.sync import run_source_sync, sync_all_sources


def main(argv: list[str] | None = None) -> int:
    configure_logging("INFO")
    parser = argparse.ArgumentParser(prog="byg")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed-sources", help="create/refresh the source catalogue")
    s = sub.add_parser("sync", help="synchronise one source or all of them")
    s.add_argument("source", nargs="?")
    a = sub.add_parser("create-admin", help="create an administrator account")
    a.add_argument("--email", required=True)
    a.add_argument("--name", default="Administrator")
    a.add_argument("--password", help="omit to be prompted")
    args = parser.parse_args(argv)

    if args.cmd == "seed-sources":
        with session_scope() as db:
            seed_sources(db)
        print("source catalogue refreshed")
    elif args.cmd == "sync":
        with session_scope() as db:
            seed_sources(db)
        result = [run_source_sync(args.source, trigger="manual")] if args.source else sync_all_sources("manual")
        print(json.dumps(result, indent=2, default=str))
    elif args.cmd == "create-admin":
        password = args.password or getpass.getpass("Password: ")
        problems = validate_password_strength(password)
        if problems:
            print("Weak password: " + " ".join(problems), file=sys.stderr)
            return 2
        with session_scope() as db:
            if db.scalar(select(User).where(User.email == args.email.lower())):
                print("A user with that email already exists.", file=sys.stderr)
                return 1
            db.add(User(email=args.email.lower(), password_hash=hash_password(password), display_name=args.name, role="admin"))
        print("admin created")
    _ = get_settings
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
