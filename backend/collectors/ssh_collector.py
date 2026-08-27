"""
Linux server collector. Runs read-only shell commands over SSH via Fabric
(which is built on Paramiko) and returns their raw output.

Phase 1 scope -- raw output only. This module deliberately does no parsing, no
normalisation and no evaluation. Every command's stdout, stderr and exit code are
returned exactly as the host produced them, so that the normalizer built in Phase 2
is written against real observed output rather than invented fixtures.

Two properties of this collector are load-bearing and should not be "tidied away"
later:

1.  Every command is read-only. Nothing here writes, installs, restarts or modifies
    state on an audited host. An audit tool that can change the system it audits is
    a liability, and on a government-facing pitch it is the first thing anyone will
    ask about. Commands that need root use "sudo -n" (non-interactive) so that a
    missing sudo right fails immediately and visibly rather than hanging on a
    password prompt.

2.  A non-zero exit code is evidence, not an error. "cat /etc/security/faillock.conf"
    returning 1 because the file does not exist is precisely the finding a control
    cares about. Such results are recorded and returned. Only a failure that prevents
    collection altogether -- host unreachable, authentication rejected -- raises
    CollectorError.
"""

from __future__ import annotations

import datetime
import socket
import time

import paramiko.ssh_exception
from fabric import Connection

from .base import Collector, CollectorError

#: Filesystem kernel modules checked by CIS-1.1.1.
_UNUSED_FS_MODULES = ["cramfs", "freevxfs", "jffs2", "hfs", "hfsplus", "squashfs", "udf"]

#: Kernel parameters read for CIS-3.2.1 and CIS-3.3.1.
_SYSCTL_KEYS = [
    "net.ipv4.ip_forward",
    "net.ipv6.conf.all.forwarding",
    "net.ipv4.conf.all.accept_redirects",
    "net.ipv4.conf.default.accept_redirects",
    "net.ipv4.conf.all.secure_redirects",
    "net.ipv4.conf.default.secure_redirects",
    "net.ipv6.conf.all.accept_redirects",
    "net.ipv6.conf.default.accept_redirects",
    "fs.suid_dumpable",
]


def _cat_dir(directory: str, pattern: str = "*") -> str:
    """Shell snippet that prints every matching file in a directory with a header.

    The '### <path>' header is what lets the Phase 2 normalizer attribute a config
    line back to the specific drop-in file it came from, which matters because the
    last file to load wins for sysctl, sshd_config and pam.
    """
    return (
        f"for f in {directory}/{pattern}; do "
        f'[ -f "$f" ] && echo "### $f" && cat "$f"; '
        f"done 2>/dev/null; true"
    )


