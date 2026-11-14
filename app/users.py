"""Create and manage people in a deployment that is not the demo.

    python -m app.users create --username meera --name "Meera Iyer" --role admin
    python -m app.users set-password --username meera
    python -m app.users list

The password is asked for on the terminal (or read from NEW_USER_PASSWORD for scripted setup).
It is never accepted on the command line, where it would end up in shell history and process
lists. Passwords must be at least 10 characters and not a common password. Setting a password
signs the person out everywhere. Run it where DATABASE_URL points at the deployment's database,
for example from the service's shell.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import WEAK_PASSWORDS
from .enums import Role
from .models import User
from .security import set_user_password

MIN_LENGTH = 10


def check_password(password: str) -> None:
    if len(password) < MIN_LENGTH:
        raise ValueError(f"The password must be at least {MIN_LENGTH} characters.")
    if password.lower() in WEAK_PASSWORDS:
        raise ValueError("That password is too common. Choose another.")


def create_user(session: Session, username: str, display_name: str, role: str, password: str) -> User:
    username = username.strip().lower()
    if not username or len(username) > 64 or not username.replace("_", "").replace("-", "").replace(".", "").isalnum():
        raise ValueError("Username: letters, numbers, dot, dash or underscore, up to 64 characters.")
    if not display_name.strip():
        raise ValueError("A display name is required.")
    check_password(password)
    if session.scalar(select(User.id).where(User.username == username)):
        raise ValueError(f"The user {username!r} already exists. Use set-password to change the password.")
    user = User(username=username, display_name=display_name.strip()[:128], role=Role(role))
    set_user_password(user, password)
    session.add(user)
    session.commit()
    return user


def change_password(session: Session, username: str, password: str) -> User:
    check_password(password)
    user = session.scalar(select(User).where(User.username == username.strip().lower()))
    if user is None:
        raise ValueError(f"No user named {username!r}.")
    set_user_password(user, password)
    session.commit()
    return user


def _ask_password() -> str:
    env = os.environ.get("NEW_USER_PASSWORD")
    if env:
        return env
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat the password: "):
        raise ValueError("The two passwords differ.")
    return first


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.users", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create", help="add a person")
    c.add_argument("--username", required=True)
    c.add_argument("--name", required=True, help="display name")
    c.add_argument("--role", choices=[r.value for r in Role], default="viewer")
    p = sub.add_parser("set-password", help="change a password and sign the person out everywhere")
    p.add_argument("--username", required=True)
    sub.add_parser("list", help="show usernames and roles")
    args = ap.parse_args(argv)

    from .config import settings
    from .db import SessionLocal, init_db
    init_db(settings.migrate_on_startup)
    try:
        with SessionLocal() as session:
            if args.cmd == "list":
                for u in session.scalars(select(User).order_by(User.username)):
                    print(f"{u.username}\t{u.role.value}\t{u.display_name}")
            elif args.cmd == "create":
                user = create_user(session, args.username, args.name, args.role, _ask_password())
                print(f"Created {user.username} ({user.role.value}).")
            else:
                user = change_password(session, args.username, _ask_password())
                print(f"Password changed for {user.username}; they are signed out everywhere.")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
