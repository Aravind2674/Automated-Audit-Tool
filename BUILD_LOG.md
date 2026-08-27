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

### ⚠️ TRACKED OPEN ITEM — Phase 5 real-AWS validation (logged exception)

**2026-08-27.** The project owner granted an explicit, logged exception to proceed to
Phase 6 while Phase 5 remains ⚠️ rather than ✅.

**This does not close Phase 5.** Real AWS account validation moves from "blocks
Phase 6/7" to "must close before final demo/submission". The requirement is unchanged
and is restated here so it cannot be lost between phases:

> Re-run the full Phase 5 verification against a real AWS test account containing
> deliberately misconfigured resources — the cloud equivalent of the demo VM — and
> reconcile the results against a hand-built answer key, exactly as
> `EXPECTED_POSTURE.md` was reconciled for Linux. Until then the AWS findings are
> mock-derived and are not trustworthy to the standard of the Linux findings.
> See `architecture.md` §3.6 for the full gap analysis, including the moto root-user
> limitation that leaves AWS-1.4 and AWS-1.5 each exercised in only one direction.

Anything this tool reports about AWS before that validation must carry the caveat.
The Phase 6 dashboard and PDF export therefore label AWS findings explicitly rather
than presenting them alongside Linux findings as equally evidenced.


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

---

## Phase 6 — Dashboard + report export

**Date:** 2026-08-27
**Status:** ✅ **COMPLETE — all acceptance criteria met with evidence.**

### What was built

- **`backend/api/main.py`** — read-only FastAPI app: `/api/health`, `/api/dashboard`,
  `/api/findings`, `/api/reports/pdf`.
- **Dashboard queries appended to `backend/queries.py`** — summary, per-domain,
  per-severity, exceptions with expiry, per-finding report rows.
- **`backend/reports/generator.py`** — reportlab PDF export, framework-mapped, with
  verbatim per-finding evidence.
- **`frontend/`** — Next.js 15 + React 19 + Tailwind dashboard
  (`components/Dashboard.tsx`), including an inline-SVG compliance trend chart.
- **`tests/verify_phase6.py`** — 40 checks in the current database state. The count is data-dependent (it loops over domains, exceptions and trend rows), so it grows as more runs and exceptions accumulate rather than being fixed.

### Section 10 install record

| Package | Version | Method | Result |
|---|---|---|---|
| Node.js LTS | 24.19.0 | **portable ZIP** from nodejs.org, SHA-256 verified against the published `SHASUMS256.txt`, extracted to `C:\Users\deepa\nodejs`, added to **user** PATH | ✅ |
| npm | 11.17.0 | bundled with the above | ✅ |
| fastapi / uvicorn / reportlab / pypdf / httpx | current | pip into `venv/` | ✅ |

**`winget install OpenJS.NodeJS.LTS` failed** and is worth recording, because it is the
obvious command and it does not work here:

```
The installer will request to run as administrator. Expect a prompt.
You cancelled the installation.
Installer failed with exit code: 1602
```

`1602` is "user cancelled". The Node MSI raises a UAC prompt that a non-interactive
session cannot answer — unlike VirtualBox, Vagrant and PostgreSQL, whose elevation
winget brokered itself. The official portable ZIP needs no elevation at all and was
checksum-verified before use, which is the better path on a machine where an
interactive UAC prompt may not be available.

### Acceptance criterion 1 — dashboard shows overall %, per-domain, exceptions with expiry, drift chart ✅

The dashboard was **rendered in a real browser** and its DOM read back, rather than
assumed from the code:

```
OVERALL COMPLIANCE  16.7%   (3 passed of 18 scored)
OPEN FINDINGS       14      (15 failing, 1 accepted risk)
ACCEPTED RISK       1
OPEN FINDINGS BY SEVERITY   Critical 1 · High 4 · Medium 7 · Low 2

COMPLIANCE BY DOMAIN
  access_control 1/1/0 100%      hardening 2/0/2 0%
  authentication 5/0/5 0%        logging   3/0/3 0%
  filesystem     4/1/3 25%       network   3/1/2 33.3%

COMPLIANCE TREND (7 runs plotted)
  16.7 · 16.7 · 27.8 · 16.7 · 16.7 · 16.7 · 16.7

EXCEPTIONS
  CIS-3.1.1  critical  aravind → priya  2026-08-27T15:42:10  expired — finding reopened
  CIS-1.4.2  critical  aravind → priya  2026-09-03T15:39:51  active · 6d left
```

All four required elements are present. The exceptions table shows expiry dates *and*
distinguishes an expired exception from an active one — the Phase 4 expiry behaviour
surfaced in the UI rather than only in the database.

### Acceptance criterion 2 — PDF includes per-finding evidence, mapped to CIS/NIST/SOC2/CERT-In ✅

Every finding gets a framework mapping table and its evidence:

```
PASS  framework column 'CIS Linux v8' present
PASS  framework column 'NIST CSF' present
PASS  framework column 'SOC 2' present
PASS  framework column 'CERT-In' present
PASS  every finding's control_id appears in the PDF
```

The CIS column is labelled per control — `CIS Linux v8` for the Linux set,
`CIS AWS v3` for the AWS set — rather than filing an AWS benchmark number under a
Linux-labelled heading.

### Rule 8 — dashboard figures cross-checked against direct DB queries

Per the project owner's instruction, **every number is checked against the database,
not against the API's own response.** The independent SQL is written in a different
style from `backend/queries.py` — `CASE/SUM` aggregates and correlated subqueries
instead of `FILTER` and `EXISTS` — so agreement means the figures are right rather
than merely that one code path is deterministic.

