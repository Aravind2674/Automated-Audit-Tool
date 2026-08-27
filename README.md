# Automated IT Systems Audit Tool

Agentless compliance auditing for Linux servers and AWS accounts. Collects real system
state over SSH and the AWS API, evaluates it against a YAML control library mapped to
CIS / NIST CSF / SOC 2 / CERT-In, and records every result as append-only evidence.

`CLAUDE.md` at the repo root is the authoritative build spec. Read it before changing
anything — it defines the phase order, the schemas, and the rules the code follows.

---

## Current status

| Phase | State |
|---|---|
| 1 — Control library + SSH collector (raw output) | ✅ complete, verified |
| 2 — Normalizer + evaluator + persistence | ✅ complete, verified |
| 3 — Historical results + drift | ✅ complete, verified |
| 4 — Exception workflow | ✅ complete, verified |
| 5 — AWS collector | ⚠️ code complete, **moto-mocked only** — open pending real-account validation |
| 6–7 | not started |

Latest scan of the demo VM: **3 pass, 15 fail, 16.7% compliance**, every verdict
independently confirmed on the host.

See `BUILD_LOG.md` for what has been verified and how, and `architecture.md` for
design rationale and known limitations. Do not treat a phase as done because code for
it exists; check `BUILD_LOG.md`.

---

## 1. Prerequisites

Python 3.11+, VirtualBox, and Vagrant. **No Docker and no WSL** — the demo audit
target is a real VM (spec Section 1).

PostgreSQL is needed from Phase 2 onward. Node.js is not needed until Phase 6.

### Windows (verified on Windows 11, this is what the project was built on)

```bash
winget install --id Oracle.VirtualBox -e --accept-package-agreements --accept-source-agreements
```

```bash
winget install --id Hashicorp.Vagrant -e --accept-package-agreements --accept-source-agreements
```

```bash
winget install --id PostgreSQL.PostgreSQL.17 -e --accept-package-agreements --accept-source-agreements --custom "--mode unattended --unattendedmodeui none --superpassword CHANGE_ME --serverport 5432"
```

If the PostgreSQL download fails with HTTP 403, that is EnterpriseDB rate-limiting and
is transient — wait a few minutes and re-run the same command.

The VirtualBox winget package does **not** add `VBoxManage` to `PATH`. Add it once,
then open a new terminal:

```bash
setx PATH "%PATH%;C:\Program Files\Oracle\VirtualBox"
```

