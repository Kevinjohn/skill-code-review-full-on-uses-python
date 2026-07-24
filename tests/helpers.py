from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/skill-code-review-full-on-uses-python/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from review_tool.io import canonical_bytes, canonical_identity, digest_bytes, jsonl_bytes, load_json, state_digest  # noqa: E402
from review_tool.operations import initialize  # noqa: E402
from review_tool.security import permitted_validation_classes, security_level  # noqa: E402
from review_tool.transactions import transact  # noqa: E402

CONTRACT = ROOT / "skills/skill-code-review-full-on-uses-python/references/contract.md"
PACK = ROOT / "skills/skill-code-review-full-on-uses-python/references/reference-pack.md"
TOOL = ROOT / "skills/skill-code-review-full-on-uses-python/scripts/review_tool"


def new_review(
    base: Path, *, level: str = "off", stable_reviewer_lineage: bool = False
) -> Path:
    review = base / "review"
    initialize(
        review,
        CONTRACT,
        PACK,
        "none",
        security_level=level,
        security_source="user",
        stable_reviewer_lineage=stable_reviewer_lineage,
    )
    return review


def clean_unit(review: Path, *, tier: str = "B", reviewer: str = "EXEC-PRIMARY") -> dict:
    run = load_json(review / "run.json")
    review_spec_version = run["reviewSpecVersion"]
    level = security_level(run)
    required_angles = [number for number in range(1, 11) if not (level == "off" and number == 5)]
    path_row = {
        "path": "src/example.py", "revisionEpoch": "EPOCH-0001", "entryKind": "file",
        "baselineState": "tracked", "contentId": "content-1", "sizeBytes": 10,
        "implementationLines": 1, "language": "python", "subsystem": "core",
        "classification": "production", "exclusion": None,
    }
    content_set = canonical_identity([path_row])
    requirements = (
        [{"id": "SR-001", "angle": 3, "scope": {"kind": "whole_unit"}}]
        if tier == "A"
        else []
    )
    capsule = {
        "capsuleId": "CAPSULE-CORE-0001",
        "baselineContentSetHash": content_set,
        "specEpoch": "SPEC-0001",
        "subsystem": "core",
        "role": "Fixture component",
        "entryPoints": ["src/example.py"],
        "publicBoundaries": [],
        "dependencySeams": [],
        "importantCallersCallees": [],
        "tests": [],
        "documentation": [],
        "configuration": [],
        "commands": [],
        "sharedInvariants": ["The fixture is readable."],
        "failureBoundaries": [],
        "evidenceLocations": ["src/example.py:1"],
        "architectureHash": digest_bytes((review / "architecture.md").read_bytes()),
        "referenceManifestHash": digest_bytes(
            (review / "tooling/reference/manifest.json").read_bytes()
        ),
    }
    capsule_bytes = canonical_bytes(capsule)
    capsule_hash = digest_bytes(capsule_bytes)
    unit_manifest = {
        "workId": "WORK-0001", "revision": 1, "supersedes": None, "reason": "initial",
        "revisionEpoch": "EPOCH-0001", "reviewSpecVersion": review_spec_version, "specEpoch": "SPEC-0001",
        "riskTier": tier, "securityLevel": level, "contentSetHash": content_set, "paths": [{"path": "src/example.py", "contentId": "content-1"}],
        "sizeTotals": {"productionFiles": 1, "implementationLines": 1}, "limitException": None,
        "symbols": [], "subsystem": "core",
        "orientationCapsule": {
            "path": "assignments/capsules/core.json",
            "hash": capsule_hash,
        },
        "requiredAngleDispositions": required_angles, "requiredSecondReviews": requirements,
        "repositoryInstructions": [], "permittedValidationScope": [],
        "permittedValidationClasses": permitted_validation_classes(level),
        "outputSchema": "specialist-result-schema.md",
        "preservedAttemptManifestHashes": [],
    }
    unit_manifest_bytes = canonical_bytes(unit_manifest)
    unit_hash = digest_bytes(unit_manifest_bytes)
    attempt_manifest = {
        "workId": "WORK-0001", "attemptId": "ATTEMPT-0001",
        "unitManifest": "assignments/WORK-0001/MANIFEST-0001.json", "unitManifestHash": unit_hash,
        "packetType": "primary_semantic", "reviewerExecutionId": reviewer,
        "reviewerPrincipalId": reviewer,
        "reviewerReuseMode": "cold",
        "reviewerBatchId": None,
        "reviewSpecVersion": review_spec_version, "specEpoch": "SPEC-0001", "securityLevel": level,
        "assignedScope": {"paths": ["src/example.py"], "symbols": [], "angles": required_angles},
        "secondReviewRequirementId": None, "independentFromAttemptIds": [], "primaryEvidenceSetHash": None,
        "repositoryInstructions": [], "permittedValidationScope": [],
        "permittedValidationClasses": permitted_validation_classes(level),
        "outputDirectory": "agents/WORK-0001/ATTEMPT-0001",
    }
    attempt_bytes = canonical_bytes(attempt_manifest)
    attempt_hash = digest_bytes(attempt_bytes)
    angles = {str(number): {"status": "pending", "evidence": [], "specEpoch": None} for number in range(1, 11)}
    if level == "off":
        angles["5"] = {
            "status": "excluded_by_profile",
            "evidence": [],
            "specEpoch": "SPEC-0001",
            "profileExclusion": {"domain": "security", "level": "off"},
        }
    unit = {
        "id": "WORK-0001", "revisionEpoch": "EPOCH-0001", "specEpoch": "SPEC-0001",
        "currentManifest": "assignments/WORK-0001/MANIFEST-0001.json", "currentManifestHash": unit_hash,
        "manifestHistory": [{"revision": 1, "path": "assignments/WORK-0001/MANIFEST-0001.json", "hash": unit_hash, "supersedes": None, "reason": "initial", "preservedAttemptManifestHashes": []}],
        "contentSetHash": content_set, "paths": ["src/example.py"], "title": "example", "subsystem": "core",
        "riskTier": tier,
        "securityLevel": level,
        "criticalReasons": (
            [{
                "code": "durability_recovery",
                "locations": [{"path": "src/example.py", "startLine": 1}],
                "invariant": "The fixture preserves its recorded value.",
                "materialConsequence": "Loss of the fixture value.",
                "whyTierBInsufficient": "The test explicitly exercises Tier-A validation.",
            }]
            if tier == "A"
            else []
        ),
        "status": "assigned",
        "reviewAttempts": [{"attemptId": "ATTEMPT-0001", "manifest": "assignments/WORK-0001/ATTEMPT-0001.json", "manifestHash": attempt_hash, "unitManifestHash": unit_hash, "packetType": "primary_semantic", "reviewerExecutionId": reviewer, "reviewerPrincipalId": reviewer, "independentFromAttemptIds": [], "status": "assigned", "resultHash": None, "attemptEvidenceHash": None, "importDisposition": "pending"}],
        "angles": angles, "requiredSecondReviews": requirements, "completedSecondReviews": [], "residualUncertainty": [], "updatedAt": "2026-01-01T00:00:00Z",
    }
    run["repositoryIdentity"] = "fixture-repository"
    run["baselineCommit"] = "abc123"
    run["baselineContentSetHash"] = content_set
    run["updatedAt"] = "2026-01-01T00:00:00Z"
    replacements = {
        "run.json": canonical_bytes(run), "paths.jsonl": jsonl_bytes([path_row]), "work-units.jsonl": jsonl_bytes([unit]),
        "assignments/WORK-0001/MANIFEST-0001.json": unit_manifest_bytes,
        "assignments/WORK-0001/ATTEMPT-0001.json": attempt_bytes,
        "assignments/capsules/core.json": capsule_bytes,
    }
    transact(review, replacements, operation="mutate", actor="orchestrator", timestamp="2026-01-01T00:00:00Z", expected_digest=state_digest(review))
    return {"unit": unit, "unitHash": unit_hash, "attemptHash": attempt_hash}


def rewrite_canonical(review: Path, relative: str, value) -> None:
    path = review / relative
    if relative.endswith(".jsonl"):
        path.write_bytes(jsonl_bytes(value))
    else:
        path.write_bytes(canonical_bytes(value))
