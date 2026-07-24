"""Deterministic specialist packets and attempt-local result scaffolding."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .evidence import (
    load_sealed_attempt_manifest,
    load_sealed_unit_manifest,
    scope_is_valid,
    validate_reviewer_independence,
    validate_second_review_assignment,
    validate_second_review_payload,
)
from .errors import ReviewToolError
from .identifiers import attempt_token
from .io import (
    atomic_write,
    canonical_bytes,
    digest_bytes,
    load_json,
    load_jsonl,
    parse_json_bytes,
    safe_child,
)
from .policy import (
    CAPSULE_BYTE_WARNING,
    CAPSULE_LIST_FIELDS,
    PACKET_BYTE_WARNING,
)
from .references import verified_reference_bytes
from .result_schema import validate_candidate_schema, validate_validation_schema


class CapsuleFreshnessError(ReviewToolError):
    """A valid capsule that must be regenerated after an identity change."""


def _string_list(value: Any, label: str, issues: list[str]) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        issues.append(f"{label} must be an array of strings")
        return []
    return value


def _valid_evidence_location(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if not isinstance(value, dict):
        return False
    path = value.get("path")
    symbol = value.get("symbol")
    if not (
        (isinstance(path, str) and bool(path.strip()))
        or (isinstance(symbol, str) and bool(symbol.strip()))
    ):
        return False
    for field in ("startLine", "endLine"):
        line = value.get(field)
        if line is not None and (
            not isinstance(line, int) or isinstance(line, bool) or line < 1
        ):
            return False
    return True


def _evidence_list(
    value: Any,
    label: str,
    issues: list[str],
    assigned_scope: dict[str, Any],
    unit_scope: dict[str, set[str]],
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or not all(
        isinstance(item, dict)
        and isinstance(item.get("claim"), str)
        and bool(item["claim"].strip())
        and isinstance(item.get("scopeCovered"), dict)
        and isinstance(item.get("locations"), list)
        and bool(item["locations"])
        and all(_valid_evidence_location(location) for location in item["locations"])
        and scope_is_valid(item.get("scopeCovered"))
        for item in value
    ):
        issues.append(
            f"{label} must contain substantive scope, locations, and claim fields"
        )
        return []
    assigned_paths = set(assigned_scope.get("paths", []))
    assigned_symbols = set(assigned_scope.get("symbols", []))
    for item in value:
        covered = item["scopeCovered"]
        if covered == {"kind": "whole_unit"} and (
            assigned_paths != unit_scope["paths"]
            or assigned_symbols != unit_scope["symbols"]
        ):
            issues.append(
                f"{label} cannot claim whole_unit from a sliced assignment"
            )
        if covered.get("kind") == "items":
            for entry in covered.get("items", []):
                if (
                    not isinstance(entry, dict)
                    or entry.get("type") not in {"path", "symbol"}
                    or not isinstance(entry.get("value"), str)
                    or (
                        entry["type"] == "path"
                        and entry["value"] not in assigned_paths
                    )
                    or (
                        entry["type"] == "symbol"
                        and entry["value"] not in assigned_symbols
                    )
                ):
                    issues.append(f"{label} claims scope outside the assignment")
                    break
        for location in item["locations"]:
            if isinstance(location, str):
                if not any(
                    location == target or location.startswith(f"{target}:")
                    for target in assigned_paths | assigned_symbols
                ):
                    issues.append(
                        f"{label} contains an out-of-assignment location"
                    )
                    break
                continue
            path = location.get("path")
            symbol = location.get("symbol")
            if (
                (isinstance(path, str) and path not in assigned_paths)
                or (
                    isinstance(symbol, str)
                    and symbol not in assigned_symbols
                )
            ):
                issues.append(f"{label} contains an out-of-assignment location")
                break
    return value


def load_orientation_capsule(root: Path, unit_manifest: dict[str, Any]) -> dict[str, Any]:
    reference = unit_manifest.get("orientationCapsule")
    if not isinstance(reference, dict):
        raise ReviewToolError("unit manifest does not reference an orientation capsule")
    path = safe_child(root, reference.get("path", "invalid"))
    data = path.read_bytes()
    if digest_bytes(data) != reference.get("hash"):
        raise ReviewToolError("orientation capsule identity mismatch")
    capsule = parse_json_bytes(data, str(path))
    if not isinstance(capsule, dict):
        raise ReviewToolError("orientation capsule must contain an object")
    if capsule.get("specEpoch") != unit_manifest.get("specEpoch"):
        raise CapsuleFreshnessError("orientation capsule uses the wrong specification epoch")
    if capsule.get("subsystem") != unit_manifest.get("subsystem"):
        raise ReviewToolError("orientation capsule subsystem mismatch")
    run = load_json(root / "run.json")
    if capsule.get("specEpoch") != run.get("specEpoch"):
        raise CapsuleFreshnessError("orientation capsule uses the wrong specification epoch")
    if capsule.get("baselineContentSetHash") != run.get("baselineContentSetHash"):
        raise CapsuleFreshnessError("orientation capsule uses the wrong baseline content set")
    for field in (
        "capsuleId",
        "specEpoch",
        "subsystem",
        "role",
        "architectureHash",
        "referenceManifestHash",
    ):
        if not isinstance(capsule.get(field), str) or not capsule[field].strip():
            raise ReviewToolError(f"orientation capsule {field} must be a non-empty string")
    if not isinstance(capsule.get("baselineContentSetHash"), str):
        raise ReviewToolError("orientation capsule baselineContentSetHash must be a string")
    for field in CAPSULE_LIST_FIELDS:
        values = capsule.get(field)
        if not isinstance(values, list) or not all(
            isinstance(value, (str, dict)) for value in values
        ):
            raise ReviewToolError(f"orientation capsule {field} must be an array of strings or objects")
    architecture_path = root / "architecture.md"
    reference_path = root / "tooling/reference/manifest.json"
    if not architecture_path.is_file():
        raise ReviewToolError("review architecture.md is missing")
    if not reference_path.is_file():
        raise ReviewToolError("reference installation manifest is missing")
    if capsule.get("architectureHash") != digest_bytes(architecture_path.read_bytes()):
        raise CapsuleFreshnessError("orientation capsule uses a stale architecture identity")
    if capsule.get("referenceManifestHash") != digest_bytes(reference_path.read_bytes()):
        raise CapsuleFreshnessError("orientation capsule uses a stale reference identity")
    return capsule


def render_packet(root: Path, work_id: str, attempt_id: str) -> tuple[bytes, dict[str, Any]]:
    units = {row["id"]: row for row in load_jsonl(root / "work-units.jsonl")}
    unit = units.get(work_id)
    if unit is None:
        raise ReviewToolError(f"unknown work unit: {work_id}")
    attempt = next(
        (
            item
            for item in unit.get("reviewAttempts", [])
            if item.get("attemptId") == attempt_id
        ),
        None,
    )
    if attempt is None:
        raise ReviewToolError(f"unknown attempt: {work_id}/{attempt_id}")
    _require_executable_attempt(unit, attempt)
    run = load_json(root / "run.json")
    attempt_manifest = load_sealed_attempt_manifest(root, unit, attempt, run)
    unit_manifest = load_sealed_unit_manifest(root, unit, attempt_manifest)
    validate_second_review_assignment(unit, unit_manifest, attempt_manifest)
    capsule = load_orientation_capsule(root, unit_manifest)
    assigned_scope = attempt_manifest.get("assignedScope")
    if not isinstance(assigned_scope, dict):
        raise ReviewToolError("attempt manifest assignedScope must be an object")
    assigned_angles = assigned_scope.get("angles")
    if not isinstance(assigned_angles, list):
        raise ReviewToolError("attempt manifest assignedScope angles must be an array")

    reference_root = root / "tooling/reference"
    angle_names = []
    for number in assigned_angles:
        if not isinstance(number, int) or isinstance(number, bool) or not 1 <= number <= 10:
            raise ReviewToolError(f"invalid assigned angle: {number!r}")
        angle_names.append(f"angle-{number:02d}.md")
    schema_name = unit_manifest.get("outputSchema", "specialist-result-schema.md")
    if not isinstance(schema_name, str):
        raise ReviewToolError("unit manifest outputSchema must be a string")
    safe_child(reference_root, schema_name)
    reference_names = [
        "mandatory-specialist-block.md",
        *angle_names,
        schema_name,
    ]
    references = verified_reference_bytes(root, reference_names)
    common = references["mandatory-specialist-block.md"].decode("utf-8")
    angle_sections = [
        references[name].decode("utf-8").rstrip() for name in angle_names
    ]
    schema = references[schema_name].decode("utf-8")

    sections = [
        "# Specialist assignment",
        "",
        common.rstrip(),
        "",
        "## Assigned review references",
        "",
        "\n\n".join(angle_sections),
        "",
        "## Output schema",
        "",
        schema.rstrip(),
        "",
        "## Orientation capsule",
        "",
        "Use this capsule as an index. Verify all material claims against assigned source.",
        "",
        "```json",
        json.dumps(capsule, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "```",
        "",
        "## Immutable assignment",
        "",
        "```json",
        json.dumps(
            attempt_manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "```",
        "",
        "Do not proactively restart general review outside this assignment. Preserve incidental observations and record exact follow-up scope when widening is required.",
        "",
    ]
    packet = "\n".join(sections).encode()
    capsule_size = len(canonical_bytes(capsule))
    warnings = []
    if capsule_size > CAPSULE_BYTE_WARNING:
        warnings.append(
            f"orientation capsule is {capsule_size} bytes; "
            f"target at most {CAPSULE_BYTE_WARNING}"
        )
    if len(packet) > PACKET_BYTE_WARNING:
        warnings.append(
            f"specialist packet is {len(packet)} bytes; "
            f"target at most {PACKET_BYTE_WARNING}"
        )
    return packet, {
        "workId": work_id,
        "attemptId": attempt_id,
        "packetHash": digest_bytes(packet),
        "byteSize": len(packet),
        "assignedAngles": assigned_angles,
        "capsuleHash": unit_manifest["orientationCapsule"]["hash"],
        "warnings": warnings,
    }


def _require_executable_attempt(
    unit: dict[str, Any], attempt: dict[str, Any]
) -> None:
    label = f"{unit.get('id')}/{attempt.get('attemptId')}"
    if (
        attempt.get("status") != "assigned"
        or attempt.get("importDisposition") != "pending"
    ):
        raise ReviewToolError(
            f"{label}: packets and result scaffolds require an assigned, pending attempt"
        )


def write_packet(root: Path, work_id: str, attempt_id: str) -> dict[str, Any]:
    packet, metadata = render_packet(root, work_id, attempt_id)
    unit_rows = load_jsonl(root / "work-units.jsonl")
    unit = next(row for row in unit_rows if row["id"] == work_id)
    attempt = next(
        row for row in unit["reviewAttempts"] if row["attemptId"] == attempt_id
    )
    manifest = load_sealed_attempt_manifest(
        root, unit, attempt, load_json(root / "run.json")
    )
    unit_manifest = load_sealed_unit_manifest(root, unit, manifest)
    validate_second_review_assignment(unit, unit_manifest, manifest)
    target = safe_child(root, f"{manifest['outputDirectory']}/packet.md")
    atomic_write(target, packet)
    return {**metadata, "path": target.relative_to(root.resolve()).as_posix()}


def initialize_attempt_result(root: Path, work_id: str, attempt_id: str) -> dict[str, Any]:
    unit_rows = load_jsonl(root / "work-units.jsonl")
    unit = next((row for row in unit_rows if row.get("id") == work_id), None)
    if unit is None:
        raise ReviewToolError(f"unknown work unit: {work_id}")
    attempt = next(
        (row for row in unit.get("reviewAttempts", []) if row.get("attemptId") == attempt_id),
        None,
    )
    if attempt is None:
        raise ReviewToolError(f"unknown attempt: {work_id}/{attempt_id}")
    _require_executable_attempt(unit, attempt)
    manifest = load_sealed_attempt_manifest(
        root, unit, attempt, load_json(root / "run.json")
    )
    unit_manifest = load_sealed_unit_manifest(root, unit, manifest)
    validate_second_review_assignment(unit, unit_manifest, manifest)
    result_path = safe_child(root, f"{manifest['outputDirectory']}/result.json")
    validations_path = result_path.with_name("validations.jsonl")
    if result_path.exists() and validations_path.exists():
        raise ReviewToolError("attempt output already exists")
    result = {
        "workId": work_id,
        "attemptId": attempt_id,
        "reviewerExecutionId": manifest.get("reviewerExecutionId"),
        "reviewerPrincipalId": manifest.get("reviewerPrincipalId"),
        "packetType": manifest.get("packetType"),
        "unitManifestHash": manifest.get("unitManifestHash"),
        "attemptManifestHash": attempt.get("manifestHash"),
        "specEpoch": manifest.get("specEpoch"),
        "securityLevel": manifest.get("securityLevel"),
        "status": "partial",
        "inspected": {"paths": [], "symbols": []},
        "notInspected": {
            "paths": manifest.get("assignedScope", {}).get("paths", []),
            "symbols": manifest.get("assignedScope", {}).get("symbols", []),
        },
        "angleDispositions": {},
        "secondReviewResults": [],
        "candidates": [],
        "residualUncertainty": [],
        "remainingScope": {
            "paths": manifest.get("assignedScope", {}).get("paths", []),
            "symbols": manifest.get("assignedScope", {}).get("symbols", []),
            "angles": manifest.get("assignedScope", {}).get("angles", []),
        },
    }
    repaired = result_path.exists() or validations_path.exists()
    if not result_path.exists():
        atomic_write(result_path, canonical_bytes(result))
    if not validations_path.exists():
        atomic_write(validations_path, b"")
    return {
        "result": result_path.relative_to(root.resolve()).as_posix(),
        "validations": validations_path.relative_to(root.resolve()).as_posix(),
        "repaired": repaired,
    }


def check_attempt_result(root: Path, work_id: str, attempt_id: str) -> dict[str, Any]:
    unit_rows = load_jsonl(root / "work-units.jsonl")
    unit = next((row for row in unit_rows if row.get("id") == work_id), None)
    if unit is None:
        raise ReviewToolError(f"unknown work unit: {work_id}")
    attempt = next(
        (row for row in unit.get("reviewAttempts", []) if row.get("attemptId") == attempt_id),
        None,
    )
    if attempt is None:
        raise ReviewToolError(f"unknown attempt: {work_id}/{attempt_id}")
    run = load_json(root / "run.json")
    manifest = load_sealed_attempt_manifest(root, unit, attempt, run)
    unit_manifest = load_sealed_unit_manifest(root, unit, manifest)
    validate_second_review_assignment(unit, unit_manifest, manifest)
    result = load_json(safe_child(root, f"{manifest['outputDirectory']}/result.json"))
    validations = load_jsonl(
        safe_child(root, f"{manifest['outputDirectory']}/validations.jsonl")
    )
    return validate_attempt_result_data(
        root, run, unit, attempt, manifest, result, validations
    )


def _validate_result_header(
    unit: dict[str, Any],
    attempt: dict[str, Any],
    manifest: dict[str, Any],
    result: dict[str, Any],
    issues: list[str],
) -> None:
    expected = {
        "workId": str(unit.get("id")),
        "attemptId": str(attempt.get("attemptId")),
        "reviewerExecutionId": manifest.get("reviewerExecutionId"),
        "reviewerPrincipalId": manifest.get("reviewerPrincipalId"),
        "packetType": manifest.get("packetType"),
        "unitManifestHash": manifest.get("unitManifestHash"),
        "attemptManifestHash": attempt.get("manifestHash"),
        "specEpoch": manifest.get("specEpoch"),
        "securityLevel": manifest.get("securityLevel"),
    }
    for field, value in expected.items():
        if result.get(field) != value:
            issues.append(f"{field} mismatch")
    status = result.get("status")
    if not isinstance(status, str) or status not in {
        "partial",
        "complete",
        "blocked",
    }:
        issues.append("result status is invalid")
    for field in ("secondReviewResults", "candidates", "residualUncertainty"):
        if not isinstance(result.get(field), list):
            issues.append(f"{field} must be an array")


def _validate_angle_results(
    manifest: dict[str, Any],
    unit_manifest: dict[str, Any],
    result: dict[str, Any],
    issues: list[str],
) -> dict[str, Any]:
    assigned_scope = manifest.get("assignedScope", {})
    if not isinstance(assigned_scope, dict):
        issues.append("assignedScope must be an object")
        assigned_scope = {}
    assigned_angles = assigned_scope.get("angles", [])
    if not isinstance(assigned_angles, list):
        issues.append("assignedScope angles must be an array")
        assigned_angles = []
    assigned = {str(value) for value in assigned_angles}
    dispositions = result.get("angleDispositions", {})
    if not isinstance(dispositions, dict):
        issues.append("angleDispositions must be an object")
        dispositions = {}
    disposition_ids = set(dispositions)
    if not disposition_ids <= assigned:
        issues.append("result dispositions include unassigned angles")
    for number, disposition in dispositions.items():
        if not isinstance(disposition, dict):
            issues.append(f"angle {number} must be an object")
            continue
        status = disposition.get("status")
        if not isinstance(status, str) or status not in {
            "reviewed",
            "not_applicable",
            "blocked",
        }:
            issues.append(f"angle {number} has an invalid status")
        evidence = disposition.get("evidence", [])
        if not isinstance(evidence, list) or not all(
            isinstance(item, dict) for item in evidence
        ):
            issues.append(f"angle {number} evidence must be an array of objects")
        elif status in {"reviewed", "not_applicable"}:
            _evidence_list(
                evidence,
                f"angle {number} evidence",
                issues,
                assigned_scope,
                {
                    "paths": {
                        item.get("path")
                        for item in unit_manifest.get("paths", [])
                        if isinstance(item, dict)
                        and isinstance(item.get("path"), str)
                    },
                    "symbols": {
                        value
                        for item in unit_manifest.get("symbols", [])
                        if isinstance(item, (str, dict))
                        for value in [(
                            item
                            if isinstance(item, str)
                            else item.get("symbol", item.get("value"))
                        )]
                        if isinstance(value, str)
                    },
                },
            )
    if result.get("status") != "complete":
        return assigned_scope
    if disposition_ids != assigned:
        issues.append("complete result does not disposition every assigned angle")
    for number, disposition in dispositions.items():
        if not isinstance(disposition, dict):
            issues.append(f"complete angle {number} must be an object")
            continue
        if disposition.get("status") not in {"reviewed", "not_applicable"}:
            issues.append(f"complete angle {number} has an invalid status")
    return assigned_scope


def _validate_inspection_scope(
    assigned_scope: dict[str, Any],
    result: dict[str, Any],
    issues: list[str],
) -> None:
    for field in ("inspected", "notInspected", "remainingScope"):
        if not isinstance(result.get(field), dict):
            issues.append(f"{field} must be an object")
    inspected = result.get("inspected", {})
    not_inspected = result.get("notInspected", {})
    remaining = result.get("remainingScope", {})
    inspected_values: dict[str, list[str]] = {}
    not_inspected_values: dict[str, list[str]] = {}
    remaining_values: dict[str, list[str]] = {}
    for field in ("paths", "symbols"):
        assigned_values = _string_list(
            assigned_scope.get(field, []), f"assignedScope {field}", issues
        )
        inspected_values[field] = _string_list(
            inspected.get(field, []) if isinstance(inspected, dict) else [],
            f"inspected {field}",
            issues,
        )
        not_inspected_values[field] = _string_list(
            not_inspected.get(field, [])
            if isinstance(not_inspected, dict)
            else [],
            f"notInspected {field}",
            issues,
        )
        remaining_values[field] = _string_list(
            remaining.get(field, []) if isinstance(remaining, dict) else [],
            f"remainingScope {field}",
            issues,
        )
        inspected_set = set(inspected_values[field])
        not_inspected_set = set(not_inspected_values[field])
        if (
            len(inspected_values[field]) != len(inspected_set)
            or len(not_inspected_values[field]) != len(not_inspected_set)
            or inspected_set & not_inspected_set
            or inspected_set | not_inspected_set != set(assigned_values)
        ):
            issues.append(
                f"inspected and notInspected {field} must exactly partition assigned scope"
            )
        if set(remaining_values[field]) != not_inspected_set:
            issues.append(
                f"remainingScope {field} must exactly equal notInspected {field}"
            )
    remaining_angles = (
        remaining.get("angles", []) if isinstance(remaining, dict) else []
    )
    if not isinstance(remaining_angles, list) or not all(
        isinstance(item, int) and not isinstance(item, bool)
        for item in remaining_angles
    ) or len(remaining_angles) != len(set(remaining_angles)):
        issues.append("remainingScope angles must be unique integers")
        remaining_angles = []
    assigned_angles = set(assigned_scope.get("angles", []))
    dispositions = result.get("angleDispositions", {})
    resolved_angles = {
        int(number)
        for number, disposition in dispositions.items()
        if str(number).isdigit()
        and isinstance(disposition, dict)
        and disposition.get("status") in {"reviewed", "not_applicable"}
    } if isinstance(dispositions, dict) else set()
    if set(remaining_angles) != assigned_angles - resolved_angles:
        issues.append(
            "remainingScope angles must exactly identify unresolved assigned angles"
        )
    status = result.get("status")
    if status == "complete" and (
        any(not_inspected_values.values())
        or any(remaining_values.values())
        or remaining_angles
    ):
        issues.append("complete result cannot retain remaining scope")
    if isinstance(status, str) and status in {"partial", "blocked"} and not (
        any(remaining_values.values()) or remaining_angles
    ):
        issues.append("partial or blocked result requires exact remaining scope")


def _validate_second_review_result(
    root: Path,
    run: dict[str, Any],
    unit: dict[str, Any],
    manifest: dict[str, Any],
    result: dict[str, Any],
    candidates: list[Any],
    issues: list[str],
    *,
    validate_current_evidence: bool,
) -> None:
    if manifest.get("packetType") != "independent_second_review":
        if result.get("secondReviewResults") != []:
            issues.append(
                "primary result secondReviewResults must be an empty array"
            )
        return
    second_results = (
        result.get("secondReviewResults", [])
        if isinstance(result.get("secondReviewResults"), list)
        else []
    )
    if result.get("status") != "complete":
        if second_results:
            issues.append(
                "partial or blocked second review cannot claim a structured completion"
            )
        return
    if len(second_results) != 1:
        issues.append("complete second review requires exactly one structured result")
        return
    second = second_results[0]
    if not isinstance(second, dict):
        issues.append("second-review result must be an object")
        return
    requirement_id = manifest.get("secondReviewRequirementId")
    if second.get("requirementId") != requirement_id:
        issues.append("second-review requirement mismatch")
        return
    requirements = unit.get("requiredSecondReviews")
    if not isinstance(requirements, list):
        issues.append("requiredSecondReviews must be an array")
        return
    requirement = next(
        (
            item
            for item in requirements
            if isinstance(item, dict) and item.get("id") == requirement_id
        ),
        None,
    )
    if requirement is None:
        issues.append("second-review manifest names no current requirement")
        return
    try:
        validate_second_review_payload(
            second,
            requirement,
            candidate_ids={
                str(item.get("localId"))
                for item in candidates
                if isinstance(item, dict)
            },
        )
        if validate_current_evidence:
            validate_reviewer_independence(
                root,
                run,
                unit,
                requirement,
                independent_ids=manifest.get("independentFromAttemptIds"),
                evidence_set_hash=manifest.get("primaryEvidenceSetHash"),
                reviewer_principal_id=result.get("reviewerPrincipalId"),
                reviewer_execution_id=result.get("reviewerExecutionId"),
            )
    except ReviewToolError as exc:
        issues.append(str(exc))


def _validate_local_evidence_graph(
    attempt_id: str,
    manifest: dict[str, Any],
    candidates: list[Any],
    validations: list[dict[str, Any]],
    issues: list[str],
) -> None:
    try:
        token = attempt_token(attempt_id)
    except ReviewToolError as exc:
        issues.append(str(exc))
        token = "AINVALID"
    candidate_ids: list[str] = []
    for candidate in candidates:
        local_id = candidate.get("localId") if isinstance(candidate, dict) else None
        if not isinstance(candidate, dict):
            issues.append("candidate must be an object")
            continue
        validate_candidate_schema(
            candidate, f"candidate {local_id}", issues
        )
        if not re.fullmatch(rf"CAND-{token}-\d{{3}}", str(local_id)):
            issues.append(f"invalid local candidate identifier: {local_id}")
        if isinstance(local_id, str):
            candidate_ids.append(local_id)
    if len(candidate_ids) != len(set(candidate_ids)):
        issues.append("duplicate local candidate identifier")
    permitted_classes = set(
        _string_list(
            manifest.get("permittedValidationClasses", []),
            "permittedValidationClasses",
            issues,
        )
    )
    validation_ids: list[str] = []
    for validation in validations:
        local_id = validation.get("localId")
        validate_validation_schema(
            validation, f"validation {local_id}", issues
        )
        if not re.fullmatch(rf"AVAL-{token}-\d{{3}}", str(local_id)):
            issues.append(f"invalid local validation identifier: {local_id}")
        if isinstance(local_id, str):
            validation_ids.append(local_id)
        validation_class = validation.get("validationClass")
        if (
            not isinstance(validation_class, str)
            or validation_class not in permitted_classes
        ):
            issues.append(f"validation class is not permitted: {validation_class}")
        supports = _string_list(
            validation.get("supportsCandidates", []),
            f"validation {local_id} supportsCandidates",
            issues,
        )
        unknown = set(supports) - set(candidate_ids)
        if unknown:
            issues.append(
                f"validation references unknown candidates: {sorted(unknown)}"
            )
    if len(validation_ids) != len(set(validation_ids)):
        issues.append("duplicate local validation identifier")
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        refs = _string_list(
            candidate.get("validationRefs", []),
            f"candidate {candidate.get('localId')} validationRefs",
            issues,
        )
        unknown = set(refs) - set(validation_ids)
        if unknown:
            issues.append(
                f"candidate references unknown validations: {sorted(unknown)}"
            )


def validate_attempt_result_data(
    root: Path,
    run: dict[str, Any],
    unit: dict[str, Any],
    attempt: dict[str, Any],
    manifest: dict[str, Any],
    result: Any,
    validations: list[dict[str, Any]],
    *,
    validate_current_evidence: bool = True,
) -> dict[str, Any]:
    """Apply the one canonical result preflight used by check and import."""
    issues: list[str] = []
    if not isinstance(result, dict):
        return {"ok": False, "issues": ["result.json must contain an object"]}
    attempt_id = str(attempt.get("attemptId"))
    _validate_result_header(unit, attempt, manifest, result, issues)
    try:
        unit_manifest = load_sealed_unit_manifest(root, unit, manifest)
    except ReviewToolError as exc:
        issues.append(str(exc))
        unit_manifest = {}
    assigned_scope = _validate_angle_results(
        manifest, unit_manifest, result, issues
    )
    _validate_inspection_scope(assigned_scope, result, issues)
    candidates = (
        result.get("candidates", [])
        if isinstance(result.get("candidates"), list)
        else []
    )
    _validate_second_review_result(
        root,
        run,
        unit,
        manifest,
        result,
        candidates,
        issues,
        validate_current_evidence=validate_current_evidence,
    )
    _validate_local_evidence_graph(
        attempt_id, manifest, candidates, validations, issues
    )
    return {"ok": not issues, "issues": issues}
