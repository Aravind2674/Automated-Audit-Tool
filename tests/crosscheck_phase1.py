"""
CLAUDE.md Section 9 rule 8 -- independent self-verification of collector output.

Re-runs each selected control's primary evidence command over a FRESH SSH connection,
opened separately from the one the collector used, and diffs the result against what
the collector recorded in phase1_raw_output.json.

Why a fresh connection matters: reusing the collector's own Connection object, or
re-reading its in-memory results, would verify nothing -- it would compare the
collector against itself. This opens a new transport, runs the command again, and
compares the bytes.

What a mismatch means:
  * exit code differs      -> the collector recorded a different result than the host
                              actually produces. Hard failure.
  * stdout differs         -> either the collector mangled the output, or the value
                              genuinely changed on the host between runs. Both need
                              investigating; neither is ignorable.

Volatility: the commands cross-checked here are deliberately chosen to be
deterministic across runs on an idle host (config file reads, stat, sysctl, dpkg
queries). Commands whose output legitimately varies between invocations -- anything
including timestamps, PIDs, or live counters -- are excluded from the cross-check
rather than normalised, because normalising is where a real discrepancy would get
quietly massaged away.

Usage:
    python tests/crosscheck_phase1.py --from-vagrant-ssh-config
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from fabric import Connection  # noqa: E402

from collectors.base import CollectorError  # noqa: E402
from phase1_collect import target_from_vagrant_ssh_config  # noqa: E402

#: control_id -> (source, index of the command within that source's command list)
#: The chosen command is the one carrying the control's primary evidence.
CROSSCHECK: dict[str, tuple[str, int]] = {
    "CIS-5.2.10": ("ssh_config", 0),          # sudo -n sshd -T
    "CIS-5.3.1": ("pwquality", 0),            # cat /etc/security/pwquality.conf
    "CIS-3.2.1": ("sysctl", 0),               # sysctl <keys>
    "CIS-4.1.1": ("auditd", 0),               # dpkg-query auditd
    "CIS-1.4.2": ("file_permissions", 0),     # stat /etc/passwd /etc/shadow ...
    "CIS-1.6.1": ("unattended_upgrades", 3),  # apt-config dump APT::Periodic
    "CIS-6.1.1": ("sudo_config", 1),          # sudo grep Defaults
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-vagrant-ssh-config", action="store_true")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--user", default="vagrant")
    parser.add_argument("--key", dest="key_filename")
    parser.add_argument(
        "--raw",
        default=str(REPO_ROOT / "phase1_raw_output.json"),
        help="collector output to verify against",
    )
    args = parser.parse_args()

    raw_path = pathlib.Path(args.raw)
    if not raw_path.exists():
        print(f"ERROR: {raw_path} not found -- run backend/phase1_collect.py first")
        return 2

    docs = json.loads(raw_path.read_text(encoding="utf-8"))
    by_source = {d["source"]: d for d in docs}

    if args.from_vagrant_ssh_config:
        target = target_from_vagrant_ssh_config()
    elif args.host:
        target = {
            "host": args.host,
            "port": args.port,
            "user": args.user,
            "key_filename": args.key_filename,
        }
    else:
        parser.error("supply either --from-vagrant-ssh-config or --host")

    connect_kwargs = {}
    if target.get("key_filename"):
        connect_kwargs["key_filename"] = target["key_filename"]

    # A brand-new connection, deliberately not the collector's.
    conn = Connection(
        host=target["host"],
        user=target["user"],
        port=target["port"],
        connect_timeout=15,
        connect_kwargs=connect_kwargs,
    )

    print(f"Cross-checking {len(CROSSCHECK)} controls over a fresh SSH connection")
    print(f"collector output under test: {raw_path.name}")
    print(f"target: {target['user']}@{target['host']}:{target['port']}\n")

    results: list[tuple[str, bool, str]] = []

    try:
        conn.open()
        for control_id, (source, idx) in sorted(CROSSCHECK.items()):
            recorded = by_source[source]["commands"][idx]
            command = recorded["command"]

            fresh = conn.run(command, hide=True, warn=True, pty=False, timeout=30)

            exit_match = fresh.exited == recorded["exit_code"]
            stdout_match = fresh.stdout == recorded["stdout"]
            ok = exit_match and stdout_match

            if ok:
                detail = f"exit={fresh.exited}, {len(fresh.stdout)} bytes identical"
            else:
                parts = []
                if not exit_match:
                    parts.append(
                        f"exit {recorded['exit_code']} -> {fresh.exited}"
                    )
                if not stdout_match:
                    parts.append(
                        f"stdout {len(recorded['stdout'])} -> {len(fresh.stdout)} bytes"
                    )
                detail = "; ".join(parts)

            results.append((control_id, ok, detail))
            print(f"  {'PASS' if ok else 'FAIL'}  {control_id:<12} {detail}")
    finally:
        conn.close()

    failed = [r for r in results if not r[1]]
    print()
    print(f"cross-checked : {len(results)} controls")
    print(f"matched       : {len(results) - len(failed)}")
    print(f"mismatched    : {len(failed)}")

    if failed:
        print("\nMISMATCHES -- do not report Criterion 2 as met:")
        for control_id, _, detail in failed:
            print(f"  {control_id}: {detail}")
        return 1

    print("\nall cross-checked controls match the collector's recorded output")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except CollectorError as exc:
        print(f"CROSS-CHECK FAILED TO RUN: {exc}", file=sys.stderr)
        sys.exit(2)
