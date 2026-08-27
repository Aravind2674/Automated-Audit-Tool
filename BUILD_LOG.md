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

**Addendum 2b — PostgreSQL, installed 2026-08-27 (Section 10 install record).**

| Package | Version | Source | Method | Exit |
|---|---|---|---|---|
| PostgreSQL | 17.11-1 | `PostgreSQL.PostgreSQL.17` (winget) — EDB installer, hash verified by winget | `winget install -e --disable-interactivity --custom '--mode unattended --unattendedmodeui none --superpassword <redacted> --serverport 5432'` | 0 |

No reboot required. Service `postgresql-x64-17` registered, `Running`, StartType
`Automatic`; `initdb` completed (PG_VERSION 17); listening on 5432.

Two obstacles worth recording, since both cost real time and would recur on a rebuild:

1. **The host slept mid-install**, killing the first winget attempt and leaving an
   orphaned `winget` process holding the install. It was terminated and the install
   restarted cleanly.
2. **EnterpriseDB returned HTTP 403** on the installer download for a stretch —
   every version, every endpoint, and unchanged by user-agent. It was transient:
   a later request returned HTTP 200 and downloaded at ~2.5 MB/s. If a rebuild hits
   403 here, wait and retry rather than hunting for an alternative mirror.

Application role and database were created as `audit` / `audit_tool` with a randomly
generated password written only to `.env` (gitignored, verified with
`git check-ignore`). The PostgreSQL superuser password is a local development value
and is not used by the application.

---

## Phase 2 — Normalizer + evaluation engine, Linux controls only

**Date:** 2026-08-27
**Status:** ✅ **COMPLETE — both acceptance criteria met with evidence.**
Correct pass/fail for all 18 controls: met, 0 mismatches, 18/18 rule-8 cross-check.
Every run writes a `runs` row and per-control `results` rows: met against live
PostgreSQL 17.11.

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

**2. Every run writes a `runs` row and per-control `results` rows.** ✅ Met.

Live scan against the demo VM, persisted to PostgreSQL 17.11:

```
run_id         : c4b93ee3-6932-47bd-8815-a156d0fedd76
correlation_id : ad5c2505-4780-48b6-b666-14cff77bbb66
results        : 18
outcomes       : {'fail': 15, 'pass': 3}
compliance     : 3/18 = 16.7%
```

Queried back with `psql` directly — an independent path, not through the app's ORM:

```
     t     | count            event_type     | count | distinct_corr_ids
-----------+-------          -------------------+-------+-------------------
 audit_log |    20            control_evaluated |    18 |                 1
 controls  |    18            scan_completed    |     1 |                 1
 results   |    18            scan_started      |     1 |                 1
 runs      |     1
```

One `runs` row (status `completed`, `started_at`/`completed_at` populated), 18
`results` rows one per control, 20 `audit_log` rows all sharing a single
`correlation_id` for the run. `evidence` JSONB stores per-check detail — for CIS-1.4.2
it records `/etc/shadow.mode actual "644" expected "640" mode_at_most satisfied:false`
alongside the two checks that did pass, so the finding is defensible later without
re-running the scan.

**Rule 8 on the persisted data.** Outcomes were read back **out of PostgreSQL** and
compared against a fresh on-host derivation over a new SSH connection — verifying the
stored rows, not an in-memory evaluation:

```
outcomes read from PostgreSQL: 18
cross-checked : 18 controls (DB rows vs fresh on-host derivation)
matched       : 18     mismatched : 0
```

**Append-only enforcement verified:**

```
grep for UPDATE/DELETE against results or audit_log  -> none found
AuditSink public API                                 -> ['event', 'write']
hardcoded secrets grep                               -> none found
```

`AuditSink` exposes no update or delete method, so the append-only rule is enforced by
the absence of an API rather than by everyone remembering it.

### Deviations and open items

- **`scan_completed` audit event** is emitted regardless of persistence mode, so the
  trail records a finished scan even for `--no-db` runs.
- **Section 2 file listing additions:** `backend/db.py`, `backend/audit.py`,
  `backend/run_scan.py`, `backend/models/schema.py`. The spec names `/models` and
  `/api` directories but not these modules.
- **Credentials still come from the target dict**, not `secrets_manager` (spec
  Section 6). Unchanged from Phase 1; still marked TODO; must close before Phase 7.
- **Legacy-host reachability** (Addendum 4) remains open for `architecture.md`.

---

## Phase 3 — Historical results + drift