29 dashboard checks in the current database state, all passing: total/passed/failed/errored/manual_review,
open_findings, accepted_risk, `open + accepted == failed`, compliance % recomputed
from raw counts, all six per-domain rows, per-severity counts (and that they sum to
open_findings), the exception id set, each exception's `expired` flag and
`expiry_date`, every trend row's pass/fail counts, and that the trend covers every
completed run.

Additionally, the values **rendered in the browser DOM** were compared against `psql`
output directly — a third path that touches neither the API's SQL nor the harness's.
All matched.

### The PDF evidence rule — and proving the check has teeth

`generator.py` renders `json.dumps(evidence)` of the `evidence` JSONB column exactly
as stored. It does not re-run any check, re-derive any value, or paraphrase evidence
into prose.

This is not fussiness. A report that regenerates its own evidence is not evidence — it
is a second opinion that happens to agree, and it diverges silently the moment the
audited host changes. An auditor reading a three-month-old finding must see what was
observed *then*.

The harness extracts the evidence blocks from the rendered PDF, parses them back, and
asserts a whitespace-normalised match against the JSONB read straight from PostgreSQL:

```
PASS  every finding's evidence JSON appears verbatim (18/18)
PASS  a tampered evidence blob does NOT match the PDF (check has teeth)
```

That second check matters as much as the first. A substring assertion that always
succeeds proves nothing, so the harness deliberately mutates one evidence blob and
confirms the altered version is **not** found in the PDF. Without it, the verbatim
check could be silently vacuous.

### AWS caveat surfaced in the product, not just the docs

Both the dashboard and the PDF carry the Phase 5 caveat: AWS findings are labelled by
provider and accompanied by a notice that they are moto-derived and not evidenced to
the standard of the Linux findings. A compliance report that presented the two side by
side as equally evidenced would misrepresent both.

### Deviations and open items

- **No authentication.** Spec Section 1 allows session-based auth for the MVP, and
  Phase 6's acceptance criteria concern the dashboard and export only, so none was
  built. **The API must not be exposed beyond localhost until it exists.** CORS is
  restricted to `localhost:3000` and every endpoint is read-only, but that is a
  mitigation, not a substitute. Carried as an open item.
- **`backend/api/main.py`, `tests/verify_phase6.py`** are new; `/api` and
  `/reports/generator.py` are in the Section 2 tree.
- **`audit_log` records no `report_exported` event yet.** Section 3 lists that event
  type and Phase 7's acceptance requires report export to be audited. Deliberately
  left for Phase 7, where the audit-log sweep belongs, rather than half-wired here.
- **Screenshot not captured** — the browser pane is not displayable in this session.
  The rendered DOM text was extracted and verified instead, which is stronger evidence
  than an image since it is the actual rendered content.
- **Credentials still not behind `secrets_manager`** (Section 6). Must close before
  Phase 7.
- **Phase 5 real-AWS validation** remains a tracked open item.

---

## Phase 7 — Audit log + security review pass + session auth

**Date:** 2026-08-27
**Status:** ✅ **COMPLETE — all acceptance criteria met with evidence.**

### ⚠️ Spec sync failure at the start of this phase

The project owner reported CLAUDE.md updated to sha256 `61011adb…` / 465 lines, adding
a session-auth requirement to Phase 7. **That version never reached this machine.** The
file on disk was `6c02e1c1…` / 451 lines, last written 15:49, and its Phase 7 text
contained no mention of auth or sessions.

Work proceeded anyway because the owner's chat message stated the requirements
unambiguously — session auth on scan-trigger/exception/report-export, the
`secrets_manager` migration, and a real rejected curl. The unread 14 lines remain
unverified; the owner was asked to confirm nothing else was in them. This is the
second sync failure in the project (Section 11 was the first), and the hash check is
what caught both.

### What was built

- **`backend/secrets_manager.py`** — Fernet credential store (spec Section 6).
- **`backend/auth/service.py`** — bcrypt passwords, server-side sessions.
- **`backend/bootstrap.py`** — create users, import the demo VM key encrypted.
- **`backend/api/main.py`** — auth dependency plus the state-changing endpoints:
  `POST /api/scans`, `POST /api/exceptions`, `POST /api/exceptions/{id}/approve`.
- **`backend/models/schema.py`** — `credentials`, `users`, `sessions` tables.
- **`frontend/components/Login.tsx`** and a login gate in the dashboard.
- **`tests/verify_phase7.py`** — 51 checks.

### Acceptance: auth enforced, proved with real unauthenticated HTTP ✅

Not middleware-in-code, and not FastAPI's in-process TestClient. Real requests to a
running server:

```
unauthenticated GET  /api/dashboard              -> 401
unauthenticated GET  /api/findings               -> 401
unauthenticated GET  /api/reports/pdf            -> 401
unauthenticated GET  /api/auth/me                -> 401
unauthenticated POST /api/scans                  -> 401
unauthenticated POST /api/exceptions             -> 401
unauthenticated POST /api/exceptions/{id}/approve-> 401
unauthenticated GET  /api/health                 -> 200   (discloses no compliance data)
forged session cookie                            -> 401
login with wrong password                        -> 401
login with correct password                      -> 200, HttpOnly + SameSite cookie
authenticated GET /api/dashboard                 -> 200
after logout, GET /api/dashboard                 -> 401
```

