"""Sealed attempt evidence, specification epochs, and reviewer independence."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any

from . import REVIEW_SPEC_VERSION
from .errors import ReviewToolError
from .io import (
    canonical_identity,
    digest_bytes,
    load_json,
    load_jsonl,
    normalize_relative,
    parse_json_bytes,
    parse_jsonl_bytes,
    safe_child,
)
from .security import SECURITY_LEVELS, permitted_validation_classes


@dataclass
class EvidenceCache:
    """Per-operation cache for immutable, identity-keyed evidence."""

    attempt_manifests: dict[tuple[str, str], dict[str, Any]] = dataclass_field(
        default_factory=dict
    )
    unit_manifests: dict[tuple[str, str], dict[str, Any]] = dataclass_field(
        default_factory=dict
    )
    artifacts: dict[
        tuple[str, str, str], tuple[dict[str, Any], list[dict[str, Any]]]
    ] = dataclass_field(default_factory=dict)


def validate_review_spec_version(value: Any, *, label: str = "run.json") -> int:
    if value is None:
        raise ReviewToolError(f"{label} reviewSpecVersion is required")
    if not isinstance(value, int) or isinstance(value, bool):
        raise ReviewToolError(f"{label} reviewSpecVersion must be an integer")
    if value != REVIEW_SPEC_VERSION:
        raise ReviewToolError(
            f"{label} reviewSpecVersion {value} is unsupported; "
            "re-initialize the review with this tool"
        )
    return value


def validate_output_directory(root: Path, value: Any, *, label: str) -> str:
    """Require attempt-local writes to remain below the agents namespace."""
    if not isinstance(value, str):
        raise ReviewToolError(f"{label}: outputDirectory is required")
    normalized = normalize_relative(value)
    parts = normalized.split("/")
    if (
        len(parts) < 2
        or parts[0] != "agents"
        or parts[1] == "FINAL-AUDIT"
    ):
        raise ReviewToolError(
            f"{label}: outputDirectory must be below the agents directory "
            "and outside its reserved final-audit namespace"
        )
    safe_child(root, f"{normalized}/result.json")
    return normalized


def _scope_items(scope: dict[str, Any]) -> set[tuple[str, str]] | None:
    if scope.get("kind") != "items":
        return None
    items = scope.get("items")
    if not isinstance(items, list):
        return None
    parsed: list[tuple[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            return None
        item_type = item.get("type")
        value = item.get("value")
        if (
            not isinstance(item_type, str)
            or item_type not in {"path", "symbol"}
            or not isinstance(value, str)
            or not value.strip()
        ):
            return None
        parsed.append((item_type, value))
    if len(parsed) != len(set(parsed)):
        return None
    return set(parsed)


def assigned_scope_intersects(
    assigned_scope: dict[str, Any],
    requirement: dict[str, Any],
) -> bool:
    """Whether one primary assignment can contribute to a second-review requirement."""
    if not isinstance(assigned_scope, dict) or not isinstance(requirement, dict):
        return False
    angle = requirement.get("angle")
    angles = assigned_scope.get("angles")
    if not isinstance(angles, list) or angle not in angles:
        return False
    required_scope = requirement.get("scope", {})
    if not isinstance(required_scope, dict):
        return False
    paths = assigned_scope.get("paths")
    symbols = assigned_scope.get("symbols")
    paths = paths if isinstance(paths, list) else []
    symbols = symbols if isinstance(symbols, list) else []
    if required_scope.get("kind") == "whole_unit":
        return bool(paths or symbols)
    required_items = _scope_items(required_scope)
    if required_items is None:
        return False
    assigned_items = {
        *(("path", str(value)) for value in paths),
        *(("symbol", str(value)) for value in symbols),
    }
    return bool(required_items & assigned_items)


def _attempt_rows(unit: dict[str, Any]) -> list[dict[str, Any]]:
    attempts = unit.get("reviewAttempts")
    if not isinstance(attempts, list):
        return []
    return [item for item in attempts if isinstance(item, dict)]


def primary_evidence_projection(
    root: Path,
    unit: dict[str, Any],
    requirement: dict[str, Any],
    *,
    cache: EvidenceCache | None = None,
) -> list[dict[str, Any]]:
    """Project every imported intersecting primary attempt in canonical order."""
    run = load_json(root / "run.json")
    projection: list[dict[str, Any]] = []
    for attempt in _attempt_rows(unit):
        if attempt.get("packetType") != "primary_semantic":
            continue
        if attempt.get("importDisposition") != "imported":
            continue
        manifest = load_sealed_attempt_manifest(root, unit, attempt, cache=cache)
        assigned_scope = manifest.get("assignedScope", {})
        if not assigned_scope_intersects(assigned_scope, requirement):
            continue
        if manifest.get("specEpoch") != run.get("specEpoch"):
            continue
        verify_imported_attempt_artifacts(
            root, unit, attempt, manifest, cache=cache
        )
        evidence_hash = attempt.get("attemptEvidenceHash")
        if not evidence_hash:
            raise ReviewToolError(
                f"{unit.get('id')}/{attempt.get('attemptId')}: imported primary attempt lacks attemptEvidenceHash"
            )
        projection.append(
            {
                "attemptId": attempt.get("attemptId"),
                "manifestHash": attempt.get("manifestHash"),
                "assignedScope": assigned_scope,
                "resultHash": attempt.get("resultHash"),
                "attemptEvidenceHash": evidence_hash,
                "specEpoch": manifest.get("specEpoch"),
            }
        )
    return sorted(projection, key=lambda item: str(item["attemptId"]).encode("utf-8"))


def validate_attempt_manifest_data(
    root: Path,
    unit: dict[str, Any],
    attempt: dict[str, Any],
    manifest: dict[str, Any],
    run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one attempt assignment independently of where it was loaded."""
    label = f"{unit.get('id')}/{attempt.get('attemptId')}"
    expected_fields = {
        "workId": unit.get("id"),
        "attemptId": attempt.get("attemptId"),
        "packetType": attempt.get("packetType"),
        "reviewerExecutionId": attempt.get("reviewerExecutionId"),
        "unitManifestHash": attempt.get("unitManifestHash"),
    }
    for field, expected in expected_fields.items():
        if manifest.get(field) != expected:
            raise ReviewToolError(f"{label}: attempt manifest {field} mismatch")
    required_fields = {
        "reviewerPrincipalId",
        "reviewerExecutionId",
        "reviewerReuseMode",
        "reviewerBatchId",
        "reviewSpecVersion",
        "specEpoch",
        "assignedScope",
        "secondReviewRequirementId",
        "independentFromAttemptIds",
        "primaryEvidenceSetHash",
        "outputDirectory",
    }
    missing_fields = required_fields - set(manifest)
    if missing_fields:
        raise ReviewToolError(
            f"{label}: attempt manifest missing required fields: "
            f"{sorted(missing_fields)}"
        )
    execution = manifest.get("reviewerExecutionId")
    if not isinstance(execution, str) or not execution.strip():
        raise ReviewToolError(f"{label}: reviewerExecutionId is required")
    principal = attempt.get("reviewerPrincipalId")
    if not isinstance(principal, str) or not principal.strip():
        raise ReviewToolError(f"{label}: reviewerPrincipalId is required")
    if manifest.get("reviewerPrincipalId") != principal:
        raise ReviewToolError(f"{label}: attempt manifest reviewerPrincipalId mismatch")
    validate_review_spec_version(
        manifest.get("reviewSpecVersion"), label=f"{label} attempt manifest"
    )
    assigned_scope = manifest.get("assignedScope")
    if not isinstance(assigned_scope, dict):
        raise ReviewToolError(f"{label}: assignedScope must be an object")
    for field in ("paths", "symbols"):
        values = assigned_scope.get(field)
        if (
            not isinstance(values, list)
            or not all(isinstance(item, str) and bool(item.strip()) for item in values)
            or len(values) != len(set(values))
        ):
            raise ReviewToolError(
                f"{label}: assignedScope {field} must contain unique non-empty strings"
            )
    angles = assigned_scope.get("angles")
    if (
        not isinstance(angles, list)
        or not all(
            isinstance(item, int)
            and not isinstance(item, bool)
            and 1 <= item <= 10
            for item in angles
        )
        or len(angles) != len(set(angles))
    ):
        raise ReviewToolError(
            f"{label}: assignedScope angles must be unique integers from 1 through 10"
        )
    if not angles or not (
        assigned_scope.get("paths") or assigned_scope.get("symbols")
    ):
        raise ReviewToolError(
            f"{label}: assignedScope requires at least one angle and path or symbol"
        )
    validate_output_directory(root, manifest.get("outputDirectory"), label=label)
    reuse_mode = manifest.get("reviewerReuseMode")
    if not isinstance(reuse_mode, str) or reuse_mode not in {
        "cold",
        "warm_batch",
    }:
        raise ReviewToolError(f"{label}: reviewerReuseMode is required and must be valid")
    batch_id = manifest.get("reviewerBatchId")
    if reuse_mode == "cold" and batch_id is not None:
        raise ReviewToolError(f"{label}: cold reviewer reuse requires null reviewerBatchId")
    if reuse_mode == "warm_batch" and (
        not isinstance(batch_id, str) or not batch_id.strip()
    ):
        raise ReviewToolError(
            f"{label}: warm reviewer reuse requires a non-empty reviewerBatchId"
        )
    packet_type = manifest.get("packetType")
    if not isinstance(packet_type, str) or packet_type not in {
        "primary_semantic",
        "independent_second_review",
    }:
        raise ReviewToolError(f"{label}: packetType is invalid")
    independent_ids = manifest.get("independentFromAttemptIds")
    if not isinstance(independent_ids, list) or not all(
        isinstance(item, str) and bool(item.strip()) for item in independent_ids
    ):
        raise ReviewToolError(
            f"{label}: independentFromAttemptIds must be an array of strings"
        )
    if packet_type == "primary_semantic":
        if manifest.get("secondReviewRequirementId") is not None:
            raise ReviewToolError(
                f"{label}: primary attempt cannot name a second-review requirement"
            )
        if independent_ids or manifest.get("primaryEvidenceSetHash") is not None:
            raise ReviewToolError(
                f"{label}: primary attempt cannot claim second-review evidence"
            )
    if run is not None:
        run_version = validate_review_spec_version(run.get("reviewSpecVersion"))
        if manifest.get("reviewSpecVersion") != run_version:
            raise ReviewToolError(f"{label}: attempt manifest reviewSpecVersion mismatch")
        epoch = manifest.get("specEpoch")
        if not isinstance(epoch, str) or epoch != run.get("specEpoch"):
            raise ReviewToolError(f"{label}: attempt manifest specEpoch mismatch")
        profile = run.get("securityProfile")
        if not isinstance(profile, dict) or profile.get("level") not in SECURITY_LEVELS:
            raise ReviewToolError("run.json securityProfile is required and must be valid")
        level = str(profile["level"])
        if manifest.get("securityLevel") != level:
            raise ReviewToolError(f"{label}: attempt manifest securityLevel mismatch")
        if manifest.get("permittedValidationClasses") != permitted_validation_classes(
            level
        ):
            raise ReviewToolError(
                f"{label}: attempt manifest validation classes do not match security level"
            )
        if reuse_mode == "warm_batch":
            if packet_type != "independent_second_review":
                raise ReviewToolError(
                    f"{label}: warm reviewer reuse is limited to "
                    "independent second reviews"
                )
            capabilities = run.get("specialistCapabilities")
            if (
                not isinstance(capabilities, dict)
                or capabilities.get("stableReviewerLineage") is not True
            ):
                raise ReviewToolError(
                    f"{label}: warm reviewer reuse requires stable reviewer lineage"
                )
    return manifest


