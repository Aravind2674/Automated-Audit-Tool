# Build log

Per CLAUDE.md Section 9 point 7. One entry per phase: what was built, what was
verified and how, and every deviation from spec.

---

## Phase 1 — Control library + minimal SSH collector (raw output only)

**Date:** 2026-08-27
**Status:** ✅ **COMPLETE — both acceptance criteria met with evidence.**
Criterion 1 (all 18 YAMLs load without schema errors): met.
Criterion 2 (collector returns real raw output from the demo VM): met — 14/14 sources,
66/66 commands executed against the live Vagrant VM, independently cross-checked.
*(The blocked status recorded here earlier was resolved once VirtualBox and Vagrant
were installed; see Addendum 2 and Addendum 4.)*

### Environment verified before starting (Section 10)

| Tool | Result | Needed for Phase 1? |
|---|---|---|
| Python | 3.14.2 (`py` launcher; the bare `python` alias is the Microsoft Store stub) | yes ✅ |
| git | 2.55.0 | no |
| Node / npm | **missing** | no (Phase 6) |
| psql | **missing** | no (Phase 2) |
| **Vagrant** | **missing** | **yes — blocker** |
| **VirtualBox** | **missing** | **yes — blocker** |

Project-level dependencies installed automatically per Section 10:
`fabric==3.2.3`, `paramiko==5.0.0`, `PyYAML==6.0.3` (+ transitive) into `venv/`.
Pinned in `requirements.txt`.

### What was built

- **18 control YAMLs** in `backend/controls/`, one file per control, ids and
  severities exactly as listed in Section 4. Descriptions and remediation are
  original wording — no CIS Benchmark text is reproduced verbatim (Section 4).
- **`backend/control_library.py`** — strict, fail-fast loader and schema validator.
  Rejects unknown keys, bad severities, missing framework mappings, unknown operator
  names, type-mismatched `expected` values, duplicate ids, and id/filename mismatch.
- **`backend/collectors/base.py`** — the abstract `Collector` interface from
  Section 5, plus `CollectorError`.
- **`backend/collectors/ssh_collector.py`** — Fabric-based Linux collector. A
  `SOURCE_COMMANDS` registry maps each of the 14 raw data sources named by the
  controls to its read-only commands; 66 commands total per full run.
- **`backend/phase1_collect.py`** — runner that collects and prints raw output
  grouped by control, and writes `phase1_raw_output.json` for the Phase 2 normalizer
  to be written against.
- **`demo-environment/Vagrantfile` + `provision.sh`** — Ubuntu 22.04 host-only VM,
  deliberately misconfigured.
- **`demo-environment/EXPECTED_POSTURE.md`** — per-control answer key for manual
  verification in Phase 2. Originally 4 pass / 14 fail; corrected to **3 pass /
  15 fail** in Phase 2 after the squashfs finding.

### What was verified, and how

1. **All 18 YAMLs load, 0 schema errors** — `load_controls()` parsed and validated
   every file; full table of id/severity/category/source printed. ✅
2. **The validator is not vacuous** — 12 deliberately corrupted controls (bad
   severity, missing key, unknown key, typo'd operator, non-numeric `expected` for
   `gte`, non-octal mode, etc.) were each rejected with a specific error. 12/12
   rejected. ✅
3. **Control↔collector coverage** — all 14 sources required by the 18 controls have
   a command mapping; no unmapped sources, no orphaned mappings. ✅
4. **Collector code path executes** — first validated with a fake transport (14 docs,
   66 commands, non-zero exits preserved as evidence). That run used synthetic output
   and proved only the code path, never any host's state.
5. **Real collection against the live VM** — 14/14 sources, 66/66 commands, output in
   `phase1_raw_output.json`, independently cross-checked over a fresh SSH connection
   (7/7 byte-identical) and sanity-checked to contain the 10 specific states
   `provision.sh` creates. ✅ See Addendum 4.

### Deviations from spec — flagged explicitly

1. **`backend/control_library.py` is not in the Section 2 file listing.** Section 3
   requires controls to be "loaded from `/backend/controls/*.yaml` at startup" but no
   module is named for it. Added as a new top-level backend module rather than
   silently placing loader logic in `engine/`, which Section 5 reserves for the
   normalizer and evaluator.
2. **Credentials come from the target dict, not `secrets_manager`.** Section 6
   requires collectors to call `secrets_manager.get_credential(target_id)`. That
   module and the database it depends on do not exist until later phases. Marked with
   an explicit `# TODO` at `ssh_collector.py::_connect` naming the Section 6
   requirement. **Deferred, not skipped — must be closed before Phase 7.**
