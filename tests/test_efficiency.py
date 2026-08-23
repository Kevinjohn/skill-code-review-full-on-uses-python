from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.helpers import CONTRACT, PACK, clean_unit, new_review

from review_tool.evidence import primary_evidence_identity, scope_covers
from review_tool.evidence import assigned_scope_intersects
from review_tool.checks import check_review, pilot_diagnostics
from review_tool.errors import ReviewToolError
from review_tool.io import (
    canonical_bytes,
    digest_bytes,
    jsonl_bytes,
    load_json,
    load_jsonl,
    state_digest,
)
from review_tool.operations import (
    _candidate_observation,
    apply_mutation,
    generate,
    import_specialist,
)
from review_tool.packets import (
    _evidence_list,
    check_attempt_result,
    initialize_attempt_result,
    load_orientation_capsule,
    render_packet,
)
from review_tool.transactions import transact


class EfficiencyTests(unittest.TestCase):
    def _write_primary_result(
        self,
        review: Path,
        *,
        attempt_id: str = "ATTEMPT-0001",
        principal: str = "EXEC-PRIMARY",
        status: str = "complete",
    ) -> None:
        units = load_jsonl(review / "work-units.jsonl")
        unit = units[0]
        attempt = next(row for row in unit["reviewAttempts"] if row["attemptId"] == attempt_id)
        manifest = load_json(review / attempt["manifest"])
        output = review / manifest["outputDirectory"]
        output.mkdir(parents=True, exist_ok=True)
        evidence = [{
            "scopeCovered": {"kind": "whole_unit"},
            "locations": ["src/example.py:1"],
            "claim": f"Evidence from {attempt_id}.",
        }]
        result = {
            "workId": "WORK-0001",
            "attemptId": attempt_id,
            "reviewerExecutionId": manifest["reviewerExecutionId"],
            "reviewerPrincipalId": principal,
            "packetType": "primary_semantic",
            "unitManifestHash": manifest["unitManifestHash"],
            "attemptManifestHash": attempt["manifestHash"],
            "specEpoch": manifest["specEpoch"],
            "securityLevel": "off",
            "status": status,
            "inspected": {"paths": ["src/example.py"], "symbols": []},
            "notInspected": {"paths": [], "symbols": []},
            "angleDispositions": {
                str(number): {"status": "reviewed", "evidence": evidence}
                for number in manifest["assignedScope"]["angles"]
            },
            "secondReviewResults": [],
            "candidates": [],
            "residualUncertainty": [],
            "remainingScope": {"paths": [], "symbols": [], "angles": []},
        }
        if status != "complete":
            result["inspected"] = {"paths": [], "symbols": []}
            result["notInspected"] = {
                "paths": manifest["assignedScope"]["paths"],
                "symbols": manifest["assignedScope"]["symbols"],
            }
            result["angleDispositions"] = {}
            result["remainingScope"] = manifest["assignedScope"]
        (output / "result.json").write_text(json.dumps(result))
        (output / "validations.jsonl").write_text("")

    def _add_second_review(
        self,
        review: Path,
        *,
        principal: str = "EXEC-SECOND",
        attempt_id: str = "ATTEMPT-0002",
        reuse_mode: str = "cold",
        batch_id: str | None = None,
        execution_id: str | None = None,
    ) -> dict:
        units = load_jsonl(review / "work-units.jsonl")
        unit = units[0]
        run = load_json(review / "run.json")
        requirement = unit["requiredSecondReviews"][0]
        primary_ids, primary_hash = primary_evidence_identity(review, unit, requirement)
        unit_hash = unit["currentManifestHash"]
        manifest = {
            "workId": "WORK-0001",
            "attemptId": attempt_id,
            "unitManifest": unit["currentManifest"],
            "unitManifestHash": unit_hash,
            "packetType": "independent_second_review",
            "reviewerExecutionId": execution_id or f"EXEC-{attempt_id}",
            "reviewerPrincipalId": principal,
            "reviewerReuseMode": reuse_mode,
            "reviewerBatchId": batch_id,
            "reviewSpecVersion": run["reviewSpecVersion"],
            "specEpoch": run["specEpoch"],
            "securityLevel": "off",
            "assignedScope": {"paths": ["src/example.py"], "symbols": [], "angles": [3]},
            "secondReviewRequirementId": "SR-001",
            "independentFromAttemptIds": primary_ids,
            "primaryEvidenceSetHash": primary_hash,
            "repositoryInstructions": [],
            "permittedValidationScope": [],
            "permittedValidationClasses": ["ordinary"],
            "outputDirectory": f"agents/WORK-0001/{attempt_id}",
        }
        manifest_bytes = canonical_bytes(manifest)
        manifest_hash = digest_bytes(manifest_bytes)
        unit["reviewAttempts"].append({
            "attemptId": attempt_id,
            "manifest": f"assignments/WORK-0001/{attempt_id}.json",
            "manifestHash": manifest_hash,
            "unitManifestHash": unit_hash,
            "packetType": "independent_second_review",
            "reviewerExecutionId": execution_id or f"EXEC-{attempt_id}",
            "reviewerPrincipalId": principal,
            "independentFromAttemptIds": primary_ids,
            "status": "assigned",
            "resultHash": None,
            "attemptEvidenceHash": None,
            "importDisposition": "pending",
        })
        unit["status"] = "assigned"
        transact(
            review,
            {
                "work-units.jsonl": jsonl_bytes([unit]),
                f"assignments/WORK-0001/{attempt_id}.json": manifest_bytes,
            },
            operation="mutate",
            actor="orchestrator",
            timestamp="2026-01-01T00:00:01Z",
            expected_digest=state_digest(review),
        )
        return {"requirement": requirement, "manifest": manifest, "manifestHash": manifest_hash}

    def _write_second_result(self, review: Path, data: dict, *, principal: str) -> None:
        output = review / data["manifest"]["outputDirectory"]
        output.mkdir(parents=True, exist_ok=True)
        result = {
            "workId": "WORK-0001",
            "attemptId": data["manifest"]["attemptId"],
            "reviewerExecutionId": data["manifest"]["reviewerExecutionId"],
            "reviewerPrincipalId": principal,
            "packetType": "independent_second_review",
            "unitManifestHash": data["manifest"]["unitManifestHash"],
            "attemptManifestHash": data["manifestHash"],
            "specEpoch": data["manifest"]["specEpoch"],
            "securityLevel": "off",
            "status": "complete",
            "inspected": {"paths": ["src/example.py"], "symbols": []},
            "notInspected": {"paths": [], "symbols": []},
            "angleDispositions": {
                "3": {
                    "status": "reviewed",
                    "evidence": [{
                        "scopeCovered": {"kind": "whole_unit"},
                        "locations": ["src/example.py:1"],
                        "claim": "Independent fixture review.",
                    }],
                }
            },
            "secondReviewResults": [{
                "requirementId": "SR-001",
                "required": data["requirement"],
                "scopeCovered": {"kind": "whole_unit"},
                "evidence": ["Independent fixture review."],
                "conclusion": "concur",
                "candidateRefs": [],
            }],
            "candidates": [],
            "residualUncertainty": [],
            "remainingScope": {"paths": [], "symbols": [], "angles": []},
        }
        (output / "result.json").write_text(json.dumps(result))
        (output / "validations.jsonl").write_text("")

    def _rewrite_attempt_manifest(
        self,
        review: Path,
        attempt_id: str,
        mutate,
    ) -> dict:
        units = load_jsonl(review / "work-units.jsonl")
        unit = units[0]
        attempt = next(
            row for row in unit["reviewAttempts"] if row["attemptId"] == attempt_id
        )
        manifest = load_json(review / attempt["manifest"])
        mutate(manifest)
        manifest_bytes = canonical_bytes(manifest)
        attempt["manifestHash"] = digest_bytes(manifest_bytes)
        transact(
            review,
            {
                "work-units.jsonl": jsonl_bytes([unit]),
                attempt["manifest"]: manifest_bytes,
            },
            operation="mutate",
            actor="orchestrator",
            timestamp="2026-01-01T00:00:02Z",
            expected_digest=state_digest(review),
        )
        requirements = unit.get("requiredSecondReviews", [])
        return {
            "requirement": requirements[0] if requirements else None,
            "manifest": manifest,
            "manifestHash": attempt["manifestHash"],
        }

    def _add_late_primary_attempt(
        self,
        review: Path,
        *,
        angle: int = 3,
        attempt_id: str = "ATTEMPT-0003",
    ) -> None:
        units = load_jsonl(review / "work-units.jsonl")
        unit = units[0]
        run = load_json(review / "run.json")
        manifest = {
            "workId": "WORK-0001",
            "attemptId": attempt_id,
            "unitManifest": unit["currentManifest"],
            "unitManifestHash": unit["currentManifestHash"],
            "packetType": "primary_semantic",
            "reviewerExecutionId": f"EXEC-{attempt_id}",
            "reviewerPrincipalId": "PRINCIPAL-LATE-PRIMARY",
            "reviewerReuseMode": "cold",
            "reviewerBatchId": None,
            "reviewSpecVersion": run["reviewSpecVersion"],
            "specEpoch": run["specEpoch"],
            "securityLevel": "off",
            "assignedScope": {
                "paths": ["src/example.py"],
                "symbols": [],
                "angles": [angle],
            },
            "secondReviewRequirementId": None,
            "independentFromAttemptIds": [],
            "primaryEvidenceSetHash": None,
            "repositoryInstructions": [],
            "permittedValidationScope": [],
            "permittedValidationClasses": ["ordinary"],
            "outputDirectory": f"agents/WORK-0001/{attempt_id}",
        }
        manifest_bytes = canonical_bytes(manifest)
        manifest_hash = digest_bytes(manifest_bytes)
        unit["reviewAttempts"].append({
            "attemptId": attempt_id,
            "manifest": f"assignments/WORK-0001/{attempt_id}.json",
            "manifestHash": manifest_hash,
            "unitManifestHash": unit["currentManifestHash"],
            "packetType": "primary_semantic",
            "reviewerExecutionId": f"EXEC-{attempt_id}",
            "reviewerPrincipalId": "PRINCIPAL-LATE-PRIMARY",
            "independentFromAttemptIds": [],
            "status": "assigned",
            "resultHash": None,
            "attemptEvidenceHash": None,
            "importDisposition": "pending",
        })
        transact(
            review,
            {
                "work-units.jsonl": jsonl_bytes([unit]),
                f"assignments/WORK-0001/{attempt_id}.json": manifest_bytes,
            },
            operation="mutate",
            actor="orchestrator",
            timestamp="2026-01-01T00:00:03Z",
            expected_digest=state_digest(review),
        )

    def test_second_review_uses_derived_evidence_and_principal(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review, tier="A")
            self._write_primary_result(review)
            import_specialist(review, "WORK-0001", "ATTEMPT-0001", state_digest(review))
            second = self._add_second_review(review)
            self._write_second_result(review, second, principal="EXEC-SECOND")
            import_specialist(review, "WORK-0001", "ATTEMPT-0002", state_digest(review))
            unit = load_jsonl(review / "work-units.jsonl")[0]
            self.assertEqual(unit["status"], "complete")
            self.assertFalse(unit["completedSecondReviews"][0]["stale"])

    def test_second_review_rejects_primary_principal(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review, tier="A")
            self._write_primary_result(review)
            import_specialist(review, "WORK-0001", "ATTEMPT-0001", state_digest(review))
            second = self._add_second_review(review, principal="EXEC-PRIMARY")
            self._write_second_result(review, second, principal="EXEC-PRIMARY")
            with self.assertRaisesRegex(ReviewToolError, "principal conflicts"):
                import_specialist(review, "WORK-0001", "ATTEMPT-0002", state_digest(review))

    def test_v2_import_rejects_empty_reviewer_principal(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            units = load_jsonl(review / "work-units.jsonl")
            attempt = units[0]["reviewAttempts"][0]
            manifest_path = review / attempt["manifest"]
            manifest = load_json(manifest_path)
            manifest["reviewerPrincipalId"] = ""
            manifest_path.write_bytes(canonical_bytes(manifest))
            attempt["reviewerPrincipalId"] = ""
            attempt["manifestHash"] = digest_bytes(manifest_path.read_bytes())
            transact(
                review,
                {"work-units.jsonl": jsonl_bytes(units)},
                operation="mutate",
                actor="test",
                timestamp="2026-01-01T00:00:02Z",
                expected_digest=state_digest(review),
            )
            self._write_primary_result(review, principal="")
            with self.assertRaisesRegex(ReviewToolError, "reviewerPrincipalId is required"):
                import_specialist(
                    review, "WORK-0001", "ATTEMPT-0001", state_digest(review)
                )

    def test_second_review_rejects_incomplete_contributor_set(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review, tier="A")
            self._write_primary_result(review)
            import_specialist(review, "WORK-0001", "ATTEMPT-0001", state_digest(review))
            self._add_second_review(review)
            second = self._rewrite_attempt_manifest(
                review,
                "ATTEMPT-0002",
                lambda manifest: manifest.update(independentFromAttemptIds=[]),
            )
            self._write_second_result(review, second, principal="EXEC-SECOND")
            with self.assertRaisesRegex(ReviewToolError, "contributor set is stale"):
                import_specialist(review, "WORK-0001", "ATTEMPT-0002", state_digest(review))

    def test_second_review_rejects_mismatched_evidence_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review, tier="A")
            self._write_primary_result(review)
            import_specialist(review, "WORK-0001", "ATTEMPT-0001", state_digest(review))
            self._add_second_review(review)
            second = self._rewrite_attempt_manifest(
                review,
                "ATTEMPT-0002",
                lambda manifest: manifest.update(primaryEvidenceSetHash="0" * 64),
            )
            self._write_second_result(review, second, principal="EXEC-SECOND")
            with self.assertRaisesRegex(ReviewToolError, "primary evidence identity mismatch"):
                import_specialist(review, "WORK-0001", "ATTEMPT-0002", state_digest(review))

    def test_second_review_conflict_is_detected_before_dispatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review, tier="A")
            self._write_primary_result(review)
            import_specialist(review, "WORK-0001", "ATTEMPT-0001", state_digest(review))
            self._add_second_review(review, principal="EXEC-PRIMARY")
            result = check_review(review, check_generated=False)
            self.assertTrue(
                any(
                    "reviewer principal conflicts with contributing primary evidence"
                    in issue
                    for issue in result["issues"]
                )
            )

    def test_scope_intersection_is_angle_and_item_aware(self):
        whole = {"id": "SR-001", "angle": 3, "scope": {"kind": "whole_unit"}}
        item = {
            "id": "SR-002",
            "angle": 3,
            "scope": {
                "kind": "items",
                "items": [{"type": "path", "value": "src/target.py"}],
            },
        }
        assigned = {
            "paths": ["src/target.py"],
            "symbols": [],
            "angles": [3],
        }
        self.assertTrue(assigned_scope_intersects(assigned, whole))
        self.assertTrue(assigned_scope_intersects(assigned, item))
        self.assertFalse(
            assigned_scope_intersects(
                {**assigned, "paths": ["src/other.py"]},
                item,
            )
        )
        self.assertFalse(
            scope_covers(
                {
                    "kind": "items",
                    "items": [
                        {"type": "path", "value": "src/target.py"},
                        {"type": "symbol", "value": "extra"},
                    ],
                },
                item["scope"],
            )
        )
        self.assertFalse(
            scope_covers(
                {"kind": "items", "items": [{"type": "path"}]},
                {"kind": "items", "items": [{"type": "path"}]},
            )
        )
        self.assertFalse(
            assigned_scope_intersects(
                {**assigned, "angles": [2]},
                whole,
            )
        )

    def test_tier_a_density_warning_can_be_acknowledged(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            run = load_json(review / "run.json")
            units = [
                {
                    "id": f"WORK-{number:04d}",
                    "riskTier": "A",
                    "criticalReasons": [{"code": "durability_recovery"}],
                    "currentManifest": f"assignments/WORK-{number:04d}/MANIFEST-0001.json",
                    "currentManifestHash": f"hash-{number}",
                }
                for number in range(1, 6)
            ]
            result = pilot_diagnostics(run, units, [])
            self.assertTrue(result["warning"].startswith("PILOT-TIER-A-DENSITY:"))
            self.assertFalse(result["bulkDispatchAllowed"])
            acknowledgements = [{
                "id": "PILOT-TIER-A-DENSITY",
                "diagnosticIdentity": result["identity"],
            }]
            acknowledged = pilot_diagnostics(run, units, acknowledgements)
            self.assertIsNone(acknowledged["warning"])
            self.assertTrue(acknowledged["bulkDispatchAllowed"])
            units[0]["riskTier"] = "B"
            changed = pilot_diagnostics(run, units, acknowledgements)
            self.assertFalse(changed["acknowledged"])

    def test_warm_reuse_is_rejected_for_primary_attempts(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            self._rewrite_attempt_manifest(
                review,
                "ATTEMPT-0001",
                lambda manifest: manifest.update(
                    reviewerReuseMode="warm_batch",
                    reviewerBatchId="BATCH-0001",
                ),
            )
            with self.assertRaisesRegex(ReviewToolError, "requires stable reviewer lineage"):
                import_specialist(review, "WORK-0001", "ATTEMPT-0001", state_digest(review))

    def test_unhashable_attempt_result_status_fails_preflight_and_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            self._write_primary_result(review)
            unit = load_jsonl(review / "work-units.jsonl")[0]
            manifest = load_json(review / unit["reviewAttempts"][0]["manifest"])
            result_path = review / manifest["outputDirectory"] / "result.json"
            result = load_json(result_path)
            result["status"] = {"malformed": True}
            result_path.write_bytes(canonical_bytes(result))
            self.assertFalse(
                check_attempt_result(review, "WORK-0001", "ATTEMPT-0001")["ok"]
            )
            with self.assertRaisesRegex(ReviewToolError, "failed attempt checks"):
                import_specialist(
                    review,
                    "WORK-0001",
                    "ATTEMPT-0001",
                    state_digest(review),
                )

    def test_late_primary_import_invalidates_completed_second_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review, tier="A")
            self._write_primary_result(review)
            import_specialist(review, "WORK-0001", "ATTEMPT-0001", state_digest(review))
            second = self._add_second_review(review)
            self._write_second_result(review, second, principal="EXEC-SECOND")
            import_specialist(review, "WORK-0001", "ATTEMPT-0002", state_digest(review))
            self._add_late_primary_attempt(review)
            self._write_primary_result(
                review,
                attempt_id="ATTEMPT-0003",
                principal="PRINCIPAL-LATE-PRIMARY",
            )
            import_specialist(review, "WORK-0001", "ATTEMPT-0003", state_digest(review))
            unit = load_jsonl(review / "work-units.jsonl")[0]
            self.assertEqual(unit["status"], "needs_revalidation")
            self.assertEqual(unit["completedSecondReviews"], [])
            self.assertTrue(unit["secondReviewHistory"][0]["stale"])
            self._add_late_primary_attempt(
                review, angle=2, attempt_id="ATTEMPT-0004"
            )
            self._write_primary_result(
                review,
                attempt_id="ATTEMPT-0004",
                principal="PRINCIPAL-LATE-PRIMARY",
            )
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0004", state_digest(review)
            )
            self.assertEqual(
                load_jsonl(review / "work-units.jsonl")[0]["status"],
                "needs_revalidation",
            )

    def test_stale_second_review_can_be_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review, tier="A")
            self._write_primary_result(review)
            import_specialist(review, "WORK-0001", "ATTEMPT-0001", state_digest(review))
            second = self._add_second_review(review)
            self._write_second_result(review, second, principal="EXEC-SECOND")
            import_specialist(review, "WORK-0001", "ATTEMPT-0002", state_digest(review))
            self._add_late_primary_attempt(review)
            self._write_primary_result(
                review,
                attempt_id="ATTEMPT-0003",
                principal="PRINCIPAL-LATE-PRIMARY",
            )
            import_specialist(review, "WORK-0001", "ATTEMPT-0003", state_digest(review))
            replacement = self._add_second_review(
                review, principal="EXEC-REVIEW-AGAIN", attempt_id="ATTEMPT-0004"
            )
            self._write_second_result(
                review, replacement, principal="EXEC-REVIEW-AGAIN"
            )
            import_specialist(review, "WORK-0001", "ATTEMPT-0004", state_digest(review))
            unit = load_jsonl(review / "work-units.jsonl")[0]
            self.assertEqual(unit["status"], "complete")
            self.assertFalse(unit["completedSecondReviews"][0]["stale"])
            self.assertTrue(unit["secondReviewHistory"][0]["stale"])
            self.assertEqual(check_review(review, check_generated=False)["issues"], [])

    def test_nonintersecting_primary_does_not_revalidate_second_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review, tier="A")
            self._write_primary_result(review)
            import_specialist(review, "WORK-0001", "ATTEMPT-0001", state_digest(review))
            second = self._add_second_review(review)
            self._write_second_result(review, second, principal="EXEC-SECOND")
            import_specialist(review, "WORK-0001", "ATTEMPT-0002", state_digest(review))
            self._add_late_primary_attempt(review, angle=2)
            self._write_primary_result(
                review,
                attempt_id="ATTEMPT-0003",
                principal="PRINCIPAL-LATE-PRIMARY",
            )
            import_specialist(review, "WORK-0001", "ATTEMPT-0003", state_digest(review))
            unit = load_jsonl(review / "work-units.jsonl")[0]
            self.assertEqual(unit["status"], "complete")
            self.assertFalse(unit["completedSecondReviews"][0]["stale"])

    def test_duplicate_import_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            self._write_primary_result(review)
            import_specialist(review, "WORK-0001", "ATTEMPT-0001", state_digest(review))
            with self.assertRaisesRegex(ReviewToolError, "already been reconciled"):
                import_specialist(
                    review, "WORK-0001", "ATTEMPT-0001", state_digest(review)
                )

    def test_partial_second_review_cannot_create_completion(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review, tier="A")
            self._write_primary_result(review)
            import_specialist(review, "WORK-0001", "ATTEMPT-0001", state_digest(review))
            second = self._add_second_review(review)
            self._write_second_result(review, second, principal="EXEC-SECOND")
            result_path = review / second["manifest"]["outputDirectory"] / "result.json"
            result = load_json(result_path)
            result["status"] = "partial"
            result["secondReviewResults"] = []
            result["angleDispositions"] = {}
            result["remainingScope"]["angles"] = [3]
            result_path.write_bytes(canonical_bytes(result))
            import_specialist(review, "WORK-0001", "ATTEMPT-0002", state_digest(review))
            unit = load_jsonl(review / "work-units.jsonl")[0]
            self.assertEqual(unit["status"], "partial")
            self.assertEqual(unit["completedSecondReviews"], [])

    def test_warm_second_review_is_rejected_even_with_legacy_declared_lineage(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            run_path = review / "run.json"
            run = load_json(run_path)
            run["specialistCapabilities"] = {
                "stableReviewerLineage": True,
                "source": "harness_declared",
            }
            run_path.write_bytes(canonical_bytes(run))
            clean_unit(review, tier="A")
            self._write_primary_result(review)
            import_specialist(review, "WORK-0001", "ATTEMPT-0001", state_digest(review))
            second = self._add_second_review(
                review,
                reuse_mode="warm_batch",
                batch_id="BATCH-0001",
            )
            self._write_second_result(review, second, principal="EXEC-SECOND")
            with self.assertRaisesRegex(
                ReviewToolError, "requires stable reviewer lineage"
            ):
                import_specialist(review, "WORK-0001", "ATTEMPT-0002", state_digest(review))

    def test_warm_second_review_is_rejected_without_stable_lineage(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review, tier="A")
            self._write_primary_result(review)
            import_specialist(review, "WORK-0001", "ATTEMPT-0001", state_digest(review))
            second = self._add_second_review(
                review,
                reuse_mode="warm_batch",
                batch_id="BATCH-0001",
            )
            self._write_second_result(review, second, principal="EXEC-SECOND")
            with self.assertRaisesRegex(
                ReviewToolError, "requires stable reviewer lineage"
            ):
                import_specialist(review, "WORK-0001", "ATTEMPT-0002", state_digest(review))

    def test_packet_capsule_and_attempt_scaffold_are_deterministic(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            units = load_jsonl(review / "work-units.jsonl")
            unit = units[0]
            capsule = {
                "capsuleId": "CAPSULE-CORE-0001",
                "baselineContentSetHash": load_json(review / "run.json")["baselineContentSetHash"],
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
                "architectureHash": digest_bytes(
                    (review / "architecture.md").read_bytes()
                ),
                "referenceManifestHash": digest_bytes(
                    (review / "tooling/reference/manifest.json").read_bytes()
                ),
            }
            capsule_bytes = canonical_bytes(capsule)
            capsule_hash = digest_bytes(capsule_bytes)
            unit_manifest = load_json(review / unit["currentManifest"])
            unit_manifest["subsystem"] = "core"
            unit_manifest["orientationCapsule"] = {
                "path": "assignments/capsules/core.json",
                "hash": capsule_hash,
            }
            for field in ("entryPoints", "boundaries", "knownInvariants"):
                unit_manifest.pop(field, None)
            unit_bytes = canonical_bytes(unit_manifest)
            unit_hash = digest_bytes(unit_bytes)
            attempt_manifest = load_json(review / unit["reviewAttempts"][0]["manifest"])
            attempt_manifest["unitManifestHash"] = unit_hash
            attempt_bytes = canonical_bytes(attempt_manifest)
            attempt_hash = digest_bytes(attempt_bytes)
            unit["currentManifestHash"] = unit_hash
            unit["manifestHistory"][-1]["hash"] = unit_hash
            unit["reviewAttempts"][0]["unitManifestHash"] = unit_hash
            unit["reviewAttempts"][0]["manifestHash"] = attempt_hash
            transact(
                review,
                {
                    "work-units.jsonl": jsonl_bytes([unit]),
                    unit["currentManifest"]: unit_bytes,
                    unit["reviewAttempts"][0]["manifest"]: attempt_bytes,
                    "assignments/capsules/core.json": capsule_bytes,
                },
                operation="mutate",
                actor="orchestrator",
                timestamp="2026-01-01T00:00:01Z",
                expected_digest=state_digest(review),
            )
            first, metadata = render_packet(review, "WORK-0001", "ATTEMPT-0001")
            second, repeated = render_packet(review, "WORK-0001", "ATTEMPT-0001")
            self.assertEqual(first, second)
            self.assertEqual(metadata["packetHash"], repeated["packetHash"])
            self.assertIn(b"CAPSULE-CORE-0001", first)
            self.assertNotIn(b"### Angle 5", first)
            self.assertNotIn(b"Contract version:", first)
            initialize_attempt_result(review, "WORK-0001", "ATTEMPT-0001")
            self.assertTrue(
                check_attempt_result(review, "WORK-0001", "ATTEMPT-0001")["ok"]
            )
            reference_manifest_path = review / "tooling/reference/manifest.json"
            reference_manifest_bytes = reference_manifest_path.read_bytes()
            reference_manifest_path.unlink()
            with self.assertRaisesRegex(
                ReviewToolError, "reference installation manifest is missing"
            ):
                render_packet(review, "WORK-0001", "ATTEMPT-0001")
            reference_manifest_path.write_bytes(reference_manifest_bytes)
            (review / "architecture.md").write_text("# Changed architecture\n")
            with self.assertRaisesRegex(ReviewToolError, "stale architecture"):
                render_packet(review, "WORK-0001", "ATTEMPT-0001")
            (review / "architecture.md").unlink()
            with self.assertRaisesRegex(ReviewToolError, "architecture.md is missing"):
                render_packet(review, "WORK-0001", "ATTEMPT-0001")

    def test_capsule_structure_and_attempt_scaffold_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            unit = load_jsonl(review / "work-units.jsonl")[0]
            manifest = load_json(review / unit["currentManifest"])
            capsule_path = review / manifest["orientationCapsule"]["path"]
            capsule = load_json(capsule_path)
            capsule.pop("role")
            capsule_path.write_bytes(canonical_bytes(capsule))
            manifest["orientationCapsule"]["hash"] = digest_bytes(
                capsule_path.read_bytes()
            )
            with self.assertRaisesRegex(ReviewToolError, "role must be"):
                load_orientation_capsule(review, manifest)

            capsule["role"] = "Fixture component"
            capsule_path.write_bytes(canonical_bytes(capsule))
            validations = review / "agents/WORK-0001/ATTEMPT-0001/validations.jsonl"
            validations.parent.mkdir(parents=True)
            validations.write_bytes(b"")
            recovered = initialize_attempt_result(
                review, "WORK-0001", "ATTEMPT-0001"
            )
            self.assertTrue(recovered["repaired"])
            self.assertTrue(
                (review / "agents/WORK-0001/ATTEMPT-0001/result.json").is_file()
            )

    def test_attempt_check_reports_malformed_nested_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            initialize_attempt_result(review, "WORK-0001", "ATTEMPT-0001")
            result_path = review / "agents/WORK-0001/ATTEMPT-0001/result.json"
            result = load_json(result_path)
            result["angleDispositions"] = {"1": "not-an-object"}
            result["status"] = "complete"
            result_path.write_bytes(canonical_bytes(result))
            checked = check_attempt_result(
                review, "WORK-0001", "ATTEMPT-0001"
            )
            self.assertFalse(checked["ok"])
            self.assertTrue(
                any("must be an object" in issue for issue in checked["issues"])
            )

    def test_attempt_check_rejects_unhashable_inspected_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            initialize_attempt_result(review, "WORK-0001", "ATTEMPT-0001")
            result_path = review / "agents/WORK-0001/ATTEMPT-0001/result.json"
            result = load_json(result_path)
            result["inspected"]["paths"] = [{}]
            result_path.write_bytes(canonical_bytes(result))
            checked = check_attempt_result(
                review, "WORK-0001", "ATTEMPT-0001"
            )
            self.assertFalse(checked["ok"])
            self.assertTrue(
                any("array of strings" in issue for issue in checked["issues"])
            )

    def test_attempt_check_matches_import_requirement_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review, tier="A")
            self._write_primary_result(review)
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0001", state_digest(review)
            )
            second = self._add_second_review(review)
            self._write_second_result(review, second, principal="EXEC-SECOND")
            result_path = (
                review / second["manifest"]["outputDirectory"] / "result.json"
            )
            result = load_json(result_path)
            result["secondReviewResults"][0]["required"] = {
                "id": "SR-CORRUPTED"
            }
            result_path.write_bytes(canonical_bytes(result))
            checked = check_attempt_result(
                review, "WORK-0001", "ATTEMPT-0002"
            )
            self.assertFalse(checked["ok"])
            self.assertTrue(
                any("assigned requirement" in issue for issue in checked["issues"])
            )

    def test_second_review_requires_evidence_and_valid_conclusion(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review, tier="A")
            self._write_primary_result(review)
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0001", state_digest(review)
            )
            second = self._add_second_review(review)
            self._write_second_result(review, second, principal="EXEC-SECOND")
            result_path = (
                review / second["manifest"]["outputDirectory"] / "result.json"
            )
            result = load_json(result_path)
            result["secondReviewResults"][0]["evidence"] = []
            result["secondReviewResults"][0]["conclusion"] = "anything"
            result_path.write_bytes(canonical_bytes(result))
            checked = check_attempt_result(
                review, "WORK-0001", "ATTEMPT-0002"
            )
            self.assertFalse(checked["ok"])
            with self.assertRaisesRegex(
                ReviewToolError, "failed attempt checks"
            ):
                import_specialist(
                    review, "WORK-0001", "ATTEMPT-0002", state_digest(review)
                )

    def test_v2_independence_requires_distinct_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review, tier="A")
            self._write_primary_result(review)
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0001", state_digest(review)
            )
            second = self._add_second_review(
                review,
                principal="EXEC-SECOND",
                execution_id="EXEC-PRIMARY",
            )
            self._write_second_result(review, second, principal="EXEC-SECOND")
            with self.assertRaisesRegex(ReviewToolError, "execution conflicts"):
                import_specialist(
                    review, "WORK-0001", "ATTEMPT-0002", state_digest(review)
                )

    def test_imported_raw_evidence_is_revalidated(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review, tier="A")
            self._write_primary_result(review)
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0001", state_digest(review)
            )
            second = self._add_second_review(review)
            self._write_second_result(review, second, principal="EXEC-SECOND")
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0002", state_digest(review)
            )
            (
                review / "agents/WORK-0001/ATTEMPT-0001/result.json"
            ).write_bytes(canonical_bytes({}))
            checked = check_review(review, check_generated=False)
            self.assertFalse(checked["ok"])
            self.assertTrue(
                any("result identity mismatch" in issue for issue in checked["issues"])
            )

    def test_completion_must_resolve_to_imported_second_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review, tier="A")
            self._write_primary_result(review)
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0001", state_digest(review)
            )
            second = self._add_second_review(review)
            self._write_second_result(review, second, principal="EXEC-SECOND")
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0002", state_digest(review)
            )
            units = load_jsonl(review / "work-units.jsonl")
            units[0]["completedSecondReviews"][0]["attempt"] = (
                "WORK-0001/ATTEMPT-9999"
            )
            transact(
                review,
                {"work-units.jsonl": jsonl_bytes(units)},
                operation="mutate",
                actor="test",
                timestamp="2026-01-01T00:00:05Z",
                expected_digest=state_digest(review),
            )
            checked = check_review(review, check_generated=False)
            self.assertFalse(checked["ok"])
            self.assertTrue(
                any("second-review attempt is missing" in issue for issue in checked["issues"])
            )
            self._add_late_primary_attempt(review, angle=2)
            self._write_primary_result(
                review,
                attempt_id="ATTEMPT-0003",
                principal="PRINCIPAL-LATE-PRIMARY",
            )
            with self.assertRaisesRegex(
                ReviewToolError, "second-review attempt is missing"
            ):
                import_specialist(
                    review, "WORK-0001", "ATTEMPT-0003", state_digest(review)
                )

    def test_packet_rejects_modified_reference_extract(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            (review / "tooling/reference/angle-03.md").write_text("changed\n")
            with self.assertRaisesRegex(ReviewToolError, "extraction changed"):
                render_packet(review, "WORK-0001", "ATTEMPT-0001")

    def test_manifest_output_directory_is_used_by_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            units = load_jsonl(review / "work-units.jsonl")
            attempt = units[0]["reviewAttempts"][0]
            manifest_path = review / attempt["manifest"]
            manifest = load_json(manifest_path)
            manifest["outputDirectory"] = "agents/custom-output"
            manifest_bytes = canonical_bytes(manifest)
            attempt["manifestHash"] = digest_bytes(manifest_bytes)
            transact(
                review,
                {
                    "work-units.jsonl": jsonl_bytes(units),
                    attempt["manifest"]: manifest_bytes,
                },
                operation="mutate",
                actor="test",
                timestamp="2026-01-01T00:00:06Z",
                expected_digest=state_digest(review),
            )
            initialize_attempt_result(review, "WORK-0001", "ATTEMPT-0001")
            imported = import_specialist(
                review, "WORK-0001", "ATTEMPT-0001", state_digest(review)
            )
            self.assertIn("stateDigest", imported)

    def test_later_primary_supersedes_pending_second_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review, tier="A")
            self._write_primary_result(review)
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0001", state_digest(review)
            )
            self._add_second_review(review)
            self._add_late_primary_attempt(review)
            self._write_primary_result(
                review,
                attempt_id="ATTEMPT-0003",
                principal="PRINCIPAL-LATE-PRIMARY",
            )
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0003", state_digest(review)
            )
            unit = load_jsonl(review / "work-units.jsonl")[0]
            pending = next(
                item
                for item in unit["reviewAttempts"]
                if item["attemptId"] == "ATTEMPT-0002"
            )
            self.assertEqual(pending["importDisposition"], "superseded")
            self.assertFalse(check_review(review, check_generated=False)["issues"])

    def test_attempt_check_reports_malformed_attempt_identifier(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            units = load_jsonl(review / "work-units.jsonl")
            unit = units[0]
            original = unit["reviewAttempts"][0]
            manifest = load_json(review / original["manifest"])
            manifest.update(
                attemptId="BAD-ID",
                outputDirectory="agents/WORK-0001/BAD-ID",
            )
            manifest_bytes = canonical_bytes(manifest)
            unit["reviewAttempts"].append({
                **original,
                "attemptId": "BAD-ID",
                "manifest": "assignments/WORK-0001/BAD-ID.json",
                "manifestHash": digest_bytes(manifest_bytes),
            })
            transact(
                review,
                {
                    "work-units.jsonl": jsonl_bytes([unit]),
                    "assignments/WORK-0001/BAD-ID.json": manifest_bytes,
                },
                operation="mutate",
                actor="test",
                timestamp="2026-01-01T00:00:03Z",
                expected_digest=state_digest(review),
            )
            initialize_attempt_result(review, "WORK-0001", "BAD-ID")
            checked = check_attempt_result(review, "WORK-0001", "BAD-ID")
            self.assertFalse(checked["ok"])
            self.assertTrue(
                any("expected ATTEMPT-NNNN" in issue for issue in checked["issues"])
            )
    def test_second_review_assignment_must_exactly_match_requirement(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review, tier="A")
            self._write_primary_result(review)
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0001", state_digest(review)
            )
            self._add_second_review(review)
            self._rewrite_attempt_manifest(
                review,
                "ATTEMPT-0002",
                lambda manifest: manifest["assignedScope"].update(angles=[7]),
            )
            with self.assertRaisesRegex(ReviewToolError, "exactly match"):
                initialize_attempt_result(
                    review, "WORK-0001", "ATTEMPT-0002"
                )

    def test_complete_result_cannot_leave_scope_uninspected(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            self._write_primary_result(review)
            result_path = (
                review / "agents/WORK-0001/ATTEMPT-0001/result.json"
            )
            result = load_json(result_path)
            result["inspected"]["paths"] = []
            result["notInspected"]["paths"] = ["src/example.py"]
            result["remainingScope"]["paths"] = ["src/example.py"]
            result_path.write_bytes(canonical_bytes(result))
            checked = check_attempt_result(
                review, "WORK-0001", "ATTEMPT-0001"
            )
            self.assertFalse(checked["ok"])
            self.assertTrue(
                any("exactly partition" in issue or "remaining scope" in issue for issue in checked["issues"])
            )

    def test_complete_angle_requires_substantive_evidence_shape(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            self._write_primary_result(review)
            result_path = (
                review / "agents/WORK-0001/ATTEMPT-0001/result.json"
            )
            result = load_json(result_path)
            for disposition in result["angleDispositions"].values():
                disposition["evidence"] = [{"x": 1}]
            result_path.write_bytes(canonical_bytes(result))
            checked = check_attempt_result(
                review, "WORK-0001", "ATTEMPT-0001"
            )
            self.assertFalse(checked["ok"])
            self.assertTrue(
                any("substantive" in issue for issue in checked["issues"])
            )

    def test_check_revalidates_imported_result_schema_after_hash_reseal(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            self._write_primary_result(review)
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0001", state_digest(review)
            )
            result_path = (
                review / "agents/WORK-0001/ATTEMPT-0001/result.json"
            )
            result = load_json(result_path)
            result["workId"] = "WORK-9999"
            result_path.write_bytes(canonical_bytes(result))
            units = load_jsonl(review / "work-units.jsonl")
            attempt = units[0]["reviewAttempts"][0]
            attempt["resultHash"] = digest_bytes(result_path.read_bytes())
            attempt["attemptEvidenceHash"] = digest_bytes(
                canonical_bytes({"result": result, "validations": []}).removesuffix(
                    b"\n"
                )
            )
            (review / "work-units.jsonl").write_bytes(jsonl_bytes(units))
            checked = check_review(review, check_generated=False)
            self.assertTrue(
                any("workId mismatch" in issue for issue in checked["issues"]),
                checked["issues"],
            )

    def test_completion_observations_are_bound_to_candidate_refs(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review, tier="A")
            self._write_primary_result(review)
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0001", state_digest(review)
            )
            second = self._add_second_review(review)
            self._write_second_result(review, second, principal="EXEC-SECOND")
            result_path = (
                review / second["manifest"]["outputDirectory"] / "result.json"
            )
            result = load_json(result_path)
            result["candidates"] = [{
                "localId": "CAND-A2-001",
                "title": "",
                "category": "",
                "primaryLocation": None,
                "additionalLocations": [],
                "proposedDisposition": "",
                "proposedMateriality": "",
                "proposedMaterialityRationale": "",
                "confidence": "",
                "affectedComponents": [],
                "affectedConfigurations": [],
                "affectedDeployments": [],
                "trigger": "",
                "expected": "",
                "actual": "",
                "impact": "",
                "likelihood": "",
                "blastRadius": "",
                "evidence": [],
                "reachability": "",
                "existingChecks": "",
                "reproduction": "",
                "recommendation": "",
                "regressionTest": "",
                "counterargument": "",
                "residualUncertainty": "",
                "validationRefs": [],
            }]
            result["secondReviewResults"][0]["candidateRefs"] = ["CAND-A2-001"]
            result_path.write_bytes(canonical_bytes(result))
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0002", state_digest(review)
            )
            units = load_jsonl(review / "work-units.jsonl")
            units[0]["completedSecondReviews"][0]["observations"] = [
                "OBS-999999"
            ]
            (review / "work-units.jsonl").write_bytes(jsonl_bytes(units))
            checked = check_review(review, check_generated=False)
            self.assertTrue(
                any(
                    "completion observations" in issue
                    for issue in checked["issues"]
                ),
                checked["issues"],
            )

    def test_second_review_history_is_hash_validated(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review, tier="A")
            self._write_primary_result(review)
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0001", state_digest(review)
            )
            second = self._add_second_review(review)
            self._write_second_result(review, second, principal="EXEC-SECOND")
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0002", state_digest(review)
            )
            self._add_late_primary_attempt(review)
            self._write_primary_result(
                review,
                attempt_id="ATTEMPT-0003",
                principal="PRINCIPAL-LATE-PRIMARY",
            )
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0003", state_digest(review)
            )
            units = load_jsonl(review / "work-units.jsonl")
            units[0]["secondReviewHistory"][0]["staleReason"] = "tampered"
            (review / "work-units.jsonl").write_bytes(jsonl_bytes(units))
            checked = check_review(review, check_generated=False)
            self.assertTrue(
                any("secondReviewHistory identity" in issue for issue in checked["issues"])
            )

    def test_residual_uncertainty_is_merged_by_source_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            self._write_primary_result(review)
            first_path = (
                review / "agents/WORK-0001/ATTEMPT-0001/result.json"
            )
            first = load_json(first_path)
            first["residualUncertainty"] = ["primary uncertainty"]
            first_path.write_bytes(canonical_bytes(first))
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0001", state_digest(review)
            )
            self._add_late_primary_attempt(
                review, angle=2, attempt_id="ATTEMPT-0002"
            )
            self._write_primary_result(
                review,
                attempt_id="ATTEMPT-0002",
                principal="PRINCIPAL-LATE-PRIMARY",
            )
            second_path = (
                review / "agents/WORK-0001/ATTEMPT-0002/result.json"
            )
            second = load_json(second_path)
            second["residualUncertainty"] = ["later uncertainty"]
            second_path.write_bytes(canonical_bytes(second))
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0002", state_digest(review)
            )
            values = load_jsonl(review / "work-units.jsonl")[0][
                "residualUncertainty"
            ]
            self.assertEqual(
                {item["value"] for item in values},
                {"primary uncertainty", "later uncertainty"},
            )

    def test_reference_source_and_extract_cannot_be_resealed_together(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            source_path = review / "tooling/reference/source/reference-pack.md"
            source = source_path.read_bytes()
            original = b"Storage, durability, and crash recovery"
            replacement = b"Storage, durability, and crash recoverx"
            self.assertEqual(len(original), len(replacement))
            source_path.write_bytes(source.replace(original, replacement, 1))
            angle_path = review / "tooling/reference/angle-03.md"
            angle_path.write_bytes(
                angle_path.read_bytes().replace(original, replacement, 1)
            )
            with self.assertRaisesRegex(ReviewToolError, "source identity"):
                render_packet(review, "WORK-0001", "ATTEMPT-0001")

    def test_new_attempt_cannot_arrive_already_imported(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            review = new_review(base)
            clean_unit(review)
            units = load_jsonl(review / "work-units.jsonl")
            unit = units[0]
            original = unit["reviewAttempts"][0]
            manifest = load_json(review / original["manifest"])
            manifest["attemptId"] = "ATTEMPT-0002"
            manifest["outputDirectory"] = "agents/WORK-0001/ATTEMPT-0002"
            manifest_bytes = canonical_bytes(manifest)
            unit["reviewAttempts"].append(
                {
                    **original,
                    "attemptId": "ATTEMPT-0002",
                    "manifest": "assignments/WORK-0001/ATTEMPT-0002.json",
                    "manifestHash": digest_bytes(manifest_bytes),
                    "status": "complete",
                    "importDisposition": "imported",
                    "resultHash": "fabricated",
                    "attemptEvidenceHash": "fabricated",
                }
            )
            changes = base / "changes.json"
            changes.write_bytes(
                canonical_bytes(
                    {
                        "work-units.jsonl": [unit],
                        "assignments/WORK-0001/ATTEMPT-0002.json": manifest,
                    }
                )
            )
            with self.assertRaisesRegex(ReviewToolError, "must start assigned"):
                apply_mutation(review, state_digest(review), changes)

    def test_check_pass_reuses_identity_keyed_artifact_reads(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review, tier="A")
            self._write_primary_result(review)
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0001", state_digest(review)
            )
            second = self._add_second_review(review)
            self._write_second_result(review, second, principal="EXEC-SECOND")
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0002", state_digest(review)
            )
            original_read = Path.read_bytes
            loaded_paths: list[Path] = []

            def recording_read(path):
                loaded_paths.append(Path(path).resolve())
                return original_read(path)

            with patch.object(Path, "read_bytes", recording_read):
                checked = check_review(review, check_generated=False)
            self.assertTrue(checked["ok"], checked["issues"])
            for attempt_id in ("ATTEMPT-0001", "ATTEMPT-0002"):
                result_path = (
                    review
                    / f"agents/WORK-0001/{attempt_id}/result.json"
                ).resolve()
                self.assertEqual(loaded_paths.count(result_path), 1)
    def test_oversized_capsule_and_packet_emit_efficiency_warnings(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            units = load_jsonl(review / "work-units.jsonl")
            unit = units[0]
            manifest_path = review / unit["currentManifest"]
            unit_manifest = load_json(manifest_path)
            capsule_path = (
                review / unit_manifest["orientationCapsule"]["path"]
            )
            capsule = load_json(capsule_path)
            capsule["sharedInvariants"] = ["x" * (140 * 1024)]
            capsule_bytes = canonical_bytes(capsule)
            capsule_path.write_bytes(capsule_bytes)
            unit_manifest["orientationCapsule"]["hash"] = digest_bytes(
                capsule_bytes
            )
            unit_manifest_bytes = canonical_bytes(unit_manifest)
            manifest_path.write_bytes(unit_manifest_bytes)
            unit_hash = digest_bytes(unit_manifest_bytes)
            unit["currentManifestHash"] = unit_hash
            unit["manifestHistory"][-1]["hash"] = unit_hash
            attempt = unit["reviewAttempts"][0]
            attempt["unitManifestHash"] = unit_hash
            attempt_path = review / attempt["manifest"]
            attempt_manifest = load_json(attempt_path)
            attempt_manifest["unitManifestHash"] = unit_hash
            attempt_bytes = canonical_bytes(attempt_manifest)
            attempt_path.write_bytes(attempt_bytes)
            attempt["manifestHash"] = digest_bytes(attempt_bytes)
            (review / "work-units.jsonl").write_bytes(jsonl_bytes(units))
            _, metadata = render_packet(
                review, "WORK-0001", "ATTEMPT-0001"
            )
            self.assertTrue(
                any("orientation capsule" in item for item in metadata["warnings"])
            )
            self.assertTrue(
                any("specialist packet" in item for item in metadata["warnings"])
            )

    def test_second_review_history_is_append_only_and_complete(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            review = new_review(base)
            clean_unit(review, tier="A")
            self._write_primary_result(review)
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0001", state_digest(review)
            )
            second = self._add_second_review(review)
            self._write_second_result(
                review,
                second,
                principal="EXEC-SECOND",
            )
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0002", state_digest(review)
            )
            self._add_late_primary_attempt(review)
            self._write_primary_result(
                review,
                attempt_id="ATTEMPT-0003",
                principal="PRINCIPAL-LATE-PRIMARY",
            )
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0003", state_digest(review)
            )
            units = load_jsonl(review / "work-units.jsonl")
            self.assertEqual(len(units[0]["secondReviewHistory"]), 1)
            units[0]["secondReviewHistory"] = []
            changes = base / "delete-second-history.json"
            changes.write_bytes(
                canonical_bytes({"work-units.jsonl": units})
            )
            with self.assertRaisesRegex(
                ReviewToolError,
                "secondReviewHistory is append-only",
            ):
                apply_mutation(
                    review,
                    state_digest(review),
                    changes)
            (review / "work-units.jsonl").write_bytes(jsonl_bytes(units))
            issues = check_review(review, check_generated=False)["issues"]
            self.assertTrue(
                any(
                    "second-review attempt provenance is incomplete" in issue
                    for issue in issues
                ),
                issues,
            )

    def test_partial_primary_rejects_invalid_angle_status_before_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            self._write_primary_result(review, status="partial")
            result_path = (
                review / "agents/WORK-0001/ATTEMPT-0001/result.json"
            )
            result = load_json(result_path)
            result["angleDispositions"]["1"] = {
                "status": "teleported",
                "evidence": [],
            }
            result_path.write_bytes(canonical_bytes(result))
            checked = check_attempt_result(
                review,
                "WORK-0001",
                "ATTEMPT-0001",
            )
            self.assertFalse(checked["ok"])
            self.assertTrue(
                any("invalid status" in issue for issue in checked["issues"])
            )
            with self.assertRaisesRegex(
                ReviewToolError,
                "invalid status",
            ):
                import_specialist(
                    review,
                    "WORK-0001",
                    "ATTEMPT-0001",
                    state_digest(review),
                )

    def test_attempt_row_lifecycle_must_match_imported_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            self._write_primary_result(review)
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0001", state_digest(review)
            )
            units = load_jsonl(review / "work-units.jsonl")
            units[0]["reviewAttempts"][0]["status"] = "assigned"
            (review / "work-units.jsonl").write_bytes(jsonl_bytes(units))
            issues = check_review(review, check_generated=False)["issues"]
            self.assertTrue(
                any(
                    "status and importDisposition are inconsistent" in issue
                    for issue in issues
                ),
                issues,
            )
            self.assertTrue(
                any(
                    "status does not match imported result" in issue
                    for issue in issues
                ),
                issues,
            )

    def test_specialist_import_reads_result_snapshot_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            self._write_primary_result(review)
            result_path = (
                review / "agents/WORK-0001/ATTEMPT-0001/result.json"
            ).resolve()
            original_read = Path.read_bytes
            reads: list[Path] = []

            def recording_read(path):
                resolved = Path(path).resolve()
                if resolved == result_path:
                    reads.append(resolved)
                return original_read(path)

            with patch.object(Path, "read_bytes", recording_read):
                import_specialist(
                    review,
                    "WORK-0001",
                    "ATTEMPT-0001",
                    state_digest(review),
                )
            self.assertEqual(reads, [result_path])

    def test_primary_assignment_cannot_escape_sealed_unit_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            self._rewrite_attempt_manifest(
                review,
                "ATTEMPT-0001",
                lambda manifest: manifest["assignedScope"].update(
                    paths=["src/not-in-unit.py"]
                ),
            )
            checked = check_review(review, check_generated=False)
            self.assertTrue(
                any(
                    "exceeds the sealed unit manifest" in issue
                    for issue in checked["issues"]
                ),
                checked["issues"],
            )

    def test_complete_unit_requires_aggregate_primary_scope_coverage(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            self._write_primary_result(review, status="partial")
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0001", state_digest(review)
            )
            units = load_jsonl(review / "work-units.jsonl")
            units[0]["status"] = "complete"
            (review / "work-units.jsonl").write_bytes(jsonl_bytes(units))
            checked = check_review(review, check_generated=False)
            self.assertFalse(checked["ok"])
            self.assertFalse(checked["bulkDispatchAllowed"])
            self.assertTrue(
                any(
                    "lacks primary scope coverage" in issue
                    for issue in checked["issues"]
                ),
                checked["issues"],
            )

    def test_partial_result_requires_exact_remaining_partition(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            self._write_primary_result(review, status="partial")
            result_path = (
                review / "agents/WORK-0001/ATTEMPT-0001/result.json"
            )
            result = load_json(result_path)
            result["remainingScope"] = {
                "paths": [],
                "symbols": [],
                "angles": [],
            }
            result_path.write_bytes(canonical_bytes(result))
            checked = check_attempt_result(
                review, "WORK-0001", "ATTEMPT-0001"
            )
            self.assertFalse(checked["ok"])
            self.assertTrue(
                any("remainingScope" in issue for issue in checked["issues"])
            )

    def test_angle_evidence_requires_valid_in_assignment_scope_and_location(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            self._write_primary_result(review)
            result_path = (
                review / "agents/WORK-0001/ATTEMPT-0001/result.json"
            )
            result = load_json(result_path)
            result["angleDispositions"]["1"]["evidence"] = [{
                "scopeCovered": {},
                "locations": [""],
                "claim": "claim",
            }]
            result_path.write_bytes(canonical_bytes(result))
            checked = check_attempt_result(
                review, "WORK-0001", "ATTEMPT-0001"
            )
            self.assertFalse(checked["ok"])
            self.assertTrue(
                any("substantive scope" in issue for issue in checked["issues"])
            )

    def test_angle_evidence_accepts_canonical_structured_location(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            self._write_primary_result(review)
            result_path = (
                review / "agents/WORK-0001/ATTEMPT-0001/result.json"
            )
            result = load_json(result_path)
            result["angleDispositions"]["1"]["evidence"][0]["locations"] = [{
                "path": "src/example.py",
                "startLine": 1,
                "endLine": 1,
            }]
            result_path.write_bytes(canonical_bytes(result))
            checked = check_attempt_result(
                review, "WORK-0001", "ATTEMPT-0001"
            )
            self.assertTrue(checked["ok"], checked["issues"])

    def test_attempt_local_validation_result_enum_is_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            self._write_primary_result(review)
            validation_path = (
                review
                / "agents/WORK-0001/ATTEMPT-0001/validations.jsonl"
            )
            validation_path.write_bytes(canonical_bytes({
                "localId": "AVAL-A1-001",
                "validationClass": "ordinary",
                "command": "",
                "cwd": "",
                "environmentSummary": "",
                "startedAt": "",
                "endedAt": "",
                "exitStatus": None,
                "result": "teleported",
                "limitations": [],
                "createdArtifacts": [],
                "supportsCandidates": [],
            }))
            checked = check_attempt_result(
                review, "WORK-0001", "ATTEMPT-0001"
            )
            self.assertFalse(checked["ok"])
            self.assertTrue(
                any("result is invalid" in issue for issue in checked["issues"])
            )

    def test_attempt_local_candidate_schema_is_complete(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            self._write_primary_result(review)
            result_path = (
                review / "agents/WORK-0001/ATTEMPT-0001/result.json"
            )
            result = load_json(result_path)
            result["candidates"] = [{"localId": "CAND-A1-001"}]
            result_path.write_bytes(canonical_bytes(result))
            checked = check_attempt_result(
                review, "WORK-0001", "ATTEMPT-0001"
            )
            self.assertFalse(checked["ok"])
            self.assertTrue(
                any(
                    "missing required fields" in issue
                    for issue in checked["issues"]
                )
            )

    def test_sealed_packet_artifacts_are_hashed_and_parsed_from_one_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            units = load_jsonl(review / "work-units.jsonl")
            attempt_path = (
                review / units[0]["reviewAttempts"][0]["manifest"]
            ).resolve()
            unit_path = (review / units[0]["currentManifest"]).resolve()
            capsule_path = (
                review / "assignments/capsules/core.json"
            ).resolve()
            targets = {attempt_path, unit_path, capsule_path}
            reads = {target: 0 for target in targets}
            original_read = Path.read_bytes

            def recording_read(path):
                resolved = Path(path).resolve()
                if resolved in reads:
                    reads[resolved] += 1
                return original_read(path)

            with patch.object(Path, "read_bytes", recording_read):
                render_packet(review, "WORK-0001", "ATTEMPT-0001")
            self.assertEqual(reads, {target: 1 for target in targets})

    def test_reviewer_execution_id_is_globally_unique(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review, tier="A")
            self._write_primary_result(review)
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0001", state_digest(review)
            )
            self._add_second_review(
                review,
                principal="PRINCIPAL-SECOND",
                execution_id="EXEC-PRIMARY",
            )
            checked = check_review(review, check_generated=False)
            self.assertTrue(
                any(
                    "reviewerExecutionId is already owned" in issue
                    for issue in checked["issues"]
                ),
                checked["issues"],
            )

    def test_packet_and_scaffold_reject_reconciled_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            self._write_primary_result(review)
            import_specialist(
                review, "WORK-0001", "ATTEMPT-0001", state_digest(review)
            )
            for action in (render_packet, initialize_attempt_result):
                with self.subTest(action=action.__name__):
                    with self.assertRaisesRegex(
                        ReviewToolError, "assigned, pending"
                    ):
                        action(review, "WORK-0001", "ATTEMPT-0001")

    def test_item_scoped_evidence_uses_canonical_type_discriminator(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            self._write_primary_result(review)
            result_path = (
                review / "agents/WORK-0001/ATTEMPT-0001/result.json"
            )
            result = load_json(result_path)
            result["angleDispositions"]["1"]["evidence"][0][
                "scopeCovered"
            ] = {
                "kind": "items",
                "items": [{"type": "path", "value": "src/example.py"}],
            }
            result_path.write_bytes(canonical_bytes(result))
            checked = check_attempt_result(
                review, "WORK-0001", "ATTEMPT-0001"
            )
            self.assertTrue(checked["ok"], checked["issues"])

    def test_string_evidence_location_must_be_inside_assignment(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            self._write_primary_result(review)
            result_path = (
                review / "agents/WORK-0001/ATTEMPT-0001/result.json"
            )
            result = load_json(result_path)
            result["angleDispositions"]["1"]["evidence"][0][
                "locations"
            ] = ["src/not-assigned.py:1"]
            result_path.write_bytes(canonical_bytes(result))
            checked = check_attempt_result(
                review, "WORK-0001", "ATTEMPT-0001"
            )
            self.assertFalse(checked["ok"])
            self.assertTrue(
                any("out-of-assignment" in issue for issue in checked["issues"])
            )

    def test_sliced_assignment_cannot_claim_whole_unit_evidence(self):
        issues: list[str] = []
        _evidence_list(
            [{
                "scopeCovered": {"kind": "whole_unit"},
                "locations": ["src/a.py:1"],
                "claim": "slice",
            }],
            "angle 1 evidence",
            issues,
            {"paths": ["src/a.py"], "symbols": []},
            {"paths": {"src/a.py", "src/b.py"}, "symbols": set()},
        )
        self.assertTrue(
            any("sliced assignment" in issue for issue in issues), issues
        )

    def test_canonical_validation_evidence_is_append_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            review = new_review(base)
            clean_unit(review)
            validation = {
                "id": "VAL-000001",
                "sourceAttempt": "WORK-0001/ATTEMPT-0001",
                "sourceLocalId": "AVAL-A1-001",
                "workUnits": ["WORK-0001"],
                "observationIds": [],
                "securityLevel": "off",
                "validationClass": "ordinary",
                "command": "true",
                "cwd": ".",
                "environmentSummary": "fixture",
                "startedAt": "2026-01-01T00:00:00Z",
                "endedAt": "2026-01-01T00:00:00Z",
                "exitStatus": 0,
                "result": "passed",
                "limitations": [],
                "createdArtifacts": [],
                "trackedTreeMutation": None,
            }
            first = base / "validation-add.json"
            first.write_bytes(
                canonical_bytes({"validations.jsonl": [validation]})
            )
            with self.assertRaisesRegex(
                ReviewToolError, "only by evidence import"
            ):
                apply_mutation(
                    review, state_digest(review), first)
            (review / "validations.jsonl").write_bytes(
                canonical_bytes(validation)
            )
            changed = dict(validation)
            changed["command"] = "rewritten"
            second = base / "validation-rewrite.json"
            second.write_bytes(
                canonical_bytes({"validations.jsonl": [changed]})
            )
            with self.assertRaisesRegex(
                ReviewToolError, "validation evidence is immutable"
            ):
                apply_mutation(
                    review, state_digest(review), second)

    def test_canonical_validation_requires_full_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            (review / "validations.jsonl").write_bytes(canonical_bytes({
                "id": "VAL-000001",
                "result": "passed",
                "validationClass": "ordinary",
                "securityLevel": "off",
                "observationIds": [],
            }))
            checked = check_review(review, check_generated=False)
            self.assertFalse(checked["ok"])
            self.assertTrue(
                any(
                    "missing required fields" in issue
                    for issue in checked["issues"]
                ),
                checked["issues"],
            )

    def test_canonical_validation_requires_imported_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            (review / "validations.jsonl").write_bytes(canonical_bytes({
                "id": "VAL-000001",
                "sourceLocalId": "AVAL-A1-001",
                "observationIds": [],
                "securityLevel": "off",
                "validationClass": "ordinary",
                "command": "true",
                "cwd": ".",
                "environmentSummary": "fixture",
                "startedAt": "2026-01-01T00:00:00Z",
                "endedAt": "2026-01-01T00:00:00Z",
                "exitStatus": 0,
                "result": "passed",
                "limitations": [],
                "createdArtifacts": [],
                "trackedTreeMutation": None,
            }))
            checked = check_review(review, check_generated=False)
            self.assertFalse(checked["ok"])
            self.assertTrue(
                any(
                    "invalid or unimported sourceAttempt" in issue
                    or "invalid workUnits provenance" in issue
                    for issue in checked["issues"]
                ),
                checked["issues"],
            )

    def test_canonical_observation_imported_evidence_is_immutable(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            review = new_review(base)
            clean_unit(review)
            candidate = {
                "localId": "CAND-A1-001",
                "title": "",
                "category": "",
                "primaryLocation": None,
                "additionalLocations": [],
                "proposedDisposition": "",
                "proposedMateriality": "",
                "proposedMaterialityRationale": "",
                "confidence": "",
                "affectedComponents": [],
                "affectedConfigurations": [],
                "affectedDeployments": [],
                "trigger": "",
                "expected": "",
                "actual": "",
                "impact": "",
                "likelihood": "",
                "blastRadius": "",
                "evidence": ["sealed evidence"],
                "reachability": "",
                "existingChecks": "",
                "reproduction": "",
                "recommendation": "",
                "regressionTest": "",
                "counterargument": "",
                "residualUncertainty": "",
                "validationRefs": [],
            }
            observation = _candidate_observation(
                candidate,
                identifier="OBS-000001",
                source_work_units=["WORK-0001"],
                source_attempt="WORK-0001/ATTEMPT-0001",
                default_title="",
                default_category="",
            )
            (review / "observations.jsonl").write_bytes(
                canonical_bytes(observation)
            )
            changed = dict(observation)
            changed["evidence"] = ["rewritten"]
            second = base / "observation-rewrite.json"
            second.write_bytes(
                canonical_bytes({"observations.jsonl": [changed]})
            )
            with self.assertRaisesRegex(
                ReviewToolError, "immutable observation evidence changed"
            ):
                apply_mutation(
                    review, state_digest(review), second)

    def test_duplicate_second_review_requirement_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review, tier="A")
            units = load_jsonl(review / "work-units.jsonl")
            duplicate = dict(units[0]["requiredSecondReviews"][0])
            duplicate["angle"] = 4
            units[0]["requiredSecondReviews"].append(duplicate)
            (review / "work-units.jsonl").write_bytes(jsonl_bytes(units))
            checked = check_review(review, check_generated=False)
            self.assertTrue(
                any(
                    "duplicate second-review requirement identifiers" in issue
                    for issue in checked["issues"]
                ),
                checked["issues"],
            )

    def test_nested_candidate_and_limitation_items_must_be_substantive(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            self._write_primary_result(review)
            result_path = (
                review / "agents/WORK-0001/ATTEMPT-0001/result.json"
            )
            result = load_json(result_path)
            result["candidates"] = [{
                "localId": "CAND-A1-001",
                "title": "",
                "category": "",
                "primaryLocation": {},
                "additionalLocations": [{}],
                "proposedDisposition": "",
                "proposedMateriality": "",
                "proposedMaterialityRationale": "",
                "confidence": "",
                "affectedComponents": [None],
                "affectedConfigurations": [],
                "affectedDeployments": [],
                "trigger": "",
                "expected": "",
                "actual": "",
                "impact": "",
                "likelihood": "",
                "blastRadius": "",
                "evidence": [None],
                "reachability": "",
                "existingChecks": "",
                "reproduction": "",
                "recommendation": "",
                "regressionTest": "",
                "counterargument": "",
                "residualUncertainty": "",
                "validationRefs": [],
            }]
            result_path.write_bytes(canonical_bytes(result))
            validations = (
                review
                / "agents/WORK-0001/ATTEMPT-0001/validations.jsonl"
            )
            validations.write_bytes(canonical_bytes({
                "localId": "AVAL-A1-001",
                "validationClass": "ordinary",
                "command": "",
                "cwd": "",
                "environmentSummary": "",
                "startedAt": "",
                "endedAt": "",
                "exitStatus": None,
                "result": "blocked",
                "limitations": [{"x": 1}],
                "createdArtifacts": [],
                "supportsCandidates": [],
            }))
            checked = check_attempt_result(
                review, "WORK-0001", "ATTEMPT-0001"
            )
            self.assertFalse(checked["ok"])
            self.assertTrue(
                any(
                    "invalid location" in issue
                    or "empty or malformed item" in issue
                    for issue in checked["issues"]
                ),
                checked["issues"],
            )

    def test_blocked_validation_requires_structured_limitation(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            self._write_primary_result(review)
            validation_path = (
                review
                / "agents/WORK-0001/ATTEMPT-0001/validations.jsonl"
            )
            validation_path.write_bytes(canonical_bytes({
                "localId": "AVAL-A1-001",
                "validationClass": "ordinary",
                "command": "",
                "cwd": "",
                "environmentSummary": "",
                "startedAt": "",
                "endedAt": "",
                "exitStatus": None,
                "result": "blocked",
                "limitations": [{"x": 1}],
                "createdArtifacts": [],
                "supportsCandidates": [],
            }))
            checked = check_attempt_result(
                review, "WORK-0001", "ATTEMPT-0001"
            )
            self.assertFalse(checked["ok"])
            self.assertTrue(
                any(
                    "description, materiality" in issue
                    for issue in checked["issues"]
                ),
                checked["issues"],
            )

    def test_duplicate_observation_cycles_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            rows = [
                {
                    "id": "OBS-000001",
                    "disposition": "duplicate",
                    "duplicateOf": "OBS-000002",
                    "validationRefs": [],
                },
                {
                    "id": "OBS-000002",
                    "disposition": "duplicate",
                    "duplicateOf": "OBS-000001",
                    "validationRefs": [],
                },
            ]
            (review / "observations.jsonl").write_bytes(jsonl_bytes(rows))
            checked = check_review(review, check_generated=False)
            self.assertTrue(
                any(
                    "duplicate observation mapping contains a cycle" in issue
                    for issue in checked["issues"]
                ),
                checked["issues"],
            )

    def test_primary_result_rejects_second_review_claims(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            self._write_primary_result(review)
            result_path = (
                review / "agents/WORK-0001/ATTEMPT-0001/result.json"
            )
            result = load_json(result_path)
            result["secondReviewResults"] = [{"requirementId": "SR-FORGED"}]
            result_path.write_bytes(canonical_bytes(result))
            checked = check_attempt_result(
                review,
                "WORK-0001",
                "ATTEMPT-0001",
            )
            self.assertFalse(checked["ok"])
            self.assertTrue(
                any(
                    "must be an empty array" in issue
                    for issue in checked["issues"]
                )
            )
            with self.assertRaisesRegex(
                ReviewToolError,
                "must be an empty array",
            ):
                import_specialist(
                    review,
                    "WORK-0001",
                    "ATTEMPT-0001",
                    state_digest(review),
                )


if __name__ == "__main__":
    unittest.main()