#: Maps each raw data source named by a control's test_logic.collector to the
#: read-only commands that produce the evidence for it. Controls reference sources,
#: never commands, so a change in how evidence is gathered on a given distribution
#: does not require touching any control definition.
SOURCE_COMMANDS: dict[str, list[str]] = {
    # --- CIS-5.2.10, CIS-5.2.11 -------------------------------------------------
    "ssh_config": [
        # Effective running configuration, after Include processing. This is the
        # authoritative answer; the files below are collected to show provenance.
        "sudo -n sshd -T",
        "cat /etc/ssh/sshd_config",
        _cat_dir("/etc/ssh/sshd_config.d", "*.conf"),
        "ssh -V",
    ],
    # --- CIS-5.3.1 --------------------------------------------------------------
    "pwquality": [
        "cat /etc/security/pwquality.conf",
        _cat_dir("/etc/security/pwquality.conf.d", "*.conf"),
        "cat /etc/pam.d/common-password",
        "dpkg-query -W -f='${Package} ${Status}\\n' libpam-pwquality",
        "grep -E '^\\s*(PASS_MIN_LEN|PASS_MIN_DAYS)' /etc/login.defs",
    ],
    # --- CIS-5.3.2 --------------------------------------------------------------
    "login_defs": [
        "grep -E '^\\s*PASS_' /etc/login.defs",
        # Per-account aging. The login.defs default applies only to accounts created
        # after it was set, so existing accounts are collected individually to make
        # that gap visible rather than assumed away.
        "for u in $(awk -F: '($3>=1000)&&($3<65534){print $1}' /etc/passwd); do "
        'echo \"### $u\"; sudo -n chage -l \"$u\"; done',
    ],
    # --- CIS-5.4.1 --------------------------------------------------------------
    "pam_faillock": [
        "cat /etc/security/faillock.conf",
        "cat /etc/pam.d/common-auth",
        "grep -rn 'pam_faillock\\|pam_tally' /etc/pam.d/ 2>/dev/null; true",
        "grep -rn 'pam_faillock' /usr/share/pam-configs/ 2>/dev/null; true",
    ],
    # --- CIS-3.1.1 --------------------------------------------------------------
    "firewall": [
        "sudo -n ufw status verbose",
        "systemctl is-enabled ufw 2>&1; true",
        "systemctl is-active ufw 2>&1; true",
        "sudo -n iptables -S",
        "sudo -n nft list ruleset",
        "systemctl is-enabled nftables 2>&1; true",
        "systemctl is-enabled firewalld 2>&1; true",
    ],
    # --- CIS-3.2.1, CIS-3.3.1 ---------------------------------------------------
    "sysctl": [
        # Running kernel values -- what is actually in force right now.
        "sysctl " + " ".join(_SYSCTL_KEYS) + " 2>&1; true",
        # Persisted values -- what survives a reboot. A host can be compliant in one
        # and not the other, and that divergence is itself a finding.
        "cat /etc/sysctl.conf",
        _cat_dir("/etc/sysctl.d", "*.conf"),
        _cat_dir("/usr/lib/sysctl.d", "*.conf"),
        _cat_dir("/run/sysctl.d", "*.conf"),
    ],
    # --- CIS-4.1.1, CIS-4.1.2 ---------------------------------------------------
    "auditd": [
        "dpkg-query -W -f='${Package} ${Status} ${Version}\\n' auditd",
        "systemctl is-enabled auditd 2>&1; true",
        "systemctl is-active auditd 2>&1; true",
        "cat /etc/audit/auditd.conf",
        "sudo -n auditctl -s",
    ],
    # --- CIS-4.2.1 --------------------------------------------------------------
    "rsyslog": [
        "cat /etc/rsyslog.conf",
        _cat_dir("/etc/rsyslog.d", "*.conf"),
        "systemctl is-active rsyslog 2>&1; true",
        "cat /etc/systemd/journald.conf",
        _cat_dir("/etc/systemd/journald.conf.d", "*.conf"),
        "cat /etc/systemd/journal-upload.conf",
        "systemctl is-enabled systemd-journal-upload 2>&1; true",
    ],
    # --- CIS-1.1.1 --------------------------------------------------------------
    "kernel_modules": [
        # "modprobe -n" is a dry run: it reports what loading would do without
        # loading anything. An install override to /bin/true or /bin/false shows up
        # in this output, which is the reliable way to confirm the module is blocked.
        "for m in " + " ".join(_UNUSED_FS_MODULES) + "; do "
        'echo "### $m"; modprobe -n -v "$m" 2>&1; done; true',
        "lsmod",
        "modprobe --showconfig 2>/dev/null | grep -E '"
        + "|".join(_UNUSED_FS_MODULES)
        + "'; true",
        _cat_dir("/etc/modprobe.d", "*.conf"),
    ],
    # --- CIS-1.1.2 --------------------------------------------------------------
    "mounts": [
        "findmnt --kernel --noheadings --output TARGET,SOURCE,FSTYPE,OPTIONS /tmp 2>&1; true",
        "findmnt --kernel --noheadings --output TARGET,SOURCE,FSTYPE,OPTIONS",
        "cat /etc/fstab",
        "systemctl is-enabled tmp.mount 2>&1; true",
        "cat /proc/mounts",
    ],
    # --- CIS-1.4.1, CIS-1.4.2 ---------------------------------------------------
    "file_permissions": [
        "stat -c '%n mode=%a owner=%U group=%G' /etc/passwd /etc/shadow "
        "/etc/group /etc/gshadow 2>&1; true",
    ],
    # --- CIS-1.5.1 --------------------------------------------------------------
    "coredump": [
        "grep -E 'core' /etc/security/limits.conf 2>/dev/null; true",
        _cat_dir("/etc/security/limits.d", "*.conf"),
        "sysctl fs.suid_dumpable 2>&1; true",
        "cat /etc/systemd/coredump.conf",
        _cat_dir("/etc/systemd/coredump.conf.d", "*.conf"),
        "dpkg-query -W -f='${Package} ${Status}\\n' systemd-coredump",
        "ulimit -Hc",
    ],
    # --- CIS-1.6.1 --------------------------------------------------------------
    "unattended_upgrades": [
        "dpkg-query -W -f='${Package} ${Status} ${Version}\\n' unattended-upgrades",
        "cat /etc/apt/apt.conf.d/20auto-upgrades",
        "cat /etc/apt/apt.conf.d/50unattended-upgrades",
        # Effective merged APT periodic settings, which is what actually governs.
        "apt-config dump APT::Periodic 2>&1; true",
        "systemctl is-enabled unattended-upgrades 2>&1; true",
        "systemctl is-active unattended-upgrades 2>&1; true",
    ],
    # --- CIS-6.1.1 --------------------------------------------------------------
    "sudo_config": [
        "sudo -n cat /etc/sudoers",
        "sudo -n grep -rhE '^[[:space:]]*Defaults' /etc/sudoers /etc/sudoers.d/ 2>/dev/null; true",
        "sudo -n ls -l /etc/sudoers.d/",
        "stat -c '%n mode=%a owner=%U group=%G' /var/log/sudo.log 2>&1; true",
    ],
}


