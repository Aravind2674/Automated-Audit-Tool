# Demo target — expected posture (answer key)

This is the manual answer key for the demo VM provisioned by `provision.sh`. Per
CLAUDE.md Section 9 point 6, Phase 2's evaluator output is verified **against this
table by hand**, not against itself.

The target is deliberately a **mix**: 4 controls are configured to pass and 14 to
fail. A demo host that fails everything cannot distinguish a correct evaluator from
one that returns `fail` unconditionally.

> **Status of this table:** these are the outcomes the provisioner is *written to
> produce*. They have **not yet been confirmed against a running VM** — see
> BUILD_LOG.md, Phase 1. Each row must be re-checked by hand on the live VM before
> Phase 2 uses it as ground truth.

| Control | Severity | Expected | What `provision.sh` does | Manual verification command |
|---|---|---|---|---|
| CIS-5.2.10 | high | **FAIL** | `PermitRootLogin yes` in an sshd drop-in | `sudo sshd -T \| grep permitrootlogin` |
| CIS-5.2.11 | high | **FAIL** | CBC ciphers, `hmac-md5`/`hmac-sha1` MACs, SHA-1 KEX offered | `sudo sshd -T \| grep -E '^(ciphers\|macs\|kexalgorithms)'` |
| CIS-5.3.1 | medium | **FAIL** | `minlen = 8` in pwquality.conf | `grep minlen /etc/security/pwquality.conf` |
| CIS-5.3.2 | medium | **FAIL** | `PASS_MAX_DAYS 99999`; vagrant user aged to match | `grep PASS_MAX_DAYS /etc/login.defs; sudo chage -l vagrant` |
| CIS-5.4.1 | high | **FAIL** | every faillock.conf setting commented out; pam_faillock not in auth stack | `grep -v '^#' /etc/security/faillock.conf; grep faillock /etc/pam.d/common-auth` |
| CIS-3.1.1 | critical | **FAIL** | ufw installed, disabled, default allow incoming | `sudo ufw status verbose; systemctl is-enabled ufw` |
| CIS-3.2.1 | medium | **FAIL** | `net.ipv4.ip_forward = 1` | `sysctl net.ipv4.ip_forward net.ipv6.conf.all.forwarding` |
| CIS-3.3.1 | low | **PASS** | all six redirect parameters set to 0 | `sysctl -a \| grep redirects` |
| CIS-4.1.1 | high | **FAIL** | auditd purged | `dpkg-query -W auditd; systemctl is-active auditd` |
| CIS-4.1.2 | medium | **FAIL** | no `/etc/audit/auditd.conf` exists (follows from 4.1.1) | `cat /etc/audit/auditd.conf` |
| CIS-4.2.1 | medium | **FAIL** | no rsyslog forwarding action, no journal-upload target | `grep -r '@' /etc/rsyslog.conf /etc/rsyslog.d/` |
| CIS-1.1.1 | low | **PASS** | all 7 modules given `install … /bin/false` + `blacklist` | `modprobe -n -v cramfs` |
| CIS-1.1.2 | medium | **FAIL** | `/tmp` on the root filesystem, `tmp.mount` masked | `findmnt /tmp` |
| CIS-1.4.1 | high | **PASS** | `/etc/passwd` left at 644 root:root | `stat -c '%a %U %G' /etc/passwd` |
| CIS-1.4.2 | critical | **FAIL** | `/etc/shadow` chmod 644 — world-readable hashes | `stat -c '%a %U %G' /etc/shadow` |
| CIS-1.5.1 | low | **FAIL** | `* hard core unlimited`, `fs.suid_dumpable = 2` | `sysctl fs.suid_dumpable; ulimit -Hc` |
| CIS-1.6.1 | medium | **FAIL** | both APT periodic keys set to `"0"`, unit disabled | `apt-config dump APT::Periodic` |
| CIS-6.1.1 | medium | **PASS** | `Defaults logfile="/var/log/sudo.log"`, file at 640 root:root | `sudo grep -r logfile /etc/sudoers.d/; stat -c '%a' /var/log/sudo.log` |

**Expected totals once Phase 2 runs:** 4 pass, 14 fail, 0 error, 0 manual_review
→ compliance 4/18 = **22.2%**.

## Note on the absence of `manual_review`

All 18 controls are `scored: true`, so none of them exercise the
`scored: false → manual_review` path required by CLAUDE.md Section 5. That path still
needs a test in Phase 2 — a synthetic control fixture is the intended way to cover it
rather than downgrading a real control to create one artificially. Flagged in
BUILD_LOG.md as an open item.
