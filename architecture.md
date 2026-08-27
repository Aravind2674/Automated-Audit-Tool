# Architecture

Automated IT Systems Audit Tool — data flow, technology rationale, correctness
evidence, known limitations, and every deliberate deviation from the build spec.

`CLAUDE.md` is the authoritative spec. `BUILD_LOG.md` records what was built and
verified, phase by phase. This document explains *why* the system is shaped the way
it is, and — just as importantly — where it is not trustworthy.

---

## 1. Data flow

```
   ┌────────────┐   raw provider-specific docs    ┌────────────┐
   │ Collector  │ ──────────────────────────────► │ Normalizer │
   │ (SSH/AWS)  │   {source, commands:[{cmd,      │            │
   └────────────┘    exit_code, stdout, stderr}]} └─────┬──────┘
         ▲                                               │
         │ read-only commands                            │ canonical resource docs
         │ over SSH / read-only API                      │ {resource_type,
   ┌─────┴──────┐                                        │  resource_id,
   │  Audited   │                                        │  attributes:{source:{…}}}
   │   host     │                                        ▼
   └────────────┘                                  ┌────────────┐
                                                   │ Evaluator  │◄── controls/*.yaml
                                                   └─────┬──────┘
                                                         │ {control_id, resource_id,
                                                         │  outcome, evidence}
                                                         ▼
                                    ┌────────────────────────────────────┐
                                    │ PostgreSQL                         │
                                    │  runs        (one row per scan)    │
                                    │  results     APPEND-ONLY           │
                                    │  audit_log   APPEND-ONLY           │
                                    │  controls    refreshed from YAML   │
                                    │  exceptions  (Phase 4)             │
                                    └────────────────────────────────────┘
```

The boundary that matters most is between **collection** and **interpretation**.
A collector gathers raw state and returns it verbatim; it never decides whether that
state is compliant. All interpretation happens in the normalizer and evaluator.

### Why the evaluator never sees `collector_type`

`normalize(raw_docs, collector_type)` consumes the collector type and does not
propagate it. The evaluator receives only canonical resource documents and a control's
`test_logic`. There is no `if collector_type ==` anywhere in `engine/evaluator.py`.

This is what makes the second collector type cheap. Adding AWS in Phase 5 means
writing `aws_collector.py` and a set of parsers in the normalizer — the evaluator, the
control schema, the persistence layer and the reporting layer are all untouched. If a
future change ever seems to require provider branching in the evaluator, the fix
belongs in the normalizer instead; that rule is stated in the module docstring so it
survives contact with whoever maintains this next.

---

## 2. Why you should trust this tool's verdicts

The honest answer to "how do you know your compliance results are correct?" is not
"the code has tests." It is that the tool has been checked against a real host by a
path that does not share code with the tool itself, and that doing so **found real
bugs** — including one in the answer key that the tool was supposedly being graded
against.

### 2.1 The ufw finding — a critical control that a plausible implementation gets wrong

While building the firewall parser against real collected output from the demo VM,
three commands disagreed about the same host:

```
$ sudo ufw status verbose        ->  Status: inactive
$ systemctl is-enabled ufw       ->  disabled
$ systemctl is-active ufw        ->  active        # <-- the trap
```

The host had **no firewall running at all**. `ufw.service` is a systemd *oneshot* unit:
it runs, applies whatever ufw's saved state says, and exits. systemd then reports the
unit as `active` because it completed successfully — regardless of whether ufw itself
is enabled or enforcing anything.

`systemctl is-active` is the natural thing to reach for when asking "is the firewall
running?", and it is wrong here. An implementation that used it would have reported
**CIS-3.1.1 — a `critical`-severity, default-deny firewall control — as PASSING on a
completely unprotected host.**

That is the worst possible class of bug in an audit tool. It is not a crash and not an
obviously wrong number; it is a confident green result that causes someone to stop
looking at a genuinely exposed machine. The finding is worth more than the fix,
because it demonstrates the failure mode this whole category of tool is prone to:
**a check that is plausible, runs cleanly, and silently answers a different question
than the one the control asked.**