class SSHCollector(Collector):
    """Collects raw Linux host state over SSH using Fabric."""

    collector_type = "ssh"

    def __init__(self, command_timeout: int = 30, connect_timeout: int = 15) -> None:
        self.command_timeout = command_timeout
        self.connect_timeout = connect_timeout

    # -- connection ---------------------------------------------------------------

    def _connect(self, target: dict) -> Connection:
        """Open a Fabric connection to the target.

        TODO (Phase 2+, spec Section 6): credentials are currently read from the
        target dict. They must move behind secrets_manager.get_credential(target_id)
        so that the Fernet-encrypted store is the only source and every use writes an
        audit_log row with event_type='credential_used'. secrets_manager and the
        database do not exist yet at Phase 1, so this is deferred, not skipped.
        """
        connect_kwargs: dict = {}
        if target.get("key_filename"):
            connect_kwargs["key_filename"] = target["key_filename"]
        if target.get("password"):
            connect_kwargs["password"] = target["password"]

        return Connection(
            host=target["host"],
            user=target.get("user", "root"),
            port=target.get("port", 22),
            connect_timeout=self.connect_timeout,
            connect_kwargs=connect_kwargs,
        )

    # -- command execution --------------------------------------------------------

    def _run_command(self, conn: Connection, command: str) -> dict:
        """Run one read-only command and capture its raw result verbatim."""
        started = time.perf_counter()
        try:
            result = conn.run(
                command,
                hide=True,
                warn=True,  # a non-zero exit is evidence, not an exception
                pty=False,
                timeout=self.command_timeout,
            )
            return {
                "command": command,
                "exit_code": result.exited,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "timed_out": False,
            }
        except (socket.timeout, TimeoutError) as exc:
            # A single hung command must not abort collection of the other sources.
            return {
                "command": command,
                "exit_code": None,
                "stdout": "",
                "stderr": f"command timed out after {self.command_timeout}s: {exc}",
                "timed_out": True,
            }
        finally:
            self._last_duration_ms = round((time.perf_counter() - started) * 1000, 1)

    # -- Collector interface ------------------------------------------------------

    def collect(self, target: dict) -> list[dict]:
        """Returns raw provider-specific state docs. Never touches evaluation logic.

        target keys:
            target_id     required -- stable identifier for the audited host
            host          required -- hostname or IP
            port          optional -- defaults to 22
            user          optional -- defaults to root
            key_filename  optional -- path to private key
            password      optional -- password auth
            sources       optional -- list of source names to gather; defaults to all

        Returns one doc per source:
            {source, collector_type, target_id, resource_type, resource_id,
             collected_at, commands: [{command, exit_code, stdout, stderr,
             timed_out, duration_ms}]}
        """
        for required in ("target_id", "host"):
            if required not in target:
                raise CollectorError(f"target is missing required key {required!r}")

        sources = target.get("sources") or sorted(SOURCE_COMMANDS)
        unknown = [s for s in sources if s not in SOURCE_COMMANDS]
        if unknown:
            raise CollectorError(f"no command mapping for source(s): {unknown}")

        resource_type = target.get("resource_type", "linux_server")
        resource_id = f"{resource_type}:{target['target_id']}"

        docs: list[dict] = []
        conn = self._connect(target)
        try:
            try:
                conn.open()
            except (
                paramiko.ssh_exception.AuthenticationException,
                paramiko.ssh_exception.NoValidConnectionsError,
                paramiko.ssh_exception.SSHException,
                socket.error,
                socket.timeout,
                TimeoutError,
                OSError,
            ) as exc:
                # Deliberately does not include target.get("password") or the key
                # contents in the message.
                raise CollectorError(
                    f"cannot collect from {target['target_id']} at "
                    f"{target['host']}:{target.get('port', 22)} as "
                    f"{target.get('user', 'root')}: {type(exc).__name__}: {exc}"
                ) from exc

            for source in sources:
                commands = []
                for command in SOURCE_COMMANDS[source]:
                    record = self._run_command(conn, command)
                    record["duration_ms"] = self._last_duration_ms
                    commands.append(record)

                docs.append(
                    {
                        "source": source,
                        "collector_type": self.collector_type,
                        "target_id": target["target_id"],
                        "resource_type": resource_type,
                        "resource_id": resource_id,
                        "collected_at": datetime.datetime.now(
                            datetime.timezone.utc
                        ).isoformat(),
                        "commands": commands,
                    }
                )
        finally:
            conn.close()

        return docs
