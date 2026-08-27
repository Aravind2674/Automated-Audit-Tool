"""
Tests for the control library loader and schema validator.

Runnable without pytest so it works before the test tooling is chosen:

    python tests/test_control_library.py
"""

from __future__ import annotations

import copy
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

import yaml  # noqa: E402

from control_library import (  # noqa: E402
    VALID_CERT_IN_MARKERS,
    ControlSchemaError,
    load_controls,
    validate_control,
)

FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures"

EXPECTED_CERT_IN = {
    "CIS-1.1.1": "IMP", "CIS-1.1.2": "IMP", "CIS-1.4.1": "IMP", "CIS-1.4.2": "IMP",
    "CIS-1.5.1": "IMP", "CIS-1.6.1": "IMP", "CIS-5.2.10": "IMP", "CIS-5.2.11": "IMP",
    "CIS-5.3.1": "IMP", "CIS-5.3.2": "IMP", "CIS-5.4.1": "IMP", "CIS-6.1.1": "IMP",
    "CIS-3.1.1": "PRO", "CIS-3.2.1": "PRO", "CIS-3.3.1": "PRO",
    "CIS-4.1.1": "DET", "CIS-4.1.2": "DET", "CIS-4.2.1": "DET",
}

_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}" + (f" -- {detail}" if detail else ""))
        _failures.append(label)


def test_library_loads() -> None:
    print("\nControl library:")
    controls = load_controls()
    check("exactly 18 controls load", len(controls) == 18, f"got {len(controls)}")
    check(
        "all ids are CIS-prefixed (no fixture contamination)",
        all(c["id"].startswith("CIS-") for c in controls),
        str([c["id"] for c in controls if not c["id"].startswith("CIS-")]),
    )


def test_cert_in_remap() -> None:
    print("\ncert_in_marker remap:")
    controls = load_controls()
    actual = {c["id"]: c["framework_mappings"]["cert_in_marker"] for c in controls}
    check("all 18 markers match the specified remap", actual == EXPECTED_CERT_IN,
          str({k: v for k, v in actual.items() if EXPECTED_CERT_IN.get(k) != v}))
    check("MAN appears nowhere", "MAN" not in set(actual.values()))
    check(
        "every marker is in the six-marker vocabulary",
        set(actual.values()) <= VALID_CERT_IN_MARKERS,
        str(set(actual.values()) - VALID_CERT_IN_MARKERS),
    )

    good = copy.deepcopy(controls[0])
    good["framework_mappings"]["cert_in_marker"] = "MAN"
    try:
        validate_control(good, "negative.yaml")
        check("validator rejects a reintroduced MAN", False, "it was accepted")
    except ControlSchemaError:
        check("validator rejects a reintroduced MAN", True)


def test_manual_review_fixture_is_quarantined() -> None:
    print("\nmanual_review fixture quarantine:")
    controls = load_controls()
    ids = {c["id"] for c in controls}

    check(
        "no scored=false control in the real library",
        all(c["scored"] for c in controls),
        str([c["id"] for c in controls if not c["scored"]]),
    )
    check("fixture id absent from the library", "TEST-MANUAL-REVIEW-001" not in ids)
    check(
        "fixture file is not inside backend/controls/",
        not (REPO_ROOT / "backend" / "controls" / "TEST-MANUAL-REVIEW-001.yaml").exists(),
    )

    # The fixture must still be a schema-valid control, or it cannot exercise the
    # evaluator at all.
    fixture_path = FIXTURE_DIR / "TEST-MANUAL-REVIEW-001.yaml"
    parsed = yaml.safe_load(fixture_path.read_text(encoding="utf-8"))
    try:
        validate_control(parsed, fixture_path.name)
        check("fixture passes schema validation", True)
    except ControlSchemaError as exc:
        check("fixture passes schema validation", False, str(exc))

    check("fixture is scored=false", parsed["scored"] is False)

    fixtures = load_controls(FIXTURE_DIR)
    check("fixture dir loads independently", len(fixtures) == 1, f"got {len(fixtures)}")


if __name__ == "__main__":
    test_library_loads()
    test_cert_in_remap()
    test_manual_review_fixture_is_quarantined()
    print()
    if _failures:
        print(f"{len(_failures)} CHECK(S) FAILED: {_failures}")
        sys.exit(1)
    print("all checks passed")
