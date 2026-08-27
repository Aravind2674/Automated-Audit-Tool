"""
Loads and strictly validates the control YAML files in backend/controls/.

Phase 1 scope: this module only reads and validates control definitions and reports
which raw data sources the loaded set requires. It performs no evaluation -- that
arrives in Phase 2 with the evaluator.

Validation here is deliberately strict and fail-fast. A control file that loads but
carries a typo in an operator name or a missing framework mapping would otherwise
surface much later as a wrong pass/fail verdict, which is the failure mode this
project can least afford.
"""

from __future__ import annotations

import pathlib

import yaml

CONTROLS_DIR = pathlib.Path(__file__).parent / "controls"

VALID_SEVERITIES = {"critical", "high", "medium", "low"}

REQUIRED_TOP_LEVEL = {
    "id",
    "title",
    "framework_mappings",
    "severity",
    "category",
    "description",
    "applies_to",
    "test_logic",
    "remediation",
    "scored",
}

REQUIRED_FRAMEWORK_KEYS = {"cis_linux_v8", "nist_csf", "soc2", "cert_in_marker"}

#: Permitted cert_in_marker values.
#:
#: PROVENANCE -- READ BEFORE USING THIS ANYWHERE USER-FACING.
#: This six-marker taxonomy is drawn from the public methodology descriptions
#: published by CERT-In-empanelled auditors. It is NOT transcribed from a primary
#: CERT-In document. It must never be presented as official CERT-In text in the
#: application, in exported reports, or in project documentation. Label it as an
#: auditor-methodology-derived mapping wherever it is surfaced.
VALID_CERT_IN_MARKERS = {
    "CSM",  # Configuration and Security Management
    "PRO",  # Protection
    "DET",  # Detection
    "RES",  # Response
    "REC",  # Recovery
    "IMP",  # Implementation
}

# Leaf comparison operators. The evaluator built in Phase 2 must implement exactly
# this set -- nothing here is accepted unless there is a matching implementation.
LEAF_OPERATORS = {
    "equals",
    "not_equals",
    "lte",
    "gte",
    "in",
    "contains_none",
    "superset_of",
    "mode_at_most",
    "equals_or_absent",
}

# Composite operators combine a list of leaf checks.
COMPOSITE_OPERATORS = {"all_of", "any_of"}


class ControlSchemaError(Exception):
    """Raised when a control YAML file violates the Section 4 schema."""


def _require(condition: bool, source: str, message: str) -> None:
    if not condition:
        raise ControlSchemaError(f"{source}: {message}")


def _validate_leaf_check(check: dict, source: str, where: str) -> None:
    _require(isinstance(check, dict), source, f"{where}: check must be a mapping")

    unknown = set(check) - {"check", "operator", "expected"}
    _require(not unknown, source, f"{where}: unknown key(s) {sorted(unknown)}")

    _require("check" in check, source, f"{where}: missing 'check'")
    _require(
        isinstance(check["check"], str) and check["check"].strip() != "",
        source,
        f"{where}: 'check' must be a non-empty string",
    )

    _require("operator" in check, source, f"{where}: missing 'operator'")
    _require(
        check["operator"] in LEAF_OPERATORS,
        source,
        f"{where}: operator {check['operator']!r} is not one of {sorted(LEAF_OPERATORS)}",
    )

    _require("expected" in check, source, f"{where}: missing 'expected'")

    # Operators that compare against a collection require a list.
    if check["operator"] in {"in", "contains_none", "superset_of"}:
        _require(
            isinstance(check["expected"], list),
            source,
            f"{where}: operator {check['operator']!r} requires 'expected' to be a list",
        )

    # Numeric comparisons require a number.
    if check["operator"] in {"lte", "gte"}:
        _require(
            isinstance(check["expected"], (int, float))
            and not isinstance(check["expected"], bool),
            source,
            f"{where}: operator {check['operator']!r} requires a numeric 'expected'",
        )

    # Octal mode comparison requires a mode-shaped string.
    if check["operator"] == "mode_at_most":
        expected = check["expected"]
        _require(
            isinstance(expected, str)
            and 3 <= len(expected) <= 4
            and all(c in "01234567" for c in expected),
            source,
            f"{where}: operator 'mode_at_most' requires a 3- or 4-digit octal "
            f"string, got {expected!r}",
        )