**Verified in a browser too:** `document.cookie` returns empty while the session is
active — HttpOnly is doing its job, so an XSS flaw in the dashboard cannot exfiltrate
the session. The login form was exercised through its real `onSubmit` handler and
transitioned the page to the dashboard as `aravind`.

Scope note: the spec named the three state-changing endpoints. Enforcement was applied
to the read endpoints as well, because an unauthenticated `/api/dashboard` discloses
which controls are failing on which resources with evidence attached — a target list.
Going broader than asked is flagged here rather than assumed to be wanted.

**Identity is taken from the session, never from the request body.** The exception
endpoints set `requested_by`/`approved_by` from the authenticated user. Accepting them
from the body would let a caller claim to be someone else and defeat separation of
duties with a text edit. Confirmed through the API: `aravind` self-approving a `high`
control gets **403**; `priya` approving the same exception gets **200**.

### Acceptance: credentials behind secrets_manager — Phase-1 TODO closed ✅

The demo VM's SSH key is stored as Fernet ciphertext and fetched at scan time:

```
POST /api/scans {"mode":"live"}
  -> {"run_id":"75aed5d6-...","results":18,"outcomes":{"fail":15,"pass":3},
      "compliance_pct":16.7}

credential_used | aravind | ok | {"target_id": "demo-ubuntu-vagrant"}
```

A live scan over SSH, with the key decrypted from the store. Checks:

```
PASS  secrets_manager.py is the ONLY module that decrypts
PASS  collectors never read the credentials table directly
PASS  ssh_collector calls secrets_manager.get_credential
PASS  the Phase-1 credential TODO is closed
PASS  credentials table holds ciphertext only, no PEM markers
PASS  passwords are bcrypt hashes, not reversible
PASS  credential_used never records the credential value
PASS  credential_used records the target_id
```

Key material is never written to disk. Paramiko is handed the key in memory rather
than via `key_filename`, because writing it to a temp file to satisfy that parameter
would leave plaintext key material on the filesystem — the exact thing the encrypted
store exists to prevent.

### Acceptance: audit-log sweep ✅

Every event type present, and all four Section 7 state-changing actions recorded:

```
credential_used    | aravind | ok            | {"target_id": "demo-ubuntu-vagrant"}
exception_approved | priya   | accepted_risk | {"severity":"high","control_id":"CIS-5.4.1",...}
report_exported    | aravind | ok            | {"bytes":43984,"format":"pdf","run_id":...}
scan_started       | aravind | ok            | {"mode":"live","controls":24}
```

Login successes and failures are audited too — a brute-force attempt is invisible
without the failures.

### Bug found and fixed: report_exported sat outside its run's trail

The first version of the export endpoint minted a **fresh** `correlation_id` while
still tagging the row with the `run_id`. An investigator following a run's
correlation_id would never have seen that a report of it was taken. Fixed to reuse the
run's correlation_id; every run after the fix is clean.

**The bad row was NOT deleted or rewritten.** `audit_log` is append-only, so run
`75aed5d6` permanently carries two correlation_ids. Being unable to erase one's own
mistake is the guarantee working correctly, so it is documented in
`tests/verify_phase7.py` as a known pre-fix anomaly with the reason, and the harness
asserts that no *new* run has the problem rather than pretending the old one does not.

### Bug found and fixed: Phase 5 broke the live-scan path

`required_sources(controls)` returned the AWS sources added in Phase 5, which the SSH
collector has no command mapping for:

```
CollectorError: no command mapping for source(s):
  ['cloudtrail','ebs_volume','iam_root','s3_bucket','security_group']
```

Every live scan — CLI and API — would have failed since Phase 5. It went unnoticed
because Phases 6 and 7 exercised the cached path, which skips collection entirely.
Fixed by filtering to controls whose `applies_to` includes `linux_server`.

**This is the strongest argument in the project for Section 9's insistence on running
things rather than reasoning about them.** The code looked right, every existing test
passed, and the break was only visible by actually triggering a live scan.

A second, smaller one: `paramiko.DSSKey` no longer exists in Paramiko 5.0.0, and
naming it unconditionally raised `AttributeError` for *every* key type including RSA.
Key classes are now resolved by name with `getattr`.

### Acceptance: hardcoded-secrets grep returns nothing ✅

```
PASS  no hardcoded secrets in tracked source        ([])
PASS  .env is gitignored
PASS  .env is NOT tracked by git
PASS  no key material tracked in git                ([])
PASS  no UPDATE/DELETE against results or audit_log in the codebase
```

Patterns cover assigned literal secrets, embedded private keys, AWS access key ids,
hardcoded Fernet keys and DB URLs with inline passwords, across `.py/.ts/.tsx/.js/
.yaml/.sh/.json` in backend, tests, frontend and demo-environment.

### Rule 8

Auth enforcement is proved over real HTTP against a running server — a dependency
attached to the wrong router, a middleware bypassed by route ordering, or a server
running stale code would all pass a code review and fail this. The stale-code case
was real: the first check run hit a server still running pre-auth code and returned
200, which is exactly what the live-HTTP approach is for.

`tests/verify_phase6.py` now authenticates through the real `/api/auth/login` rather
than disabling the dependency — a test that turns auth off to reach what it is testing
stops verifying the deployed configuration.

### Deviations and open items

- **`backend/auth/service.py`, `bootstrap.py`, `secrets_manager.py`** — Section 2 lists
  `/auth` and `secrets_manager.py`; `bootstrap.py` is new.
