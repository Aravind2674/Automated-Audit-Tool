"""
Runs controls against normalized resource documents.

Architectural rule (spec Section 5): this module NEVER sees `collector_type`, and
contains no branching on where evidence came from. It reads a control's `test_logic`
and looks the named attributes up in the canonical resource document. Adding the AWS
collector in Phase 5 must not require a single line of change here — if it does, the
fix belongs in normalizer.py.

Outcome semantics, in the order they are decided:

    manual_review  the control is `scored: false`. Never pass, never fail.
    error          the evidence could not determine the answer -- the source was
                   unavailable, the control names an attribute the normalizer does
                   not produce, or the comparison itself raised.
    fail           the evidence was read successfully and does not satisfy the control.
    pass           the evidence was read successfully and satisfies the control.

The `error` / `fail` boundary is deliberate and is the subtlest thing in this file.
A value of None means "read the host fine, this setting is not configured" and is a
FAIL. A source marked UNAVAILABLE means "could not read the host" and is an ERROR.
Collapsing the two would let a missing sudo right show up as a tidy list of
compliance failures, which is worse than an outright crash because it looks credible.
"""

from __future__ import annotations

import datetime
import uuid

from .normalizer import UNAVAILABLE

VALID_OUTCOMES = {"pass", "fail", "error", "manual_review"}


class EvaluationError(Exception):
    """Raised only for programming errors, e.g. an operator with no implementation."""


# ---------------------------------------------------------------------------
# leaf operators
# ---------------------------------------------------------------------------


def _op_equals(actual, expected) -> bool:
    return actual == expected


def _op_not_equals(actual, expected) -> bool:
    return actual != expected


def _op_lte(actual, expected) -> bool:
    if not isinstance(actual, (int, float)) or isinstance(actual, bool):
        return False  # unset or non-numeric -> not satisfied
    return actual <= expected


def _op_gte(actual, expected) -> bool:
    if not isinstance(actual, (int, float)) or isinstance(actual, bool):
        return False
    return actual >= expected


def _op_in(actual, expected) -> bool:
    return actual in expected


def _op_contains_none(actual, expected) -> bool:
    """The actual list must contain none of the disallowed values."""
    if actual is None:
        return False
    actual_set = {str(x).strip().lower() for x in actual}
    return not (actual_set & {str(x).strip().lower() for x in expected})


def _op_superset_of(actual, expected) -> bool:
    """The actual list must contain every required value."""
    if actual is None:
        return False
    actual_set = {str(x).strip().lower() for x in actual}
    return {str(x).strip().lower() for x in expected} <= actual_set


def _op_mode_at_most(actual, expected) -> bool:
    """No permission bit may be set beyond those allowed by `expected`.

    Compares bitwise rather than numerically: mode 0400 is not "less than" 0640 in
    any useful sense, but it sets no bit that 0640 does not, so it is acceptable.
    A numeric `<=` would wrongly accept 0604 against an expected 0640.
    """
    if actual is None:
        return False
    try:
        actual_bits = int(str(actual), 8)
        allowed_bits = int(str(expected), 8)
    except ValueError:
        return False
    return (actual_bits & ~allowed_bits) == 0


def _op_equals_or_absent(actual, expected) -> bool:
    return actual is None or actual == expected


_LEAF_OPS = {
    "equals": _op_equals,
    "not_equals": _op_not_equals,
    "lte": _op_lte,
    "gte": _op_gte,
    "in": _op_in,
    "contains_none": _op_contains_none,
    "superset_of": _op_superset_of,
    "mode_at_most": _op_mode_at_most,
    "equals_or_absent": _op_equals_or_absent,
}


# ---------------------------------------------------------------------------
# evaluation
# ---------------------------------------------------------------------------


class _AttributeMissing(Exception):
    """The control names an attribute the normalizer does not produce."""


def _leaf_checks(test_logic: dict) -> tuple[str, list[dict]]:
    """Return (composite_operator, [leaf checks]) for either test_logic form."""
    if "checks" in test_logic:
        return test_logic["operator"], test_logic["checks"]
    return "all_of", [
        {
            "check": test_logic["check"],
            "operator": test_logic["operator"],
            "expected": test_logic["expected"],
        }
    ]


def _evaluate_leaf(check: dict, source_attrs: dict) -> dict:
    name = check["check"]
    if name not in source_attrs:
        raise _AttributeMissing(name)

    actual = source_attrs[name]
    operator = check["operator"]
    func = _LEAF_OPS.get(operator)
    if func is None:
        raise EvaluationError(f"no implementation for operator {operator!r}")

    return {
        "check": name,
        "operator": operator,
        "expected": check["expected"],
        "actual": actual,
        "satisfied": bool(func(actual, check["expected"])),
    }


