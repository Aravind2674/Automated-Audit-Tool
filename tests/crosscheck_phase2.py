"""
CLAUDE.md Section 9 rule 8 -- independent self-verification of evaluator verdicts.

For every one of the 18 controls, this re-derives the pass/fail answer directly on the
host over a FRESH SSH connection, using a command formulated INDEPENDENTLY of the
collector's -- different tools, different flags, different parsing -- and compares it
against what the evaluator concluded from the normalized evidence.

Why the commands are deliberately different: re-running the collector's own command
and re-applying the normalizer's own parser would only prove the pipeline is
deterministic. It would not catch the failure mode that actually matters, which is the
collector and normalizer agreeing with each other about something the host never said.
Using `sysctl -n`, `stat -c %a`, `systemctl is-active --quiet` and friends -- none of
which the collector uses in that form -- makes agreement meaningful.

Usage:
    python tests/crosscheck_phase2.py --from-vagrant-ssh-config
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from fabric import Connection  # noqa: E402

from control_library import load_controls  # noqa: E402
from engine.evaluator import evaluate  # noqa: E402
from engine.normalizer import normalize  # noqa: E402
from phase1_collect import target_from_vagrant_ssh_config  # noqa: E402

WEAK = "cbc|hmac-md5|hmac-sha1|arcfour|group1-sha1|group14-sha1|group-exchange-sha1"

#: control_id -> shell snippet printing exactly "PASS" or "FAIL".
INDEPENDENT: dict[str, str] = {
    "CIS-5.2.10":
        "sudo -n sshd -T | grep -qiE '^permitrootlogin +no$' && echo PASS || echo FAIL",
    "CIS-5.2.11":
        f"sudo -n sshd -T | grep -E '^(ciphers|macs|kexalgorithms) ' | "
        f"grep -qiE '{WEAK}' && echo FAIL || echo PASS",
    "CIS-5.3.1":
        "v=$(grep -hE '^[[:space:]]*minlen' /etc/security/pwquality.conf "
        "/etc/security/pwquality.conf.d/*.conf 2>/dev/null | tail -1 | "
        "tr -d ' ' | cut -d= -f2); [ \"${v:-0}\" -ge 14 ] && echo PASS || echo FAIL",
    "CIS-5.3.2":
        "v=$(awk '/^PASS_MAX_DAYS/{print $2}' /etc/login.defs | tail -1); "
        "[ \"${v:-99999}\" -le 90 ] && echo PASS || echo FAIL",
    "CIS-5.4.1":
        "grep -qE '^[^#]*pam_faillock' /etc/pam.d/common-auth && echo PASS || echo FAIL",
    "CIS-3.1.1":
        "sudo -n ufw status verbose 2>/dev/null | grep -qiE '^Status: active' && "
        "sudo -n ufw status verbose | grep -qiE 'Default: (deny|reject) \\(incoming\\)' "
        "&& echo PASS || echo FAIL",
    "CIS-3.2.1":
        "[ \"$(sysctl -n net.ipv4.ip_forward)\" = 0 ] && "
        "[ \"$(sysctl -n net.ipv6.conf.all.forwarding)\" = 0 ] && echo PASS || echo FAIL",
    "CIS-3.3.1":
        "ok=1; for k in net.ipv4.conf.all.accept_redirects "
        "net.ipv4.conf.default.accept_redirects net.ipv4.conf.all.secure_redirects "
        "net.ipv4.conf.default.secure_redirects net.ipv6.conf.all.accept_redirects "
        "net.ipv6.conf.default.accept_redirects; do "
        "[ \"$(sysctl -n $k 2>/dev/null)\" = 0 ] || ok=0; done; "
        "[ $ok = 1 ] && echo PASS || echo FAIL",
    "CIS-4.1.1":
        "dpkg-query -W -f='${Status}' auditd 2>/dev/null | grep -q 'install ok installed' "
        "&& systemctl is-enabled --quiet auditd 2>/dev/null "
        "&& systemctl is-active --quiet auditd 2>/dev/null && echo PASS || echo FAIL",
    "CIS-4.1.2":
        "[ -f /etc/audit/auditd.conf ] && "
        "grep -qE '^[[:space:]]*max_log_file_action[[:space:]]*=[[:space:]]*keep_logs' "
        "/etc/audit/auditd.conf && echo PASS || echo FAIL",
    "CIS-4.2.1":
        "{ grep -rhE '^[^#[:space:]]\\S*[[:space:]]+@{1,2}[A-Za-z0-9]' "
        "/etc/rsyslog.conf /etc/rsyslog.d/ 2>/dev/null; "
        "grep -hE '^[[:space:]]*URL=' /etc/systemd/journal-upload.conf 2>/dev/null; } "
        "| grep -q . && echo PASS || echo FAIL",
    "CIS-1.1.1":
        "ok=1; for m in cramfs freevxfs jffs2 hfs hfsplus squashfs udf; do "
        "modprobe -n -v $m 2>&1 | grep -qE '/bin/(false|true)' || ok=0; done; "
        "[ $ok = 1 ] && echo PASS || echo FAIL",
    "CIS-1.1.2":
        "findmnt -n /tmp >/dev/null 2>&1 && "
        "findmnt -n -o OPTIONS /tmp | grep -q noexec && "
        "findmnt -n -o OPTIONS /tmp | grep -q nosuid && "
        "findmnt -n -o OPTIONS /tmp | grep -q nodev && echo PASS || echo FAIL",
    "CIS-1.4.1":
        "[ \"$(stat -c %a /etc/passwd)\" = 644 ] && "
        "[ \"$(stat -c %U /etc/passwd)\" = root ] && echo PASS || echo FAIL",
    "CIS-1.4.2":
        "case \"$(stat -c %a /etc/shadow)\" in 640|600|400|000|440|040) "
        "[ \"$(stat -c %U /etc/shadow)\" = root ] && echo PASS || echo FAIL;; "
        "*) echo FAIL;; esac",
    "CIS-1.5.1":
        "[ \"$(sysctl -n fs.suid_dumpable)\" = 0 ] && "
        "[ \"$(ulimit -Hc)\" = 0 ] && echo PASS || echo FAIL",
    "CIS-1.6.1":
        "u=$(apt-config dump APT::Periodic::Unattended-Upgrade 2>/dev/null | "
        "grep -oE '\"[0-9]+\"' | tr -d '\"'); "
        "l=$(apt-config dump APT::Periodic::Update-Package-Lists 2>/dev/null | "
        "grep -oE '\"[0-9]+\"' | tr -d '\"'); "
        "[ \"${u:-0}\" -ge 1 ] && [ \"${l:-0}\" -ge 1 ] && echo PASS || echo FAIL",
    "CIS-6.1.1":
        "sudo -n grep -rhqE '^[[:space:]]*Defaults.*logfile[[:space:]]*=' "
        "/etc/sudoers /etc/sudoers.d/ 2>/dev/null && echo PASS || echo FAIL",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-vagrant-ssh-config", action="store_true")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--user", default="vagrant")
    parser.add_argument("--key", dest="key_filename")
    parser.add_argument("--raw", default=str(REPO_ROOT / "phase1_raw_output.json"))
    args = parser.parse_args()

    raw_docs = json.loads(pathlib.Path(args.raw).read_text(encoding="utf-8"))
    resources = normalize(raw_docs, "ssh")
    controls = {c["id"]: c for c in load_controls()}

    if args.from_vagrant_ssh_config:
        target = target_from_vagrant_ssh_config()
    elif args.host:
        target = {
            "host": args.host, "port": args.port,
            "user": args.user, "key_filename": args.key_filename,
        }
    else:
        parser.error("supply either --from-vagrant-ssh-config or --host")

    connect_kwargs = {}
    if target.get("key_filename"):
        connect_kwargs["key_filename"] = target["key_filename"]

    conn = Connection(
        host=target["host"], user=target["user"], port=target["port"],
        connect_timeout=15, connect_kwargs=connect_kwargs,
    )

    print("Rule 8 cross-check: evaluator verdicts vs independent on-host derivation")
    print(f"target: {target['user']}@{target['host']}:{target['port']}")
    print("(commands below are formulated independently of the collector's)\n")

    mismatches = []
    print(f"{'CONTROL':<12} {'EVALUATOR':<11} {'ON-HOST':<9} MATCH")
    print("-" * 48)

    try:
        conn.open()
        for control_id in sorted(INDEPENDENT):
            verdict = evaluate(controls[control_id], resources)[0]["outcome"]
            fresh = conn.run(
                INDEPENDENT[control_id], hide=True, warn=True, pty=False, timeout=45
            )
            on_host = fresh.stdout.strip().splitlines()[-1].strip().lower() if fresh.stdout.strip() else "?"

            ok = verdict == on_host
            if not ok:
                mismatches.append((control_id, verdict, on_host, fresh.stdout.strip()))
            print(f"{control_id:<12} {verdict:<11} {on_host:<9} {'OK' if ok else '*MISMATCH*'}")
    finally:
        conn.close()

    print()
    print(f"cross-checked : {len(INDEPENDENT)} controls")
    print(f"matched       : {len(INDEPENDENT) - len(mismatches)}")
    print(f"mismatched    : {len(mismatches)}")

    if mismatches:
        print("\nMISMATCHES -- do not report Phase 2 as met:")
        for control_id, verdict, on_host, raw in mismatches:
            print(f"  {control_id}: evaluator={verdict} on-host={on_host} raw={raw!r}")
        return 1

    print("\nevery evaluator verdict independently confirmed on the host")
    return 0


if __name__ == "__main__":
    sys.exit(main())