def load_sealed_attempt_manifest(
    root: Path,
    unit: dict[str, Any],
    attempt: dict[str, Any],
    run: dict[str, Any] | None = None,
    *,
    cache: EvidenceCache | None = None,
) -> dict[str, Any]:
    """Load an attempt assignment only after verifying its immutable identity."""
    label = f"{unit.get('id')}/{attempt.get('attemptId')}"
    cache_key = (str(attempt.get("manifest")), str(attempt.get("manifestHash")))
    if cache is not None and cache_key in cache.attempt_manifests:
        manifest = cache.attempt_manifests[cache_key]
    else:
        path = safe_child(root, attempt.get("manifest", "invalid"))
        if not path.is_file():
            raise ReviewToolError(f"{label}: attempt manifest is missing")
        data = path.read_bytes()
        if digest_bytes(data) != attempt.get("manifestHash"):
            raise ReviewToolError(f"{label}: attempt manifest identity mismatch")
        manifest = parse_json_bytes(data, str(path))
        if not isinstance(manifest, dict):
            raise ReviewToolError(f"{label}: attempt manifest must be an object")
        if cache is not None:
            cache.attempt_manifests[cache_key] = manifest
    return validate_attempt_manifest_data(root, unit, attempt, manifest, run)


def load_sealed_unit_manifest(
    root: Path,
    unit: dict[str, Any],
    attempt_manifest: dict[str, Any] | None = None,
    *,
    cache: EvidenceCache | None = None,
) -> dict[str, Any]:
    """Load the authoritative unit assignment and verify every available pin."""
    reference = (
        attempt_manifest.get("unitManifest")
        if attempt_manifest is not None
        else unit.get("currentManifest")
    )
    path = safe_child(root, reference or "invalid")
    if not path.is_file():
        raise ReviewToolError(f"{unit.get('id')}: unit manifest is missing")
    data = path.read_bytes()
    manifest_hash = digest_bytes(data)
    expected = (
        attempt_manifest.get("unitManifestHash")
        if attempt_manifest is not None
        else next(
            (
                entry.get("hash")
                for entry in reversed(
                    unit.get("manifestHistory")
                    if isinstance(unit.get("manifestHistory"), list)
                    else []
                )
                if isinstance(entry, dict)
                if entry.get("path") == reference
            ),
            None,
        )
    )
    if expected != manifest_hash:
        raise ReviewToolError(f"{unit.get('id')}: unit manifest identity mismatch")
    cache_key = (str(reference), str(expected))
    if cache is not None and cache_key in cache.unit_manifests:
        manifest = cache.unit_manifests[cache_key]
    else:
        manifest = parse_json_bytes(data, str(path))
        if not isinstance(manifest, dict):
            raise ReviewToolError(f"{unit.get('id')}: unit manifest must be an object")
        if cache is not None:
            cache.unit_manifests[cache_key] = manifest
    if manifest.get("workId") != unit.get("id"):
        raise ReviewToolError(f"{unit.get('id')}: unit manifest workId mismatch")
    validate_review_spec_version(
        manifest.get("reviewSpecVersion"),
        label=f"{unit.get('id')} unit manifest",
    )
    return manifest