3. **`test_logic` schema extended beyond the Section 4 example.** The example shows
   a flat `collector`/`check`/`expected`. Controls such as CIS-5.2.11 (four separate
   algorithm-list conditions) and CIS-4.1.1 (installed *and* enabled *and* active)
   cannot be expressed that way without either losing correctness or splitting one
   control into several, which would break the fixed 18-control set. Added an
   `operator` field and an optional composite `all_of`/`any_of` + `checks` form. The
   flat form from the spec example still validates and is used where it fits
   (CIS-5.2.10, CIS-5.3.1, CIS-5.3.2).
4. **`EXPECTED_POSTURE.md` was unverified when first written** — it recorded what
   `provision.sh` is written to produce, not what a running VM was observed to do.
   Now resolved: all 18 rows are confirmed against the live VM (Phase 2, rule 8
   cross-check), and one row was found to be **wrong** and corrected — see the
   squashfs finding in the Phase 2 entry.

### Addendum — 2026-08-27, follow-up session

Three items resolved by direction from the project owner.

**1. Vagrant confirmed as the demo target.** The "Docker container" wording in the
task prompt was superseded; CLAUDE.md Section 1 stands unchanged. No code changes.

**2. `cert_in_marker` vocabulary corrected and remapped.** The severity-derived
placeholder (`MAN`/`IMP`/`REC`) is gone. The vocabulary is now six markers — `CSM`
(Configuration and Security Management), `PRO` (Protection), `DET` (Detection), `RES`
(Response), `REC` (Recovery), `IMP` (Implementation). All 18 controls were remapped:

| Marker | Controls |
|---|---|
| `IMP` | 1.1.1, 1.1.2, 1.4.1, 1.4.2, 1.5.1, 1.6.1, 5.2.10, 5.2.11, 5.3.1, 5.3.2, 5.4.1, 6.1.1 |
| `PRO` | 3.1.1, 3.2.1, 3.3.1 |
| `DET` | 4.1.1, 4.1.2, 4.2.1 |

`MAN` was dropped entirely, and `VALID_CERT_IN_MARKERS` in `control_library.py` now
enforces the vocabulary at load time so it cannot be reintroduced silently. Note that
`REC` changed meaning between the two vocabularies — placeholder "Recommended" versus
"Recovery" — but no control carries `REC` under the new mapping, so no stale value
survived the remap with a shifted meaning.

> ### ⚠️ PROVENANCE OF THIS TAXONOMY — carries a documentation obligation
>
> These six markers come from **public methodology descriptions published by
> CERT-In-empanelled auditors**. They are **not** transcribed from a primary CERT-In
> document.
>
> **This taxonomy must never be presented as official CERT-In text** — not in the
> application UI, not in exported PDF reports, not in `architecture.md`, not in demo
> material. Wherever the marker column is surfaced it must be labelled as an
> auditor-methodology-derived mapping. Phase 6 builds the report exporter with a
> CERT-In column; that column needs this caveat rendered next to it.
>
> The same warning is duplicated at `control_library.VALID_CERT_IN_MARKERS` so it is
> visible at the point of use.

**3. Synthetic `manual_review` fixture added, quarantined.**
`tests/fixtures/TEST-MANUAL-REVIEW-001.yaml` is a `scored: false` control that
exercises the Section 5 `manual_review` path. It sits outside `backend/controls/`, so
`load_controls()` — which globs that directory only — never sees it. Its id is
`TEST-` prefixed rather than `CIS-` so any leak into a table is obvious on sight.
`tests/test_control_library.py` asserts the quarantine holds: 18 controls load, all
ids are `CIS-` prefixed, no `scored: false` control is in the real library, and the
fixture is absent from `backend/controls/`. 12/12 checks pass.

`tests/` is a new directory not in the Section 2 tree, added at the project owner's
explicit direction.

### Addendum 2 — 2026-08-27, system-level tooling installed

CLAUDE.md Section 10 was amended by the project owner to grant autonomy over
system-level installs, with the standing conditions that a reboot must be announced
before it happens, and that **every install is logged here regardless**. This section
is that log.

