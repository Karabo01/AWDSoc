"""Operator CLI. Bootstrapping only - everything else belongs in the API.

    python -m app.cli generate-key
    python -m app.cli create-user --email a@b.c --name "A B" --role platform_admin
    python -m app.cli create-user --email u@client.co --name "U" \
        --role client_admin --tenant-slug acme-corp
"""

import argparse
import asyncio
import getpass
import secrets
import sys

from sqlalchemy import select

from app.crypto import generate_key
from app.db import SessionLocal
from app.models import Tenant, User
from app.models.user import CLIENT_ROLES, ROLES, STAFF_ROLES
from app.security import hash_password


async def create_user(args: argparse.Namespace) -> int:
    if args.role not in ROLES:
        print(f"role must be one of: {', '.join(ROLES)}", file=sys.stderr)
        return 2

    is_staff = args.role in STAFF_ROLES
    if is_staff and args.tenant_slug:
        print("staff users are not scoped to a tenant; drop --tenant-slug", file=sys.stderr)
        return 2
    if args.role in CLIENT_ROLES and not args.tenant_slug:
        print(f"--tenant-slug is required for role {args.role}", file=sys.stderr)
        return 2

    password = args.password or getpass.getpass("Password: ")
    if not password:
        password = secrets.token_urlsafe(18)
        print(f"Generated password: {password}")

    async with SessionLocal() as session:
        tenant_id = None
        if args.tenant_slug:
            tenant = await session.scalar(select(Tenant).where(Tenant.slug == args.tenant_slug))
            if tenant is None:
                print(f"no tenant with slug {args.tenant_slug!r}", file=sys.stderr)
                return 1
            tenant_id = tenant.id

        existing = await session.scalar(select(User).where(User.email == args.email))
        if existing is not None:
            print(f"{args.email} already exists", file=sys.stderr)
            return 1

        session.add(
            User(
                email=args.email,
                full_name=args.name,
                role=args.role,
                is_staff=is_staff,
                tenant_id=tenant_id,
                password_hash=hash_password(password),
            )
        )
        await session.commit()

    print(f"created {args.email} ({args.role})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("generate-key", help="print a fresh base64 ENCRYPTION_KEY")

    cu = sub.add_parser("create-user", help="create a user")
    cu.add_argument("--email", required=True)
    cu.add_argument("--name", required=True)
    cu.add_argument("--role", required=True, choices=list(ROLES))
    cu.add_argument("--tenant-slug", help="client roles only")
    cu.add_argument("--password", help="omit to be prompted, or to have one generated")

    args = parser.parse_args()

    if args.command == "generate-key":
        print(generate_key())
        return 0
    return asyncio.run(create_user(args))


if __name__ == "__main__":
    raise SystemExit(main())
