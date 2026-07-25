"""Declarative field rules for canonical review records.

Each table below is the single source of truth for the pure field-shape
constraints of one record type: one row per constraint, stating the field,
the predicate, and the exact reported message. Relational and cross-file
validation (hash pins, manifest comparisons, graph references) stays in
checks.py; this module answers "is field X validated, and how?" by
inspection.

Predicates and messages receive ``(value, context)`` where ``context``
carries the surrounding records a constraint may need (the run, the unit
identifier, the security level). A rule with ``when`` applies only when
that guard passes.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from .security import SECURITY_LEVELS

RUN_STATUSES = {"active", "paused", "concluded", "superseded"}
UNIT_STATUSES = {"pending", "assigned", "partial", "complete", "blocked", "needs_revalidation"}
ANGLE_STATUSES = {"pending", "reviewed", "not_applicable", "excluded_by_profile", "blocked", "needs_revalidation"}
RUNTIME_CAPABILITIES = {"continuous", "persistent_task", "external_supervisor", "none"}
VERDICTS = {
    "PASS",
    "CONDITIONAL PASS",
    "CHANGES REQUIRED",
    "MAJOR CHANGES REQUIRED",
    "BLOCK",
    "INCOMPLETE REVIEW",
}

# Legal attempt (importDisposition -> statuses) pairs; anything else is
# reported as an inconsistent or unreconciled attempt row.
ATTEMPT_LIFECYCLE = {
    "pending": {"assigned"},
    "imported": {"complete", "partial", "blocked"},
    "superseded": {"interrupted"},
    "rejected": {"interrupted"},
    "reconciled_interruption": {"interrupted"},
}

Context = dict[str, Any]
Predicate = Callable[[Any, Context], bool]
Message = str | Callable[[Any, Context], str]


class Rule:
    __slots__ = ("field", "valid", "message", "default", "when")

    def __init__(
        self,
        field: str,
        valid: Predicate,
        message: Message,
        *,
        default: Any = None,
        when: Predicate | None = None,
    ) -> None:
        self.field = field
        self.valid = valid
        self.message = message
        self.default = default
        self.when = when


def apply_rules(
    record: dict[str, Any],
    rules: list[Rule],
    issues: list[str],
    context: Context | None = None,
) -> None:
    context = context or {}
    for rule in rules:
        value = record.get(rule.field, rule.default)
        if rule.when is not None and not rule.when(value, context):
            continue
        if not rule.valid(value, context):
            message = rule.message
            issues.append(message(value, context) if callable(message) else message)


def equals(expected: Any) -> Predicate:
    return lambda value, context: value == expected


def one_of(choices: set[str]) -> Predicate:
    return lambda value, context: isinstance(value, str) and value in choices


def nullable(predicate: Predicate) -> Predicate:
    return lambda value, context: value is None or predicate(value, context)


def non_empty_str(value: Any, context: Context) -> bool:
    return isinstance(value, str) and bool(value)


def matches(pattern: str) -> Predicate:
    compiled = re.compile(pattern)
    return lambda value, context: bool(compiled.fullmatch(str(value if value is not None else "")))


def matches_run(field: str) -> Predicate:
    return lambda value, context: value == context["run"].get(field)


def status_is(*statuses: str) -> Predicate:
    """Guard: apply the rule only for these values of the record's status."""
    allowed = set(statuses)

    def guard(value: Any, context: Context) -> bool:
        status = context.get("status")
        return isinstance(status, str) and status in allowed

    return guard


def _valid_capabilities(value: Any, context: Context) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("stableReviewerLineage"), bool)
        and isinstance(value.get("source"), str)
        and value["source"] in {"harness_declared", "absent_default_false"}
    )


def _valid_acknowledgements(value: Any, context: Context) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and isinstance(item.get("diagnosticIdentity"), str)
        for item in value
    )


SPEC_MIGRATION_RULES = [
    Rule(
        "specMigrations",
        equals([]),
        "run.json specMigrations must be an empty array; specification "
        "migration is not supported — start a new review instead",
    ),
    Rule("specEpoch", equals("SPEC-0001"), "run.json specEpoch must be SPEC-0001"),
]