| Package | Version | Source | Method | Exit |
|---|---|---|---|---|
| Oracle VirtualBox | 7.2.16 r174877 | `Oracle.VirtualBox` (winget) — installer fetched from `download.virtualbox.org`, hash verified by winget | `winget install -e --disable-interactivity` | 0 |
| Microsoft VC++ Redistributable 2015+ x64 | (pulled as a dependency of VirtualBox) | `Microsoft.VCRedist.2015+.x64` (winget) | dependency of the above | 0 |
| HashiCorp Vagrant | 2.4.9 | `Hashicorp.Vagrant` (winget) — installer fetched from `releases.hashicorp.com`, hash verified by winget | `winget install -e --disable-interactivity` | 0 |

**No reboot was required or performed.** The pending-reboot flag
(`HKLM:\…\Component Based Servicing\RebootPending`) was checked immediately after both
installs and was absent; the `VBoxSup` kernel support driver came up `Running` without
one.

**One post-install fix-up:** the winget VirtualBox package does not add its install
directory to `PATH`, so `VBoxManage` was unresolvable even though VirtualBox was
correctly installed. `C:\Program Files\Oracle\VirtualBox` was appended to the **user**
`PATH` (not machine `PATH`, which would have needed elevation and would have affected
all accounts on the host). Vagrant locates VirtualBox through the registry key
`HKLM:\SOFTWARE\Oracle\VirtualBox\InstallDir` rather than `PATH`, so this was for the
benefit of direct `VBoxManage` invocations and future troubleshooting.

Note for the demo: this session's shell was **not** elevated, and winget still
completed both installs — it brokered the elevation itself. Worth knowing if the build
is ever reproduced on a locked-down machine, since a UAC prompt that cannot be answered
is the usual failure mode there.

Host capability confirmed before provisioning: 8 processor cores, 15674 MB RAM,
81.7 GB free on C:.

---

## Phase 2 — Normalizer + evaluation engine, Linux controls only

**Date:** 2026-08-27
**Status:** see the acceptance section below — evaluation correctness is met and
independently verified; database persistence is pending PostgreSQL finishing install.

### What was built

- **`backend/engine/normalizer.py`** — 14 per-source parsers, written against the real
  `phase1_raw_output.json`, not fixtures. Emits the canonical
  `{resource_type, resource_id, attributes}` shape. `collector_type` is consumed here
  and never appears in the output.
- **`backend/engine/evaluator.py`** — the 9 leaf operators and 2 composite operators
  declared in `control_library`, with `pass`/`fail`/`error`/`manual_review` semantics.
  Contains no reference to `collector_type` (spec Section 5).
- **`backend/models/schema.py`** — SQLAlchemy models mirroring the Section 3 DDL,
  CHECK constraints included.
- **`backend/db.py`** — engine/session; URL from `DATABASE_URL`, never hardcoded.
- **`backend/audit.py`** — append-only audit sink. Deliberately exposes no update or
  delete method, so the append-only rule is enforced by the absence of an API rather
  than by everyone remembering it.
- **`backend/run_scan.py`** — collect → normalize → evaluate → persist orchestrator.
- **`tests/crosscheck_phase2.py`** — rule 8 verification.

### Three real-host traps the normalizer had to handle

These are the concrete payoff of Section 7's instruction to build the normalizer
against real captured output rather than invented fixtures. None would have appeared
in a fixture written from intuition.

1. **`systemctl is-active ufw` reported `active` on a host with no firewall running.**
   `ufw status` said `Status: inactive` and `is-enabled` said `disabled`. The ufw unit
   is a oneshot that remains "active" after exiting regardless of whether ufw is
   enforcing anything. Trusting `is-active` would have passed CIS-3.1.1 — a *critical*
   control — on a completely unprotected host. The parser uses `ufw status` only.

2. **`sshd -T` versus the config file.** `/etc/ssh/sshd_config` contains an `Include`
   and the drop-in `99-audit-demo.conf` overrides it. Parsing the main file would have
   reported the distro default for `PermitRootLogin` and missed the override entirely.
   Only the post-Include effective config is parsed.

3. **A fully-commented `faillock.conf` shipped by the distro.** The file exists and
   looks like configuration, but `pam_faillock.so` is not in the PAM auth stack, so it
   enforces nothing. The parser requires the module to be wired in before reading the
   file as configured.

### Finding: EXPECTED_POSTURE.md contained an error, caught against the real VM

The answer key predicted CIS-1.1.1 would **pass**, because `provision.sh` writes
`install squashfs /bin/false` for all seven filesystem modules. On the actual VM the
control **fails**, and the evaluator was right:

```
CONFIG_SQUASHFS=y          <- compiled into the kernel, not a module
CONFIG_CRAMFS=m            <- genuinely a module
/proc/filesystems: squashfs
no squashfs.ko anywhere under /lib/modules/$(uname -r)
```

