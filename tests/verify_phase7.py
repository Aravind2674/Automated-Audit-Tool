"""
Phase 7 verification: session auth, secrets_manager migration, audit-log sweep,
and the hardcoded-secrets review.

Auth enforcement is proved with **real HTTP requests against a running server**, not
with FastAPI's in-process TestClient and not by reading the code. A middleware that
exists in source but is bypassed by route ordering, a dependency attached to the wrong
router, or a server running stale code would all pass a code review and fail here.

Requires the API to be running:
    python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --app-dir backend

Usage:
    python tests/verify_phase7.py
    AUDIT_USER=aravind AUDIT_PASSWORD=... python tests/verify_phase7.py
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402

from db import get_engine  # noqa: E402

BASE = os.environ.get("AUDIT_API", "http://127.0.0.1:8000")
USER = os.environ.get("AUDIT_USER", "aravind")
PASSWORD = os.environ.get("AUDIT_PASSWORD", "demo-only-password-2026")

#: Endpoints that must reject an unauthenticated caller.
PROTECTED = [
    ("GET", "/api/dashboard"),
    ("GET", "/api/findings"),
    ("GET", "/api/reports/pdf"),
    ("GET", "/api/auth/me"),
    ("POST", "/api/scans"),
    ("POST", "/api/exceptions"),
    ("POST", "/api/exceptions/00000000-0000-0000-0000-000000000000/approve"),
]

#: Endpoints that must remain reachable without a session.
PUBLIC = [("GET", "/api/health"), ("POST", "/api/auth/login")]

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  PASS  {label}" + (f"  ({detail})" if detail else ""))
    else:
        print(f"  FAIL  {label}" + (f"  -- {detail}" if detail else ""))
        _failures.append(label)


def _server_up() -> bool:
    try:
        return httpx.get(f"{BASE}/api/health", timeout=5).status_code == 200
    except Exception:
        return False


def test_auth_enforcement() -> None:
    print("\n=== Auth enforcement, proved over real HTTP ===\n")
    if not _server_up():
        check("API is running", False, f"nothing answering at {BASE}")
        return
    check("API is running", True, BASE)

    # ---- unauthenticated: everything protected must 401 --------------------
    with httpx.Client(timeout=30) as c:
        for method, path in PROTECTED:
            r = c.request(method, f"{BASE}{path}", json={} if method == "POST" else None)
            check(f"unauthenticated {method} {path} -> 401",
                  r.status_code == 401, f"got {r.status_code}")

        r = c.get(f"{BASE}/api/health")
        check("unauthenticated GET /api/health -> 200", r.status_code == 200,
              f"got {r.status_code}")
        check("/api/health discloses no compliance data",
              "compliance" not in r.text and "findings" not in r.text, r.text[:80])

        # ---- a forged/garbage cookie must not be accepted ------------------
        r = c.get(f"{BASE}/api/dashboard",
                  cookies={"audit_session": "not-a-real-session-id-000000"})
        check("forged session cookie -> 401", r.status_code == 401, f"got {r.status_code}")

    # ---- wrong password must fail -----------------------------------------
    with httpx.Client(timeout=30) as c:
        r = c.post(f"{BASE}/api/auth/login",
                   json={"username": USER, "password": "definitely-the-wrong-password"})
        check("login with wrong password -> 401", r.status_code == 401,
              f"got {r.status_code}")

    # ---- correct password, then the same endpoints must succeed -----------
    with httpx.Client(timeout=60) as c:
        r = c.post(f"{BASE}/api/auth/login", json={"username": USER, "password": PASSWORD})
        check("login with correct password -> 200", r.status_code == 200,
              f"got {r.status_code}")
        if r.status_code != 200:
            return

        cookie = r.headers.get("set-cookie", "")
        check("session cookie is HttpOnly", "httponly" in cookie.lower(), cookie[:60])
        check("session cookie is SameSite", "samesite" in cookie.lower(), cookie[:60])

        for method, path in [("GET", "/api/dashboard"), ("GET", "/api/findings"),
                             ("GET", "/api/auth/me")]:
            rr = c.request(method, f"{BASE}{path}")
            check(f"authenticated {method} {path} -> 200", rr.status_code == 200,
                  f"got {rr.status_code}")

        me = c.get(f"{BASE}/api/auth/me").json()
        check("identity comes from the session", me.get("username") == USER, str(me))

        # ---- logout must actually revoke -----------------------------------
        c.post(f"{BASE}/api/auth/logout")
        rr = c.get(f"{BASE}/api/dashboard")
        check("after logout, GET /api/dashboard -> 401", rr.status_code == 401,
              f"got {rr.status_code}")


def test_secrets_manager() -> None:
    print("\n=== secrets_manager (spec Section 6) ===\n")
    backend = REPO_ROOT / "backend"

    # Only secrets_manager may decrypt.
    decrypting = []
    for path in backend.rglob("*.py"):
        if path.name == "secrets_manager.py":
            continue
        body = path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"Fernet\s*\(", body) or ".decrypt(" in body:
            decrypting.append(str(path.relative_to(REPO_ROOT)))
    check("secrets_manager.py is the ONLY module that decrypts",
          not decrypting, str(decrypting))

    # Collectors must not touch the credentials table directly.
    #
    # Docstrings and comments are stripped before searching. The first version of this
    # check matched the bare word "credentials" and flagged base.py for the phrase
    # "rejected credentials" in prose -- a false positive that would have trained
    # whoever saw it to ignore the check, which is worse than not having it.
    def _code_only(src: str) -> str:
        src = re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "", src)   # docstrings
        return re.sub(r"#[^\n]*", "", src)                    # comments

    offenders = []
    for path in (backend / "collectors").rglob("*.py"):
        code = _code_only(path.read_text(encoding="utf-8", errors="ignore"))
        touches_table = (
            re.search(r"\bCredential\b", code)                       # the ORM model
            or re.search(r"(?i)\bfrom\s+credentials\b", code)        # raw SQL
            or re.search(r"(?i)\b(insert\s+into|update)\s+credentials\b", code)
        )
        if touches_table:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    check("collectors never read the credentials table directly",
          not offenders, str(offenders))

    src = (backend / "collectors" / "ssh_collector.py").read_text(encoding="utf-8")
    check("ssh_collector calls secrets_manager.get_credential",
          "secrets_manager.get_credential" in src)
    check("the Phase-1 credential TODO is closed",
          "TODO (Phase 2+, spec Section 6)" not in src)

    with get_engine().connect() as conn:
        rows = conn.execute(text("SELECT target_id, ciphertext FROM credentials")).all()
        check("at least one credential is stored", len(rows) > 0, f"{len(rows)}")
        leaks = [r[0] for r in rows
                 if "PRIVATE KEY" in r[1] or "BEGIN" in r[1] or "ssh-rsa" in r[1]]
        check("credentials table holds ciphertext only, no PEM markers",
              not leaks, str(leaks))

        hashes = conn.execute(text("SELECT username, password_hash FROM users")).all()
        check("passwords are bcrypt hashes, not reversible",
              all(h[1].startswith("$2") for h in hashes),
              str([h[0] for h in hashes if not h[1].startswith("$2")]))

        # credential_used must never carry the secret itself.
        used = conn.execute(text(
            "SELECT details::text FROM audit_log WHERE event_type='credential_used'"
        )).all()
        check("credential_used rows exist", len(used) > 0, f"{len(used)}")
        bad = [d[0] for d in used
               if "PRIVATE KEY" in d[0] or "BEGIN" in d[0] or "ssh-rsa" in d[0]]
        check("credential_used never records the credential value", not bad, str(bad[:2]))
        check("credential_used records the target_id",
              all("target_id" in d[0] for d in used))


def test_audit_sweep() -> None:
    print("\n=== Audit-log sweep: every state-changing action is recorded ===\n")
    with get_engine().connect() as conn:
        present = {r[0] for r in conn.execute(
            text("SELECT DISTINCT event_type FROM audit_log")).all()}

        for event in ("scan_started", "scan_completed", "control_evaluated",
                      "exception_requested", "exception_approved",
                      "exception_approval_denied", "credential_used",
                      "report_exported", "login_succeeded", "login_failed"):
            check(f"audit_log contains {event}", event in present)

        # correlation_id must be shared per run, and unique across runs.
        #
        # KNOWN PRE-FIX ANOMALY, permanently in the log by design.
        # Run 75aed5d6 carries TWO correlation_ids because the first version of the
        # report-export endpoint minted a fresh correlation_id while still tagging the
        # row with the run_id, leaving that export outside its run's trail. The bug is
        # fixed (the endpoint now reuses the run's correlation_id), and the fix is
        # proved by every run after it being clean.
        #
        # The bad row is NOT deleted or rewritten: audit_log is append-only, and that
        # guarantee is worth more than a tidy table. Being unable to erase one's own
        # mistake is the property working correctly, so it is documented here instead.
        KNOWN_PREFIX_SPLIT = {"75aed5d6-128a-4a6c-8900-505acd2588ae"}

        rows = conn.execute(text(
            "SELECT run_id, count(DISTINCT correlation_id) AS c FROM audit_log "
            "WHERE run_id IS NOT NULL GROUP BY run_id")).all()
        split = {str(r[0]) for r in rows if r[1] != 1}

        check("no NEW run has a split correlation_id",
              not (split - KNOWN_PREFIX_SPLIT), str(sorted(split - KNOWN_PREFIX_SPLIT)))
        check("the known pre-fix split is still exactly one run, unchanged",
              split == KNOWN_PREFIX_SPLIT or not split,
              f"observed={sorted(split)} expected={sorted(KNOWN_PREFIX_SPLIT)}")

        latest = conn.execute(text(
            "SELECT run_id FROM runs WHERE status='completed' "
            "ORDER BY completed_at DESC LIMIT 1")).scalar()
        latest_corr = conn.execute(text(
            "SELECT count(DISTINCT correlation_id) FROM audit_log WHERE run_id=:r"),
            {"r": latest}).scalar()
        check("the latest run's events share exactly ONE correlation_id",
              latest_corr == 1, f"{latest_corr} distinct on {latest}")

        exported = conn.execute(text(
            "SELECT count(*) FROM audit_log a JOIN runs r ON r.run_id = a.run_id "
            "AND r.correlation_id = a.correlation_id "
            "WHERE a.event_type='report_exported'")).scalar()
        check("report_exported rows join their run's correlation_id",
              exported >= 1, f"{exported} correctly-correlated export(s)")

        shared = conn.execute(text(
            "SELECT count(*) FROM (SELECT correlation_id FROM audit_log "
            "WHERE run_id IS NOT NULL GROUP BY correlation_id "
            "HAVING count(DISTINCT run_id) > 1) x")).scalar()
        check("no correlation_id is reused across runs", shared == 0, str(shared))

        # The most recent live scan must have credential_used under its correlation_id.
        live = conn.execute(text(
            "SELECT run_id, correlation_id FROM audit_log "
            "WHERE event_type='scan_started' AND details->>'mode'='live' "
            "ORDER BY timestamp DESC LIMIT 1")).first()
        if live:
            n = conn.execute(text(
                "SELECT count(*) FROM audit_log WHERE correlation_id=:c "
                "AND event_type='credential_used'"), {"c": live[1]}).scalar()
            check("a live scan's credential_used shares the run's correlation_id",
                  n >= 1, f"{n} rows")
        else:
            check("a live scan exists to check correlation on", False, "none found")

        # Append-only: no UPDATE/DELETE against results or audit_log anywhere.
        offenders = []
        for path in (REPO_ROOT / "backend").rglob("*.py"):
            body = path.read_text(encoding="utf-8", errors="ignore")
            for m in re.finditer(
                    r"(?i)\b(update|delete)\s+(from\s+)?(results|audit_log)\b", body):
                offenders.append(f"{path.name}: {m.group(0)}")
        check("no UPDATE/DELETE against results or audit_log in the codebase",
              not offenders, str(offenders[:3]))


def test_no_hardcoded_secrets() -> None:
    """Spec Section 7: grep the codebase for hardcoded secrets -- must return nothing."""
    print("\n=== Hardcoded-secrets review (spec Section 7) ===\n")

    patterns = [
        (r"(?i)(password|passwd|secret|api[_-]?key|token)\s*=\s*[\"'][^\"'{}$][^\"']{5,}",
         "assigned literal secret"),
        (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "embedded private key"),
        (r"(?i)AKIA[0-9A-Z]{16}", "AWS access key id"),
        (r"(?i)\bfernet\s*\(\s*[\"'][A-Za-z0-9_\-=]{40,}", "hardcoded Fernet key"),
        (r"postgresql(\+\w+)?://[^:\s]+:[^@\s]{3,}@", "DB URL with inline password"),
    ]
    allow = re.compile(
        r"replace-me|your-app-password|CHANGE_ME|demo-only|test|example|placeholder|"
        r"dummy|getenv|environ|os\.environ|Body|Cookie|field|param",
        re.I,
    )

    scan_dirs = ["backend", "tests", "frontend/app", "frontend/components",
                 "demo-environment"]
    hits = []
    for d in scan_dirs:
        base = REPO_ROOT / d
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if (not path.is_file()
                    or path.suffix not in (".py", ".ts", ".tsx", ".js", ".yaml",
                                           ".yml", ".sh", ".json")
                    or "node_modules" in path.parts):
                continue
            body = path.read_text(encoding="utf-8", errors="ignore")
            for pattern, label in patterns:
                for m in re.finditer(pattern, body):
                    line = body[:m.start()].count("\n") + 1
                    snippet = m.group(0)[:90]
                    if allow.search(snippet):
                        continue
                    hits.append(f"{path.relative_to(REPO_ROOT)}:{line} [{label}] {snippet}")

    check("no hardcoded secrets in tracked source", not hits, str(hits[:4]))

    # .env must be gitignored and untracked.
    r = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=REPO_ROOT)
    check(".env is gitignored", r.returncode == 0)
    r = subprocess.run(["git", "ls-files", "--error-unmatch", ".env"],
                       cwd=REPO_ROOT, capture_output=True)
    check(".env is NOT tracked by git", r.returncode != 0)

    tracked = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT,
                             capture_output=True, text=True).stdout.split()
    bad = [f for f in tracked if f.endswith((".pem", ".key", ".p12")) or f == ".env"]
    check("no key material tracked in git", not bad, str(bad))


def main() -> int:
    test_auth_enforcement()
    test_secrets_manager()
    test_audit_sweep()
    test_no_hardcoded_secrets()
    print()
    if _failures:
        print(f"{len(_failures)} CHECK(S) FAILED: {_failures}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