def evaluate(
    control: dict,
    normalized_resources: list[dict],
    audit_sink=None,
    correlation_id: str | None = None,
    run_id: str | None = None,
    actor: str = "system",
) -> list[dict]:
    """
    Returns list of {control_id, resource_id, outcome, evidence}.

    outcome is one of: pass, fail, error, manual_review.
    - scored=false controls -> always manual_review, never pass/fail.
    - Any exception during evaluation -> outcome='error', never silently pass.
    - Every call writes one row to audit_log with event_type='control_evaluated'.

    `audit_sink` is any object with `.write(row: dict)`. It is injected rather than
    imported so this module stays free of database concerns; see audit.py.
    """
    control_id = control["id"]
    source = control["test_logic"]["collector"]
    results: list[dict] = []

    for resource in normalized_resources:
        # applies_to gates which resource types a control is evaluated against.
        if resource["resource_type"] not in control["applies_to"]:
            continue

        resource_id = resource["resource_id"]
        outcome: str
        evidence: dict

        if not control["scored"]:
            # Checked before anything else: an unscored control must never be
            # assigned pass or fail, regardless of what the evidence says.
            outcome = "manual_review"
            evidence = {
                "reason": "control is scored: false; requires human judgement",
                "source": source,
                "collected": resource["attributes"].get(source, {}),
            }
            results.append(
                {
                    "control_id": control_id,
                    "resource_id": resource_id,
                    "outcome": outcome,
                    "evidence": evidence,
                }
            )
            continue

        try:
            source_attrs = resource["attributes"].get(source)
            if source_attrs is None:
                outcome = "error"
                evidence = {
                    "reason": f"no evidence collected for source {source!r}",
                    "source": source,
                }
            elif UNAVAILABLE in source_attrs:
                outcome = "error"
                evidence = {
                    "reason": source_attrs[UNAVAILABLE],
                    "source": source,
                }
            else:
                composite, checks = _leaf_checks(control["test_logic"])
                evaluated = [_evaluate_leaf(c, source_attrs) for c in checks]
                satisfied = [e["satisfied"] for e in evaluated]

                if composite == "all_of":
                    passed = all(satisfied)
                elif composite == "any_of":
                    passed = any(satisfied)
                else:
                    raise EvaluationError(
                        f"no implementation for composite operator {composite!r}"
                    )

                outcome = "pass" if passed else "fail"
                evidence = {
                    "source": source,
                    "operator": composite,
                    "checks": evaluated,
                    "failed_checks": [
                        e["check"] for e in evaluated if not e["satisfied"]
                    ],
                }

        except _AttributeMissing as exc:
            # A control naming an attribute the normalizer never produces is a
            # wiring bug. It must surface as `error`, never as a quiet pass.
            outcome = "error"
            evidence = {
                "reason": (
                    f"normalizer produced no attribute {str(exc)!r} for source "
                    f"{source!r} -- control and normalizer are out of sync"
                ),
                "source": source,
                "available_attributes": sorted(
                    resource["attributes"].get(source, {})
                ),
            }
        except Exception as exc:  # noqa: BLE001 -- spec Section 5: never silently pass
            outcome = "error"
            evidence = {
                "reason": f"{type(exc).__name__}: {exc}",
                "source": source,
            }

        assert outcome in VALID_OUTCOMES, f"invalid outcome {outcome!r}"
        results.append(
            {
                "control_id": control_id,
                "resource_id": resource_id,
                "outcome": outcome,
                "evidence": evidence,
            }
        )

    # Spec Section 5: every call writes one audit_log row.
    if audit_sink is not None:
        audit_sink.write(
            {
                "event_id": str(uuid.uuid4()),
                "correlation_id": correlation_id,
                "run_id": run_id,
                "actor": actor,
                "event_type": "control_evaluated",
                "timestamp": datetime.datetime.now(datetime.timezone.utc),
                "result": ",".join(sorted({r["outcome"] for r in results})) or "no_resources",
                "details": {
                    "control_id": control_id,
                    "source": source,
                    "resources_evaluated": len(results),
                    "outcomes": {
                        outcome: sum(1 for r in results if r["outcome"] == outcome)
                        for outcome in sorted({r["outcome"] for r in results})
                    },
                },
            }
        )

    return results