def _manifest_symbols(unit_manifest: dict[str, Any]) -> list[str]:
    symbols: list[str] = []
    for item in unit_manifest.get("symbols", []):
        if isinstance(item, str):
            symbols.append(item)
        elif isinstance(item, dict):
            value = item.get("symbol", item.get("value"))
            if isinstance(value, str):
                symbols.append(value)
    return symbols


def validate_second_review_assignment(
    unit: dict[str, Any],
    unit_manifest: dict[str, Any],
    attempt_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Bind every attempt scope to its unit and second reviews to one requirement."""
    assigned = attempt_manifest.get("assignedScope", {})
    packet_type = attempt_manifest.get("packetType")
    if packet_type == "primary_semantic":
        manifest_paths = {
            item.get("path")
            for item in unit_manifest.get("paths", [])
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }
        manifest_symbols = set(_manifest_symbols(unit_manifest))
        required_angles = set(unit_manifest.get("requiredAngleDispositions", []))
        if (
            not set(assigned.get("paths", [])) <= manifest_paths
            or not set(assigned.get("symbols", [])) <= manifest_symbols
            or not set(assigned.get("angles", [])) <= required_angles
        ):
            raise ReviewToolError(
                f"{unit.get('id')}/{attempt_manifest.get('attemptId')}: "
                "primary assignedScope exceeds the sealed unit manifest"
            )
        return {}
    if packet_type != "independent_second_review":
        return {}
    requirement_id = attempt_manifest.get("secondReviewRequirementId")
    requirements = unit.get("requiredSecondReviews")
    if not isinstance(requirements, list):
        raise ReviewToolError(
            f"{unit.get('id')}: requiredSecondReviews must be an array"
        )
    requirement = next(
        (
            item
            for item in requirements
            if isinstance(item, dict) and item.get("id") == requirement_id
        ),
        None,
    )
    if requirement is None:
        raise ReviewToolError(
            f"{unit.get('id')}/{attempt_manifest.get('attemptId')}: "
            "second-review manifest names no current requirement"
        )
    expected_paths: list[str]
    expected_symbols: list[str]
    required_scope = requirement.get("scope")
    if required_scope == {"kind": "whole_unit"}:
        expected_paths = list(unit.get("paths", []))
        expected_symbols = _manifest_symbols(unit_manifest)
    else:
        items = _scope_items(required_scope) if isinstance(required_scope, dict) else None
        if items is None:
            raise ReviewToolError(
                f"{unit.get('id')}/{requirement_id}: requirement scope is malformed"
            )
        expected_paths = sorted(value for kind, value in items if kind == "path")
        expected_symbols = sorted(value for kind, value in items if kind == "symbol")
    if (
        sorted(assigned.get("paths", [])) != sorted(expected_paths)
        or sorted(assigned.get("symbols", [])) != sorted(expected_symbols)
        or assigned.get("angles") != [requirement.get("angle")]
    ):
        raise ReviewToolError(
            f"{unit.get('id')}/{attempt_manifest.get('attemptId')}: "
            "second-review assignedScope does not exactly match its requirement"
        )
    return requirement


def missing_primary_scope(
    root: Path,
    run: dict[str, Any],
    unit: dict[str, Any],
    *,
    cache: EvidenceCache | None = None,
) -> dict[int, dict[str, list[str]]]:
    """Return current required scope not covered by surviving imported primaries."""
    unit_manifest = load_sealed_unit_manifest(root, unit, cache=cache)
    required_paths = {
        item.get("path")
        for item in unit_manifest.get("paths", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    required_symbols = set(_manifest_symbols(unit_manifest))
    required_angles = {
        item
        for item in unit_manifest.get("requiredAngleDispositions", [])
        if isinstance(item, int) and not isinstance(item, bool)
    }
    covered = {
        angle: {"paths": set(), "symbols": set()} for angle in required_angles
    }
    for attempt in _attempt_rows(unit):
        if (
            attempt.get("packetType") != "primary_semantic"
            or attempt.get("importDisposition") != "imported"
        ):
            continue
        manifest = load_sealed_attempt_manifest(
            root, unit, attempt, run, cache=cache
        )
        validate_second_review_assignment(unit, unit_manifest, manifest)
        result, _ = verify_imported_attempt_artifacts(
            root, unit, attempt, manifest, cache=cache
        )
        inspected = result.get("inspected")
        dispositions = result.get("angleDispositions")
        if not isinstance(inspected, dict) or not isinstance(dispositions, dict):
            continue
        inspected_paths = {
            item for item in inspected.get("paths", []) if isinstance(item, str)
        }
        inspected_symbols = {
            item for item in inspected.get("symbols", []) if isinstance(item, str)
        }
        source_epoch = manifest.get("specEpoch")
        for angle in manifest.get("assignedScope", {}).get("angles", []):
            if angle not in required_angles:
                continue
            disposition = dispositions.get(str(angle))
            if (
                not isinstance(disposition, dict)
                or disposition.get("status") not in {"reviewed", "not_applicable"}
            ):
                continue
            if source_epoch != run.get("specEpoch"):
                continue
            covered[angle]["paths"].update(inspected_paths)
            covered[angle]["symbols"].update(inspected_symbols)
    missing: dict[int, dict[str, list[str]]] = {}
    for angle in sorted(required_angles):
        paths = sorted(required_paths - covered[angle]["paths"])
        symbols = sorted(required_symbols - covered[angle]["symbols"])
        if paths or symbols:
            missing[angle] = {"paths": paths, "symbols": symbols}
    return missing


def scope_covers(covered: Any, required: Any) -> bool:
    """Whether a second-review scope is exactly the required canonical scope."""
    return scope_is_valid(covered) and scope_is_valid(required) and covered == required


def scope_is_valid(scope: Any) -> bool:
    if scope == {"kind": "whole_unit"}:
        return True
    if not isinstance(scope, dict) or set(scope) != {"kind", "items"}:
        return False
    items = _scope_items(scope)
    return items is not None and bool(items)


def verify_imported_attempt_artifacts(
    root: Path,
    unit: dict[str, Any],
    attempt: dict[str, Any],
    manifest: dict[str, Any] | None = None,
    *,
    cache: EvidenceCache | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Recompute the identities sealing one imported attempt's raw output."""
    cache_key = (
        str(attempt.get("manifestHash")),
        str(attempt.get("resultHash")),
        str(attempt.get("attemptEvidenceHash")),
    )
    if cache is not None and cache_key in cache.artifacts:
        return cache.artifacts[cache_key]
    manifest = manifest or load_sealed_attempt_manifest(
        root, unit, attempt, cache=cache
    )
    output = manifest.get("outputDirectory")
    if not isinstance(output, str):
        raise ReviewToolError(
            f"{unit.get('id')}/{attempt.get('attemptId')}: outputDirectory is required"
        )
    result_path = safe_child(root, f"{output}/result.json")
    validations_path = safe_child(root, f"{output}/validations.jsonl")
    try:
        result_bytes = result_path.read_bytes()
    except FileNotFoundError as exc:
        raise ReviewToolError(f"missing JSON file: {result_path}") from exc
    except OSError as exc:
        raise ReviewToolError(f"invalid JSON in {result_path}: {exc}") from exc
    try:
        validations_bytes = validations_path.read_bytes()
    except FileNotFoundError as exc:
        raise ReviewToolError(f"missing JSONL file: {validations_path}") from exc
    except OSError as exc:
        raise ReviewToolError(f"cannot read {validations_path}: {exc}") from exc
    result = parse_json_bytes(result_bytes, str(result_path))
    validations = parse_jsonl_bytes(validations_bytes, str(validations_path))
    if digest_bytes(result_bytes) != attempt.get("resultHash"):
        raise ReviewToolError(
            f"{unit.get('id')}/{attempt.get('attemptId')}: imported result identity mismatch"
        )
    derived = canonical_identity({"result": result, "validations": validations})
    if derived != attempt.get("attemptEvidenceHash"):
        raise ReviewToolError(
            f"{unit.get('id')}/{attempt.get('attemptId')}: imported evidence identity mismatch"
        )
    verified = (result, validations)
    if cache is not None:
        cache.artifacts[cache_key] = verified
    return verified


def validate_second_review_evidence(
    root: Path,
    run: dict[str, Any],
    unit: dict[str, Any],
    requirement: dict[str, Any],
    *,
    independent_ids: Any,
    evidence_set_hash: Any,
    reviewer_principal_id: Any,
    reviewer_execution_id: Any,
    cache: EvidenceCache | None = None,
) -> tuple[list[str], str]:
    """Validate v2 contributor derivation and principal independence."""
    if not isinstance(reviewer_principal_id, str) or not reviewer_principal_id.strip():
        raise ReviewToolError(
            f"{unit.get('id')}/{requirement.get('id')}: reviewerPrincipalId is required"
        )
    derived_ids, derived_hash = primary_evidence_identity(
        root, unit, requirement, cache=cache
    )
    if independent_ids != derived_ids:
        raise ReviewToolError(
            f"{unit.get('id')}/{requirement.get('id')}: second-review contributor set is stale or incomplete"
        )
    if evidence_set_hash != derived_hash:
        raise ReviewToolError(
            f"{unit.get('id')}/{requirement.get('id')}: second-review primary evidence identity mismatch"
        )
    attempts = {
        attempt.get("attemptId"): attempt for attempt in _attempt_rows(unit)
    }
    principals: set[str] = set()
    executions: set[str] = set()
    for attempt_id in derived_ids:
        attempt = attempts.get(attempt_id, {})
        principal = attempt.get("reviewerPrincipalId")
        if not isinstance(principal, str) or not principal.strip():
            raise ReviewToolError(
                f"{unit.get('id')}/{attempt_id}: contributing reviewerPrincipalId is required"
            )
        load_sealed_attempt_manifest(root, unit, attempt, cache=cache)
        principals.add(principal)
        execution = attempt.get("reviewerExecutionId")
        if not isinstance(execution, str) or not execution.strip():
            raise ReviewToolError(
                f"{unit.get('id')}/{attempt_id}: contributing reviewerExecutionId is required"
            )
        executions.add(execution)
    if reviewer_principal_id in principals:
        raise ReviewToolError(
            f"{unit.get('id')}/{requirement.get('id')}: second reviewer principal conflicts with contributing primary evidence"
        )
    if (
        not isinstance(reviewer_execution_id, str)
        or not reviewer_execution_id.strip()
    ):
        raise ReviewToolError(
            f"{unit.get('id')}/{requirement.get('id')}: reviewerExecutionId is required"
        )
    if reviewer_execution_id in executions:
        raise ReviewToolError(
            f"{unit.get('id')}/{requirement.get('id')}: second reviewer execution conflicts with contributing primary evidence"
        )
    return derived_ids, derived_hash


def validate_reviewer_independence(
    root: Path,
    run: dict[str, Any],
    unit: dict[str, Any],
    requirement: dict[str, Any],
    *,
    independent_ids: Any,
    evidence_set_hash: Any,
    reviewer_principal_id: Any,
    reviewer_execution_id: Any,
    cache: EvidenceCache | None = None,
) -> tuple[list[str], str]:
    """Validate v2 evidence identity plus principal and execution independence."""
    validate_review_spec_version(run.get("reviewSpecVersion"))
    return validate_second_review_evidence(
        root,
        run,
        unit,
        requirement,
        independent_ids=independent_ids,
        evidence_set_hash=evidence_set_hash,
        reviewer_principal_id=reviewer_principal_id,
        reviewer_execution_id=reviewer_execution_id,
        cache=cache,
    )


def validate_second_review_payload(
    second: Any,
    requirement: dict[str, Any],
    *,
    candidate_ids: set[str] | None = None,
) -> None:
    """Validate the substantive structured result shared by preflight and import."""
    if not isinstance(second, dict):
        raise ReviewToolError("second-review result must be an object")
    if second.get("requirementId") != requirement.get("id"):
        raise ReviewToolError("second-review requirement mismatch")
    if second.get("required") != requirement:
        raise ReviewToolError(
            "second-review result does not match the assigned requirement"
        )
    if not scope_covers(second.get("scopeCovered"), requirement.get("scope")):
        raise ReviewToolError("second-review scope does not cover the requirement")
    evidence = second.get("evidence")
    if (
        not isinstance(evidence, list)
        or not evidence
        or not all(
            (isinstance(item, str) and bool(item.strip()))
            or (isinstance(item, dict) and bool(item))
            for item in evidence
        )
    ):
        raise ReviewToolError("second-review completion requires non-empty evidence")
    conclusion = second.get("conclusion")
    if not isinstance(conclusion, str) or conclusion not in {
        "concur",
        "dissent",
        "expanded",
    }:
        raise ReviewToolError("second-review conclusion is invalid")
    candidate_refs = second.get("candidateRefs")
    if not isinstance(candidate_refs, list) or not all(
        isinstance(item, str) and bool(item.strip()) for item in candidate_refs
    ):
        raise ReviewToolError("second-review candidateRefs must be an array of strings")
    if len(candidate_refs) != len(set(candidate_refs)):
        raise ReviewToolError("second-review candidateRefs must be unique")
    if candidate_ids is not None:
        unknown = set(candidate_refs) - candidate_ids
        if unknown:
            raise ReviewToolError(
                f"second-review completion references unknown candidates: {sorted(unknown)}"
            )


def _canonical_observation_ids(
    root: Path,
    unit: dict[str, Any],
    attempt_id: str,
    candidate_refs: list[str],
    observations: list[dict[str, Any]] | None = None,
) -> list[str | None]:
    rows = (
        observations
        if observations is not None
        else load_jsonl(root / "observations.jsonl")
    )
    source_attempt = f"{unit.get('id')}/{attempt_id}"
    local_to_canonical = {
        item.get("sourceLocalId"): item.get("id")
        for item in rows
        if item.get("sourceAttempt") == source_attempt
        and isinstance(item.get("sourceLocalId"), str)
        and isinstance(item.get("id"), str)
    }
    return [local_to_canonical.get(local_id) for local_id in candidate_refs]


def validate_second_review_completion_provenance(
    root: Path,
    run: dict[str, Any],
    unit: dict[str, Any],
    requirement: dict[str, Any],
    completion: dict[str, Any],
    *,
    cache: EvidenceCache | None = None,
    observations: list[dict[str, Any]] | None = None,
) -> None:
    """Bind an active completion to one complete imported sealed attempt."""
    reference = completion.get("attempt")
    expected_prefix = f"{unit.get('id')}/"
    if not isinstance(reference, str) or not reference.startswith(expected_prefix):
        raise ReviewToolError(
            f"{unit.get('id')}/{requirement.get('id')}: invalid second-review attempt reference"
        )
    attempt_id = reference[len(expected_prefix) :]
    attempt = next(
        (
            item
            for item in _attempt_rows(unit)
            if item.get("attemptId") == attempt_id
        ),
        None,
    )
    if attempt is None:
        raise ReviewToolError(
            f"{unit.get('id')}/{requirement.get('id')}: second-review attempt is missing"
        )
    if (
        attempt.get("packetType") != "independent_second_review"
        or attempt.get("importDisposition") != "imported"
        or attempt.get("status") != "complete"
    ):
        raise ReviewToolError(
            f"{unit.get('id')}/{attempt_id}: completion does not reference a complete imported second review"
        )
    if completion.get("attemptManifestHash") != attempt.get("manifestHash"):
        raise ReviewToolError(
            f"{unit.get('id')}/{attempt_id}: completion attempt manifest identity mismatch"
        )
    manifest = load_sealed_attempt_manifest(root, unit, attempt, cache=cache)
    if manifest.get("specEpoch") != run.get("specEpoch"):
        raise ReviewToolError(
            f"{unit.get('id')}/{attempt_id}: second-review evidence uses a "
            "stale specEpoch"
        )
    if manifest.get("secondReviewRequirementId") != requirement.get("id"):
        raise ReviewToolError(
            f"{unit.get('id')}/{attempt_id}: completion requirement does not match its manifest"
        )
    for field in ("reviewerExecutionId", "reviewerPrincipalId"):
        if (
            completion.get(field) != attempt.get(field)
            or completion.get(field) != manifest.get(field)
        ):
            raise ReviewToolError(
                f"{unit.get('id')}/{attempt_id}: completion {field} mismatch"
            )
    if completion.get("independentFromAttemptIds") != manifest.get(
        "independentFromAttemptIds"
    ):
        raise ReviewToolError(
            f"{unit.get('id')}/{attempt_id}: completion contributor set mismatch"
        )
    if completion.get("primaryEvidenceSetHash") != manifest.get(
        "primaryEvidenceSetHash"
    ):
        raise ReviewToolError(
            f"{unit.get('id')}/{attempt_id}: completion evidence identity mismatch"
        )
    result, _ = verify_imported_attempt_artifacts(
        root, unit, attempt, manifest, cache=cache
    )
    second_results = result.get("secondReviewResults")
    if not isinstance(second_results, list) or len(second_results) != 1:
        raise ReviewToolError(
            f"{unit.get('id')}/{attempt_id}: imported second-review result is malformed"
        )
    second = second_results[0]
    validate_second_review_payload(second, requirement)
    for field in (
        "required",
        "scopeCovered",
        "evidence",
        "conclusion",
        "candidateRefs",
    ):
        if completion.get(field) != second.get(field):
            raise ReviewToolError(
                f"{unit.get('id')}/{attempt_id}: completion {field} does not match imported result"
            )
    expected_observations = _canonical_observation_ids(
        root,
        unit,
        attempt_id,
        second["candidateRefs"],
        observations,
    )
    if None in expected_observations or completion.get(
        "observations"
    ) != expected_observations:
        raise ReviewToolError(
            f"{unit.get('id')}/{attempt_id}: completion observations do not "
            "match imported candidateRefs"
        )


def seal_second_review_history(
    completion: dict[str, Any],
    reason: str,
    *,
    previous_history_hash: str | None,
) -> dict[str, Any]:
    """Create one tamper-evident historical second-review record."""
    history = {
        **completion,
        "stale": True,
        "staleReason": reason,
        "previousHistoryHash": previous_history_hash,
    }
    history["historyHash"] = canonical_identity(history)
    return history


def validate_second_review_history(
    root: Path,
    unit: dict[str, Any],
    entry: Any,
    *,
    cache: EvidenceCache | None = None,
    expected_previous_hash: str | None = None,
) -> None:
    """Validate a superseded completion without reapplying current evidence rules."""
    if not isinstance(entry, dict):
        raise ReviewToolError(f"{unit.get('id')}: secondReviewHistory entry is malformed")
    supplied_hash = entry.get("historyHash")
    unsigned = dict(entry)
    unsigned.pop("historyHash", None)
    if (
        not isinstance(supplied_hash, str)
        or supplied_hash != canonical_identity(unsigned)
    ):
        raise ReviewToolError(
            f"{unit.get('id')}: secondReviewHistory identity mismatch"
        )
    if entry.get("stale") is not True or not isinstance(
        entry.get("staleReason"), str
    ):
        raise ReviewToolError(
            f"{unit.get('id')}: secondReviewHistory requires a stale reason"
        )
    if entry.get("previousHistoryHash") != expected_previous_hash:
        raise ReviewToolError(
            f"{unit.get('id')}: secondReviewHistory chain is broken"
        )
    reference = entry.get("attempt")
    prefix = f"{unit.get('id')}/"
    if not isinstance(reference, str) or not reference.startswith(prefix):
        raise ReviewToolError(
            f"{unit.get('id')}: secondReviewHistory attempt reference is invalid"
        )
    attempt_id = reference[len(prefix) :]
    attempt = next(
        (
            item
            for item in _attempt_rows(unit)
            if item.get("attemptId") == attempt_id
        ),
        None,
    )
    if (
        attempt is None
        or attempt.get("packetType") != "independent_second_review"
        or attempt.get("importDisposition") != "imported"
        or attempt.get("status") != "complete"
    ):
        raise ReviewToolError(
            f"{unit.get('id')}/{attempt_id}: historical second-review attempt is invalid"
        )
    if entry.get("attemptManifestHash") != attempt.get("manifestHash"):
        raise ReviewToolError(
            f"{unit.get('id')}/{attempt_id}: historical manifest identity mismatch"
        )
    manifest = load_sealed_attempt_manifest(root, unit, attempt, cache=cache)
    if entry.get("requirementId") != manifest.get("secondReviewRequirementId"):
        raise ReviewToolError(
            f"{unit.get('id')}/{attempt_id}: historical requirement mismatch"
        )
    for identity_field in ("reviewerExecutionId", "reviewerPrincipalId"):
        if (
            entry.get(identity_field) != attempt.get(identity_field)
            or entry.get(identity_field) != manifest.get(identity_field)
        ):
            raise ReviewToolError(
                f"{unit.get('id')}/{attempt_id}: historical "
                f"{identity_field} mismatch"
            )
    if entry.get("independentFromAttemptIds") != manifest.get(
        "independentFromAttemptIds"
    ):
        raise ReviewToolError(
            f"{unit.get('id')}/{attempt_id}: historical contributor set mismatch"
        )
    if entry.get("primaryEvidenceSetHash") != manifest.get(
        "primaryEvidenceSetHash"
    ):
        raise ReviewToolError(
            f"{unit.get('id')}/{attempt_id}: historical evidence identity mismatch"
        )
    result, _ = verify_imported_attempt_artifacts(
        root, unit, attempt, manifest, cache=cache
    )
    second_results = result.get("secondReviewResults")
    if not isinstance(second_results, list) or len(second_results) != 1:
        raise ReviewToolError(
            f"{unit.get('id')}/{attempt_id}: historical second-review result is malformed"
        )
    second = second_results[0]
    if not isinstance(second, dict):
        raise ReviewToolError(
            f"{unit.get('id')}/{attempt_id}: historical second-review payload is malformed"
        )
    historical_requirement = entry.get("required")
    if not isinstance(historical_requirement, dict):
        raise ReviewToolError(
            f"{unit.get('id')}/{attempt_id}: historical requirement is malformed"
        )
    validate_second_review_payload(second, historical_requirement)
    for field in (
        "required",
        "scopeCovered",
        "evidence",
        "conclusion",
        "candidateRefs",
    ):
        if entry.get(field) != second.get(field):
            raise ReviewToolError(
                f"{unit.get('id')}/{attempt_id}: historical completion {field} mismatch"
            )
    expected_observations = _canonical_observation_ids(
        root,
        unit,
        attempt_id,
        second.get("candidateRefs", []),
    )
    if None in expected_observations or entry.get(
        "observations"
    ) != expected_observations:
        raise ReviewToolError(
            f"{unit.get('id')}/{attempt_id}: historical observations mismatch"
        )


def primary_evidence_identity(
    root: Path,
    unit: dict[str, Any],
    requirement: dict[str, Any],
    *,
    cache: EvidenceCache | None = None,
) -> tuple[list[str], str]:
    projection = primary_evidence_projection(
        root, unit, requirement, cache=cache
    )
    if not projection:
        raise ReviewToolError(
            f"{unit.get('id')}/{requirement.get('id')}: second review has no sealed primary evidence"
        )
    return [str(item["attemptId"]) for item in projection], canonical_identity(projection)