The parser therefore treats `ufw status` as the only trustworthy signal for whether
ufw is enforcing, and consults `systemctl is-enabled` separately for persistence
across reboot. `systemctl is-active` is deliberately not used, and the reason is
recorded in a comment at `backend/engine/normalizer.py::_parse_firewall` so it cannot
be "cleaned up" later by someone who assumes it was an oversight.

Two sibling traps were caught the same way and handled the same way:

- **`sshd -T` vs. the config file.** `/etc/ssh/sshd_config` contains
  `Include /etc/ssh/sshd_config.d/*.conf`, and a drop-in overrides `PermitRootLogin`.
  Parsing the main file — again, the obvious thing to do — reports the distro default
  and misses the override entirely. Only the post-Include *effective* configuration is
  parsed.
- **A config file that looks configured but enforces nothing.** Ubuntu ships
  `/etc/security/faillock.conf` fully commented out. Reading it as evidence of account
  lockout is wrong unless `pam_faillock.so` is actually present in the PAM auth stack,
  which is checked separately.

All three were found because Section 7 requires the normalizer to be written against
**real captured output** rather than fixtures. A fixture written from intuition would
have encoded the intuition — including the wrong one about `is-active` — and the tests
would have passed.

### 2.2 Independent cross-verification (spec Section 9 rule 8)

Every collection and evaluation claim is verified by a second path that shares no
parsing code with the first.

- **`tests/crosscheck_phase1.py`** re-runs each control's primary evidence command over
  a **freshly opened SSH connection** and diffs exit code and stdout bytes against what
  the collector recorded. Result: 7 controls across 7 sources, **7/7 identical**.
- **`tests/crosscheck_phase2.py`** re-derives every control's pass/fail verdict directly
  on the host using commands **formulated independently of the collector's** —
  `sysctl -n`, `stat -c %a`, `systemctl is-active --quiet`, `findmnt -o OPTIONS`,
  `apt-config dump` — none of which the collector uses in that form. Result:
  **18/18 verdicts confirmed.**

The independence is the point. Re-running the collector's own command through the
normalizer's own parser proves only that the pipeline is deterministic. It cannot
catch the collector and the normalizer agreeing with each other about something the
host never said.

A separate check confirms the collected evidence actually contains the specific states
the provisioner creates (10/10), because byte-identical reproducibility is not the same
as reading the right thing.

### 2.3 The answer key was wrong and the tool was right

`demo-environment/EXPECTED_POSTURE.md` is the hand-written answer key for the demo VM.
It predicted CIS-1.1.1 (unused filesystem modules disabled) would **pass**, since
`provision.sh` writes `install squashfs /bin/false` for all seven modules.

The evaluator said **fail**. The evaluator was correct:

```
CONFIG_SQUASHFS=y                     # compiled into the kernel, not a module
CONFIG_CRAMFS=m                       # genuinely a module
/proc/filesystems: squashfs           # kernel supports it natively, right now
(no squashfs.ko anywhere under /lib/modules/$(uname -r))
```

A modprobe `install` override cannot disable a filesystem that is **built into the
kernel**. The override is inert; squashfs remains fully available. The answer key was
corrected from 4 pass / 14 fail to **3 pass / 15 fail** (16.7% compliance).

This is the case Section 9 rule 6 exists to force. Had the evaluator been "verified"
against the answer key instead of against the host, the obvious move would have been
to adjust the evaluator until the numbers matched — breaking correct code to satisfy a
wrong expectation, and shipping a tool that reports a filesystem as disabled when the
kernel will happily mount it.

The correct remedy is the **Phase 4 exception workflow**, not a weakened control:
snapd mounts squashfs images and the host genuinely depends on it, which is precisely
the "accepted risk, documented, with compensating control and an expiry date" case.
CIS-1.1.1's own remediation text anticipates this.

### 2.4 `error` is a distinct outcome from `fail`, on purpose

A control whose evidence could not be read reports `error`, never `fail`:

