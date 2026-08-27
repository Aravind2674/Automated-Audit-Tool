# Project: Automated IT Systems Audit Tool

### Persistent build context for Claude Code — read this fully before writing any code.

This file is the spec. Do not deviate from the phase order in Section 7 without
explicit instruction — each phase has acceptance criteria that must pass before
starting the next one. This is a one-semester capstone graded primarily on
correctness of control evaluation (25%), architecture/extensibility (20%), and
exception handling + tool security (30% combined). Depth over breadth, always.

\---

## 1\. Stack

* **Backend**: Python 3.11+, FastAPI
* **Collectors**: Python — Fabric (built on Paramiko) for SSH/Linux servers — this is
Paramiko's own documented recommendation for running remote shell commands, not just
a convenience pick. AWS collector uses boto3's **`client` interface only**
(`boto3.client('s3')` etc.) — do NOT use `boto3.resource(...)`. AWS has put the
resources interface into a permanent feature freeze and confirmed it will not carry
into the next major SDK version, so building against it now is building on something
already being phased out.
* **Rules engine**: lightweight custom Python evaluator (see Section 5) — not OPA,
timeline doesn't justify the overhead for 15-20 controls
* **Database**: PostgreSQL (results, controls, exceptions, audit log — all append-only
where noted)
* **Frontend**: Next.js + React, Tailwind
* **Auth**: simple session-based auth is sufficient; do not build SSO/OAuth for MVP
* **Local environment — no Docker, no WSL.** Everything below installs as a plain
standalone program, nothing containerized:

  * PostgreSQL: install natively via the official installer for your OS
(postgresql.org/download) — run it as a normal local service, not in a container
  * Backend: standard Python venv (`python -m venv venv`), pip install dependencies,
run FastAPI with `uvicorn` directly
  * Frontend: `npm install \&\& npm run dev`, plain Next.js dev server
  * **Demo audit target: Vagrant + VirtualBox**, not Docker. This is the problem
statement's own explicitly sanctioned alternative to Docker containers for
standing in as "real" audited systems (see Section 6 of the original brief).
A Vagrant-provisioned Ubuntu VM is arguably more realistic for an SSH-based
collector than a container anyway — you're auditing real OS-level
configuration (sshd, PAM, filesystem permissions, auditd) on a real init
system, not a container's stripped-down userspace. Vagrant + VirtualBox run
standalone on native Windows/Mac/Linux with zero WSL involvement — install
both as regular programs, no subsystem required.
  * Document in architecture.md that a production deployment would containerize