- **`credentials`, `users`, `sessions` tables** are not in the Section 3 DDL. Section 6
  requires a credentials table without specifying its shape; users/sessions follow from
  the Phase 7 auth requirement.
- **Session cookie has `secure=False`** because the demo runs over plain HTTP on
  localhost. **This MUST become `True` behind TLS** — a session cookie without the
  Secure flag is sent over unencrypted connections. Marked in the code.
- **No password-reset, lockout, or rate-limiting on login.** Failures are audited, but
  nothing throttles them. Out of scope for the MVP; a real deployment needs it.
- **No CSRF token.** `SameSite=lax` blocks the common cross-site POST case, which is
  adequate for a localhost MVP but is not a substitute for a token.
- **A live scan runs synchronously in the request.** It takes ~20s and will block a
  worker; a real deployment wants a job queue.

---

## Phase 8 — Scale validation (spec Section 7a)

**Date:** 2026-08-27
**Status:** ✅ **COMPLETE — the 50-host/resource NFR is met, with one real defect found and fixed.**

The original problem statement requires handling "at least 50 simulated
hosts/resources without redesign". Every run before this used exactly one Linux
target, so the requirement had zero evidence either way.

### What was built

- **`execute_multi_target_scan()`** in `backend/run_scan.py` — scans N targets in one
  run, writing one `runs` row and results for every target.
- **`tests/verify_phase8.py`** — both halves, real timings, rule-8 DB verification.

**What did NOT have to change is the point.** The normalizer, evaluator, control
schema, persistence layer and dashboard queries are all untouched. `applies_to`
already fans controls across whatever resources it is handed, so 50 targets needed an
orchestration loop — not a redesign. That is the NFR's actual wording satisfied.

### AWS: 153 resources

```
resources normalized : 153   (50 buckets + 51 security groups + 50 volumes + 1 account)
results persisted    : 155
outcomes             : {'pass': 86, 'fail': 69}
collect (moto)       : 0.86s
evaluate             : 0.00s
persist              : 0.04s
TOTAL                : 0.08s
```

Resources alternate compliant/non-compliant by construction, so the run produces a
genuine mix rather than a uniform block — a scale run where every resource shares one
outcome would not exercise aggregation meaningfully.

### Linux: 50 targets — and the honesty caveat

```
targets              : 50
resources normalized : 50
results persisted    : 900
collect (SSH, seq.)  : 128.42s
evaluate             : 0.06s
persist              : 0.12s
TOTAL                : 128.64s
per-target average   : 2.57s
```

> **These are 50 target entries pointing at the SAME demo VM**, with distinct
> `target_id`s and therefore distinct `resource_id`s
> (`linux_server:demo-ubuntu-vagrant`, `…-clone-001` … `…-clone-049`).
>
> This validates **orchestration, credential handling, database writes and dashboard
> aggregation across 50 targets. It does NOT validate 50 independent real security
> postures** — there is one host underneath, so all 50 produce identical findings by
> construction. Provisioning 50 real VMs is impractical on this hardware; the
> substitution is deliberate and must not be blurred in any writeup or demo.

**A real behaviour surfaced during setup:** the first attempt failed with
`SecretsError: no credential stored for target_id '…-clone-001'`. `secrets_manager`
correctly refuses to serve a credential for an unregistered target. Fixed by
registering a credential per target — which is exactly what onboarding 50 real hosts
would involve, and exercises the credential store at scale as a side effect (50
`credential_used` audit rows, one per target).

### Timing verdict: the synchronous-execution open item is now a REAL problem

Section 7a asked whether synchronous scan execution is a genuine problem at this scale
or still theoretical. The measurement answers it:

| Stage | Time | Share |
|---|---|---|
| SSH collection (sequential) | 128.42s | **99.8%** |
| Evaluation | 0.06s | 0.05% |
| Persistence | 0.12s | 0.09% |

**Collection dominates completely.** Evaluation and persistence are effectively free —
0.18s combined for 900 results — so the engine scales fine. The problem is entirely
that 50 sequential SSH sessions take over two minutes inside one synchronous HTTP
request.

That exceeds the default idle timeout of most reverse proxies and load balancers
(commonly 30–60s). `POST /api/scans` with 50 targets would return a gateway timeout to
the browser **while the scan continued running server-side** — the worst outcome,
because the user sees failure and may retry, doubling the load against the same hosts.

Promoted from 🟠 to 🔴. Two fixes, neither in scope here: run collection concurrently
(the per-host work is independent and I/O-bound, so a thread pool should give close to
linear speed-up), and return `202 Accepted` with a run_id immediately, polling for
completion.

### Defect found and fixed: unbounded drift payload

The dashboard shipped **every** drift row to the browser. At 50 targets:

```
BEFORE:  187,308 bytes total  |  drift_since_previous_run = 192,892 bytes (97%)
AFTER :   41,017 bytes total  |  drift_since_previous_run =  36,252 bytes
```

Drift between two runs with different target sets produced 1,055 rows and grew
linearly with target count. The API still answered in 0.1s, so this was never a
failure — but an unbounded list to a browser is a defect waiting to become one.

Capped at 100 rows **per category**, with `drift_total` and per-category
`drift_counts` still returned in full so nothing is hidden. The UI renders
"1055 changes (900 appeared, 155 disappeared) — showing first 100 per category".

This is the kind of thing only a scale run finds: at one target the drift list is a
handful of rows and looks perfectly reasonable.

### Rule 8 — independent verification

Every claim re-checked in `psql`, not through the harness's own SQLAlchemy:

```
   run    | triggered_by | results | distinct_resources | wall_clock_s
 755611ef | phase8-scale |     155 |                153 |         0.39
 c1c65ede | phase8-scale |     900 |                 50 |       128.70

 single_target_results | fifty_target_results | ratio
                    18 |                  900 |  50.0
```

Exactly **50.0×** the data, and the DB's own wall-clock (128.70s) matches the
harness's measurement (128.64s). Also confirmed: all 900 results carry evidence, one
correlation_id for the whole run, 50 distinct `resource_id`s, and 50 `credential_used`
rows.

Dashboard aggregation at 900 results: 6 domain rows totalling 900
(authentication 250, filesystem 200, logging 150, network 150, hardening 100,
access_control 50), severity counts summing correctly (critical 99, high 199,
medium 350, low 100), compliance 16.7% — identical to the single-target figure, which
is exactly right given it is the same VM 50 times.

### Deviations and open items

- **`execute_multi_target_scan` is not exposed via the API.** `POST /api/scans` still
  scans the single configured target. Multi-target scanning is available through the
  function and the Phase 8 harness only; wiring it to the endpoint should wait until
  the synchronous-execution problem above is fixed, since a 50-target scan is exactly
  the request that would time out.
- **50 clone credentials remain in the `credentials` table.** Harmless (all the same
  demo VM key) but they are visible in `bootstrap.py list`. Left in place because
  deleting them would break the audit trail's reference to targets that were really
  scanned.

### Phase 8 addendum — two more defects the scale run exposed

Running the full regression *after* the scale runs existed in the database surfaced
two further problems. Both had been latent since Phase 4 and were invisible at one
target.

**1. App bug — `accepted_risks()` double-counted findings.**

The query was a plain `JOIN` from `results` to `exceptions`, so a finding covered by
more than one active exception produced **one row per exception**. Nothing prevents
several exceptions covering the same `(control_id, resource_id)` — a repeated request,
overlapping approvals, or a re-request before the previous one lapsed all do it, and
the Phase 4 harness had itself created three for `CIS-1.4.2` across its runs.

The dashboard's accepted-risk count was inflated accordingly, and the
`open + accepted == total failing` invariant broke:

```
BEFORE:  total failing 45  |  OPEN 43  |  ACCEPTED 4   -> 43 + 4 != 45
AFTER :  total failing 45  |  OPEN 43  |  ACCEPTED 2   -> 43 + 2 == 45
```

Fixed with `DISTINCT ON (control_id, resource_id)` keeping the exception that expires
**last**, since that is the one actually governing how long suppression lasts.

Worth noting the blast radius was limited: the dashboard *summary* counts used
`count(*) FILTER (... EXISTS ...)`, which cannot multiply rows and was always correct.
Only the itemised accepted-risk list was wrong — so the headline number and the list
beneath it disagreed, which is arguably worse than both being wrong.

**2. Harness flaw — suppression compared by `control_id` alone.**

`verify_phase4.py` checked that suppressed controls were absent from open findings by
comparing control ids. That was correct while every run had exactly one target, and
became wrong the moment a run covered several: in the scale runs `CIS-1.4.2` is
legitimately **suppressed** on `linux_server:demo-ubuntu-vagrant` and **open** on
`…-clone-001`, because the exception was only ever granted for the first. The check
read that correct behaviour as a failure.

Now compares `(control_id, resource_id)` pairs, and `open_findings()` returns
`resource_id` so it can. Suppression is per finding, and a finding is a control
against a specific resource.

**Why both matter beyond the fix:** neither is reachable with one target. The Phase 8
scale run was worth doing for the NFR evidence alone, but it also functioned as the
first test of assumptions that had quietly been baked in since Phase 4 — that a
finding maps to at most one exception, and that a control maps to one resource.

### Addendum — async `POST /api/scans` (Section 7 addendum, implemented)

`CLAUDE.md` was replaced with the byte-verified `CLAUDE_SYNC_v2.md` plus the owner's
addendum block, and the result verified: sha256 `17605119…`, **527 lines, exact
match**. CLAUDE.md and the sync file are now identical in substance; a fresh clone
finally carries Phase 8 and this addendum.

**What changed.** `POST /api/scans` now fires and returns. The `runs` row is created
synchronously with `status='running'`; collection and evaluation run in a FastAPI
`BackgroundTask` in the same process. No Celery, no Redis, no new infrastructure —
the right weight for this deployment. The endpoint returns **202 Accepted**, not 200,
because the work is accepted rather than finished.

`GET /api/scans/{run_id}` was added so a caller can poll, and `/api/dashboard` now
returns `active_runs` so in-flight scans are visible rather than the UI looking idle.

**Latency, measured over real HTTP:**

| Trigger | Before (synchronous) | After (202) |
|---|---|---|
| 1 live target | ~14s | **0.51s** |
| 50 live targets | ~128s (past proxy timeouts) | **0.84s** |

**Rule 8 — the transition watched live, not just the end state.** Polling the database
while a 50-target scan ran:

```
t+7s    status=running  results=0  creds_used=0
t+35s   status=running  results=0  creds_used=3
t+70s   status=running  results=0  creds_used=18
t+112s  status=running  results=0  creds_used=35
...
        status=completed results=900 creds_used=50
final:  wall_s 152.76 | results 900 | resources 50
```

`credential_used` climbing 3 → 50 while `status='running'` is the evidence the work is
genuinely progressing in the background rather than the row simply being stale. The
client had its response in 0.84s of that 152.76s.