**Date:** 2026-08-27
**Status:** ✅ **COMPLETE — both acceptance criteria met with evidence.**

### What was built

- **`backend/queries.py`** — read-only historical queries: compliance trend per run,
  drift between any two runs, latest-completed-run resolution, and drift
  classification into improved / regressed / appeared / disappeared / other.
- **`tests/verify_phase3.py`** — append-only verification harness and trend validator.

No changes were made to the collector, normalizer or evaluator. Phase 3 is entirely
additive, which is the point: history is *derived* from the append-only results table,
not maintained alongside it.

### Design notes

**Drift is computed, never stored.** There is no drift table and no changelog. A drift
report for any pair of historical runs is a query over `results`, so it can be
regenerated at any time and can never fall out of sync with the evidence it describes.

**`manual_review` and `error` are excluded from the compliance denominator.** A control
awaiting human judgement has not passed and has not failed, and an unreadable source is
a broken audit rather than a compliance failure. Counting either as a failure would
make the headline percentage move for reasons unrelated to the host's security posture
— an SSH permission problem would look like a security regression. Both are returned as
separate counts so a reader sees they exist instead of having them silently vanish.

**`FULL JOIN` + `IS DISTINCT FROM` in the drift query.** An inner join would drop a
control present in only one of the two runs — a control added to or removed from the
library, or a resource that fell out of a scan — which is exactly the kind of change a
drift report must not silently omit. `IS DISTINCT FROM` rather than `<>` for the same
reason: `NULL <> 'pass'` evaluates to NULL, not true, so a plain inequality would
discard those very rows.

### Acceptance criterion 1 — two scans, two run_ids, no mutation of prior rows ✅

Four scans were run. Before each, every existing `results` and `audit_log` row was
fingerprinted **column-by-column with SHA-256**; afterwards the pre-existing rows were
fingerprinted again and compared. A row count alone would catch deletions but not
mutations — if a later run silently rewrote a prior finding's `outcome` or `evidence`,
which is precisely what the append-only rule exists to prevent, the count would be
unchanged and the digest would not.

```
TABLE       BEFORE   AFTER   NEW  MUTATED  DELETED
run 2:  results  18 ->  36    18        0        0
        audit_log 20 ->  40    20        0        0
run 3:  results  36 ->  54    18        0        0
        audit_log 40 ->  60    20        0        0
run 4:  results  54 ->  72    18        0        0
        audit_log 60 ->  80    20        0        0
```

Four distinct run_ids, four distinct correlation_ids, one correlation_id per run:

```
   run    | events | distinct_corr_ids        total_distinct_corr_ids | total_runs
----------+--------+-------------------      -------------------------+------------
 c4b93ee3 |     20 |                 1                             4 |          4
 51f38dd3 |     20 |                 1
 81fad9d8 |     20 |                 1
 b4811f62 |     20 |                 1
```

**Run 1's evidence survived three subsequent scans unchanged.** `/etc/shadow` was
changed to 640 and back to 644 during Phase 3, and run 1 still records what it observed
at the time:

```
SELECT evidence->'checks'->0->>'actual' FROM results
WHERE run_id='c4b93ee3-...' AND control_id='CIS-1.4.2';   ->  644
```

That is the property that makes a finding defensible months later.

### Acceptance criterion 2 — trend query returns correct data ✅

Real drift was induced rather than simulated. Two controls were remediated on the live
VM between runs 2 and 3 (`chmod 640 /etc/shadow`, `ip_forward = 0`), each verified by
hand on the host before and after (rule 6), then reverted before run 4 to restore the
documented posture.

```
#   RUN_ID     COMPLETED             PASS  FAIL  ERR  MR  COMPLIANCE
1   c4b93ee3   2026-08-27 15:23:52      3    15    0   0       16.7%
2   51f38dd3   2026-08-27 15:30:48      3    15    0   0       16.7%
3   81fad9d8   2026-08-27 15:31:46      5    13    0   0       27.8%
4   b4811f62   2026-08-27 15:32:32      3    15    0   0       16.7%

Drift between consecutive runs:
  c4b93ee3 -> 51f38dd3: no change
  51f38dd3 -> 81fad9d8: 2 improved
      improved   CIS-1.4.2  [critical] fail -> pass
      improved   CIS-3.2.1  [medium]   fail -> pass
  81fad9d8 -> b4811f62: 2 regressed
      regressed  CIS-1.4.2  [critical] pass -> fail
      regressed  CIS-3.2.1  [medium]   pass -> fail
```

