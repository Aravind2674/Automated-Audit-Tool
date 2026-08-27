"""
Maps raw collector output into canonical resource documents.

Written against the REAL output captured in Phase 1 (`phase1_raw_output.json`), not
invented fixtures. Several of the parsers below exist in the shape they do because of
something the real Ubuntu 22.04 host actually did; those cases are commented where
they occur, because they are exactly the details a fixture-driven normalizer gets
wrong.

Canonical shape (spec Section 5):

    {resource_type, resource_id, attributes: {}}

`attributes` is keyed by raw source name, and within each source the keys are the
exact `check` strings the controls use:

    attributes["ssh_config"]["PermitRootLogin"] -> "yes"
    attributes["file_permissions"]["/etc/shadow.mode"] -> "644"

Flat string keys are used deliberately rather than nested paths, because several
check names legitimately contain dots (`net.ipv4.ip_forward`, `/etc/passwd.mode`) and
a dotted-path resolver would have to guess where the path ends and the key begins.

A value of None means "this could not be determined from the collected evidence".
The evaluator treats None distinctly from a wrong value -- see evaluator.py.
"""

from __future__ import annotations

import re

# Attribute value used when a resource limit is explicitly unlimited. Chosen so that
# numeric comparisons still work and an "unlimited" core dump size can never satisfy
# `equals 0`.
UNLIMITED = -1

#: Sentinel key. When present in a source's attribute dict, the collected evidence
#: was insufficient to determine ANY attribute for that source, and every control
#: depending on it must evaluate to `error` rather than `fail`.
#:
#: This distinction is load-bearing. "The setting is not configured" is a compliance
#: failure; "I could not read the configuration" is a broken audit. Reporting the
#: second as the first produces a finding that looks actionable but is really a
#: permissions or connectivity problem, and it is the kind of error that erodes trust
#: in the whole report.
UNAVAILABLE = "_unavailable"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _commands(doc: dict) -> list[dict]:
    return doc.get("commands", [])


def _stdout(doc: dict, index: int) -> str:
    cmds = _commands(doc)
    return cmds[index]["stdout"] if index < len(cmds) else ""


def _exit(doc: dict, index: int) -> int | None:
    cmds = _commands(doc)
    return cmds[index]["exit_code"] if index < len(cmds) else None


