from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.helpers import clean_unit, new_review, rewrite_canonical
from review_tool.checks import check_review
from review_tool.errors import ReviewToolError
from review_tool.io import canonical_bytes, load_json, load_jsonl, state_digest
from review_tool.operations import apply_mutation, generate
from review_tool.transactions import simulate_transaction


class BrokenStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.review = new_review(Path(self.temporary.name))
        clean_unit(self.review)
        generate(self.review)

    def tearDown(self):
        self.temporary.cleanup()

    def assertIssue(self, text: str):
        issues = check_review(self.review)["issues"]
        self.assertTrue(any(text in issue for issue in issues), f"{text!r} not found in {issues}")

    def test_clean_equivalent_passes(self):
        self.assertEqual(check_review(self.review)["issues"], [])

    def test_duplicate_permanent_identifiers(self):
        row = {"id": "OBS-000001", "disposition": "open", "validationRefs": []}
        rewrite_canonical(self.review, "observations.jsonl", [row, dict(row)])
        self.assertIssue("duplicate permanent identifiers")

    def test_invalid_status_transition(self):
        units = load_jsonl(self.review / "work-units.jsonl")
        units[0]["status"] = "teleported"
        rewrite_canonical(self.review, "work-units.jsonl", units)
        self.assertIssue("invalid status transition")

    def test_missing_primary_assignment(self):
        units = load_jsonl(self.review / "work-units.jsonl")
        units[0]["paths"] = []
        rewrite_canonical(self.review, "work-units.jsonl", units)
        self.assertIssue("expected 1")

    def test_multiple_primary_assignments(self):
        units = load_jsonl(self.review / "work-units.jsonl")
        other = dict(units[0])
        other["id"] = "WORK-0002"
        units.append(other)
        rewrite_canonical(self.review, "work-units.jsonl", units)
        self.assertIssue("count is 2")

    def test_repository_content_identity_mismatch(self):
        paths = load_jsonl(self.review / "paths.jsonl")
        paths[0]["contentId"] = "changed-content"
        rewrite_canonical(self.review, "paths.jsonl", paths)
        self.assertIssue("repository-content or canonical-state identity mismatch")

    def test_stale_generated_views(self):
        run = load_json(self.review / "run.json")
        run["checkpointReason"] = "new mutation"
        changes = Path(self.temporary.name) / "changes.json"
        changes.write_bytes(canonical_bytes({"run.json": run}))
        apply_mutation(self.review, state_digest(self.review), changes, None)
        self.assertIssue("generated views are stale")

    def test_unreconciled_specialist_attempt(self):
        units = load_jsonl(self.review / "work-units.jsonl")
        units[0]["reviewAttempts"][0]["status"] = "complete"
        rewrite_canonical(self.review, "work-units.jsonl", units)
        self.assertIssue("unreconciled specialist attempt")

    def test_orphaned_validation_reference(self):
        observation = {"id": "OBS-000001", "disposition": "open", "validationRefs": ["VAL-000001"]}
        rewrite_canonical(self.review, "observations.jsonl", [observation])
        self.assertIssue("orphaned validation reference")

    def _second_review(self, *, scope=None, reviewer="EXEC-SECOND", stale=False):
        units = load_jsonl(self.review / "work-units.jsonl")
        unit = units[0]
        unit["riskTier"] = "A"
        requirement = {"id": "SR-001", "angle": 3, "scope": {"kind": "whole_unit"}}
        unit["requiredSecondReviews"] = [requirement]
        unit["completedSecondReviews"] = [{
            "requirementId": "SR-001", "scopeCovered": scope or {"kind": "whole_unit"},
            "reviewerExecutionId": reviewer, "independentFromAttemptIds": ["ATTEMPT-0001"],
            "specEpoch": "SPEC-0001", "stale": stale,
        }]
        rewrite_canonical(self.review, "work-units.jsonl", units)

    def test_invalid_whole_unit_second_review(self):
        self._second_review(scope={"kind": "items", "items": [{"type": "path", "value": "src/example.py"}]})
        self.assertIssue("invalid whole-unit")

    def test_non_independent_second_review(self):
        self._second_review(reviewer="EXEC-PRIMARY")
        self.assertIssue("contributing primary reviewer")

    def test_stale_superseded_manifest(self):
        units = load_jsonl(self.review / "work-units.jsonl")
        units[0]["manifestHistory"].append({"path": "assignments/WORK-0001/MANIFEST-0002.json"})
        rewrite_canonical(self.review, "work-units.jsonl", units)
        self.assertIssue("stale superseded manifest")

    def test_late_primary_import_invalidates_second_review(self):
        self._second_review(stale=True)
        self.assertIssue("later intersecting primary import")

    def test_excluded_path_assigned(self):
        paths = load_jsonl(self.review / "paths.jsonl")
        paths[0]["exclusion"] = {"category": "explicit_out_of_scope", "rationale": "fixture", "boundaryEvidence": ["test"], "authorizedBy": "user:test"}
        rewrite_canonical(self.review, "paths.jsonl", paths)
        self.assertIssue("excluded path assigned")

    def test_pass_with_material_concern(self):
        run = load_json(self.review / "run.json")
        run["verdict"] = "PASS"
        rewrite_canonical(self.review, "run.json", run)
        observation = {"id": "OBS-000001", "disposition": "unresolved", "materiality": "material", "validationRefs": []}
        rewrite_canonical(self.review, "observations.jsonl", [observation])
        self.assertIssue("terminal pass verdict")

    def test_wrong_specification_epoch(self):
        units = load_jsonl(self.review / "work-units.jsonl")
        units[0]["angles"]["1"] = {"status": "reviewed", "evidence": [{"claim": "x"}], "specEpoch": "SPEC-9999"}
        rewrite_canonical(self.review, "work-units.jsonl", units)
        self.assertIssue("wrong specEpoch")

    def test_security_angle_assigned_while_profile_is_off(self):
        units = load_jsonl(self.review / "work-units.jsonl")
        units[0]["angles"]["5"] = {"status": "pending", "evidence": [], "specEpoch": None}
        rewrite_canonical(self.review, "work-units.jsonl", units)
        self.assertIssue("angle 5 must be excluded")

    def test_dynamic_security_validation_rejected_while_profile_is_off(self):
        validation = {
            "id": "VAL-000001",
            "sourceAttempt": "WORK-0001/ATTEMPT-0001",
            "sourceLocalId": "AVAL-A1-001",
            "workUnits": ["WORK-0001"],
            "observationIds": [],
            "securityLevel": "off",
            "validationClass": "security_dynamic_isolated",
        }
        rewrite_canonical(self.review, "validations.jsonl", [validation])
        self.assertIssue("validation class is not permitted")

    def test_profile_deferral_requires_security_category(self):
        observation = {
            "id": "OBS-000001",
            "category": "correctness",
            "disposition": "deferred_by_profile",
            "validationRefs": [],
        }
        rewrite_canonical(self.review, "observations.jsonl", [observation])
        self.assertIssue("invalid profile deferral")

    def test_security_profile_change_is_rejected(self):
        run = load_json(self.review / "run.json")
        run["securityProfile"]["level"] = "high"
        changes = Path(self.temporary.name) / "security-change.json"
        changes.write_bytes(canonical_bytes({"run.json": run}))
        with self.assertRaisesRegex(ReviewToolError, "securityProfile is immutable"):
            apply_mutation(self.review, state_digest(self.review), changes, None)

    def test_malformed_security_profile_is_reported(self):
        run = load_json(self.review / "run.json")
        run["securityProfile"] = "off"
        rewrite_canonical(self.review, "run.json", run)
        self.assertIssue("securityProfile must be an object")

    def test_uncommitted_staged_transaction(self):
        simulate_transaction(self.review, {"architecture.md": b"changed\n"}, committed=False)
        self.assertIssue("uncommitted staged")

    def test_committed_incomplete_transaction(self):
        simulate_transaction(self.review, {"architecture.md": b"changed\n"}, committed=True)
        self.assertIssue("committed-but-incomplete")

    def test_duplicate_and_withdrawal_mappings(self):
        observations = [
            {"id": "OBS-000001", "findingId": "DBR-0001", "disposition": "withdrawn", "withdrawal": {"reason": "fixed"}, "validationRefs": []},
            {"id": "OBS-000002", "findingId": None, "disposition": "duplicate", "duplicateOf": "DBR-0001", "validationRefs": []},
        ]
        rewrite_canonical(self.review, "observations.jsonl", observations)
        issues = check_review(self.review)["issues"]
        self.assertFalse(any("mapping" in issue for issue in issues))
        observations[1]["duplicateOf"] = "DBR-9999"
        rewrite_canonical(self.review, "observations.jsonl", observations)
        self.assertIssue("invalid duplicate mapping")

    def test_lifecycle_transition_rejected_before_commit(self):
        run = load_json(self.review / "run.json")
        run["status"] = "concluded"
        first = Path(self.temporary.name) / "first.json"
        first.write_bytes(canonical_bytes({"run.json": run}))
        apply_mutation(self.review, state_digest(self.review), first, None)
        digest = state_digest(self.review)
        run["status"] = "active"
        second = Path(self.temporary.name) / "second.json"
        second.write_bytes(canonical_bytes({"run.json": run}))
        with self.assertRaisesRegex(ReviewToolError, "invalid status transition"):
            apply_mutation(self.review, digest, second, None)
        self.assertEqual(state_digest(self.review), digest)


if __name__ == "__main__":
    unittest.main()