Runs 1→2 are identical scans of an unchanged host and correctly show **no drift**,
which matters as much as detecting the change: a drift report that flags spurious
differences between identical scans is unusable.

### Rule 8 — independent self-verification

Three independent checks, none sharing a code path with the thing under test:

1. **Trend recomputed in Python** from raw `GROUP BY outcome` counts and compared
   against the `FILTER`-based aggregate: `PASS: all 4 trend rows independently
   recomputed and matched.`
2. **Trend and drift recomputed in `psql`** using deliberately different SQL — a
   `CASE/SUM` aggregate instead of `FILTER`, and a window-function self-join instead of
   `FULL JOIN`. Both produced identical numbers (16.7 / 16.7 / 27.8 / 16.7, and the
   same 4 drift rows).
3. **Latest run's persisted outcomes re-derived on the host** over a fresh SSH
   connection using the independent command set: **18/18 matched, 0 mismatched.**

### Deviations and open items

- **`backend/queries.py` is not in the Section 2 file listing.** Added as a read-only
  query module rather than putting historical SQL in `engine/`, which Section 5
  reserves for the normalizer and evaluator.
- **Credentials still come from the target dict**, not `secrets_manager` (Section 6).
  Unchanged; still `# TODO`; must close before Phase 7.
- **Legacy-host reachability** (Addendum 4, architecture.md §3.1) remains open.

### Phase 3 addendum — drift across a CHANGED control set, tested for real

The Phase 3 write-up argued from the SQL that `FULL JOIN` + `IS DISTINCT FROM`
handles a control appearing or disappearing between runs. That was reasoning, not
evidence. At the project owner's request it is now demonstrated with real runs.

`run_scan.py` gained a `--controls-dir` flag so a scan can be executed against a
genuinely different control set **without mutating the real 18-control library**. A
temporary 19-control set (the 18 plus one extra, `CIS-5.2.20`) was assembled in a
scratch directory, and two further scans were run:

```
run 5  --controls-dir <19 controls>   ->  19 results
run 6  (default 18 controls)          ->  18 results

  run b4811f62 -> 64ccb53e: 1 appeared
      appeared     CIS-5.2.20   [medium] None  -> error
  run 64ccb53e -> 19b4544d: 1 disappeared
      disappeared  CIS-5.2.20   [medium] error -> None
```

Both directions are handled correctly. An inner join would have silently dropped
both rows.

Two incidental confirmations from the same test, neither of which was the point but
both of which are worth recording:

1. **The added control returned `error`, not a false `pass`.** `CIS-5.2.20` checks
   `MaxAuthTries`, which the normalizer does not produce, so the control/normalizer
   mismatch guard fired exactly as designed. Adding a control without extending the
   normalizer cannot silently produce a passing verdict.
2. **Compliance stayed 16.7% in run 5 despite the extra `error`.** This validates the
   denominator decision: `error` is excluded, so an unevaluatable control does not
   depress the compliance figure and make a tooling gap look like a security
   regression.

`backend/controls/` still contains exactly 18 files and the control-library tests
pass. The `controls` table now holds 19 rows, because `results` from run 5 reference
`CIS-5.2.20` via foreign key — a control definition cannot be deleted while
historical evidence points at it, which is the correct behaviour for an audit trail.
It is absent from the latest run, so current posture is unaffected.

---

## Phase 4 — Exception workflow

**Date:** 2026-08-27
**Status:** ✅ **COMPLETE — all acceptance criteria met with evidence.**

### What was built

- **`backend/exceptions_service.py`** — request, approve, and the two views
  (`open_findings`, `accepted_risks`), plus `expired_exceptions`.
- **`tests/verify_phase4.py`** — workflow, separation-of-duties and expiry harness.

### Core design decision: an exception never rewrites a result

`results` stays append-only and continues to record `fail`. An exception is applied
as a **filter over the view**, not a mutation of the evidence — a suppressed finding
is still a `fail` row, merely presented under "accepted risk" instead of "open
findings".

If approval flipped the stored outcome to `pass`, the compliance percentage would
improve because somebody signed a form, and there would be no surviving record that
the control was ever failing. Verified explicitly: every row in the accepted-risk
view still carries `outcome = 'fail'`.

### Acceptance: request an exception on a failing control ✅

`exception_requested` recorded, row created with `status = 'pending_review'` and
`approved_by = NULL`. A pending exception suppresses nothing — suppression requires
`approved_by IS NOT NULL`.

### Acceptance: distinct approver enforced for high/critical ✅