A modprobe install override cannot disable a filesystem that is built into the kernel.
The override is inert and squashfs remains available. `EXPECTED_POSTURE.md` has been
corrected (4 pass/14 fail → **3 pass/15 fail**, compliance 16.7%) with the reasoning
recorded inline.

This is the case Section 9 rule 6 exists for. Had the evaluator been "verified" against
the answer key rather than against the host, the sensible move would have been to
adjust the evaluator until it matched — which would have meant breaking correct code to
satisfy a wrong expectation.

The right remedy is the Phase 4 exception workflow, not a weakened control: snapd
mounts squashfs images and the host genuinely depends on it, which is exactly an
"accepted risk with compensating control". CIS-1.1.1's own remediation text already
anticipates this case.

### Acceptance criteria

**1. Correct pass/fail for all 18 controls, verified against the VM's actual config.**
✅ Met.

```
outcome totals: {'fail': 15, 'pass': 3}
compliance: 3/18 = 16.7%
MISMATCHES vs EXPECTED_POSTURE.md: 0
```

**Rule 8 independent verification.** `tests/crosscheck_phase2.py` re-derived every
control's verdict over a **fresh SSH connection** using commands formulated
independently of the collector's — `sysctl -n`, `stat -c %a`,
`systemctl is-active --quiet`, `findmnt -o OPTIONS`, `apt-config dump`, none of which
the collector uses in that form. Re-running the collector's own command through the
normalizer's own parser would only prove the pipeline is deterministic; it would not
catch collector and normalizer agreeing about something the host never said.

```
cross-checked : 18 controls
matched       : 18
mismatched    : 0
```

All 18 rows of `EXPECTED_POSTURE.md` are now confirmed against the live VM.

**Outcome paths beyond pass/fail** — all four verified:

```
manual_review  scored:false fixture            -> manual_review   PASS
error          source unavailable              -> error, NOT fail PASS
error          control names unknown attribute -> error           PASS
error          exception inside comparison     -> error           PASS
audit_log      18 controls -> 18 rows, all event_type=control_evaluated,
               all sharing one correlation_id                     PASS
```

The `error` vs `fail` boundary is deliberate: a value of `None` means "read the host
fine, setting not configured" → **fail**; a source marked `UNAVAILABLE` means "could
not read the host" → **error**. Collapsing them would let a missing sudo right appear
as a tidy list of compliance failures, which is worse than crashing because it looks
credible.

**2. Every run writes a `runs` row and per-control `results` rows.**
⏳ **Not yet verified.** Code is complete and the orchestrator runs end-to-end without
a database (18 results, 19 audit rows). PostgreSQL was blocked for part of this
session by an EnterpriseDB HTTP 403 on the installer download — transient, later
returning HTTP 200 — and the install was still in progress at the time of writing.
**This criterion must be confirmed against a live database before Phase 3 starts.**

### Deviations and open items

- **`scan_completed` audit event** is emitted regardless of persistence mode, so the
  trail records a finished scan even for `--no-db` runs.
- **Section 2 file listing additions:** `backend/db.py`, `backend/audit.py`,
  `backend/run_scan.py`, `backend/models/schema.py`. The spec names `/models` and
  `/api` directories but not these modules.
- **Credentials still come from the target dict**, not `secrets_manager` (spec
  Section 6). Unchanged from Phase 1; still marked TODO; must close before Phase 7.
- **Legacy-host reachability** (Addendum 4) remains open for `architecture.md`.

### Addendum 3 — 2026-08-27, source control and collaboration setup

Prompted by an imminent laptop switch and additional contributors joining.

**Pre-flight inspection (before any destructive action, per the request):**
the project was **not a git repository at all** — no `.git` directory, no parent
repository above it, zero commits. Nothing had ever been committed, so no history
audit or rewrite was needed. `venv/` (34 MB) and `demo-environment/.vagrant/` were
present in the working tree but had never been tracked.

**`.gitignore`** — rewritten to cover secrets (`.env`, `*.key`, `*.pem`, with a
`!.env.example` negation), Python artefacts, Node/Next.js artefacts, Vagrant state,
OS/editor noise, and collected audit evidence. Verified *behaviourally* rather than by
reading it: `git add --dry-run` confirms `.env.example` is trackable and a real `.env`
is refused, and `git check-ignore` confirms `venv/`, `.vagrant/`, `node_modules/` and
`phase1_raw_output.json` are all excluded.