(Docker Compose or similar, per the problem statement's own wording) — this
local setup is a deliberate, justified substitution, not a shortfall.
* **Secrets**: Fernet (symmetric encryption) with key from environment variable, never
committed. See Section 6. Document in architecture.md that production would delegate
to Vault/cloud KMS instead — do not attempt to build actual Vault integration.

\---

## 2\. Repository structure

```
/backend
  /collectors
    base.py              # abstract Collector interface — all collectors implement this
    ssh\_collector.py      # Linux server collector (Fabric, built on Paramiko)
    aws\_collector.py      # AWS collector (boto3)
  /engine
    evaluator.py          # runs controls against normalized resource docs
    normalizer.py         # raw collector output -> canonical resource docs
  /controls
    \*.yaml                 # one file per control — see Section 4
  /models                  # SQLAlchemy models — see Section 3
  /api                     # FastAPI routers
  /auth
  /secrets\_manager.py       # Fernet-based credential store, isolated module
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

\---

## 3\. Database schema (PostgreSQL DDL)

```sql
CREATE TABLE controls (
  id VARCHAR PRIMARY KEY,              -- e.g. 'CIS-5.2.10'
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  category VARCHAR NOT NULL,
  severity VARCHAR NOT NULL CHECK (severity IN ('critical','high','medium','low')),
  applies\_to VARCHAR\[] NOT NULL,       -- e.g. {linux\_server}
  scored BOOLEAN NOT NULL DEFAULT true,
  framework\_mappings JSONB NOT NULL,   -- {"cis\_linux\_v8":"5.2.10","nist\_csf":"PR.AC-1","cert\_in\_marker":"IMP"}
  test\_logic JSONB NOT NULL,
  remediation TEXT NOT NULL
);
-- controls are loaded from /backend/controls/\*.yaml at startup, not hand-inserted

CREATE TABLE runs (
  run\_id UUID PRIMARY KEY,
  correlation\_id UUID NOT NULL,
  triggered\_by VARCHAR NOT NULL,       -- user id or 'scheduler'
  started\_at TIMESTAMPTZ NOT NULL,
  completed\_at TIMESTAMPTZ,
  status VARCHAR NOT NULL              -- running | completed | failed
);

CREATE TABLE results (                  -- APPEND-ONLY. Never UPDATE. Never DELETE.
  result\_id UUID PRIMARY KEY,
  run\_id UUID REFERENCES runs(run\_id),
  control\_id VARCHAR REFERENCES controls(id),
  resource\_id VARCHAR NOT NULL,
  outcome VARCHAR NOT NULL CHECK (outcome IN ('pass','fail','error','manual\_review')),
  evidence JSONB NOT NULL,             -- exact collected state that produced this outcome
  evaluated\_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE exceptions (
  exception\_id UUID PRIMARY KEY,
  control\_id VARCHAR REFERENCES controls(id),
  resource\_id VARCHAR NOT NULL,
  status VARCHAR NOT NULL CHECK (status IN ('accepted\_risk','false\_positive','pending\_review')),
  justification TEXT NOT NULL,
  requested\_by VARCHAR NOT NULL,
  approved\_by VARCHAR,                  -- must differ from requested\_by if severity is high/critical
  approval\_date TIMESTAMPTZ,
  expiry\_date TIMESTAMPTZ NOT NULL,     -- no permanent exceptions, ever
  compensating\_control TEXT
);

CREATE TABLE audit\_log (                -- APPEND-ONLY
  event\_id UUID PRIMARY KEY,
  correlation\_id UUID NOT NULL,
  run\_id UUID,
  actor VARCHAR NOT NULL,
  event\_type VARCHAR NOT NULL,          -- scan\_started|scan\_completed|control\_evaluated|exception\_approved|credential\_used|report\_exported
  timestamp TIMESTAMPTZ NOT NULL,
  result VARCHAR NOT NULL,
  details JSONB
);
```

**Rule Claude Code must follow**: `results` and `audit\_log` are insert-only tables.
Never write an UPDATE or DELETE statement against them anywhere in the codebase.
"Current compliance posture" is always computed as "results where run\_id = latest
completed run," not a mutable current-state table.

\---

## 4\. Control library — starter set (create these as individual YAML files in /backend/controls/)

Build exactly these 18 to start. Do not add more until this set is passing end-to-end
through collection → evaluation → dashboard → report export → exception workflow.

|#|id|title|category|severity|
|-|-|-|-|-|
|1|CIS-5.2.10|SSH root login disabled|authentication|high|
|2|CIS-5.2.11|SSH protocol restricted to SSHv2 with approved ciphers|authentication|high|
|3|CIS-5.3.1|Minimum password length enforced (14+ chars)|authentication|medium|
|4|CIS-5.3.2|Password expiration configured (max 90 days)|authentication|medium|
|5|CIS-5.4.1|Account lockout after failed login attempts configured|authentication|high|
|6|CIS-3.1.1|Default-deny firewall policy with explicit allow rules|network|critical|
|7|CIS-3.2.1|IP forwarding disabled unless host is a router|network|medium|
|8|CIS-3.3.1|ICMP redirects not accepted|network|low|
|9|CIS-4.1.1|auditd installed and enabled|logging|high|
|10|CIS-4.1.2|audit logs configured to persist and not be rotated away silently|logging|medium|
|11|CIS-4.2.1|rsyslog/journald configured to forward logs to a remote host|logging|medium|
|12|CIS-1.1.1|Unused filesystem modules (cramfs, freevxfs, etc.) disabled|filesystem|low|
|13|CIS-1.1.2|/tmp mounted as a separate partition with noexec|filesystem|medium|
|14|CIS-1.4.1|Permissions on /etc/passwd restricted (644, root-owned)|filesystem|high|
|15|CIS-1.4.2|Permissions on /etc/shadow restricted (000/640, root-owned)|filesystem|critical|
|16|CIS-1.5.1|Core dumps restricted|hardening|low|
|17|CIS-1.6.1|Automatic security updates enabled|hardening|medium|
|18|CIS-6.1.1|sudo usage logged to a dedicated log file|access\_control|medium|

**AWS collector controls** (add these 6-8 once the Linux set is solid, to satisfy the
"two collector types" requirement — do not build more than this for MVP):

* S3 buckets: block public access enabled by default
* IAM: root account MFA enabled
* IAM: no active access keys on root account
* Security groups: no rule allowing 0.0.0.0/0 on port 22
* CloudTrail: enabled and logging to all regions
* EBS volumes: encryption at rest enabled

Each control YAML file follows this exact schema — write the description and
remediation text in your own words, do not copy CIS Benchmark document text verbatim
(copyright):

```yaml
id: CIS-5.2.10
title: Ensure SSH root login is disabled
framework\_mappings:
  cis\_linux\_v8: "5.2.10"
  nist\_csf: "PR.AC-1"
  soc2: "CC6.1"
  cert\_in\_marker: "IMP"
severity: high
category: authentication
description: >
  Original-wording description of what this checks and why.
applies\_to: \[linux\_server]
test\_logic:
  collector: ssh\_config
  check: "PermitRootLogin"
  expected: "no"
remediation: >
  Original-wording remediation steps.
scored: true
```

\---

## 5\. Collector and evaluator contracts

```python
# backend/collectors/base.py
from abc import ABC, abstractmethod

class Collector(ABC):
    @abstractmethod
    def collect(self, target: dict) -> list\[dict]:
        """Returns raw provider-specific state docs. Never touches evaluation logic."""
        ...

# backend/engine/normalizer.py
def normalize(raw\_docs: list\[dict], collector\_type: str) -> list\[dict]:
    """
    Maps raw collector output into canonical shape:
    {resource\_type, resource\_id, attributes: {}}
    The evaluator NEVER sees collector\_type. If evaluator.py contains any
    `if collector\_type ==` branching, that's an architecture violation — fix it
    by adding to the normalizer, not the evaluator.
    """
    ...

# backend/engine/evaluator.py
def evaluate(control: dict, normalized\_resources: list\[dict]) -> list\[dict]:
    """
    Returns list of {control\_id, resource\_id, outcome, evidence}.
    outcome must be one of: pass, fail, error, manual\_review.
    - scored=false controls -> always manual\_review, never pass/fail.
    - Any exception during evaluation -> outcome='error', never silently pass.
    - Every call writes one row to audit\_log with event\_type='control\_evaluated'.
    """
    ...
```

\---

## 6\. Credential handling (`backend/secrets\_manager.py`)

* Fernet key loaded from `os.environ\["SECRETS\_KEY"]`, never hardcoded, never committed
(add to `.gitignore` explicitly, add `.env.example` with a placeholder)
* Credentials table stores only the Fernet ciphertext, never plaintext
* `secrets\_manager.py` is the ONLY module permitted to decrypt credentials. Collectors
call `secrets\_manager.get\_credential(target\_id)` — they never touch the encrypted
table directly.
* Every call to `get\_credential()` writes an `audit\_log` row with
`event\_type='credential\_used'` and the target\_id in `details` — never the credential
value itself.
* AWS collector's IAM policy documentation (in architecture.md) must state it only
requires `SecurityAudit`/`ViewOnlyAccess` — read-only. Do not request write
permissions anywhere in the AWS collector.

\---

## 7\. Build phases — do not start phase N+1 until phase N's acceptance criteria pass

**Phase 1 — Control library + minimal SSH collector (raw output only)**
Build all 18 Linux control YAMLs. Provision the demo Ubuntu VM via `vagrant up`
(Vagrantfile + provision.sh in /demo-environment) with intentional misconfigurations
matching several of the 18 controls (e.g. root SSH login enabled, weak password
policy, /etc/shadow permissions too open) — this doubles as your Section 8 demo
material later. Build the Fabric-based SSH collector against this VM (Vagrant
exposes SSH access via `vagrant ssh-config`) — at this stage it only needs to run
the read-only commands each control's `test\_logic` requires (e.g. `cat /etc/ssh/sshd\_config`, `stat -c "%a" /etc/shadow`) and return the raw output. No
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
Acceptance: running the same scan twice produces two distinct `run\_id`s with no
mutation of prior rows; a basic trend query (compliance % per run over time) returns
correct data.

**Phase 4 — Exception workflow**
Acceptance: can request exception on a failing control, approve it (as a distinct
approver from requester for high/critical severity), see the control excluded from
the "open findings" view but still visible in an "accepted risk" view, and see it
automatically return to `fail` after `expiry\_date` passes on a subsequent run.

**Phase 5 — AWS collector**
Acceptance: same correctness bar as Phase 2, against a real or mocked AWS test
account, for the 6-8 AWS controls listed in Section 4.

**Phase 6 — Dashboard + report export**
Acceptance: dashboard shows overall %, per-domain breakdown, open exceptions with
expiry dates, and a drift chart. PDF export includes per-finding evidence and is
explicitly mapped to CIS/NIST/SOC2/CERT-In columns per control.

**Phase 7 — Audit log + security review pass**
Acceptance: every state-changing action in the app (scan trigger, exception approval,
report export, credential use) has a corresponding `audit\_log` row with a shared
`correlation\_id` per run. Manual review: grep the codebase for hardcoded secrets —
must return nothing.

\---

## 8\. Explicit non-goals for this build — do not implement unless asked

* OPA/Rego — custom evaluator only (Section 1)
* Real HashiCorp Vault integration — Fernet + documented rationale only
* Multi-tenancy
* Auto-remediation
* SIEM/ticketing integration
* SSO/OAuth
* A third collector type (network devices, Kubernetes, SaaS)
* More than 18 Linux + 8 AWS controls

If you (Claude Code) find yourself about to build any of the above, stop and flag it
rather than proceeding — it's out of scope for this grading cycle even if it seems
like a natural next step.

\---

## 9\. Standards of rigor — apply this to every phase, no exceptions

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
7. **Keep a running build log** (`BUILD\_LOG.md`, one entry per phase) noting what
was built, what was verified and how, and any deviations from spec. This
becomes the answer key for defending design decisions in the live demo Q\&A —
treat it as a real deliverable, not busywork.

If you ever notice yourself about to write "should work," "this looks correct," or
similar hedged language in a completion report instead of actual verification
output — that's the signal to go verify it for real before reporting, not to report
it anyway.

\---

## 10\. Missing tool policy

Before starting a phase, verify the tools that phase needs are actually present
(`python --version`, `node --version`, `psql --version`, `vagrant --version`,
`VBoxManage --version`, etc. as relevant).

* **Project-level dependencies** — Python packages (pip, inside the project's venv)
and npm packages. Install these automatically as needed. No need to ask first;
these are sandboxed to the project and trivially reversible.
* **System-level tools** — the Python interpreter itself, Node.js, the PostgreSQL
server, VirtualBox, Vagrant. If one of these is missing:

  * Do NOT download and run an installer for it yourself.
  * Report exactly which tool is missing, why this phase needs it, and the
official download link and standard install command for the OS in use.
  * Stop and wait for confirmation that it's installed before proceeding.

  Reason: these installs need admin/elevated privileges, can require a system
reboot (VirtualBox in particular), and can conflict with existing system
configuration — a human needs to be the one deciding what changes at the OS
level on their own machine, even if it means one extra round-trip.

**11. Portability \& team setup**



  The project owner is switching laptops next week and collaborators are joining. Everything here exists so that a fresh clone on a different machine, by a different person, works without re-deriving anything from a chat history they weren't part of.



  .gitignore must exclude, at minimum: venv/, \_\_pycache\_\_/, node\_modules/, .next/, .vagrant/, \*.box, .env, OS junk files (.DS\_Store, Thumbs.db), editor config (.vscode/, .idea/). None of these are portable or safe to commit — venv/node\_modules are machine-specific and huge, .vagrant//\*.box are local VM state and multi-GB, .env holds the local SECRETS\_KEY and must never be shared via git.

  README.md is a required deliverable, not optional polish. It must let someone clone the repo on a machine that has none of today's tools installed and get to a running Phase-N state with copy-pasteable commands only — no "as discussed earlier" references to context they don't have. Pull the exact install commands from BUILD\_LOG.md rather than re-deriving them.

  CLAUDE.md stays at repo root and stays current. This is what gives every collaborator's Claude Code session the same spec and the same Section 9/10 rigor rules automatically — there is no separate onboarding needed for standards, just "clone, open Claude Code here."

  Secrets are per-machine, never shared. Each contributor generates their own local SECRETS\_KEY into their own .env from .env.example. Never commit a real key, never send one over chat/Slack/WhatsApp — regenerating locally is free, a leaked key in git history is not.

  Small evidence artifacts (e.g. phase1\_raw\_output.json) are fine to commit — they're part of the audit trail this project is supposed to produce. Anything multi-megabyte or machine-generated-and-regenerable (VM boxes, build output) is not.

