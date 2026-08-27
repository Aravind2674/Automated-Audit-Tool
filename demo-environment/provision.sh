#!/usr/bin/env bash
#
# Shell provisioner for the demo audit target.
#
# ############################################################################
# #  WARNING -- THIS SCRIPT DELIBERATELY WEAKENS THE MACHINE IT RUNS ON.     #
# #  It is intended ONLY for the disposable, host-only Vagrant VM defined    #
# #  in the adjacent Vagrantfile. Never run it on a real host.               #
# ############################################################################
#
# The resulting posture is a deliberate MIX of compliant and non-compliant settings.
# A demo target that fails every single control proves nothing: it cannot distinguish
# an audit tool that evaluates correctly from one that returns "fail" unconditionally.
# Four controls are therefore configured to pass.
#
# The expected posture per control is recorded in EXPECTED_POSTURE.md in this
# directory. That file is the answer key against which Phase 2's evaluator output is
# manually verified, per CLAUDE.md Section 9 point 6.

set -euo pipefail

echo "=== [provision] demo audit target: applying intentional misconfigurations ==="

export DEBIAN_FRONTEND=noninteractive

# ---------------------------------------------------------------------------
# CIS-5.2.10 -- FAIL: permit direct root login over SSH.
# CIS-5.2.11 -- FAIL: offer weak CBC ciphers and SHA-1/MD5 MACs.
# ---------------------------------------------------------------------------
cat > /etc/ssh/sshd_config.d/99-audit-demo.conf <<'SSHEOF'
PermitRootLogin yes
Ciphers aes128-cbc,3des-cbc,aes256-cbc,aes128-ctr,aes256-ctr
MACs hmac-md5,hmac-sha1,hmac-sha2-256
KexAlgorithms diffie-hellman-group14-sha1,curve25519-sha256
SSHEOF
chmod 644 /etc/ssh/sshd_config.d/99-audit-demo.conf
sshd -t && systemctl restart ssh
echo "[provision] CIS-5.2.10 / CIS-5.2.11 -> configured to FAIL"

# ---------------------------------------------------------------------------
# CIS-5.3.1 -- FAIL: minimum password length of 8, well below the required 14.
# ---------------------------------------------------------------------------
apt-get update -qq
apt-get install -y -qq libpam-pwquality >/dev/null
sed -i 's/^#\?\s*minlen\s*=.*/minlen = 8/' /etc/security/pwquality.conf
grep -q '^minlen' /etc/security/pwquality.conf || echo "minlen = 8" >> /etc/security/pwquality.conf
echo "[provision] CIS-5.3.1 -> configured to FAIL (minlen = 8)"

# ---------------------------------------------------------------------------
# CIS-5.3.2 -- FAIL: passwords never expire.
# ---------------------------------------------------------------------------
sed -i 's/^PASS_MAX_DAYS.*/PASS_MAX_DAYS\t99999/' /etc/login.defs
chage --maxdays 99999 vagrant
echo "[provision] CIS-5.3.2 -> configured to FAIL (PASS_MAX_DAYS = 99999)"

# ---------------------------------------------------------------------------
# CIS-5.4.1 -- FAIL: no account lockout. faillock.conf is left with every setting
# commented out and pam_faillock is not wired into the auth stack.
# ---------------------------------------------------------------------------
if [ -f /etc/security/faillock.conf ]; then
  sed -i 's/^\([^#].*\)$/# \1/' /etc/security/faillock.conf
fi
echo "[provision] CIS-5.4.1 -> configured to FAIL (no lockout configured)"

# ---------------------------------------------------------------------------
# CIS-3.1.1 -- FAIL: host firewall installed but disabled, with a default-allow policy.
# ---------------------------------------------------------------------------
apt-get install -y -qq ufw >/dev/null
ufw --force disable || true
ufw default allow incoming || true
systemctl disable ufw || true
echo "[provision] CIS-3.1.1 -> configured to FAIL (ufw disabled, default allow)"

# ---------------------------------------------------------------------------
# CIS-3.2.1 -- FAIL: IP forwarding enabled on a host that is not a router.
# CIS-3.3.1 -- PASS: ICMP redirects correctly refused.
#
# Both live in the same sysctl source, which is the point: it demonstrates that the
# evaluator resolves individual parameters rather than judging a whole source at once.
# ---------------------------------------------------------------------------
cat > /etc/sysctl.d/99-audit-demo.conf <<'SYSCTLEOF'
# CIS-3.2.1 -- intentionally non-compliant
net.ipv4.ip_forward = 1
net.ipv6.conf.all.forwarding = 1

# CIS-3.3.1 -- intentionally compliant
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv4.conf.all.secure_redirects = 0
net.ipv4.conf.default.secure_redirects = 0
net.ipv6.conf.all.accept_redirects = 0
net.ipv6.conf.default.accept_redirects = 0
SYSCTLEOF
sysctl --system >/dev/null
echo "[provision] CIS-3.2.1 -> configured to FAIL / CIS-3.3.1 -> configured to PASS"