**Re-proven in the browser**, as the addendum requires. The Run New Scan button round
trip was **984ms**; the dashboard showed
`Scan 6207647b started (1 target) — running in the background.` and a live banner
`N scans running … figures below are from the last completed run and will update
automatically`. The button message deliberately says *started*, not *completed* —
claiming a finished scan on a 202 would be a lie the user could check.

The dashboard polls every 4s only while `active_runs` is non-empty, reusing the same
refresh path the button already used. A single refetch would have shown stale figures
and an idle-looking dashboard during a 152s scan — exactly the "silently block or
hang" appearance the change exists to remove.

### Two defects found while re-proving

**1. Orphaned `running` rows survive a restart.** Restarting uvicorn mid-scan left run
`55df169b` stuck on `running` permanently, and the dashboard reported it as an active
scan indefinitely. A run that never leaves `running` is indistinguishable from one
still working, so the UI showed a perpetually-scanning system with no error anywhere —
worse than a visible failure.

This is inherent to in-process background execution: the task cannot outlive the
process that owns it, and there is no queue to resume from. Mitigated with a startup
reaper — any run still `running` when the application starts is definitionally dead
and is marked `failed`, with the reason written to the append-only `audit_log`:

```
[audit-tool] marked 1 orphaned 'running' run(s) as failed on startup
55df169b | failed
scan_failed | aravind | "orphaned by application restart -- background task cannot
              survive the process that owns it"
```

`runs` is not append-only, so correcting its status is permitted. A real job queue
would let a worker resume or explicitly fail the job instead; that remains the honest
upgrade path.

**2. The trigger was not actually sub-second at first — 2.897s.** `create_pending_run()`
called `create_schema()`, which reflects all eight tables on every single trigger.
Moved to a startup hook, which is both faster and more correct: **2.897s → 0.512s**.

Worth noting this was caught only because the harness asserts a *number* rather than
"returns quickly". The endpoint was already 45x faster than before and would have
looked fine in any manual check.

### Open items updated

- **Synchronous scan execution: CLOSED.** Promoted to 🔴 by Phase 8's measurement and
  resolved here.
- **New 🟠 item — no scan resumption across restarts.** The reaper makes the failure
  visible and correct, but a scan interrupted by a restart is lost and must be
  re-triggered. Fixing it properly means an external job queue, which Section 8's
  spirit (no new infrastructure) argues against for this deployment's scale.
- Multi-target scanning is now exposed on the endpoint (`{"targets": N}`, max 200,
  requires `mode="live"`), which was previously deferred precisely because a
  50-target request was the one guaranteed to time out.

### Addendum — one-click demo launcher (`start_audit_tool.bat` / `stop_audit_tool.bat`)

Two Windows batch scripts at repo root so the demo starts from a double-click.

**start_audit_tool.bat** — checks the `postgresql-x64-17` service and attempts
`net start` if it is stopped; refuses to spawn duplicates if the ports are taken;
builds the frontend when no production build exists; launches API and dashboard as
separate minimised windows; **polls until each actually answers** before opening the
browser. Nothing sleeps a fixed interval and hopes.

**stop_audit_tool.bat** — stops both by listening port (not by PID file, which goes
stale and can kill whatever inherited the number), verifies the ports are clear, and
**leaves PostgreSQL running**: it is a shared Windows service and not this
application's to stop.

#### Verified end to end, from a clean baseline

```
BASELINE : no uvicorn/next processes, ports 8000+3000 free, PostgreSQL Running

START    [1/4] PostgreSQL service (postgresql-x64-17)... already running.
         [2/4] Checking ports 8000 and 3000...        both free.
         [3/4] Starting backend and frontend...
         [4/4] Waiting for services to come up...
               API ready on port 8000.
               Dashboard ready on port 3000.
         Ready. Opening http://localhost:3000
         exit code 0

VERIFY   :8000 -> HTTP 200   :3000 -> HTTP 200   <title>IT Systems Audit Tool</title>
         compliance 16.7% | 54 results | 6 domains | 29 trend runs | 8 exceptions
         DATA-POPULATED: YES

ALREADY-RUNNING PATH (second launch while up)
         "The audit tool appears to be running already.
          Opening the browser instead of starting a second copy."
         service processes before: 3   after: 3   -> no duplicates

STOP     Stopping API [uvicorn] on port 8000 (PID 22320)...      stopped.
         Stopping Dashboard [next] on port 3000 (PID 16660)...   stopped.
         Ports 8000 and 3000 are clear.
         PostgreSQL (postgresql-x64-17) left running - shared system service.
         Stopped 2 process tree(s).

AFTER    no orphaned uvicorn/next processes
         port 8000 free, port 3000 free
         PostgreSQL: Running
```

**What is NOT directly proven:** that a browser tab visibly appeared. Chrome is the
registered default (`ChromeHTML`) and was already running, so `start "" <url>` opens a
tab in the existing process rather than spawning a new one — there is no new PID to
observe. What *is* proven is that the launcher reached and executed that step (both
services answering, the "Ready. Opening…" banner printed, exit code 0) and that the URL
serves a working, data-populated dashboard.

#### Four real defects found by running it rather than eyeballing it

1. **`.bat` written with LF line endings.** Batch files need CRLF. `.gitattributes`
   already forces `*.bat text eol=crlf`, so a clone is correct, but the working copy
   had to be normalised. Same class of bug as the `provision.sh` CRLF issue in
   Phase 1, in the opposite direction.