Python 3.11+ from [python.org](https://www.python.org/downloads/). Use the `py`
launcher on Windows — the bare `python` command is often the Microsoft Store stub and
will not work.

### macOS / Linux

Not verified on this project; commands are the standard ones for each platform.

```bash
brew install --cask virtualbox vagrant
```

```bash
sudo apt-get install -y virtualbox vagrant python3-venv
```

### Verify before continuing

```bash
vagrant --version && VBoxManage --version && psql --version
```

---

## 2. Clone and set up the backend

```bash
git clone https://github.com/Aravind2674/Automated-Audit-Tool.git
```

```bash
cd Automated-Audit-Tool
```

Create the virtual environment — **Windows**:

```bash
py -m venv venv && ./venv/Scripts/python.exe -m pip install -r requirements.txt
```

**macOS / Linux**:

```bash
python3 -m venv venv && ./venv/bin/python -m pip install -r requirements.txt
```

Every command below uses `./venv/Scripts/python.exe` (Windows). On macOS/Linux
substitute `./venv/bin/python`.

Copy the environment template. `SECRETS_KEY` is not consumed until `secrets_manager`
lands in a later phase, but create the file now so it is never an afterthought:

```bash
cp .env.example .env
```

Generate a real Fernet key and paste it into `.env` as `SECRETS_KEY`:

```bash
./venv/Scripts/python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Never commit `.env`.** `.gitignore` blocks it; do not use `git add -f` to override.

---

## 3. Bring up the demo audit target

> ⚠️ **The demo VM is deliberately insecure.** `demo-environment/provision.sh`
> enables root SSH login, makes `/etc/shadow` world-readable, disables the firewall
> and guts the password policy. That is the point — it is the tool's test subject.
> It is pinned to a host-only network. Do not bridge it to a real network, do not put
> real data on it, and destroy it when you are done.

First run downloads a ~600 MB Ubuntu 22.04 box and takes 10–40 minutes depending on
your connection. Subsequent runs are fast.

```bash
cd demo-environment && vagrant up
```

Confirm it is running:

```bash
cd demo-environment && vagrant status
```

`demo-environment/EXPECTED_POSTURE.md` is the per-control answer key for this VM —
**3 pass, 15 fail**. Phase 2's evaluator output is verified by hand against that
table, and all 18 rows are confirmed against the live VM.

Useful lifecycle commands:

```bash
cd demo-environment && vagrant halt
```

```bash
cd demo-environment && vagrant destroy -f
```

---

## 4. Run Phase 1 collection

Prints raw output for all 18 controls grouped by control, and writes
`phase1_raw_output.json` for the Phase 2 normalizer to be built against.

```bash
./venv/Scripts/python.exe backend/phase1_collect.py --from-vagrant-ssh-config
```

`phase1_raw_output.json` **is** committed — spec Section 11 treats small evidence
artifacts as part of the audit trail this project exists to produce. Note that it
contains a full configuration map of whatever host was audited; harmless for the
throwaway demo VM, but think before committing one collected from a real server.

---

## 4b. Create the database

Create the application role and database (replace `CHANGE_ME` with the superuser
password you set during install, and pick your own app password):

```bash
psql -U postgres -h localhost -c "CREATE ROLE audit LOGIN PASSWORD 'your-app-password';" -c "CREATE DATABASE audit_tool OWNER audit;"
```

Put the matching URL in `.env` — the app reads it from there and never from a
hardcoded string:

```bash
echo 'DATABASE_URL=postgresql+psycopg://audit:your-app-password@localhost:5432/audit_tool' >> .env
```

Tables are created automatically on the first scan.

---

## 4c. Run a full scan (Phase 2)

Collect from the VM, normalize, evaluate all 18 controls, and persist a `runs` row,
18 `results` rows and the `audit_log` trail:

```bash
./venv/Scripts/python.exe backend/run_scan.py --from-vagrant-ssh-config --triggered-by "$USER"
```

Re-evaluate cached raw output without touching the VM:

```bash
./venv/Scripts/python.exe backend/run_scan.py --raw phase1_raw_output.json
```

Evaluate without a database at all:

```bash
./venv/Scripts/python.exe backend/run_scan.py --raw phase1_raw_output.json --no-db
```

Inspect the current compliance posture — always computed as "results from the latest
completed run", never a mutable current-state table:

```bash
psql -U audit -h localhost -d audit_tool -c "SELECT r.control_id, c.severity, r.outcome FROM results r JOIN controls c ON c.id=r.control_id WHERE r.run_id=(SELECT run_id FROM runs WHERE status='completed' ORDER BY completed_at DESC LIMIT 1) ORDER BY r.outcome, r.control_id;"
```

---

## 5. Tests

Control library schema, `cert_in_marker` mapping, and fixture quarantine — no VM
needed:

```bash
./venv/Scripts/python.exe tests/test_control_library.py
```

Independent cross-checks (spec Section 9 rule 8). Both require the VM to be running.

Phase 1 — re-runs each check over a **fresh** SSH connection and diffs bytes against
what the collector recorded:

```bash
./venv/Scripts/python.exe tests/crosscheck_phase1.py --from-vagrant-ssh-config
```

Phase 2 — re-derives all 18 verdicts on the host using commands formulated
independently of the collector's, and compares against the evaluator:

```bash
./venv/Scripts/python.exe tests/crosscheck_phase2.py --from-vagrant-ssh-config
```

Phase 3 — compliance trend per run, with each row independently recomputed, plus drift
between consecutive runs. Needs the database, not the VM:

```bash
./venv/Scripts/python.exe tests/verify_phase3.py --trend
```

Prove historical rows are immutable across a new scan — fingerprint every existing row,
run a scan, then confirm nothing prior changed:

```bash
./venv/Scripts/python.exe tests/verify_phase3.py --snapshot-before
```

```bash
./venv/Scripts/python.exe tests/verify_phase3.py --verify-after
```

Phase 4 — exception workflow and separation-of-duties enforcement. Needs the database:

```bash
./venv/Scripts/python.exe tests/verify_phase4.py --sod
```

Open findings vs accepted risk for the latest run:

```bash
./venv/Scripts/python.exe tests/verify_phase4.py --views
```

Phase 5 — AWS collector against moto. Needs no VM, no database and no AWS account:

```bash
./venv/Scripts/python.exe tests/verify_phase5.py
```

> ⚠️ Phase 5 is verified against a **mock**, not real AWS. Its findings are not
> trustworthy to the standard of the Linux controls until re-run against a real AWS
> test account — see `architecture.md` §3.6.

---

## 6. Repository layout

```
backend/
  controls/*.yaml        18 control definitions -- the control library
  control_library.py     strict loader + schema validator
  collectors/base.py     abstract Collector interface
  collectors/ssh_collector.py   Fabric/Paramiko Linux collector (read-only)
  phase1_collect.py      Phase 1 runner
  engine/                normalizer + evaluator (Phase 2)
demo-environment/
  Vagrantfile            the deliberately misconfigured Ubuntu VM
  provision.sh           creates the misconfigurations
  EXPECTED_POSTURE.md    per-control answer key for manual verification
tests/
  test_control_library.py
  crosscheck_phase1.py
  fixtures/              synthetic fixtures -- never loaded as real controls
CLAUDE.md                the build spec (authoritative)
BUILD_LOG.md             what was built, what was verified, deviations from spec
```

---

## 7. Ground rules for contributors

- **`results` and `audit_log` are append-only.** Never write an `UPDATE` or `DELETE`
  against them anywhere. Current posture is computed as "results from the latest
  completed run", never stored as mutable state.
- **The collector is read-only.** Nothing in `collectors/` may write, install, restart
  or modify state on an audited host.
- **The evaluator never sees `collector_type`.** If you find yourself adding
  `if collector_type ==` in `engine/evaluator.py`, that is an architecture violation —
  fix it in `normalizer.py` instead.
- **`secrets_manager.py` is the only module permitted to decrypt credentials.**
- **Do not start phase N+1 before phase N's acceptance criteria pass**, with evidence
  recorded in `BUILD_LOG.md`.
- **Control text must be original wording.** Do not paste CIS Benchmark text into
  `description` or `remediation` — it is copyrighted.
