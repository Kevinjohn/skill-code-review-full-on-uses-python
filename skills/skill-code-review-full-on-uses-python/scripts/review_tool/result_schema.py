"""Strict attempt-local candidate and validation schema checks."""

from __future__ import annotations

from typing import Any


CANDIDATE_STRING_FIELDS = {
    "title",
    "category",
    "proposedDisposition",
    "proposedMateriality",
    "proposedMaterialityRationale",
    "confidence",
    "trigger",
    "expected",
    "actual",
    "impact",
    "likelihood",
    "blastRadius",
    "reachability",
    "existingChecks",
    "reproduction",
    "recommendation",
    "regressionTest",
    "counterargument",
    "residualUncertainty",
}
CANDIDATE_LIST_FIELDS = {
    "additionalLocations",
    "affectedComponents",
    "affectedConfigurations",
    "affectedDeployments",
    "evidence",
    "validationRefs",
}
VALIDATION_STRING_FIELDS = {
    "localId",
    "validationClass",
    "command",
    "cwd",
    "environmentSummary",
    "startedAt",
    "endedAt",
    "result",
}
VALIDATION_LIST_FIELDS = {
    "limitations",
    "createdArtifacts",
    "supportsCandidates",
}
VALIDATION_RESULTS = {"passed", "failed", "blocked", "not_run", "inconclusive"}


def _substantive_item(value: Any) -> bool:
    return (
        isinstance(value, str) and bool(value.strip())
    ) or (isinstance(value, dict) and bool(value))


def _valid_location(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if not any(
        isinstance(value.get(field), str) and bool(value[field].strip())
        for field in ("path", "symbol")
    ):
        return False
    return all(
        line is None
        or (
            isinstance(line, int)
            and not isinstance(line, bool)
            and line >= 1
        )
        for line in (value.get("startLine"), value.get("endLine"))
    )


def _valid_limitation(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(value.get(field), str) and bool(value[field].strip())
        for field in (
            "description",
            "materiality",
            "rationale",
            "remainingAction",
        )
    )


def validate_candidate_schema(
    candidate: dict[str, Any], label: str, issues: list[str]
) -> None:
    required = {
        "localId",
        "primaryLocation",
        *CANDIDATE_STRING_FIELDS,
        *CANDIDATE_LIST_FIELDS,
    }
    missing = required - set(candidate)
    if missing:
        issues.append(f"{label} missing required fields: {sorted(missing)}")
    if not isinstance(candidate.get("localId"), str):
        issues.append(f"{label} localId must be a string")
    for field in CANDIDATE_STRING_FIELDS:
        if field in candidate and not isinstance(candidate[field], str):
            issues.append(f"{label} {field} must be a string")
    for field in CANDIDATE_LIST_FIELDS:
        if field in candidate and not isinstance(candidate[field], list):
            issues.append(f"{label} {field} must be an array")
    primary = candidate.get("primaryLocation")
    if primary is not None and not _valid_location(primary):
        issues.append(
            f"{label} primaryLocation must be a substantive location or null"
        )
    additional = candidate.get("additionalLocations")
    if isinstance(additional, list) and not all(
        _valid_location(item) for item in additional
    ):
        issues.append(f"{label} additionalLocations contains an invalid location")
    for field in (
        "affectedComponents",
        "affectedConfigurations",
        "affectedDeployments",
        "evidence",
    ):
        values = candidate.get(field)
        if isinstance(values, list) and not all(
            _substantive_item(item) for item in values
        ):
            issues.append(f"{label} {field} contains an empty or malformed item")
    refs = candidate.get("validationRefs")
    if isinstance(refs, list) and not all(
        isinstance(item, str) and bool(item.strip()) for item in refs
    ):
        issues.append(f"{label} validationRefs contains an invalid identifier")


def validate_validation_schema(
    validation: dict[str, Any], label: str, issues: list[str]
) -> None:
    required = {
        *VALIDATION_STRING_FIELDS,
        *VALIDATION_LIST_FIELDS,
        "exitStatus",
    }
    missing = required - set(validation)
    if missing:
        issues.append(f"{label} missing required fields: {sorted(missing)}")
    for field in VALIDATION_STRING_FIELDS:
        if field in validation and not isinstance(validation[field], str):
            issues.append(f"{label} {field} must be a string")
    for field in VALIDATION_LIST_FIELDS:
        if field in validation and not isinstance(validation[field], list):
            issues.append(f"{label} {field} must be an array")
    exit_status = validation.get("exitStatus")
    if exit_status is not None and (
        not isinstance(exit_status, int) or isinstance(exit_status, bool)
    ):
        issues.append(f"{label} exitStatus must be an integer or null")
    result = validation.get("result")
    if isinstance(result, str) and result not in VALIDATION_RESULTS:
        issues.append(f"{label} result is invalid: {result}")
    limitations = validation.get("limitations")
    if isinstance(limitations, list) and not all(
        _valid_limitation(item) for item in limitations
    ):
        issues.append(
            f"{label} limitations require description, materiality, "
            "rationale, and remainingAction"
        )
    artifacts = validation.get("createdArtifacts")
    if isinstance(artifacts, list) and not all(
        _substantive_item(item) for item in artifacts
    ):
        issues.append(
            f"{label} createdArtifacts contains an empty or malformed item"
        )
    supports = validation.get("supportsCandidates")
    if isinstance(supports, list) and not all(
        isinstance(item, str) and bool(item.strip()) for item in supports
    ):
        issues.append(f"{label} supportsCandidates contains an invalid identifier")
    if result in {"blocked", "not_run", "inconclusive"} and (
        not isinstance(limitations, list) or not limitations
    ):
        issues.append(f"{label} requires a non-empty limitations array")