2. **Nested quoting in the launch lines.** `start "t" /min cmd /c "cd /d "%~dp0frontend" && npm run start"`
   nests quotes inside an already-quoted `cmd /c` string, which cmd mis-parses. Fixed
   with `start /D "<dir>"` — the directory is quoted once by `start` itself, and the
   command that follows uses only relative paths containing no spaces.
   **Honest correction:** this was fixed as hardening, but it was *not* the cause of
   the failure I was chasing — see 3. The first diagnosis was wrong.

3. **The frontend had no usable production build**, which was the actual cause:
   `next start` died with *"Could not find a production build in the '.next'
   directory"*. `.next` existed but `BUILD_ID` was missing.

   The root cause is worse than a missing build, and it was mine: the Phase 8-era
   regression check ran `npm run build | grep -q '✓ Compiled'`, and **`grep -q` exits
   on first match, closing the pipe and SIGPIPE-ing npm partway through the build**.
   The check reported PASS while leaving a corrupted artifact. Any check that consumes
   a build's output with `grep -q` can do this; the regression now consumes the full
   output instead.

   The launcher now tests for `.next\\BUILD_ID` specifically — it is written *last*, so
   its presence means a build finished rather than merely started — and runs
   `npm install` / `npm run build` when needed, so a fresh clone works with no manual
   steps.

4. **`on was unexpected at this time`** from the stop script. The labels contained
   parentheses (`"API (uvicorn)"`), and `%LABEL%` is expanded into a single-line
   `if ... echo`, where a literal `)` closes the parser's block context and makes the
   next word look like a command. Switched to square brackets, which are inert.

Two smaller robustness fixes: `ping -n` replaces `timeout /t`, which aborts with
*"Input redirection is not supported"* whenever stdin is redirected (a scheduled task
or script, rather than a double-click); and a `SEEN_<pid>` guard stops the same PID
being killed twice, since `netstat` lists a port once per binding (IPv4 and IPv6) and
the second attempt reported "could not kill" for a process the script had just stopped
itself.

#### Follow-up: did the SIGPIPE bug invalidate earlier phases' "frontend build PASS"?

Asked directly, and worth answering with evidence rather than recollection.

**Assume the worst — that the `frontend build` line in the Phase 6 and Phase 7
regression tables used the same `npm run build | grep -q` form.** Those particular
lines were then weak evidence: `grep -q` can exit on first match and SIGPIPE the
build, so a PASS there asserts only that the build *reached* the "Compiled" line, not
that it finished.

**It does not invalidate those phases, for three independent reasons.**

1. **No committed test harness invokes `npm run build` at all.** Verified with
   `git grep`: the frontend build only ever ran from ad-hoc shell commands. The
   `grep -q` uses that *are* committed (in `crosscheck_phase2.py`) run short remote
   commands — `sshd -T`, `stat`, `findmnt`, `dpkg-query` — where only grep's exit
   status matters and no artifact is being produced. The build case was different
   precisely because the side effect, not the exit status, was the point.

2. **`.next` is gitignored.** It is a local artifact; a corrupt one could never affect
   committed code or any backend correctness claim.

3. **Decisively: every check that actually depended on the built frontend worked at
   the time it ran.** A build missing `BUILD_ID` makes `next start` refuse to start at
   all — it exits immediately rather than serving a broken page. So a served page is
   itself proof the build was sound:
   - Phase 6 read the complete rendered DOM (compliance, six domain rows, trend,
     exceptions) from a running `next start`.
   - Phase 7 rendered the login gate, submitted the form, and rendered the dashboard
     as `aravind`.
   - The async work clicked "Run New Scan" in the browser and saw the banner.

   The corruption first appeared when the launcher ran `npm run start`, immediately
   after the one regression that used the `grep -q` form. `.next`'s timestamps match
   that run.

**Re-verified anyway, on a known-good build** (`BUILD_ID` confirmed present), so the
claims rest on current evidence rather than inference:

```
login gate renders (auth enforced in UI)   PASS
document.cookie -> "(none - HttpOnly holds)"
dashboard renders: signed in as aravind
  DOM: compliance 16.7% | open findings 43 | 6 domains | 29 trend points
  SQL: compliance 16.7% | open findings 43 | 6 domains | 29 completed runs
```

DOM and direct SQL agree exactly.

**Unrelated finding during this re-run:** three suites (`verify_phase7`,
`verify_phase8`, both cross-checks) initially failed because the demo VM had been left
in VirtualBox's `saved` state after the host slept. `vagrant up` resumed it and all
three passed. Worth knowing for the demo: **the launcher starts the application but
not the demo VM**, so live scans fail until `vagrant up` has been run. Either add it to
the launcher or run it first — see the open items.

#### Launcher addendum — demo VM resume

`start_audit_tool.bat` gained a third step: verify the demo VM's state and resume it
if it is suspended, in the same shape as the PostgreSQL check. This removes a failure
mode that had already bitten once — VirtualBox leaves the VM `saved` after the host
sleeps, and live scans then fail for a reason nothing on screen explains.

State is read from `vagrant status --machine-readable` rather than the human output,
which is localised and reflows between Vagrant versions. `running` passes through;
`saved`/`poweroff`/`aborted` are resumed with `vagrant up`; `not_created` prints
instructions and continues, because creating the VM downloads a ~600 MB box and can
take 10-40 minutes — far too long for a launcher to do silently.

Every failure path **warns and continues** rather than aborting: the dashboard, the
historical data and the PDF export all work without the VM. Only live scans need it,
so blocking the whole demo on a missing VM would make the tool less useful, not more.