Enforced in `approve_exception`, which raises `ApprovalError`. Not a comment, not a
convention.

```
PASS  critical: self-approval REFUSED
PASS  critical: 'Aravind ' cannot bypass via case/whitespace
PASS  refused approval left the row unapproved (status=pending_review approved_by=None)
PASS  critical: distinct approver ACCEPTED (approved_by=priya status=accepted_risk)
PASS  approval_date recorded
PASS  already-approved exception cannot be re-approved
PASS  medium: self-approval ALLOWED (spec limits SoD to high/critical)
```

Identity comparison is whitespace-trimmed and case-folded, so `"  Aravind "` cannot
slip past a rule that a naive `==` would have missed.

`medium` self-approval is permitted deliberately: spec Section 3 scopes the rule to
high/critical (*"must differ from requested_by if severity is high/critical"*).
Flagged here because it is a real policy gap someone may want closed — a blanket
four-eyes rule would be defensible, but it is not what the spec says.

**Verified in the database directly, not through the service's return value** (at the
project owner's request — same principle as the Phase 2/3 psql verification). A fresh
self-approval was refused and the row left deliberately unapproved:

```
exception_id  | ba14c227-79af-4cf3-afb5-a2479261a767
control_id    | CIS-5.2.10   (severity high)
status        | pending_review
requested_by  | aravind
approved_by   |
approval_date |

 approved_by_is_null | status_is_pending_review | approval_date_is_null
---------------------+--------------------------+-----------------------
 t                   | t                        | t
```

### Acceptance: excluded from open findings, visible in accepted risk ✅

```
total failing results in run : 15
OPEN FINDINGS                : 14
ACCEPTED RISK                :  1

CONTROL      SEV       RESULT  REQ        APPR    EXPIRES
CIS-1.4.2    critical  fail    aravind    priya   2026-09-03 15:39:51
```

`open + accepted == total failing` is asserted every time the view is rendered, so a
finding can neither vanish nor be double-counted.

### Acceptance: returns to `fail` after expiry, on a subsequent run ✅

Demonstrated with a real clock, a real row and a real scan — the expiry check was
never called in isolation.

```
10:10:09Z  exception created on CIS-3.1.1 (critical), expiry_date 10:12:10Z (+120s)
           requested_by aravind, approved_by priya
10:10:12Z  OPEN FINDINGS 13  |  ACCEPTED RISK 2   <- CIS-3.1.1 suppressed
10:12:37Z  wall clock passes expiry; REAL scan run against the live VM
10:13:11Z  OPEN FINDINGS 14  |  ACCEPTED RISK 1   <- CIS-3.1.1 is an open finding again

expired (approved but lapsed) exceptions: 1
  CIS-3.1.1  [critical] approved_by=priya  expired 2026-08-27 15:42:10
```

CIS-1.4.2's 7-day exception remained active throughout, so the transition is
attributable to expiry rather than to something global.

**No scheduled job is involved.** Expiry is evaluated at query time against the
current clock, so an exception lapses on its own. There is no cron entry to forget to
run and no state to reconcile — the mechanism cannot silently fail closed *or* open.

Three-way suppression matrix confirmed in raw SQL:

```
 control_id | severity | outcome | suppressed
 CIS-1.4.2  | critical | fail    | t     <- approved, unexpired
 CIS-3.1.1  | critical | fail    | f     <- approved, EXPIRED
 CIS-5.2.10 | high     | fail    | f     <- requested, NEVER APPROVED
```

### Spec discrepancy: `audit_log.event_type` vocabulary is incomplete in Section 3

CLAUDE.md Section 3's inline comment lists
`scan_started|scan_completed|control_evaluated|exception_approved|credential_used|report_exported`.
The exception workflow emits two events that comment does not mention.

Verified against both the codebase and the live table:

| event_type | in Section 3's comment? | rows |
|---|---|---|
| `scan_started` | yes | 7 |
| `scan_completed` | yes | 7 |
| `control_evaluated` | yes | 127 |
| `exception_requested` | **no** | 3 |
| `exception_approved` | yes | 2 |
| `exception_approval_denied` | **no** | 1 |
| `credential_used` | yes — not yet emitted (needs secrets_manager) | 0 |
| `report_exported` | yes — not yet emitted (Phase 6) | 0 |

The authoritative list now lives in the `AuditLog` docstring in
`backend/models/schema.py` and is to be kept current as events are added.
**CLAUDE.md itself was left untouched** — the project owner tracks its sha256 for
sync purposes, so editing it here would desync that. The Section 3 comment should be
updated on their side when convenient.