def _validate_test_logic(test_logic: dict, source: str) -> None:
    _require(isinstance(test_logic, dict), source, "test_logic must be a mapping")
    _require("collector" in test_logic, source, "test_logic missing 'collector'")
    _require(
        isinstance(test_logic["collector"], str)
        and test_logic["collector"].strip() != "",
        source,
        "test_logic 'collector' must be a non-empty string",
    )

    has_checks = "checks" in test_logic
    has_flat = "check" in test_logic

    _require(
        has_checks != has_flat,
        source,
        "test_logic must use either the flat form (check/operator/expected) "
        "or the composite form (operator/checks), not both and not neither",
    )

    if has_flat:
        unknown = set(test_logic) - {"collector", "check", "operator", "expected"}
        _require(not unknown, source, f"test_logic: unknown key(s) {sorted(unknown)}")
        _validate_leaf_check(
            {k: v for k, v in test_logic.items() if k != "collector"},
            source,
            "test_logic",
        )
        return

    unknown = set(test_logic) - {"collector", "operator", "checks"}
    _require(not unknown, source, f"test_logic: unknown key(s) {sorted(unknown)}")

    _require("operator" in test_logic, source, "composite test_logic missing 'operator'")
    _require(
        test_logic["operator"] in COMPOSITE_OPERATORS,
        source,
        f"composite operator {test_logic['operator']!r} is not one of "
        f"{sorted(COMPOSITE_OPERATORS)}",
    )
    _require(
        isinstance(test_logic["checks"], list) and len(test_logic["checks"]) > 0,
        source,
        "checks must be a non-empty list",
    )
    for i, check in enumerate(test_logic["checks"]):
        _validate_leaf_check(check, source, f"checks[{i}]")


def validate_control(control: dict, source: str) -> None:
    """Raise ControlSchemaError if the parsed control violates the Section 4 schema."""
    _require(isinstance(control, dict), source, "top level of file must be a mapping")

    missing = REQUIRED_TOP_LEVEL - set(control)
    _require(not missing, source, f"missing required key(s) {sorted(missing)}")

    unknown = set(control) - REQUIRED_TOP_LEVEL
    _require(not unknown, source, f"unknown top-level key(s) {sorted(unknown)}")

    for key in ("id", "title", "description", "remediation", "category"):
        _require(
            isinstance(control[key], str) and control[key].strip() != "",
            source,
            f"{key} must be a non-empty string",
        )

    _require(
        control["severity"] in VALID_SEVERITIES,
        source,
        f"severity {control['severity']!r} is not one of {sorted(VALID_SEVERITIES)}",
    )

    _require(isinstance(control["scored"], bool), source, "scored must be a boolean")

    _require(
        isinstance(control["applies_to"], list)
        and len(control["applies_to"]) > 0
        and all(isinstance(x, str) and x.strip() for x in control["applies_to"]),
        source,
        "applies_to must be a non-empty list of non-empty strings",
    )

    fm = control["framework_mappings"]
    _require(isinstance(fm, dict), source, "framework_mappings must be a mapping")
    fm_missing = REQUIRED_FRAMEWORK_KEYS - set(fm)
    _require(not fm_missing, source, f"framework_mappings missing {sorted(fm_missing)}")
    for key, value in fm.items():
        _require(
            isinstance(value, str) and value.strip() != "",
            source,
            f"framework_mappings[{key}] must be a non-empty string",
        )

    _require(
        fm["cert_in_marker"] in VALID_CERT_IN_MARKERS,
        source,
        f"cert_in_marker {fm['cert_in_marker']!r} is not one of "
        f"{sorted(VALID_CERT_IN_MARKERS)}",
    )

    _validate_test_logic(control["test_logic"], source)


def load_controls(controls_dir: pathlib.Path | None = None) -> list[dict]:
    """
    Parse and validate every *.yaml file in the controls directory.

    Raises ControlSchemaError on the first file that fails validation, or on a
    duplicate control id across files. Returns controls sorted by id.
    """
    directory = controls_dir or CONTROLS_DIR
    paths = sorted(directory.glob("*.yaml"))

    if not paths:
        raise ControlSchemaError(f"no control YAML files found in {directory}")

    controls: list[dict] = []
    seen_ids: dict[str, str] = {}

    for path in paths:
        try:
            with path.open("r", encoding="utf-8") as handle:
                parsed = yaml.safe_load(handle)
        except yaml.YAMLError as exc:
            raise ControlSchemaError(f"{path.name}: YAML parse error: {exc}") from exc

        validate_control(parsed, path.name)

        # The filename is the control id -- enforced so that a control file can be
        # located from a result row without a lookup.
        _require(
            parsed["id"] == path.stem,
            path.name,
            f"id {parsed['id']!r} does not match filename stem {path.stem!r}",
        )

        if parsed["id"] in seen_ids:
            raise ControlSchemaError(
                f"{path.name}: duplicate control id {parsed['id']!r} "
                f"(already defined in {seen_ids[parsed['id']]})"
            )
        seen_ids[parsed["id"]] = path.name

        controls.append(parsed)

    return sorted(controls, key=lambda c: c["id"])


def required_sources(controls: list[dict]) -> list[str]:
    """Return the sorted set of raw data source names the given controls depend on."""
    return sorted({c["test_logic"]["collector"] for c in controls})