**A control-flow bug was introduced and caught while doing this.** The ports check
ended in `goto :launch`, which jumped straight over the newly inserted VM block — so
the check would have been dead code on the normal path, while still looking correct in
review. Routed through `:vmcheck` instead. Found by tracing every `goto`/label in the
file rather than by reading the diff.

Verified from a clean baseline with the VM **deliberately suspended**:

```
vagrant suspend            -> state: saved
stop_audit_tool.bat        -> ports free, no processes

start_audit_tool.bat
 [1/5] PostgreSQL service (postgresql-x64-17)... already running.
 [2/5] Checking ports 8000 and 3000...          both free.
 [3/5] Demo VM (Vagrant)...
       state is "saved" - resuming (this can take 30-60 seconds)...
       resumed.
 [4/5] Starting backend and frontend...
 [5/5] API ready on port 8000. Dashboard ready on port 3000.
```

Then — the part that actually matters, rather than the VM merely reporting `running` —
a **live scan over real SSH**:

```
POST /api/scans {"mode":"live"}  -> 202 in 0.51s
  t+3s   running    results=0   credential_used=0
  t+9s   running    results=0   credential_used=1
  t+12s  completed  results=18  credential_used=1

evidence read live from the VM at 2026-08-28 01:35:02:
  CIS-5.2.10  fail  PermitRootLogin      = yes
  CIS-1.4.2   fail  /etc/shadow.mode     = 644
  CIS-3.2.1   fail  net.ipv4.ip_forward  = 1
```

The `credential_used` row proves a real SSH session through `secrets_manager`, and the
evidence values are the demo VM's actual misconfigurations — not cached data.

**Known gap, deliberate:** the "already running" fast path exits before the VM check,
so a tool left running while its VM is separately suspended will not self-heal. That
path exists to open the browser instantly; making it wait 30-60s would defeat it. Run
`stop_audit_tool.bat` then start again.

### Addendum — 2026-08-27, Phase 7 reconciled against the written spec

Phase 7 was built from the project owner's chat paraphrase, because the updated
CLAUDE.md never synced to this machine. `CLAUDE_SYNC_v2.md` (sha256 `4e5af7b0…`,
511 lines — **verified on disk before reading**) made the written text available for
the first time. Reconciliation follows.

**Matches, no drift:**

| Written requirement | Status |
|---|---|
| Session auth on every state-changing endpoint (scan trigger, exception request/approve, report export) | ✅ built, and extended to the read endpoints too |
| "say so explicitly rather than leaving it ambiguous which endpoints are actually protected" | ✅ the protected/public split is stated in `api/main.py`'s docstring, BUILD_LOG and architecture.md |
| Prove enforcement with "a real curl call without a session cookie, not a code-reading exercise" | ✅ 7/7 protected endpoints 401 over real HTTP against a running server |
| Credentials behind `secrets_manager.py` before the phase closes | ✅ Phase-1 TODO closed; live SSH scan with the key decrypted from the Fernet store |
| Real `POST /api/scans` behind session auth, starting a real scan, returning the new `run_id` | ✅ built |
| "a 'Run New Scan' button in the dashboard if time allows" | ✅ built (was optional) |

**Gap found and closed on reading the spec:** the written text requires the trigger be
proven by confirming "a new row appears in `runs` and the dashboard reflects it —
**without touching the command line**". The original Phase 7 proof used an
authenticated `curl` and verified the row with `psql` — both command line. Now
re-proven end to end in the browser: the button produced
`New run 380f19c4 — 18 results, 16.7% compliant`, the dashboard switched to that run,
and the trend chart grew from 9 to 10 points. Confirmed independently afterwards in
the database (`triggered_by=aravind`, 18 results, `credential_used` present because it
was a live SSH scan).

**Drift, flagged rather than quietly kept:**

> "A single seeded reviewer account is enough; do not build multi-user roles or
> registration."

Two accounts exist (`aravind`, `priya`) and the `users` table has a `role` column.

*Why two accounts:* Phase 4's acceptance criteria require approving a high/critical
exception "as a distinct approver from requester". One account cannot demonstrate
separation of duties through the API at all — the endpoint takes the approver identity
from the session, so proving the 403/200 pair needs two real identities. The two
requirements are in genuine tension and the earlier, more specific one was kept.

*On "multi-user roles":* the `role` column is stored and returned by `/api/auth/me`
but is **not enforced anywhere** — there is no role-based access control, and both
accounts can reach every endpoint. It is an informational attribute, not a roles
system. Left in place rather than migrated out, and recorded here so nobody mistakes
it for implemented authorisation.

*On "registration":* none exists. Accounts are created only by `backend/bootstrap.py`
from the command line, with the password read from the environment rather than argv.

**Not built (explicitly optional in the spec):** the APScheduler cron option. The
written text calls the on-demand endpoint "the non-negotiable part" and scheduling "a
reasonable stretch if time allows". Carried as an open item.

**⚠️ `CLAUDE.md` on disk is missing Section 7a.** It is 485 lines / `ba70c55b…`;
`CLAUDE_SYNC_v2.md` is 511 lines and differs by exactly the 26-line Section 7a block —
otherwise identical. Section 11 requires CLAUDE.md to stay current at the repo root
"so every collaborator's Claude Code session gets the same spec", and as it stands a
fresh clone gets a spec with no Phase 8 in it. Not overwritten unilaterally, since the
owner tracks CLAUDE.md by hash and an unannounced change would break that check.

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