`exception_approval_denied` is recorded rather than merely refused in memory: an
attempted separation-of-duties violation is security-relevant, and this is the audit
trail's only record that someone tried to self-approve a high/critical finding.

No CHECK constraint is placed on `event_type`. An audit log that rejects an
unrecognised event is an audit log that can silently lose evidence when a new event
type ships ahead of a migration.

### Rule 8 — independent self-verification

Every claim above was re-checked in raw `psql` rather than through
`exceptions_service.py`'s return values: the refused row's `approved_by`/`status`/
`approval_date`, the three-way suppression matrix (computed with an inline `EXISTS`
subquery rather than the service's SQL), the event-type census, and the
open/accepted/total arithmetic.

### Deviations and open items

- **`backend/exceptions_service.py`** is not in the Section 2 file listing.
- **`exceptions` is not append-only** — unlike `results` and `audit_log`, approval
  mutates the row in place (`status`, `approved_by`, `approval_date`). The spec's DDL
  models it that way, and the immutable trail of who requested and who approved lives
  in `audit_log`. Test rows were also deleted from it during verification, which
  would be prohibited on the append-only tables.
- **Credentials still not behind `secrets_manager`** (Section 6). Must close before
  Phase 7.
- **Legacy-host reachability** (architecture.md §3.1) remains open.

---

## Phase 5 — AWS collector

**Date:** 2026-08-27
**Status:** ⚠️ **Code complete, all checks pass — but verified against `moto` only.
This is NOT the standard Phases 1-4 were held to, and Phase 5 stays OPEN until it is
re-validated against a real AWS account.** See architecture.md 3.6.

### What was built

- **6 AWS control YAMLs** (`AWS-1.4`, `AWS-1.5`, `AWS-2.1.5`, `AWS-2.2.1`, `AWS-3.1`,
  `AWS-5.2`) — exactly the set listed in Section 4, no more.
- **`backend/collectors/aws_collector.py`** — boto3 **client interface only**.
- **AWS parsers appended to `backend/engine/normalizer.py`**, with provider dispatch
  added to `normalize()`.
- **`tests/fixtures/aws_scenario_a.py`** — the scenario the collector was built
  against.
- **`tests/fixtures/aws_scenario_b.py`** — an independently written scenario for
  rule 8.
- **`tests/verify_phase5.py`** — runs both scenarios and asserts the Section 1
  client-only constraint.

### The architectural claim, now tested rather than asserted

`backend/engine/evaluator.py` is **byte-identical to its Phase 4 state**. Adding an
entire second collector type required zero evaluator changes:

```
git diff HEAD -- backend/engine/evaluator.py   ->  (no output)
grep -niE 'collector_type|aws|boto' evaluator.py
   -> only two hits, both in the docstring predicting exactly this
```

Provider dispatch happens in `normalize()` and nowhere else. This is the strongest
available evidence for the extensibility claim in Section 5, because until Phase 5
there was only one provider and the boundary had never actually been loaded.

Multi-resource evaluation was also exercised for the first time. The Linux target is a
single host; AWS produced 12 resources in scenario A (1 account, 4 buckets, 5 security
groups, 2 volumes) and the evaluator's `applies_to` filtering fanned each control out
across the right ones without modification.

### Section 1 constraint: boto3 client interface only

Asserted mechanically, not by inspection, in `tests/verify_phase5.py`:

```
PASS  no boto3.resource( in aws_collector.py
PASS  session.client( is used
PASS  no mutating API calls in the collector  ([])
```

The mutating-call check greps for `create_/delete_/put_/update_/modify_/terminate_/
attach_/detach_/revoke_/authorize_` and finds none, which also evidences the
read-only claim: the collector needs `SecurityAudit` / `ViewOnlyAccess` and nothing
more.

### Scenario A (built against) — all assertions pass

```
resources normalized: {'aws_account': 1, 's3_bucket': 4, 'security_group': 5, 'ebs_volume': 2}
AWS-1.4 pass | AWS-1.5 fail | AWS-3.1 fail
AWS-2.1.5  locked pass / open fail / partial fail / trail-logs fail
AWS-5.2    0.0.0.0/0:22 fail / ::/0:22 fail / 203.0.113.0/24 pass
AWS-2.2.1  encrypted 1, unencrypted 1
```

`s3:GetPublicAccessBlock` on a bucket with no configuration raises
`NoSuchPublicAccessBlockConfiguration`. The collector records that as evidence rather
than raising, and the normalizer maps it to all four flags `False` — **not** to
`UNAVAILABLE`. A bucket with no block configuration is the strongest possible failure
of this control; reporting `error` for a bucket that is verifiably wide open would be
exactly backwards.

### Scenario B (independent) — rule 8

Written without reference to set A: no shared helpers, no shared constructors,
different region, different names, different values. Duplication between the two
fixture files is deliberate — two scenarios built from shared code can agree with each
other about something neither AWS nor the collector would ever produce.

Set B deliberately exercises shapes set A never produces, because a cross-check that
only repeats the first scenario verifies nothing beyond determinism:

| Case | Why it matters | Result |
|---|---|---|
| SG with port **range** 20-30 | a `FromPort == 22` test misses this entirely | fail ✅ |
| SG with `IpProtocol "-1"` | all protocols/all ports; `FromPort`/`ToPort` absent from the response | fail ✅ |
| SG open to world on **443** | proves the parser is not just flagging any `0.0.0.0/0` | pass ✅ |
| Multi-region trail, logging, `All` selectors | the **passing** direction of AWS-3.1, which set A never reaches | pass ✅ |
| Multi-region trail that is **stopped** | must not be the trail chosen | correctly ignored ✅ |

All assertions pass, 0 mismatches.

### ⚠️ Rigor reduction versus Phases 1-4 — stated plainly

Every Phase 5 result above came from talking to a Python library, not to AWS.

Phases 1-4 ran against a live VM over real SSH, and that is exactly how the three
parsing traps in architecture.md 2.1 were found. A mock returns whatever its author
expected the API to return — which, in the `systemctl is-active` case, would have been
the wrong answer that started that whole investigation. The equivalent surprises
almost certainly exist in the real AWS API surface, and this build has not been in a
position to meet them.

**Specific named gap: moto does not model the root user at all.**
`AccountMFAEnabled` and `AccountAccessKeysPresent` are fixed at `0` with no way to
change them — verified directly:

```
enable_mfa_device(UserName="root")  -> NoSuchEntityException
create_access_key(UserName="root")  -> NoSuchEntityException
AccountMFAEnabled stays 0; AccountAccessKeysPresent stays 0
```

Consequently **AWS-1.5 is only ever exercised in the `fail` direction and AWS-1.4 only
in the `pass` direction.** AWS-1.4's pass is actively misleading: it passes because
moto cannot represent a root access key, not because an account was checked and found
clean.

Parser-level tests in `tests/verify_phase5.py` cover all four MFA/key combinations and
the `AccessDenied -> error` path, confirming the **logic** is right. A passing code
path is not an observation about an account, and this log does not treat it as one.

Also unverified under moto: pagination (real accounts paginate `ListBuckets`,
`DescribeVolumes`, `DescribeSecurityGroups`; moto returns single pages), IAM
permission scoping (moto does not enforce `SecurityAudit`, so a call the tool is not
actually permitted to make still succeeds), multi-region behaviour, eventual
consistency, throttling and partial failures.

**Required to close this:** run the full Phase 5 verification against a real AWS test
account containing deliberately misconfigured resources — the cloud equivalent of the
demo VM — and reconcile against a hand-built answer key the way `EXPECTED_POSTURE.md`
was reconciled for Linux.

### Schema change: `framework_mappings` CIS key

Requiring the literal key `cis_linux_v8` on an AWS control would have meant either
filing an AWS Foundations Benchmark number under a Linux-labelled key — actively
misleading in an exported report — or dropping the CIS mapping for AWS entirely. The
validator now requires **exactly one** of `cis_linux_v8` / `cis_aws_v3`, plus
`nist_csf`, `soc2` and `cert_in_marker` as before, and rejects unknown mapping keys.

Tests assert every Linux control carries `cis_linux_v8` and never `cis_aws_v3`, and
vice versa, so the two sets cannot drift into each other's namespace.

### Deviations and open items

- **`backend/collectors/aws_collector.py`** is in the Section 2 tree; the fixture
  modules and `tests/verify_phase5.py` are not.
- **`--controls-dir`** was added to `run_scan.py` during the Phase 3 addendum and is
  reused here.
- **AWS credentials come from boto3's default chain**, not `secrets_manager`
  (Section 6) — the same deferral as the SSH collector's target dict. Marked `# TODO`.
  Must close before Phase 7.
- **Phase 5 is OPEN** pending real-account validation.
- **Legacy-host reachability** (architecture.md 3.1) remains open.

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