| Situation | Attribute state | Outcome |
|---|---|---|
| Host read fine, setting not configured | value is `None` | **fail** |
| Could not read the source at all (e.g. `sudo -n sshd -T` denied) | source marked `UNAVAILABLE` | **error** |
| Control names an attribute the normalizer never produces | key absent | **error** |
| Exception raised inside the comparison | — | **error** |

Collapsing `error` into `fail` would let a missing sudo right or an SSH permission
problem render as a tidy, plausible list of compliance failures. That is worse than a
crash, because it looks credible and would be acted upon. Spec Section 5 requires that
an exception during evaluation never silently passes; this implementation additionally
guarantees it never silently *fails*, which is the subtler half.

---

## 3. Known limitations

Stated plainly, with reasoning. These are real constraints on what the tool can be
trusted to tell you.

### 3.1 The collector cannot reach genuinely legacy SSH hosts

**This limitation is structural, and it cuts against exactly the hosts an audit is
most needed for.**

The collector uses Fabric, which is built on Paramiko. **Paramiko 5.0.0 has removed
SHA-1 key exchange algorithms entirely** — `diffie-hellman-group14-sha1`,
`diffie-hellman-group1-sha1`, `diffie-hellman-group-exchange-sha1` are all gone from
`Transport._preferred_kex`. That is a correct and deliberate decision by Paramiko's
maintainers: SHA-1 is broken and a modern SSH client should not offer it.

The consequence for an audit tool is uncomfortable. An old, unmaintained server
offering only SHA-1 key exchange — precisely the kind of host most likely to be
failing a dozen other controls — **cannot be connected to at all**. The scan does not
return bad results for that host; it returns no results, because the TCP session never
gets past algorithm negotiation.

The danger is what that looks like downstream. If an unreachable host is quietly
dropped from an estate-wide report, the compliance percentage **improves** as hosts get
worse, and the worst machines vanish from the very report meant to surface them. A
tool that silently cannot see its most vulnerable targets reports a falsely clean
estate.

This was discovered concretely rather than theoretically. The demo VM's intentional
weak-crypto misconfiguration (for CIS-5.2.11) initially pinned `KexAlgorithms` to
`diffie-hellman-group14-sha1,curve25519-sha256`, and the collector could not connect:

```
paramiko.ssh_exception.IncompatiblePeer: Incompatible ssh peer
    (no acceptable kex algorithm)
```

The immediate cause was narrower than the general problem — Paramiko 5.0.0 lists only
the vendor-suffixed `curve25519-sha256@libssh.org`, while the VM offered only the
RFC 8731 name `curve25519-sha256` for the same algorithm, so there was no overlap at
all. Real OpenSSH hosts offer both spellings, so `provision.sh` was corrected to do the
same. But the underlying limitation stands: had the VM offered *only* SHA-1 key
exchange, no fix on the target side would have been legitimate.

**Current status: unresolved and unmitigated.** Options, none yet implemented:

1. A "legacy" connection profile that explicitly widens
   `Transport._preferred_kex` at the collector, accepting weak KEX **for the audit
   connection only** and recording that fact in the evidence.
2. Shelling out to the system `ssh` client as a fallback transport, which still
   supports these algorithms behind explicit opt-in flags.
3. Pinning an older Paramiko for a dedicated legacy code path.

**Whatever is chosen, the non-negotiable part is that an unreachable host must surface
as a prominent `error` finding, never as an absence.** The `error` outcome already
exists for this and `CollectorError` is raised rather than swallowed, so an
unreachable host currently fails the scan loudly. It must stay that way.

### 3.2 The demo target is a VM, not the production deployment shape

The audited target is a Vagrant + VirtualBox Ubuntu 22.04 VM rather than a container,
per spec Section 1. This is a deliberate substitution and a defensible one: several
controls cannot be represented honestly inside a container, which shares the host
kernel and has no independent init system. `net.ipv4.ip_forward` and the ICMP redirect
parameters (CIS-3.2.1, CIS-3.3.1) are not namespaced per container in the way the
controls assume; `systemctl is-enabled auditd` and `unattended-upgrades` (CIS-4.1.1,
CIS-1.6.1) require a real init system; `/tmp` mount options (CIS-1.1.2) are inherited
from the host. Auditing a container would have meant either weakening those controls or
reporting confident nonsense about them.