def _uncommented(text: str):
    """Yield stripped, non-empty, non-comment lines."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            yield stripped


def _split_marked_files(text: str) -> dict[str, str]:
    """Split '### /path' delimited concatenated file output into {path: content}.

    The collector emits that header so a config line can be attributed back to the
    drop-in file it came from -- which matters because for sysctl, sshd_config and
    modprobe the last file to load wins.
    """
    files: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []
    for line in text.splitlines():
        if line.startswith("### "):
            if current is not None:
                files[current] = "\n".join(buffer)
            current = line[4:].strip()
            buffer = []
        elif current is not None:
            buffer.append(line)
    if current is not None:
        files[current] = "\n".join(buffer)
    return files


def _kv(text: str, sep: str = "=") -> dict[str, str]:
    """Parse uncommented 'key = value' lines. Later lines win."""
    out: dict[str, str] = {}
    for line in _uncommented(text):
        if sep not in line:
            continue
        key, _, value = line.partition(sep)
        out[key.strip()] = value.strip()
    return out


def _int_or_none(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _systemd_state(text: str) -> str:
    """First line of `systemctl is-enabled/is-active`, or 'unknown'.

    Real output seen on the demo host includes
    'Failed to get unit file state for auditd.service: No such file or directory'
    for a unit that does not exist, so anything that is not a bare state word is
    normalised to 'unknown' rather than being stored verbatim.
    """
    first = text.strip().splitlines()[0].strip() if text.strip() else ""
    known = {
        "enabled", "disabled", "masked", "static", "indirect",
        "active", "inactive", "failed", "activating", "deactivating",
        "enabled-runtime", "alias", "generated", "transient",
    }
    return first if first in known else "unknown"


def _dpkg_installed(text: str, exit_code: int | None) -> bool:
    """True only if dpkg reports the package actually installed.

    dpkg-query exits non-zero and prints 'no packages found matching X' when the
    package is absent; it can also report a package as 'deinstall ok config-files'
    after a purge, which is NOT installed.
    """
    if exit_code != 0:
        return False
    return "install ok installed" in text


# ---------------------------------------------------------------------------
# per-source parsers
# ---------------------------------------------------------------------------


def _parse_ssh_config(doc: dict) -> dict:
    """`sshd -T` is authoritative -- it is the post-Include effective configuration.

    The raw sshd_config file is deliberately NOT parsed for the verdict: on the real
    host, /etc/ssh/sshd_config contains 'Include /etc/ssh/sshd_config.d/*.conf' and
    the drop-in 99-audit-demo.conf overrides it. Reading the main file alone would
    report PermitRootLogin as the distro default and miss the override entirely.
    """
    if _exit(doc, 0) != 0:
        # Without root, `sshd -T` fails. Mark the whole source unavailable rather
        # than guessing from the raw file: the evaluator must report `error` here,
        # not `fail`. "I could not read the config" and "the config is wrong" are
        # different findings, and collapsing them would let a permissions problem
        # masquerade as a compliance failure.
        return {UNAVAILABLE: "sudo -n sshd -T failed; effective SSH config unreadable"}

    effective: dict[str, str] = {}
    for line in _stdout(doc, 0).splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            effective[parts[0].lower()] = parts[1].strip()

    def csv(key: str):
        raw = effective.get(key)
        return [x.strip() for x in raw.split(",") if x.strip()] if raw else None

    return {
        "PermitRootLogin": effective.get("permitrootlogin"),
        "Ciphers": csv("ciphers"),
        "MACs": csv("macs"),
        "KexAlgorithms": csv("kexalgorithms"),
        # OpenSSH >= 7.6 removed the Protocol directive; protocol 1 is not compiled
        # in at all. Absent is therefore compliant, which is why CIS-5.2.11 uses the
        # `equals_or_absent` operator for this key.
        "Protocol": effective.get("protocol"),
    }


def _parse_pwquality(doc: dict) -> dict:
    settings = _kv(_stdout(doc, 0))
    # Drop-ins under pwquality.conf.d override the main file.
    for _path, content in _split_marked_files(_stdout(doc, 1)).items():
        settings.update(_kv(content))
    return {"minlen": _int_or_none(settings.get("minlen"))}


def _parse_login_defs(doc: dict) -> dict:
    values: dict[str, str] = {}
    for line in _uncommented(_stdout(doc, 0)):
        parts = line.split(None, 1)
        if len(parts) == 2:
            values[parts[0]] = parts[1].strip()
    return {"PASS_MAX_DAYS": _int_or_none(values.get("PASS_MAX_DAYS"))}


def _parse_pam_faillock(doc: dict) -> dict:
    conf = _kv(_stdout(doc, 0))
    # A faillock.conf full of settings enforces nothing unless pam_faillock.so is
    # actually referenced in the PAM auth stack. On the demo host the config file
    # exists (shipped by the distro, fully commented) while the grep for the module
    # returns empty -- so the file alone must never be read as "configured".
    module_enabled = bool(_stdout(doc, 2).strip())
    return {
        "module_enabled": module_enabled,
        "deny": _int_or_none(conf.get("deny")),
        "unlock_time": _int_or_none(conf.get("unlock_time")),
    }


def _parse_firewall(doc: dict) -> dict:
    ufw_status = _stdout(doc, 0)
    ufw_enabled_at_boot = _systemd_state(_stdout(doc, 1)) == "enabled"
    iptables = _stdout(doc, 3)
    nft = _stdout(doc, 4)

    ufw_active = bool(re.search(r"^Status:\s*active", ufw_status, re.M))

    # NOTE (real-host trap): `systemctl is-active ufw` returned "active" on the demo
    # host while `ufw status` reported "Status: inactive" and is-enabled reported
    # "disabled". The ufw systemd unit is a oneshot that stays "active" after
    # running, regardless of whether ufw itself is enforcing anything. Trusting
    # is-active here would have passed CIS-3.1.1 on a host with no firewall at all.
    # `ufw status` is the only trustworthy signal, so is-active is not consulted.

    default_inbound = None
    if ufw_active:
        match = re.search(r"Default:\s*(\w+)\s*\(incoming\)", ufw_status)
        if match:
            default_inbound = match.group(1).lower()
        backend = "ufw"
    elif re.search(r"^-P\s+INPUT\s+\w+", iptables, re.M):
        policy = re.search(r"^-P\s+INPUT\s+(\w+)", iptables, re.M)
        default_inbound = policy.group(1).lower() if policy else None
        has_rules = bool(re.search(r"^-A\s+INPUT", iptables, re.M))
        backend = "iptables" if has_rules else "none"
    elif "hook input" in nft:
        policy = re.search(r"hook input .*?policy (\w+)", nft)
        default_inbound = policy.group(1).lower() if policy else None
        backend = "nftables"
    else:
        backend = "none"

    # iptables/nft spell the permissive default "accept"; ufw spells it "allow".
    # Both are normalised so the control can state a single expected vocabulary.
    if default_inbound == "accept":
        default_inbound = "allow"

    return {
        "active_backend": backend,
        "enabled_at_boot": ufw_enabled_at_boot,
        "default_inbound_policy": default_inbound,
    }


def _parse_sysctl(doc: dict) -> dict:
    """Running kernel values. These are what is actually in force right now."""
    return {k: _int_or_none(v) for k, v in _kv(_stdout(doc, 0)).items()}


def _parse_auditd(doc: dict) -> dict:
    conf = _kv(_stdout(doc, 3)) if _exit(doc, 3) == 0 else {}
    return {
        "installed": _dpkg_installed(_stdout(doc, 0), _exit(doc, 0)),
        "enabled_at_boot": _systemd_state(_stdout(doc, 1)) == "enabled",
        "active": _systemd_state(_stdout(doc, 2)) == "active",
        "max_log_file_action": conf.get("max_log_file_action"),
        "num_logs": _int_or_none(conf.get("num_logs")),
        "space_left_action": conf.get("space_left_action"),
        "admin_space_left_action": conf.get("admin_space_left_action"),
    }


#: An rsyslog forwarding action: a selector followed by @host (UDP) or @@host (TCP).
#: Anchored on the '@' being the start of the action field so that local file actions
#: and email addresses inside comments are not mistaken for remote targets.
_RSYSLOG_FORWARD = re.compile(r"^[^#\s]\S*\s+@{1,2}[A-Za-z0-9\[\]\.\-:_]+")


def _parse_rsyslog(doc: dict) -> dict:
    blob = _stdout(doc, 0) + "\n"
    for _path, content in _split_marked_files(_stdout(doc, 1)).items():
        blob += content + "\n"

    remote = None
    for line in blob.splitlines():
        if _RSYSLOG_FORWARD.match(line.strip()):
            remote = line.strip()
            break

    # NOTE (real-host trap): /etc/rsyslog.d/20-ufw.conf contains
    #   :msg,contains,"[UFW " /var/log/ufw.log
    # A naive "does any line contain '@'" test would also trip over commented
    # examples and email addresses in the shipped config. Requiring the '@' to begin
    # the action field is what keeps this from reporting a remote target that does
    # not exist.

    journald_remote = None
    if _exit(doc, 5) == 0:
        url = _kv(_stdout(doc, 5)).get("URL")
        journald_remote = url or None

    return {
        "rsyslog_remote_target": remote,
        "journald_remote_target": journald_remote,
    }


def _parse_kernel_modules(doc: dict) -> dict:
    """`modprobe -n -v <mod>` is a dry run: it prints what loading *would* do.

    A blocked module prints an install override such as 'install /bin/false'.
    An available one prints 'insmod /lib/modules/.../<mod>.ko'.
    """
    attributes: dict[str, object] = {}
    for module, output in _split_marked_files(_stdout(doc, 0)).items():
        text = output.strip()
        blocked = ("/bin/false" in text) or ("/bin/true" in text)
        attributes[f"modules.{module}.blocked"] = blocked
    return attributes


def _parse_mounts(doc: dict) -> dict:
    """/proc/mounts is used rather than findmnt.

    On the demo host `findmnt /tmp` produced NO output at all (and exit 0, because
    the collector appends '; true'), since /tmp is not a mount point of its own.
    Absence of output is meaningful here, but /proc/mounts gives an unambiguous
    machine-readable answer for every mount, so it is the parsed source.
    """
    separate = False
    options: list[str] = []
    for line in _stdout(doc, 4).splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[1] == "/tmp":
            separate = True
            options = fields[3].split(",")
            break
    return {"/tmp.is_separate_partition": separate, "/tmp.options": options}


_STAT_LINE = re.compile(r"^(\S+)\s+mode=(\S+)\s+owner=(\S+)\s+group=(\S+)$")


def _parse_stat_lines(text: str) -> dict:
    attributes: dict[str, object] = {}
    for line in text.splitlines():
        match = _STAT_LINE.match(line.strip())
        if match:
            path, mode, owner, group = match.groups()
            attributes[f"{path}.mode"] = mode
            attributes[f"{path}.owner"] = owner
            attributes[f"{path}.group"] = group
    return attributes


def _parse_file_permissions(doc: dict) -> dict:
    return _parse_stat_lines(_stdout(doc, 0))


def _parse_coredump(doc: dict) -> dict:
    limit = None
    limit_sources = [_stdout(doc, 0)]
    limit_sources += list(_split_marked_files(_stdout(doc, 1)).values())
    for content in limit_sources:
        for line in _uncommented(content):
            fields = line.split()
            # e.g. "* hard core unlimited"
            if len(fields) >= 4 and fields[1] == "hard" and fields[2] == "core":
                limit = UNLIMITED if fields[3] == "unlimited" else _int_or_none(fields[3])

    suid = _int_or_none(_kv(_stdout(doc, 2)).get("fs.suid_dumpable"))

    if not _dpkg_installed(_stdout(doc, 5), _exit(doc, 5)):
        storage = "not_installed"
    else:
        conf = _kv(_stdout(doc, 3)) if _exit(doc, 3) == 0 else {}
        # systemd's compiled-in default when the key is absent is Storage=external.
        storage = conf.get("Storage", "external")

    return {
        "hard_core_limit": limit,
        "fs.suid_dumpable": suid,
        "systemd_coredump_storage": storage,
    }


def _parse_unattended_upgrades(doc: dict) -> dict:
    # `apt-config dump` gives the merged effective value, which is what actually
    # governs -- reading 20auto-upgrades alone would miss overrides elsewhere.
    periodic: dict[str, str] = {}
    for line in _stdout(doc, 3).splitlines():
        match = re.match(r'^(\S+)\s+"(.*)";$', line.strip())
        if match:
            periodic[match.group(1)] = match.group(2)

    origins = _stdout(doc, 2)
    security_configured = bool(
        re.search(r'^\s*"\$\{distro_id\}.*-security"\s*;', origins, re.M)
        or re.search(r'^\s*"\$\{distro_id\}:\$\{distro_codename\}-security"', origins, re.M)
    )

    return {
        "installed": _dpkg_installed(_stdout(doc, 0), _exit(doc, 0)),
        "enabled_at_boot": _systemd_state(_stdout(doc, 4)) == "enabled",
        "update_package_lists": _int_or_none(
            periodic.get("APT::Periodic::Update-Package-Lists")
        ),
        "unattended_upgrade_interval": _int_or_none(
            periodic.get("APT::Periodic::Unattended-Upgrade")
        ),
        "security_origin_configured": security_configured,
    }


def _parse_sudo_config(doc: dict) -> dict:
    defaults = _stdout(doc, 1)
    match = re.search(r'^\s*Defaults\s+.*logfile\s*=\s*"?([^"\s]+)"?', defaults, re.M)
    logfile_path = match.group(1) if match else None

    stat_attrs = _parse_stat_lines(_stdout(doc, 3))
    mode_key = f"{logfile_path}.mode" if logfile_path else None
    logfile_mode = stat_attrs.get(mode_key) if mode_key else None

    return {
        "logfile_configured": logfile_path is not None,
        "logfile_exists": logfile_mode is not None,
        "logfile_mode": logfile_mode,
    }


#: source name -> parser. Adding a collector means adding parsers here, never
#: adding a branch to the evaluator (spec Section 5).
_PARSERS = {
    "ssh_config": _parse_ssh_config,
    "pwquality": _parse_pwquality,
    "login_defs": _parse_login_defs,
    "pam_faillock": _parse_pam_faillock,
    "firewall": _parse_firewall,
    "sysctl": _parse_sysctl,
    "auditd": _parse_auditd,
    "rsyslog": _parse_rsyslog,
    "kernel_modules": _parse_kernel_modules,
    "mounts": _parse_mounts,
    "file_permissions": _parse_file_permissions,
    "coredump": _parse_coredump,
    "unattended_upgrades": _parse_unattended_upgrades,
    "sudo_config": _parse_sudo_config,
}


class NormalizationError(Exception):
    """Raised when raw docs cannot be mapped into canonical resources."""


def normalize(raw_docs: list[dict], collector_type: str) -> list[dict]:
    """
    Maps raw collector output into canonical shape:
    {resource_type, resource_id, attributes: {}}

    The evaluator NEVER sees collector_type -- it is consumed here and does not
    appear in the returned documents.
    """
    if collector_type != "ssh":
        # AWS arrives in Phase 5 and will be dispatched here, not in the evaluator.
        raise NormalizationError(
            f"no normalizer registered for collector_type {collector_type!r}"
        )

    resources: dict[str, dict] = {}

    for doc in raw_docs:
        source = doc.get("source")
        if source not in _PARSERS:
            raise NormalizationError(f"no parser for raw source {source!r}")

        resource_id = doc["resource_id"]
        resource = resources.setdefault(
            resource_id,
            {
                "resource_type": doc.get("resource_type", "linux_server"),
                "resource_id": resource_id,
                "attributes": {},
            },
        )

        try:
            resource["attributes"][source] = _PARSERS[source](doc)
        except Exception as exc:  # noqa: BLE001 -- surfaced, never swallowed
            raise NormalizationError(
                f"parser for source {source!r} on {resource_id} failed: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    return list(resources.values())
