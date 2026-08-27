# Project: Automated IT Systems Audit Tool
### Persistent build context for Claude Code — read this fully before writing any code.

This file is the spec. Do not deviate from the phase order in Section 7 without
explicit instruction — each phase has acceptance criteria that must pass before
starting the next one. This is a one-semester capstone graded primarily on
correctness of control evaluation (25%), architecture/extensibility (20%), and
exception handling + tool security (30% combined). Depth over breadth, always.

---

## 1. Stack

- **Backend**: Python 3.11+, FastAPI
- **Collectors**: Python — Fabric (built on Paramiko) for SSH/Linux servers — this is
  Paramiko's own documented recommendation for running remote shell commands, not just
  a convenience pick. AWS collector uses boto3's **`client` interface only**
  (`boto3.client('s3')` etc.) — do NOT use `boto3.resource(...)`. AWS has put the
  resources interface into a permanent feature freeze and confirmed it will not carry
  into the next major SDK version, so building against it now is building on something
  already being phased out.
- **Rules engine**: lightweight custom Python evaluator (see Section 5) — not OPA,
  timeline doesn't justify the overhead for 15-20 controls
- **Database**: PostgreSQL (results, controls, exceptions, audit log — all append-only
  where noted)
- **Frontend**: Next.js + React, Tailwind
- **Auth**: simple session-based auth is sufficient; do not build SSO/OAuth for MVP
- **Local environment — no Docker, no WSL.** Everything below installs as a plain
  standalone program, nothing containerized:
  - PostgreSQL: install natively via the official installer for your OS
    (postgresql.org/download) — run it as a normal local service, not in a container
  - Backend: standard Python venv (`python -m venv venv`), pip install dependencies,
    run FastAPI with `uvicorn` directly
  - Frontend: `npm install && npm run dev`, plain Next.js dev server
  - **Demo audit target: Vagrant + VirtualBox**, not Docker. This is the problem
    statement's own explicitly sanctioned alternative to Docker containers for
    standing in as "real" audited systems (see Section 6 of the original brief).
    A Vagrant-provisioned Ubuntu VM is arguably more realistic for an SSH-based
    collector than a container anyway — you're auditing real OS-level
    configuration (sshd, PAM, filesystem permissions, auditd) on a real init
    system, not a container's stripped-down userspace. Vagrant + VirtualBox run
    standalone on native Windows/Mac/Linux with zero WSL involvement — install
    both as regular programs, no subsystem required.
  - Document in architecture.md that a production deployment would containerize
    (Docker Compose or similar, per the problem statement's own wording) — this
    local setup is a deliberate, justified substitution, not a shortfall.
- **Secrets**: Fernet (symmetric encryption) with key from environment variable, never
  committed. See Section 6. Document in architecture.md that production would delegate
  to Vault/cloud KMS instead — do not attempt to build actual Vault integration.

---

## 2. Repository structure

```
/backend
  /collectors
    base.py              # abstract Collector interface — all collectors implement this
    ssh_collector.py      # Linux server collector (Fabric, built on Paramiko)
    aws_collector.py      # AWS collector (boto3)
  /engine
    evaluator.py          # runs controls against normalized resource docs
    normalizer.py         # raw collector output -> canonical resource docs
  /controls
    *.yaml                 # one file per control — see Section 4
  /models                  # SQLAlchemy models — see Section 3
  /api                     # FastAPI routers
  /auth
  /secrets_manager.py       # Fernet-based credential store, isolated module
  /reports
    generator.py            # PDF export mapped to framework
/frontend
  /app
  /components
/demo-environment
  Vagrantfile               # provisions the intentionally misconfigured Ubuntu VM
  provision.sh                # shell provisioner: creates the misconfigurations
architecture.md              # required deliverable — data flow, tech rationale, deviations
```

---

## 3. Database schema (PostgreSQL DDL)

```sql
CREATE TABLE controls (
  id VARCHAR PRIMARY KEY,              -- e.g. 'CIS-5.2.10'
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  category VARCHAR NOT NULL,
  severity VARCHAR NOT NULL CHECK (severity IN ('critical','high','medium','low')),
  applies_to VARCHAR[] NOT NULL,       -- e.g. {linux_server}
  scored BOOLEAN NOT NULL DEFAULT true,
  framework_mappings JSONB NOT NULL,   -- {"cis_linux_v8":"5.2.10","nist_csf":"PR.AC-1","cert_in_marker":"IMP"}
  test_logic JSONB NOT NULL,
  remediation TEXT NOT NULL
);
-- controls are loaded from /backend/controls/*.yaml at startup, not hand-inserted

CREATE TABLE runs (
  run_id UUID PRIMARY KEY,
  correlation_id UUID NOT NULL,
  triggered_by VARCHAR NOT NULL,       -- user id or 'scheduler'
  started_at TIMESTAMPTZ NOT NULL,
  completed_at TIMESTAMPTZ,
  status VARCHAR NOT NULL              -- running | completed | failed
);

CREATE TABLE results (                  -- APPEND-ONLY. Never UPDATE. Never DELETE.
  result_id UUID PRIMARY KEY,
  run_id UUID REFERENCES runs(run_id),
  control_id VARCHAR REFERENCES controls(id),
  resource_id VARCHAR NOT NULL,
  outcome VARCHAR NOT NULL CHECK (outcome IN ('pass','fail','error','manual_review')),
  evidence JSONB NOT NULL,             -- exact collected state that produced this outcome
  evaluated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE exceptions (
  exception_id UUID PRIMARY KEY,
  control_id VARCHAR REFERENCES controls(id),
  resource_id VARCHAR NOT NULL,
  status VARCHAR NOT NULL CHECK (status IN ('accepted_risk','false_positive','pending_review')),
  justification TEXT NOT NULL,
  requested_by VARCHAR NOT NULL,
  approved_by VARCHAR,                  -- must differ from requested_by if severity is high/critical
  approval_date TIMESTAMPTZ,
  expiry_date TIMESTAMPTZ NOT NULL,     -- no permanent exceptions, ever
  compensating_control TEXT
);

CREATE TABLE audit_log (                -- APPEND-ONLY
  event_id UUID PRIMARY KEY,
  correlation_id UUID NOT NULL,
  run_id UUID,
  actor VARCHAR NOT NULL,
  event_type VARCHAR NOT NULL,          -- scan_started|scan_completed|control_evaluated|exception_requested|exception_approved|exception_approval_denied|credential_used|report_exported
  timestamp TIMESTAMPTZ NOT NULL,
  result VARCHAR NOT NULL,
  details JSONB
);
```

**Rule Claude Code must follow**: `results` and `audit_log` are insert-only tables.
Never write an UPDATE or DELETE statement against them anywhere in the codebase.
"Current compliance posture" is always computed as "results where run_id = latest
completed run," not a mutable current-state table.

---

## 4. Control library — starter set (create these as individual YAML files in /backend/controls/)

Build exactly these 18 to start. Do not add more until this set is passing end-to-end
through collection → evaluation → dashboard → report export → exception workflow.

| # | id | title | category | severity |
|---|---|---|---|---|
| 1 | CIS-5.2.10 | SSH root login disabled | authentication | high |
| 2 | CIS-5.2.11 | SSH protocol restricted to SSHv2 with approved ciphers | authentication | high |
| 3 | CIS-5.3.1 | Minimum password length enforced (14+ chars) | authentication | medium |
| 4 | CIS-5.3.2 | Password expiration configured (max 90 days) | authentication | medium |
| 5 | CIS-5.4.1 | Account lockout after failed login attempts configured | authentication | high |
| 6 | CIS-3.1.1 | Default-deny firewall policy with explicit allow rules | network | critical |
| 7 | CIS-3.2.1 | IP forwarding disabled unless host is a router | network | medium |
| 8 | CIS-3.3.1 | ICMP redirects not accepted | network | low |
| 9 | CIS-4.1.1 | auditd installed and enabled | logging | high |
| 10 | CIS-4.1.2 | audit logs configured to persist and not be rotated away silently | logging | medium |
| 11 | CIS-4.2.1 | rsyslog/journald configured to forward logs to a remote host | logging | medium |
| 12 | CIS-1.1.1 | Unused filesystem modules (cramfs, freevxfs, etc.) disabled | filesystem | low |
| 13 | CIS-1.1.2 | /tmp mounted as a separate partition with noexec | filesystem | medium |
| 14 | CIS-1.4.1 | Permissions on /etc/passwd restricted (644, root-owned) | filesystem | high |
| 15 | CIS-1.4.2 | Permissions on /etc/shadow restricted (000/640, root-owned) | filesystem | critical |
| 16 | CIS-1.5.1 | Core dumps restricted | hardening | low |
| 17 | CIS-1.6.1 | Automatic security updates enabled | hardening | medium |
| 18 | CIS-6.1.1 | sudo usage logged to a dedicated log file | access_control | medium |

**AWS collector controls** (add these 6-8 once the Linux set is solid, to satisfy the
"two collector types" requirement — do not build more than this for MVP):
- S3 buckets: block public access enabled by default
- IAM: root account MFA enabled
- IAM: no active access keys on root account
- Security groups: no rule allowing 0.0.0.0/0 on port 22
- CloudTrail: enabled and logging to all regions
- EBS volumes: encryption at rest enabled

Each control YAML file follows this exact schema — write the description and
remediation text in your own words, do not copy CIS Benchmark document text verbatim
(copyright):

```yaml
id: CIS-5.2.10
title: Ensure SSH root login is disabled
framework_mappings:
  cis_linux_v8: "5.2.10"
  nist_csf: "PR.AC-1"
  soc2: "CC6.1"
  cert_in_marker: "IMP"
severity: high
category: authentication
description: >
  Original-wording description of what this checks and why.
applies_to: [linux_server]
test_logic:
  collector: ssh_config
  check: "PermitRootLogin"
  expected: "no"
remediation: >
  Original-wording remediation steps.
scored: true
```

---

## 5. Collector and evaluator contracts

```python
# backend/collectors/base.py
from abc import ABC, abstractmethod

class Collector(ABC):
    @abstractmethod
    def collect(self, target: dict) -> list[dict]:
        """Returns raw provider-specific state docs. Never touches evaluation logic."""
        ...

# backend/engine/normalizer.py
def normalize(raw_docs: list[dict], collector_type: str) -> list[dict]:
    """
    Maps raw collector output into canonical shape:
    {resource_type, resource_id, attributes: {}}
    The evaluator NEVER sees collector_type. If evaluator.py contains any
    `if collector_type ==` branching, that's an architecture violation — fix it
    by adding to the normalizer, not the evaluator.
    """
    ...

# backend/engine/evaluator.py
def evaluate(control: dict, normalized_resources: list[dict]) -> list[dict]:
    """
    Returns list of {control_id, resource_id, outcome, evidence}.
    outcome must be one of: pass, fail, error, manual_review.
    - scored=false controls -> always manual_review, never pass/fail.
    - Any exception during evaluation -> outcome='error', never silently pass.
    - Every call writes one row to audit_log with event_type='control_evaluated'.
    """
    ...
```

---

## 6. Credential handling (`backend/secrets_manager.py`)

- Fernet key loaded from `os.environ["SECRETS_KEY"]`, never hardcoded, never committed
  (add to `.gitignore` explicitly, add `.env.example` with a placeholder)
- Credentials table stores only the Fernet ciphertext, never plaintext
- `secrets_manager.py` is the ONLY module permitted to decrypt credentials. Collectors
  call `secrets_manager.get_credential(target_id)` — they never touch the encrypted
  table directly.
- Every call to `get_credential()` writes an `audit_log` row with
  `event_type='credential_used'` and the target_id in `details` — never the credential
  value itself.
- AWS collector's IAM policy documentation (in architecture.md) must state it only
  requires `SecurityAudit`/`ViewOnlyAccess` — read-only. Do not request write
  permissions anywhere in the AWS collector.

---

## 7. Build phases — do not start phase N+1 until phase N's acceptance criteria pass

**Phase 1 — Control library + minimal SSH collector (raw output only)**
Build all 18 Linux control YAMLs. Provision the demo Ubuntu VM via `vagrant up`
(Vagrantfile + provision.sh in /demo-environment) with intentional misconfigurations
matching several of the 18 controls (e.g. root SSH login enabled, weak password
policy, /etc/shadow permissions too open) — this doubles as your Section 8 demo
material later. Build the Fabric-based SSH collector against this VM (Vagrant
exposes SSH access via `vagrant ssh-config`) — at this stage it only needs to run
the read-only commands each control's `test_logic` requires (e.g. `cat
/etc/ssh/sshd_config`, `stat -c "%a" /etc/shadow`) and return the raw output. No
normalization, no evaluation yet.
Acceptance: all 18 YAMLs load without schema errors; collector returns real raw
output from the Vagrant VM for every one of the 18 controls' required checks,
printed/logged so you can visually confirm the data shape before building anything
that consumes it.

**Phase 2 — Normalizer + evaluation engine, Linux controls only**
Now build the normalizer AGAINST THE REAL OUTPUT captured in Phase 1 — not invented
fixtures. Then build the evaluator on top of normalized data.
Acceptance: running against the same Vagrant VM returns correct pass/fail for
all 18 controls, verified by manually checking the VM's actual config against
each expected result. Every run writes a `runs` row and per-control `results` rows.

**Phase 3 — Historical results + drift**
Acceptance: running the same scan twice produces two distinct `run_id`s with no
mutation of prior rows; a basic trend query (compliance % per run over time) returns
correct data.

**Phase 4 — Exception workflow**
Acceptance: can request exception on a failing control, approve it (as a distinct
approver from requester for high/critical severity), see the control excluded from
the "open findings" view but still visible in an "accepted risk" view, and see it
automatically return to `fail` after `expiry_date` passes on a subsequent run.

**Phase 5 — AWS collector**
Acceptance: same correctness bar as Phase 2, against a real or mocked AWS test
account, for the 6-8 AWS controls listed in Section 4. **No real AWS account is
available yet** — use the `moto` library to mock boto3 calls in-process. This is
a genuine rigor reduction versus Phases 1-4's real VM, not an equivalent
substitute — say so explicitly in BUILD_LOG.md and architecture.md, the same way
Docker-vs-Vagrant and fixture-vs-real-output were flagged earlier, not silently
treated as identical. Construct moto fixtures independently for rule 8's
cross-check (a second, separately-written fixture set, not reuse of the one the
collector was built against) — the same principle as a fresh SSH connection in
Phase 1-3, applied to mocks instead of a live host. Document in architecture.md
that this phase needs re-validation against a real AWS account before the
findings can be trusted the way the Linux controls now are — flag it as an open
item, not a completed one, until that happens.

**Phase 6 — Dashboard + report export**
Acceptance: dashboard shows overall %, per-domain breakdown, open exceptions with
expiry dates, and a drift chart. PDF export includes per-finding evidence and is
explicitly mapped to CIS/NIST/SOC2/CERT-In columns per control.

**Phase 7 — Audit log + security review pass**
Acceptance: every state-changing action in the app (scan trigger, exception approval,
report export, credential use) has a corresponding `audit_log` row with a shared
`correlation_id` per run. Manual review: grep the codebase for hardcoded secrets —
must return nothing.

**Also required in this phase — closing a gap Section 1 promised but no phase ever
assigned**: basic session-based auth (Section 1's stack decision), enforced on
every state-changing endpoint at minimum (scan trigger, exception approval/request,
report export) — read-only dashboard endpoints may stay open if time is short, but
say so explicitly rather than leaving it ambiguous which endpoints are actually
protected. A single seeded reviewer account is enough; do not build multi-user
roles or registration. Prove enforcement the same way everything else in this
build has been proven: an unauthenticated request to a protected endpoint must be
independently confirmed to be rejected (a real curl call without a session
cookie, not a code-reading exercise), not just "the middleware exists."
Credentials must be behind `secrets_manager.py` (Section 6) before this phase
closes — this was flagged as a carried-forward TODO since Phase 1 and cannot
ship to Phase 7 completion unresolved.

**Also required in this phase — a second gap, same root cause.** Section 3's
`audit_log` comment lists `scan_started` and Phase 7's own acceptance criteria
reference "scan trigger" as a state-changing action needing an audit row — both
assumed a real trigger mechanism exists, but no phase ever assigned building one.
Every scan run so far has been started by manually running a script from the
command line, which is not what FR5 in the original problem statement means by
"the same audit can be re-executed on demand" — that means a user-facing action
(an authenticated API endpoint at minimum, a "Run New Scan" button in the
dashboard if time allows), not a developer running a Python file by name. Build
a real `POST /api/scans` (or equivalent) endpoint, behind the new session auth,
that starts a real scan and returns/links the new `run_id`. Prove it the usual
way: trigger it yourself (via the button if built, via an authenticated curl
call otherwise) and independently confirm a new row appears in `runs` and the
dashboard reflects it — without touching the command line. A cron/scheduled
option (APScheduler) satisfies FR5's "or on a schedule" alternative and is a
reasonable stretch if time allows, but the on-demand endpoint is the
non-negotiable part — without it, this is a reporting dashboard over
manually-produced data, not an automated audit tool, which is what the
assignment is actually asking for.

---

## 7a. Phase 8 — Scale validation (untested NFR, catch before calling this finished)

The original problem statement's non-functional requirements include: "should handle
at least 50 simulated hosts/resources without redesign." This has never been
exercised — every run so far has used exactly one Linux target. This is graded,
explicit, and currently has zero evidence either way.

- **AWS side**: straightforward — generate 50 mocked resources (S3 buckets,
  security groups, etc.) via moto and confirm the evaluator/orchestrator handles
  the volume, with real timing recorded.
- **Linux side**: provisioning 50 real Vagrant VMs is not practical given how long
  a single VM took to provision on this hardware. Register 50 target entries
  pointing at the same demo VM (distinct `resource_id`s, same underlying host) to
  test that the orchestrator, database writes, and dashboard aggregation scale
  correctly across 50 targets. Document explicitly in architecture.md that this
  validates orchestration/DB/UI scale, not 50 independent real security
  postures — it's the same VM under the hood, and that distinction must not be
  blurred in the writeup.
- Report actual wall-clock timing for a 50-target scan — this is what determines
  whether the synchronous scan execution already noted as an open item (Phase 7's
  🟠 list) is a real problem at this scale or still just a theoretical one.
- Apply rule 8: independently confirm the database actually holds 50x the results
  of a single-target run, not just that the process exited without error.

---

## 8. Explicit non-goals for this build — do not implement unless asked

- OPA/Rego — custom evaluator only (Section 1)
- Real HashiCorp Vault integration — Fernet + documented rationale only
- Multi-tenancy
- Auto-remediation
- SIEM/ticketing integration
- SSO/OAuth
- A third collector type (network devices, Kubernetes, SaaS)
- More than 18 Linux + 8 AWS controls

If you (Claude Code) find yourself about to build any of the above, stop and flag it
rather than proceeding — it's out of scope for this grading cycle even if it seems
like a natural next step.

---

## 9. Standards of rigor — apply this to every phase, no exceptions

This project has real stakes for the person building it — job prospects, a
government-facing pitch, a live demo where every design decision will be
questioned. That doesn't change how you write code, but it does set the bar for
how you report on it. Hold to these rules strictly:

1. **Never report a phase's acceptance criteria as "met" without pasting the actual
   evidence** — real command output, real test results, real data from the demo
   VM. A summary claim like "the collector works correctly" is not
   acceptable on its own; show the raw output that proves it.
2. **If an acceptance criterion can't be verified, say so explicitly** — "I could not
   confirm X because Y" is the correct response, not silently treating it as passed
   or quietly lowering the bar to something that did pass.
3. **If you take a shortcut or simplification relative to this spec, flag it
   explicitly in your report** — do not silently substitute a simpler
   implementation and describe it as if it matches the spec.
4. **No stub logic where the spec calls for real logic.** If a function can't be
   implemented correctly in the time available, leave it clearly marked as
   incomplete with a `# TODO: reason` and say so in your report — don't return
   something that merely doesn't error out.
5. **If the spec is ambiguous or you think something in it is wrong, stop and ask**
   rather than guessing and proceeding on an assumption that affects correctness.
6. **Write every control's evaluation logic as if it will be independently
   re-verified by hand against the real demo VM** — because it will be.
   "Looks plausible" is not the bar; "matches what a manual check of the VM
   actually shows" is.
7. **Keep a running build log** (`BUILD_LOG.md`, one entry per phase) noting what
   was built, what was verified and how, and any deviations from spec. This
   becomes the answer key for defending design decisions in the live demo Q&A —
   treat it as a real deliverable, not busywork.

If you ever notice yourself about to write "should work," "this looks correct," or
similar hedged language in a completion report instead of actual verification
output — that's the signal to go verify it for real before reporting, not to report
it anyway.

8. **Self-verification for collection/evaluation claims**: before reporting any
   criterion involving collected or evaluated data as met, cross-check it yourself
   — for at least 5 of the controls involved, run the raw check command again via
   a fresh, independent execution path (not the collector's own cached/parsed
   output) and diff it against what the collector/evaluator reported. Report only
   pass/fail on this cross-check, not the raw output, unless asked. If anything
   doesn't match, do not report the criterion as met — debug and report the
   discrepancy instead.

---

## 10. Missing tool policy

Before starting a phase, verify the tools that phase needs are actually present
(`python --version`, `node --version`, `psql --version`, `vagrant --version`,
`VBoxManage --version`, etc. as relevant).

**Full install autonomy is granted, by explicit instruction from the project owner.**
If any required tool — project-level (pip/npm packages) or system-level (Python,
Node, PostgreSQL, VirtualBox, Vagrant) — is missing, install it yourself using the
official installer/package manager for the OS in use (e.g. `winget install
--id Oracle.VirtualBox -e` on Windows). Do not stop and wait for manual
installation. Proceed with the phase once the install completes.

One exception: if an install genuinely requires a system reboot to take effect
(VirtualBox's network driver is the known case), say so clearly before triggering
it, since a mid-session reboot can interrupt your own running session — but do not
wait for a separate confirmation to proceed once you've said it, just do the install
and reboot as needed.

Still required regardless of autonomy: **log every tool you installed in
BUILD_LOG.md** — what, why, and the exact command used. This isn't a permission
gate, it's a record — the project owner needs to be able to explain every piece
of the stack in a live demo Q&A, including tooling decisions made on their behalf.

---

## 11. Portability & team setup

The project owner is switching laptops next week and collaborators are joining.
Everything here exists so that a fresh clone on a different machine, by a
different person, works without re-deriving anything from a chat history they
weren't part of.

- **`.gitignore` must exclude, at minimum**: `venv/`, `__pycache__/`,
  `node_modules/`, `.next/`, `.vagrant/`, `*.box`, `.env`, OS junk files
  (`.DS_Store`, `Thumbs.db`), editor config (`.vscode/`, `.idea/`). None of these
  are portable or safe to commit — venv/node_modules are machine-specific and
  huge, `.vagrant/`/`*.box` are local VM state and multi-GB, `.env` holds the
  local `SECRETS_KEY` and must never be shared via git.
- **`README.md` is a required deliverable, not optional polish.** It must let
  someone clone the repo on a machine that has none of today's tools installed
  and get to a running Phase-N state with copy-pasteable commands only — no
  "as discussed earlier" references to context they don't have. Pull the exact
  install commands from `BUILD_LOG.md` rather than re-deriving them.
- **`CLAUDE.md` stays at repo root and stays current.** This is what gives every
  collaborator's Claude Code session the same spec and the same Section 9/10
  rigor rules automatically — there is no separate onboarding needed for
  standards, just "clone, open Claude Code here."
- **Secrets are per-machine, never shared.** Each contributor generates their own
  local `SECRETS_KEY` into their own `.env` from `.env.example`. Never commit a
  real key, never send one over chat/Slack/WhatsApp — regenerating locally is
  free, a leaked key in git history is not.
- **Small evidence artifacts (e.g. `phase1_raw_output.json`) are fine to commit** —
  they're part of the audit trail this project is supposed to produce. Anything
  multi-megabyte or machine-generated-and-regenerable (VM boxes, build output)
  is not.
