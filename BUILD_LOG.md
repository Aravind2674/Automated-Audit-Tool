# Build log

Per CLAUDE.md Section 9 point 7. One entry per phase: what was built, what was
verified and how, and every deviation from spec.

---

## Phase 1 — Control library + minimal SSH collector (raw output only)

**Date:** 2026-08-27
**Status:** ⚠️ **PARTIALLY COMPLETE — acceptance criteria NOT fully met.**
Criterion 1 (all 18 YAMLs load without schema errors) is met with evidence.
Criterion 2 (collector returns real raw output from the demo VM) is **blocked** —
Vagrant and VirtualBox are not installed on this machine.

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
- **`demo-environment/EXPECTED_POSTURE.md`** — per-control answer key (4 pass,
  14 fail by design) for manual verification in Phase 2.

### What was verified, and how

1. **All 18 YAMLs load, 0 schema errors** — `load_controls()` parsed and validated
   every file; full table of id/severity/category/source printed. ✅
2. **The validator is not vacuous** — 12 deliberately corrupted controls (bad
   severity, missing key, unknown key, typo'd operator, non-numeric `expected` for
   `gte`, non-octal mode, etc.) were each rejected with a specific error. 12/12
   rejected. ✅
3. **Control↔collector coverage** — all 14 sources required by the 18 controls have
   a command mapping; no unmapped sources, no orphaned mappings. ✅
4. **Collector code path executes** — with a fake transport substituted for Fabric's
   `Connection`, `collect()` returned 14 docs, ran all 66 commands, and preserved
   non-zero exit codes as evidence rather than raising. ⚠️ *Synthetic output — this
   validates the code path only, not any real host's state.*
5. **Real collection attempted and failed** — both `--from-vagrant-ssh-config` and a
   direct connection to the Vagrantfile's `192.168.56.10` failed, because no VM
   exists. **This is the unmet acceptance criterion.** ❌

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
4. **`EXPECTED_POSTURE.md` is unverified.** It records what `provision.sh` is written
   to produce, not what a running VM was observed to do. Every row must be confirmed
   by hand on the live VM before Phase 2 treats it as ground truth.

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
