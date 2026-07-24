"""Canonical path-partition and observation-graph validation."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .result_schema import (
    VALIDATION_RESULTS,
    validate_candidate_schema,
    validate_validation_schema,
)
from .security import validation_class_allowed

ID_PATTERNS = {
    "observations": re.compile(r"OBS-(\d{6})$"),
    "findings": re.compile(r"DBR-(\d{4})$"),
    "validations": re.compile(r"VAL-(\d{6})$"),
    "objections": re.compile(r"AOB-(\d{6})$"),
}
OBS_DISPOSITIONS = {
    "open",
    "validated",
    "rejected",
    "duplicate",
    "unresolved",
    "withdrawn",
    "deferred_by_profile",
}


def _issue(issues: list[str], condition: bool, message: str) -> None:
    if not condition:
        issues.append(message)


def _is_one_of(value: Any, choices: set[str]) -> bool:
    return isinstance(value, str) and value in choices


def _ids(rows: list[dict], field: str, kind: str, issues: list[str], *, allow_null: bool = False) -> list[str]:
    values = [row.get(field) for row in rows if row.get(field) is not None]
    if not allow_null:
        _issue(issues, len(values) == len(rows), f"{kind}: every row requires {field}")
    normalized = [str(value) for value in values]
    duplicates = [
        value for value, count in Counter(normalized).items() if count > 1
    ]
    if duplicates:
        issues.append(f"{kind}: duplicate permanent identifiers: {', '.join(map(str, duplicates))}")
    pattern = ID_PATTERNS[kind]
    numbers = []
    for value in values:
        match = pattern.fullmatch(str(value))
        if not match:
            issues.append(f"{kind}: invalid identifier {value!r}")
        else:
            numbers.append(int(match.group(1)))
    if numbers and sorted(numbers) != list(range(1, max(numbers) + 1)):
        issues.append(f"{kind}: identifier sequence has a gap")
    return normalized

def _verify_path_partition(
    current_paths: dict[Any, dict[str, Any]],
    assignments: Counter[str],
    level: str,
    issues: list[str],
) -> None:
    for path, row in current_paths.items():
        count = assignments[path]
        if row.get("exclusion") is None:
            _issue(
                issues,
                count == 1,
                f"path primary assignment count is {count}, expected 1: {path}",
            )
            continue
        _issue(
            issues,
            count == 0,
            f"excluded path assigned to primary unit: {path}",
        )
        exclusion = row.get("exclusion")
        if not isinstance(exclusion, dict):
            issues.append(f"path exclusion must be an object: {path}")
            continue
        if exclusion.get("category") == "security_profile":
            _issue(
                issues,
                level == "off",
                f"security-profile path exclusion requires security level off: {path}",
            )
            _issue(
                issues,
                exclusion.get("authorizedBy") == "securityProfile:off",
                f"security-profile path exclusion has invalid authority: {path}",
            )
            _issue(
                issues,
                bool(exclusion.get("rationale"))
                and bool(exclusion.get("boundaryEvidence")),
                f"security-profile path exclusion lacks evidence: {path}",
            )
    for path in assignments:
        _issue(
            issues,
            path in current_paths,
            f"work unit references unknown baseline path: {path}",
        )


def _verify_canonical_graph(
    observations: list[dict[str, Any]],
    validations: list[dict[str, Any]],
    objections: list[dict[str, Any]],
    declared_profile: bool,
    level: str,
    allowed_sources: set[str],
    work_ids: set[str],
    issues: list[str],
) -> None:
    observation_ids = _ids(observations, "id", "observations", issues)
    finding_rows = [row for row in observations if row.get("findingId")]
    finding_ids = _ids(
        finding_rows, "findingId", "findings", issues, allow_null=True
    )
    validation_ids = _ids(validations, "id", "validations", issues)
    _ids(objections, "id", "objections", issues)
    observation_set = set(observation_ids)
    validation_set = set(validation_ids)
    canonical_targets = observation_set | set(finding_ids)
    duplicate_edges: dict[str, str] = {}
    for observation in observations:
        candidate_projection = dict(observation)
        candidate_projection["localId"] = observation.get("sourceLocalId")
        validate_candidate_schema(
            candidate_projection,
            f"{observation.get('id')}: observation",
            issues,
        )
        _issue(
            issues,
            observation.get("sourceAttempt") in allowed_sources,
            f"{observation.get('id')}: invalid or unimported sourceAttempt",
        )
        source_units = observation.get("sourceWorkUnits")
        _issue(
            issues,
            isinstance(source_units, list)
            and bool(source_units)
            and all(
                isinstance(item, str) and item in work_ids
                for item in source_units
            ),
            f"{observation.get('id')}: invalid sourceWorkUnits provenance",
        )
        disposition = observation.get("disposition")
        _issue(
            issues,
            _is_one_of(disposition, OBS_DISPOSITIONS),
            f"{observation.get('id')}: invalid observation disposition",
        )
        refs = observation.get("validationRefs", [])
        if not isinstance(refs, list):
            issues.append(
                f"{observation.get('id')}: validationRefs must be an array"
            )
            refs = []
        for reference in refs:
            _issue(
                issues,
                isinstance(reference, str) and reference in validation_set,
                f"orphaned validation reference {reference} "
                f"from {observation.get('id')}",
            )
        if disposition == "duplicate":
            duplicate_of = observation.get("duplicateOf")
            _issue(
                issues,
                isinstance(duplicate_of, str)
                and duplicate_of in canonical_targets
                and duplicate_of != observation.get("id"),
                f"{observation.get('id')}: invalid duplicate mapping",
            )
            if (
                isinstance(observation.get("id"), str)
                and isinstance(duplicate_of, str)
                and duplicate_of in observation_set
            ):
                duplicate_edges[observation["id"]] = duplicate_of
        if disposition == "withdrawn":
            _issue(
                issues,
                bool(observation.get("findingId") and observation.get("withdrawal")),
                f"{observation.get('id')}: invalid withdrawal mapping",
            )
        if disposition == "deferred_by_profile":
            deferral = observation.get("profileDeferral", {})
            _issue(
                issues,
                isinstance(deferral, dict)
                and level == "off"
                and observation.get("category") == "security"
                and deferral.get("securityLevel") == "off"
                and bool(deferral.get("reason")),
                f"{observation.get('id')}: invalid profile deferral",
            )
    for validation in validations:
        validation_projection = dict(validation)
        validation_projection["localId"] = validation.get("sourceLocalId")
        validation_projection["supportsCandidates"] = validation.get(
            "observationIds"
        )
        validate_validation_schema(
            validation_projection,
            f"{validation.get('id')}: validation",
            issues,
        )
        _issue(
            issues,
            validation.get("sourceAttempt") in allowed_sources,
            f"{validation.get('id')}: invalid or unimported sourceAttempt",
        )
        source_units = validation.get("workUnits")
        _issue(
            issues,
            isinstance(source_units, list)
            and bool(source_units)
            and all(
                isinstance(item, str) and item in work_ids
                for item in source_units
            ),
            f"{validation.get('id')}: invalid workUnits provenance",
        )
        validation_class = validation.get("validationClass")
        _issue(
            issues,
            validation.get("result") in VALIDATION_RESULTS,
            f"{validation.get('id')}: invalid validation result",
        )
        if declared_profile:
            _issue(
                issues,
                validation.get("securityLevel") == level,
                f"{validation.get('id')}: validation securityLevel mismatch",
            )
            _issue(
                issues,
                validation_class_allowed(level, str(validation_class)),
                f"{validation.get('id')}: validation class is not permitted "
                f"at security level {level}",
            )
        refs = validation.get("observationIds", [])
        if not isinstance(refs, list):
            issues.append(
                f"{validation.get('id')}: observationIds must be an array"
            )
            refs = []
        for reference in refs:
            _issue(
                issues,
                isinstance(reference, str) and reference in observation_set,
                f"{validation.get('id')}: orphaned observation reference {reference}",
            )
    reported_cycles: set[str] = set()
    for start in duplicate_edges:
        cursor = start
        path: set[str] = set()
        while cursor in duplicate_edges and cursor not in path:
            path.add(cursor)
            cursor = duplicate_edges[cursor]
        if cursor in path:
            cycle_key = "|".join(sorted(path))
            if cycle_key not in reported_cycles:
                reported_cycles.add(cycle_key)
                issues.append(
                    f"duplicate observation mapping contains a cycle: "
                    f"{sorted(path)}"
                )
    for objection in objections:
        refs = objection.get("candidateRefs", [])
        if not isinstance(refs, list):
            issues.append(
                f"{objection.get('id')}: candidateRefs must be an array"
            )
            refs = []
        for reference in refs:
            _issue(
                issues,
                isinstance(reference, str) and reference in observation_set,
                f"{objection.get('id')}: orphaned candidate reference {reference}",
            )