**A production deployment would containerize the tool itself** — the FastAPI backend,
the Next.js frontend and PostgreSQL under Docker Compose or equivalent, per the problem
statement's own wording. That is orthogonal to what the tool *audits*. The local
setup here is a deliberate, justified substitution for the demo environment, not a
shortfall in the deployment story.

### 3.3 Credential handling is not yet wired to `secrets_manager`

Spec Section 6 requires collectors to obtain credentials via
`secrets_manager.get_credential(target_id)`, with every call writing a
`credential_used` audit row. **As of Phase 2 the SSH collector still reads credentials
from the target dict passed to `collect()`.** This is marked with an explicit `# TODO`
at `backend/collectors/ssh_collector.py::_connect` naming the Section 6 requirement.

It is deferred, not skipped, and **must close before Phase 7**. Until it does, there
is no encrypted credential store and no audit trail of credential use — a real gap,
stated here rather than left for a reviewer to find.

### 3.4 The CERT-In marker taxonomy is not primary-source

The six markers used in `framework_mappings.cert_in_marker` — `CSM`, `PRO`, `DET`,
`RES`, `REC`, `IMP` — are drawn from **public methodology descriptions published by
CERT-In-empanelled auditors**. They are **not** transcribed from a primary CERT-In
document.

**This taxonomy must never be presented as official CERT-In text** — not in the
application UI, not in exported PDF reports, not in demo material. Wherever the marker
column is surfaced it must be labelled as an auditor-methodology-derived mapping. The
Phase 6 report exporter includes a CERT-In column and must render that caveat beside
it. The same warning is duplicated at `control_library.VALID_CERT_IN_MARKERS` so it is
visible at the point of use.

### 3.5 Scope limits

Single-tenant. No auto-remediation — the tool reports and never changes an audited
host. No SIEM or ticketing integration. No SSO/OAuth; session-based auth only. Two
collector types (SSH, AWS) and 18 Linux + up to 8 AWS controls. These are explicit
non-goals in spec Section 8, not oversights.

---

## 4. Technology rationale

| Choice | Why | Alternative rejected |
|---|---|---|
| **Fabric / Paramiko** for SSH | Paramiko's own documented recommendation for remote shell execution; agentless, so nothing is installed on audited hosts | Writing raw Paramiko session handling; agent-based collection (requires deploying software to every audited host) |
| **boto3 `client` interface only** | AWS has placed the `resource` interface in permanent feature freeze and confirmed it will not carry into the next major SDK version | `boto3.resource(...)` — building on an interface already being phased out |
| **Custom Python evaluator** | 18–26 controls does not justify the operational and cognitive overhead of a policy engine; the operator set is small, explicit, and validated at load time | OPA/Rego — a second language and runtime for a rule set this size |
| **PostgreSQL** | JSONB for evidence and framework mappings, array columns for `applies_to`, real constraints; append-only tables enforced by CHECK constraints and schema design | SQLite (no JSONB/array types, weaker concurrency); a document store (loses referential integrity between runs, results and controls) |
| **Fernet for credentials** | Authenticated symmetric encryption with a key from the environment; small enough to audit by reading it | See below |
| **Vagrant + VirtualBox** demo target | Real kernel, real init system, real mount namespace — see §3.2 | Docker container (cannot honestly represent sysctl, systemd or mount-option controls) |
| **Session-based auth** | Sufficient for a single-tenant MVP | SSO/OAuth — explicit non-goal (Section 8) |

### Secrets: Fernet now, KMS in production

Credentials are encrypted with Fernet using a key read from the `SECRETS_KEY`
environment variable, never hardcoded and never committed. `.env` is gitignored;
`.env.example` carries a placeholder and each contributor generates their own key
locally.

