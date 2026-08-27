"""
Phase 1 runner: collect raw state from the demo VM and print it for inspection.

This exists to satisfy the Phase 1 acceptance criterion in CLAUDE.md Section 7 --
"collector returns real raw output from the Vagrant VM for every one of the 18
controls' required checks, printed/logged so you can visually confirm the data shape
before building anything that consumes it".

It prints the raw output grouped by control, and writes the whole collection to a
JSON file. That JSON is the input the Phase 2 normalizer is written against, so that
the normalizer is built on real observed output rather than invented fixtures.

Usage (defaults match the Vagrantfile in ../demo-environment):

    python backend/phase1_collect.py --from-vagrant-ssh-config
    python backend/phase1_collect.py --host 192.168.56.10 --user vagrant --key <path>
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from collectors.base import CollectorError  # noqa: E402
from collectors.ssh_collector import SSHCollector  # noqa: E402
from control_library import load_controls, required_sources  # noqa: E402

DEMO_DIR = pathlib.Path(__file__).parent.parent / "demo-environment"


def target_from_vagrant_ssh_config() -> dict:
    """Build a target dict by parsing 'vagrant ssh-config' in the demo directory."""
    try:
        proc = subprocess.run(
            ["vagrant", "ssh-config"],
            cwd=DEMO_DIR,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError as exc:
        raise CollectorError(
            "vagrant is not installed or not on PATH -- cannot derive SSH settings. "
            "Install Vagrant and VirtualBox, then run 'vagrant up' in "
            f"{DEMO_DIR}"
        ) from exc

    if proc.returncode != 0:
        raise CollectorError(
            f"'vagrant ssh-config' failed (exit {proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )

    fields: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            fields[parts[0]] = parts[1].strip('"')

    return {
        "target_id": "demo-ubuntu-vagrant",
        "resource_type": "linux_server",
        "host": fields.get("HostName", "127.0.0.1"),
        "port": int(fields.get("Port", 22)),
        "user": fields.get("User", "vagrant"),
        "key_filename": fields.get("IdentityFile"),
    }


def _print_command_result(record: dict, indent: str = "    ") -> None:
    status = "TIMEOUT" if record["timed_out"] else f"exit={record['exit_code']}"
    print(f"{indent}$ {record['command']}")
    print(f"{indent}  [{status}, {record['duration_ms']}ms]")

    for stream in ("stdout", "stderr"):
        text = record[stream]
        if not text.strip():
            continue
        print(f"{indent}  --- {stream} ---")
        for line in text.rstrip("\n").splitlines():
            print(f"{indent}  | {line}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-vagrant-ssh-config", action="store_true")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--user", default="vagrant")
    parser.add_argument("--key", dest="key_filename")
    parser.add_argument("--target-id", default="demo-ubuntu-vagrant")
    parser.add_argument(
        "--out",
        default=str(pathlib.Path(__file__).parent.parent / "phase1_raw_output.json"),
        help="where to write the raw collection JSON",
    )
    args = parser.parse_args()

    controls = load_controls()
    sources = required_sources(controls)
    print(f"Loaded {len(controls)} controls requiring {len(sources)} raw sources.\n")

    if args.from_vagrant_ssh_config:
        target = target_from_vagrant_ssh_config()
    elif args.host:
        target = {
            "target_id": args.target_id,
            "resource_type": "linux_server",
            "host": args.host,
            "port": args.port,
            "user": args.user,
            "key_filename": args.key_filename,
        }
    else:
        parser.error("supply either --from-vagrant-ssh-config or --host")

    target["sources"] = sources

    print(
        f"Collecting from {target['target_id']} "
        f"({target['user']}@{target['host']}:{target['port']})\n"
    )

    collector = SSHCollector()
    docs = collector.collect(target)
    by_source = {doc["source"]: doc for doc in docs}

    # Print grouped by control, so that each control's required checks can be
    # visually confirmed against the raw output that will feed its evaluation.
    for control in controls:
        source = control["test_logic"]["collector"]
        doc = by_source[source]
        print("=" * 78)
        print(f"{control['id']}  [{control['severity']}]  {control['title']}")
        print(f"source: {source}   resource_id: {doc['resource_id']}")
        print("=" * 78)
        for record in doc["commands"]:
            _print_command_result(record)

    out_path = pathlib.Path(args.out)
    out_path.write_text(json.dumps(docs, indent=2), encoding="utf-8")

    ok = sum(
        1
        for d in docs
        for c in d["commands"]
        if c["exit_code"] == 0 and not c["timed_out"]
    )
    total = sum(len(d["commands"]) for d in docs)
    print("-" * 78)
    print(f"sources collected : {len(docs)}/{len(sources)}")
    print(f"commands run      : {total}  ({ok} exit=0, {total - ok} non-zero/timeout)")
    print(f"raw output written: {out_path}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except CollectorError as exc:
        print(f"COLLECTION FAILED: {exc}", file=sys.stderr)
        sys.exit(2)