Collected evidence (`phase1_raw_output.json`, `*_raw_output.json`, `evidence/`) is
ignored by rule, not case-by-case. For the throwaway demo VM the contents are
harmless, but the same file generated against a real server is a detailed map of that
host's weaknesses, and the habit is what matters.

**`.gitattributes`** — added, and this one is a correctness fix rather than tidiness.
Without `eol=lf`, git checks `demo-environment/provision.sh` out with CRLF endings on
a Windows clone, and Vagrant's shell provisioner then fails inside the VM with
`$'\r': command not found`. With contributors on mixed platforms this would have
surfaced as an unreproducible "the demo VM just doesn't provision on my machine".

**`README.md`** — clone-to-running instructions, commands only. Install commands are
the exact ones recorded in Addendum 2. macOS/Linux equivalents are included but
labelled unverified, since only the Windows path has actually been exercised here.

**`.env.example`** — added per spec Section 6 (`SECRETS_KEY` placeholder plus
`DATABASE_URL`). Slightly ahead of `secrets_manager.py`, which does not exist yet, but
it is spec-mandated and contributors need it at clone time.

**Commit and push.** Repo initialised, default branch renamed `master` → `main`,
identity set **repo-locally** (not globally, to avoid changing the machine's git
config for unrelated projects). Initial commit `f549b4f`, 38 files. `CLAUDE.md` is
committed at the repository root and confirmed present on the remote branch. Pushed
to `https://github.com/Aravind2674/Automated-Audit-Tool.git`; the remote was verified
empty beforehand, so nothing was overwritten.

The commit message states explicitly that Phase 1 Criterion 2 is **not** yet verified,
so the repository history does not imply a completeness the build has not reached.

**⚠️ Spec discrepancy — `CLAUDE.md` has no Section 11.** This work was requested "per
Section 11's list". `CLAUDE.md` is unchanged at 395 lines, sha256 `2bae871d4337…`,
and its section headings stop at `## 10. Missing tool policy`. The `.gitignore`
contents above are therefore **my own judgement, not a spec list**, and should be
reviewed against the intended Section 11 once it exists.

### Addendum 4 — 2026-08-27, Criterion 2 met

**Demo VM.** `vagrant up` completed (exit 0). Box `ubuntu/jammy64` v20241002.0.0,
VirtualBox provider, NAT 22→2222 plus host-only adapter. `provision.sh` ran to
completion and reported all 18 controls configured — 4 to pass, 14 to fail.

**Incident: the intentional misconfiguration locked the collector out.** The first
real collection attempt failed with `IncompatiblePeer: no acceptable kex algorithm`.
Diagnosed rather than worked around:

```
VM sshd offered : diffie-hellman-group14-sha1, curve25519-sha256
Paramiko 5.0.0  : curve25519-sha256@libssh.org, ecdh-sha2-nistp{256,384,521},
                  diffie-hellman-group16-sha512, diffie-hellman-group-exchange-sha256,
                  diffie-hellman-group14-sha256
                -> no algorithm in common
```

`curve25519-sha256` and `curve25519-sha256@libssh.org` are the same algorithm; RFC
8731 standardised the plain name after OpenSSH had shipped the vendor-suffixed one,
and Paramiko 5.0.0's `_preferred_kex` lists only the vendor spelling. `provision.sh`
had pinned the VM to the plain name alone, which no real OpenSSH host does — real
hosts offer both. Fixed in `provision.sh` by offering both spellings, which makes the
demo target *more* realistic rather than less. CIS-5.2.11 still fails as designed:
`diffie-hellman-group14-sha1`, CBC ciphers and `hmac-md5`/`hmac-sha1` all remain on
offer.

> **Carried finding for `architecture.md` and the demo Q&A.** This is not just a
> provisioning typo — it is a real limitation of the tool. Paramiko 5.0.0 has dropped
> SHA-1 key exchange entirely, so this collector **cannot connect to genuinely legacy
> SSH hosts** — which are disproportionately the hosts most in need of auditing. An
> audit tool that silently cannot reach its worst-configured targets reports a
> falsely clean estate. Options to evaluate later: pin an older Paramiko for a
> "legacy" connection profile, widen `Transport._preferred_kex` explicitly at the
> collector, or shell out to the system `ssh` client as a fallback transport. Not in
> scope for Phase 1; must not be forgotten.

**Collection result.**

```
sources collected : 14/14
commands run      : 66  (60 exit=0, 6 non-zero/timeout)
raw output written: phase1_raw_output.json
```