**A production deployment would delegate to HashiCorp Vault or a cloud KMS instead.**
The weakness of the current design is not the cipher — Fernet is AES-128-CBC with
HMAC-SHA256 and is fine — it is **key custody**: the key sits in an environment
variable on the same host as the ciphertext, so anyone who can read the process
environment can decrypt the store. Vault or KMS moves the key out of the application's
blast radius entirely and adds rotation, per-use audit logging and revocation, none of
which this implementation provides. Building a real Vault integration is an explicit
non-goal for this cycle (Section 8); documenting precisely what is being traded away
is not.

### AWS: read-only by construction

The AWS collector (Phase 5) requires **only** the AWS-managed `SecurityAudit` or
`ViewOnlyAccess` policy. No write permission is requested anywhere, and no mutating
API call appears in the collector. The same principle governs the SSH collector: every
command it runs is read-only, and commands needing root use `sudo -n` so a missing
sudo right fails immediately and visibly rather than hanging on a password prompt.

An audit tool holding write credentials across an estate is a high-value target and an
insider-risk problem. Read-only by construction means a compromise of this tool
discloses configuration — bad, but bounded — rather than granting control of every
host it audits.

---

## 5. Append-only evidence model

`results` and `audit_log` are **insert-only**. No `UPDATE` or `DELETE` is issued
against them anywhere in the codebase.

Current compliance posture is computed as *"results where `run_id` = the latest
completed run"*, never stored as a mutable current-state table. Two consequences that
matter for an audit tool:

- **History cannot be rewritten.** A finding that was true last Tuesday stays in the
  record even after remediation. Drift analysis (Phase 3) is a query over accumulated
  runs rather than a separate changelog that could disagree with the results table.
- **Evidence is attached to the verdict.** Each `results` row carries the exact
  collected state that produced its outcome in `evidence` (JSONB), including which
  individual checks failed. A finding can be defended months later without re-running
  the scan or trusting that the host has not changed.

The append-only rule is enforced structurally rather than by convention:
`backend/audit.py` exposes `write()` and nothing else. There is deliberately no
update or delete method, so violating the rule requires bypassing the module rather
than merely forgetting the rule exists.

---

## 6. Deviations from spec

Every deviation, with reasoning. Full detail in `BUILD_LOG.md`.

1. **`test_logic` schema extended.** Spec Section 4's example shows a flat
   `collector`/`check`/`expected`. Controls such as CIS-5.2.11 (four independent
   algorithm-list conditions) and CIS-4.1.1 (installed **and** enabled **and** active)
   cannot be expressed that way without losing correctness or splitting one control
   into several — which would break the fixed 18-control set. An `operator` field and
   an optional composite `all_of`/`any_of` + `checks` form were added. The spec's flat
   form still validates and is used where it fits.
2. **Modules not named in the Section 2 tree:** `backend/control_library.py` (Section 3
   requires YAML loading at startup but names no module), plus `backend/db.py`,
   `backend/audit.py`, `backend/run_scan.py`, `backend/models/schema.py`.
3. **`tests/` directory** added at the project owner's direction, holding the
   cross-check harnesses and the quarantined `manual_review` fixture.
4. **Credentials not yet behind `secrets_manager`** — see §3.3.
5. **`provision.sh` KexAlgorithms corrected** to offer both spellings of
   `curve25519-sha256`, matching real OpenSSH behaviour — see §3.1.

---

## 7. Verification status

| Phase | Criterion | Status |
|---|---|---|
| 1 | 18 control YAMLs load, 0 schema errors | ✅ verified (12/12 negative tests rejected) |
| 1 | Collector returns real raw output from the VM | ✅ verified (14/14 sources, 66/66 commands; 7/7 rule-8 cross-check) |
| 2 | Correct pass/fail for all 18 controls vs the VM's actual config | ✅ verified (0 mismatches; 18/18 rule-8 cross-check) |
| 2 | Every run writes a `runs` row and per-control `results` rows | ✅ verified against live PostgreSQL 17.11 (1 run, 18 results, 20 audit_log rows sharing one correlation_id; 18/18 rule-8 cross-check of persisted rows vs fresh on-host derivation) |
| 3–7 | — | not started |

No criterion in this table is marked verified without corresponding evidence recorded
in `BUILD_LOG.md`.
