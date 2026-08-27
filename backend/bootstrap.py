"""
One-time setup: create a local user, and store a target's SSH credential encrypted.

Passwords and key material are read from the environment or a file path, never taken
as command-line arguments — argv is visible to every process on the host via the
process table and is routinely captured in shell history.

Usage:
    AUDIT_PASSWORD=... python backend/bootstrap.py create-user aravind --role admin
    python backend/bootstrap.py store-vagrant-key --target-id demo-ubuntu-vagrant
    python backend/bootstrap.py list
"""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from auth.service import AuthError, create_user  # noqa: E402
from db import create_schema, get_engine, get_sessionmaker  # noqa: E402
from secrets_manager import has_credential, store_credential  # noqa: E402

DEMO_DIR = pathlib.Path(__file__).parent.parent / "demo-environment"


def _session():
    engine = get_engine()
    create_schema(engine)
    return get_sessionmaker(engine)()


def cmd_create_user(args) -> int:
    password = os.environ.get("AUDIT_PASSWORD")
    if not password:
        print("ERROR: set AUDIT_PASSWORD in the environment (not as an argument -- "
              "argv is world-readable via the process table)")
        return 2
    with _session() as s:
        try:
            create_user(s, args.username, password, role=args.role)
        except AuthError as exc:
            print(f"ERROR: {exc}")
            return 2
        s.commit()
    print(f"user '{args.username}' created/updated with role '{args.role}'")
    return 0


def cmd_store_vagrant_key(args) -> int:
    """Read the demo VM's private key via `vagrant ssh-config` and store it encrypted."""
    proc = subprocess.run(["vagrant", "ssh-config"], cwd=DEMO_DIR,
                          capture_output=True, text=True, timeout=90)
    if proc.returncode != 0:
        print(f"ERROR: vagrant ssh-config failed: {proc.stderr.strip()}")
        return 2

    identity = None
    for line in proc.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[0] == "IdentityFile":
            identity = parts[1].strip('"')
    if not identity:
        print("ERROR: no IdentityFile in vagrant ssh-config output")
        return 2

    key_path = pathlib.Path(identity)
    if not key_path.exists():
        print(f"ERROR: identity file does not exist: {key_path}")
        return 2

    material = key_path.read_text(encoding="utf-8")
    with _session() as s:
        store_credential(s, args.target_id, material,
                         credential_type="ssh_private_key",
                         description=f"demo VM key imported from {key_path.name}")
        s.commit()
    # The key length is printed, never the key.
    print(f"stored encrypted credential for target_id '{args.target_id}' "
          f"({len(material)} bytes of key material, source: {key_path.name})")
    print("The private key is now in the credentials table as Fernet ciphertext.")
    return 0


def cmd_list(args) -> int:
    from sqlalchemy import text
    with _session() as s:
        users = s.execute(text("SELECT username, role, disabled FROM users "
                               "ORDER BY username")).all()
        creds = s.execute(text("SELECT target_id, credential_type, length(ciphertext) "
                               "FROM credentials ORDER BY target_id")).all()
    print("users:")
    for u in users:
        print(f"  {u[0]:<16} role={u[1]:<10} disabled={u[2]}")
    print("credentials (ciphertext length only -- plaintext is never printed):")
    for c in creds:
        print(f"  {c[0]:<24} type={c[1]:<18} ciphertext={c[2]} bytes")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    cu = sub.add_parser("create-user")
    cu.add_argument("username")
    cu.add_argument("--role", default="auditor")
    cu.set_defaults(func=cmd_create_user)

    sk = sub.add_parser("store-vagrant-key")
    sk.add_argument("--target-id", default="demo-ubuntu-vagrant")
    sk.set_defaults(func=cmd_store_vagrant_key)

    ls = sub.add_parser("list")
    ls.set_defaults(func=cmd_list)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