The 6 non-zero exits are expected evidence, not failures — e.g. `cat
/etc/audit/auditd.conf` returning 1 because auditd was purged is exactly the finding
CIS-4.1.1 depends on.

**Rule 8 self-verification (spec Section 9).** `tests/crosscheck_phase1.py` re-ran
each control's primary evidence command over a **fresh SSH connection**, opened
separately from the collector's, and diffed exit code and stdout bytes against
`phase1_raw_output.json`. 7 controls spanning 7 different collector sources:

```
PASS  CIS-1.4.2   PASS  CIS-1.6.1   PASS  CIS-3.2.1   PASS  CIS-4.1.1
PASS  CIS-5.2.10  PASS  CIS-5.3.1   PASS  CIS-6.1.1
cross-checked: 7   matched: 7   mismatched: 0
```

**Evidence sanity check.** Separately from the byte-diff, the collected evidence was
checked to contain the 10 specific states `provision.sh` was written to create
(`permitrootlogin yes`, `/etc/shadow mode=644`, `/etc/passwd mode=644 owner=root`,
`ip_forward = 1`, `accept_redirects = 0`, `minlen = 8`, `PASS_MAX_DAYS 99999`, auditd
absent, sudo `logfile=`, cramfs `install /bin/false`). 10/10 found. This matters
because a byte-identical diff proves only that the collector is *reproducible* — this
proves it is *reading the right thing*.

**`EXPECTED_POSTURE.md` is now partially verified.** 10 of its 18 rows are confirmed
against the live VM by the check above; its "not yet confirmed" header is accordingly
narrowed, not removed. The remaining 8 rows are confirmed during Phase 2 evaluation.

### Addendum 5 — 2026-08-27, Section 11 reconciliation

`CLAUDE.md` was updated by the project owner to add Section 11 (Portability & team
setup). The source-control work in Addendum 3 was done before it existed, so it was
checked against Section 11 rather than redone.

**Already compliant, no changes made:** all 11 of Section 11's minimum `.gitignore`
entries (`venv/`, `__pycache__/`, `node_modules/`, `.next/`, `.vagrant/`, `*.box`,
`.env`, `.DS_Store`, `Thumbs.db`, `.vscode/`, `.idea/`) were already present;
`README.md` already met the clone-to-running requirement with commands pulled from
this log; `CLAUDE.md` is at repo root and committed; `.env.example` exists with each
contributor generating their own `SECRETS_KEY`.

**One conflict, corrected:** Addendum 3's `.gitignore` excluded
`phase1_raw_output.json`, `*_raw_output.json`, `evidence/` and `*.log` on the
reasoning that collected evidence should stay out of source control. Section 11 says
the opposite — small evidence artifacts are part of the audit trail this project
exists to produce and are fine to commit. Those four patterns were removed. The
residual concern is recorded as a comment in `.gitignore` rather than as an ignore
rule: harmless for the throwaway demo VM, but evidence collected from a real
production host is a map of that host's weaknesses and warrants a deliberate decision
before it lands in a shared repo.

**⚠️ File integrity discrepancy — unresolved.** The project owner specified
`CLAUDE.md` should be sha256 `d084b80d137b6145…` at 440 lines. The file on disk is
sha256 `46d87a94abdd9626…` at **417 lines** — 23 lines short. Section 11's content is
present but rendered as `**11. Portability & team setup**` (bold) rather than a
`## 11.` heading, and the whole file now carries backslash-escaped markdown
(`## 1\. Stack`, `SECRETS\_KEY`), consistent with a paste that round-tripped through
a rich-text editor. The Section 11 text that *is* present was acted on in full. The
owner should confirm nothing further was truncated.

### Open items carried into Phase 2

- **`manual_review` fixture exists but is not yet exercised.** The fixture is in
  place and quarantined (see addendum item 3), but nothing consumes it until the
  Phase 2 evaluator exists. Phase 2 must add an evaluator test asserting it returns
  `manual_review` and never `pass`/`fail`.
- **CIS-3.2.1 kept as `scored: true`.** Its title says "unless host is a router",
  which is context-dependent. Judgement call: keep it scored and route the router case
  through the Phase 4 exception workflow, rather than weakening the control. Recorded
  in the control's own `description` and `remediation`.
- **Phase 2 evaluator must implement exactly the operator set** declared in
  `control_library.LEAF_OPERATORS` and `COMPOSITE_OPERATORS`; the validator already
  refuses anything outside it.