# ---------------------------------------------------------------------------
# CIS-4.1.1 -- FAIL: auditd is not installed at all.
# CIS-4.1.2 -- FAIL: consequently there is no auditd.conf retention policy.
# ---------------------------------------------------------------------------
apt-get purge -y -qq auditd audispd-plugins >/dev/null 2>&1 || true
echo "[provision] CIS-4.1.1 / CIS-4.1.2 -> configured to FAIL (auditd absent)"

# ---------------------------------------------------------------------------
# CIS-4.2.1 -- FAIL: logs stay local, no remote forwarding target.
# ---------------------------------------------------------------------------
sed -i 's/^\(\s*\*\.\*\s*@\)/#\1/' /etc/rsyslog.conf || true
rm -f /etc/rsyslog.d/*remote* 2>/dev/null || true
echo "[provision] CIS-4.2.1 -> configured to FAIL (no remote log target)"

# ---------------------------------------------------------------------------
# CIS-1.1.1 -- PASS: unused filesystem modules correctly blocked.
# ---------------------------------------------------------------------------
cat > /etc/modprobe.d/99-audit-demo-filesystems.conf <<'MODEOF'
install cramfs /bin/false
blacklist cramfs
install freevxfs /bin/false
blacklist freevxfs
install jffs2 /bin/false
blacklist jffs2
install hfs /bin/false
blacklist hfs
install hfsplus /bin/false
blacklist hfsplus
install squashfs /bin/false
blacklist squashfs
install udf /bin/false
blacklist udf
MODEOF
echo "[provision] CIS-1.1.1 -> configured to PASS"

# ---------------------------------------------------------------------------
# CIS-1.1.2 -- FAIL: /tmp is not a separate partition and has no noexec.
# This is the stock ubuntu/jammy64 layout, so it is left untouched deliberately
# rather than actively broken.
# ---------------------------------------------------------------------------
systemctl mask tmp.mount 2>/dev/null || true
echo "[provision] CIS-1.1.2 -> configured to FAIL (/tmp on root fs, tmp.mount masked)"

# ---------------------------------------------------------------------------
# CIS-1.4.1 -- PASS: /etc/passwd left at the correct 644 root:root.
# CIS-1.4.2 -- FAIL: /etc/shadow made world-readable. This is the headline
#              misconfiguration for the demo; every local user can now copy the
#              password hashes and attack them offline.
# ---------------------------------------------------------------------------
chown root:root /etc/passwd
chmod 644 /etc/passwd
chmod 644 /etc/shadow
echo "[provision] CIS-1.4.1 -> configured to PASS / CIS-1.4.2 -> configured to FAIL"

# ---------------------------------------------------------------------------
# CIS-1.5.1 -- FAIL: core dumps unrestricted and set-uid programs allowed to dump.
# ---------------------------------------------------------------------------
echo "* hard core unlimited" > /etc/security/limits.d/99-audit-demo.conf
echo "fs.suid_dumpable = 2" >> /etc/sysctl.d/99-audit-demo.conf
sysctl -w fs.suid_dumpable=2 >/dev/null
echo "[provision] CIS-1.5.1 -> configured to FAIL"

# ---------------------------------------------------------------------------
# CIS-1.6.1 -- FAIL: automatic security updates switched off.
# ---------------------------------------------------------------------------
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'APTEOF'
APT::Periodic::Update-Package-Lists "0";
APT::Periodic::Unattended-Upgrade "0";
APTEOF
systemctl disable unattended-upgrades 2>/dev/null || true
systemctl stop unattended-upgrades 2>/dev/null || true
echo "[provision] CIS-1.6.1 -> configured to FAIL"

# ---------------------------------------------------------------------------
# CIS-6.1.1 -- PASS: sudo writes to a dedicated, correctly permissioned log file.
# ---------------------------------------------------------------------------
echo 'Defaults logfile="/var/log/sudo.log"' > /etc/sudoers.d/99-audit-demo-logging
chmod 440 /etc/sudoers.d/99-audit-demo-logging
visudo -cf /etc/sudoers.d/99-audit-demo-logging
touch /var/log/sudo.log
chown root:root /var/log/sudo.log
chmod 640 /var/log/sudo.log
echo "[provision] CIS-6.1.1 -> configured to PASS"

# ---------------------------------------------------------------------------
# Allow the collector's non-interactive sudo (sudo -n) to work for the read-only
# commands it runs. Vagrant already grants the vagrant user passwordless sudo; this
# is asserted explicitly so the collector's behaviour does not depend on the box.
# ---------------------------------------------------------------------------
echo 'vagrant ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/99-vagrant-nopasswd
chmod 440 /etc/sudoers.d/99-vagrant-nopasswd
visudo -cf /etc/sudoers.d/99-vagrant-nopasswd

echo "=== [provision] complete -- 4 controls set to pass, 14 set to fail ==="
echo "=== see EXPECTED_POSTURE.md for the per-control answer key         ==="