RUN_RULES = [
    Rule("schemaVersion", equals(1), "run.json schemaVersion must be 1"),
    Rule("specEpoch", matches(r"SPEC-\d{4}"), "run.json specEpoch is invalid"),
    *SPEC_MIGRATION_RULES,
    Rule("status", one_of(RUN_STATUSES), "run.json status is invalid"),
    Rule(
        "verdict",
        nullable(one_of(VERDICTS)),
        lambda value, context: f"run.json verdict is invalid: {value!r}",
    ),
    Rule("currentEpoch", non_empty_str, "run.json currentEpoch is required"),
    Rule(
        "runtimeCapability",
        one_of(RUNTIME_CAPABILITIES),
        "run.json runtimeCapability is invalid",
    ),
    Rule(
        "specialistCapabilities",
        _valid_capabilities,
        "run.json specialistCapabilities must include a boolean "
        "stableReviewerLineage and valid source",
    ),
    Rule(
        "diagnosticAcknowledgements",
        _valid_acknowledgements,
        "run.json diagnosticAcknowledgements must contain scoped "
        "acknowledgement objects",
        default=[],
    ),
]

SECURITY_PROFILE_RULES = [
    Rule(
        "level",
        lambda value, context: context["level"] in SECURITY_LEVELS,
        "run.json securityProfile level is invalid",
    ),
    Rule(
        "source",
        one_of({"default", "user"}),
        "run.json securityProfile source is invalid",
    ),
    Rule(
        "externalTargets",
        equals(False),
        "run.json securityProfile must prohibit external targets",
    ),
]

UNIT_RULES = [
    Rule(
        "id",
        matches(r"WORK-\d{4}"),
        lambda value, context: f"work unit has invalid identifier: {value}",
    ),
    Rule(
        "status",
        one_of(UNIT_STATUSES),
        lambda value, context: (
            f"{context['uid']}: invalid status transition or status {value!r}"
        ),
    ),
    Rule(
        "specEpoch",
        matches_run("specEpoch"),
        lambda value, context: f"{context['uid']}: unit from wrong specEpoch",
    ),
    Rule(
        "securityLevel",
        lambda value, context: value == context["level"],
        lambda value, context: (
            f"{context['uid']}: securityLevel does not match run profile"
        ),
    ),
]

# context for ANGLE_RULES: uid, number, run, level, status (the angle's own
# status, so status_is guards conditional requirements).
ANGLE_RULES = [
    Rule(
        "status",
        one_of(ANGLE_STATUSES),
        lambda value, context: (
            f"{context['uid']} angle {context['number']}: invalid status"
        ),
    ),
    Rule(
        "evidence",
        lambda value, context: bool(value),
        lambda value, context: (
            f"{context['uid']} angle {context['number']}: "
            "semantic/applicability evidence required"
        ),
        when=status_is("reviewed", "not_applicable"),
    ),
    Rule(
        "specEpoch",
        matches_run("specEpoch"),
        lambda value, context: (
            f"{context['uid']} angle {context['number']}: "
            "disposition from wrong specEpoch"
        ),
        when=status_is("reviewed", "not_applicable"),
    ),
    Rule(
        "status",
        lambda value, context: (
            context["number"] == "5" and context["level"] == "off"
        ),
        lambda value, context: (
            f"{context['uid']} angle {context['number']}: "
            "invalid profile exclusion"
        ),
        when=status_is("excluded_by_profile"),
    ),
    Rule(
        "profileExclusion",
        lambda value, context: (
            isinstance(value, dict)
            and value.get("domain") == "security"
            and value.get("level") == "off"
        ),
        lambda value, context: (
            f"{context['uid']} angle {context['number']}: "
            "profile exclusion metadata is invalid"
        ),
        default={},
        when=status_is("excluded_by_profile"),
    ),
    Rule(
        "specEpoch",
        matches_run("specEpoch"),
        lambda value, context: (
            f"{context['uid']} angle {context['number']}: "
            "profile exclusion from wrong specEpoch"
        ),
        when=status_is("excluded_by_profile"),
    ),
]
