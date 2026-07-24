from __future__ import annotations

import copy
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.helpers import clean_unit, new_review

from review_tool.checks import check_review, pilot_diagnostics
from review_tool.errors import ReviewToolError
from review_tool.io import (
    canonical_bytes,
    canonical_identity,
    digest_bytes,
    jsonl_bytes,
    load_json,
    load_jsonl,
    state_digest,
)
from review_tool.operations import _validate_work_unit_transitions
from review_tool.transactions import recover, transact


WORK_TRANSITIONS = {
    "pending": {"pending", "assigned", "blocked"},
    "assigned": {
        "assigned",
        "partial",
        "complete",
        "blocked",
        "needs_revalidation",
    },
    "partial": {"partial", "assigned", "blocked", "needs_revalidation"},
    "complete": {"complete", "needs_revalidation"},
    "blocked": {"blocked", "pending", "assigned", "needs_revalidation"},
    "needs_revalidation": {"needs_revalidation", "assigned", "blocked"},
}

ANGLE_TRANSITIONS = {
    "pending": {
        "pending",
        "reviewed",
        "not_applicable",
        "excluded_by_profile",
        "blocked",
    },
    "reviewed": {"reviewed", "needs_revalidation"},
    "not_applicable": {"not_applicable", "needs_revalidation"},
    "excluded_by_profile": {"excluded_by_profile", "needs_revalidation"},
    "blocked": {"blocked", "pending"},
    "needs_revalidation": {
        "needs_revalidation",
        "reviewed",
        "not_applicable",
        "excluded_by_profile",
        "blocked",
    },
}


class ReleaseConfidenceTests(unittest.TestCase):
    def _install_issue_six_topology(
        self,
        review: Path,
        *,
        unit_count: int = 77,
        tier_a_count: int = 34,
    ) -> None:
        clean_unit(review)
        run = load_json(review / "run.json")
        template_unit = load_jsonl(review / "work-units.jsonl")[0]
        template_unit_manifest = load_json(
            review / template_unit["currentManifest"]
        )
        template_attempt_manifest = load_json(
            review / template_unit["reviewAttempts"][0]["manifest"]
        )
        template_capsule = load_json(
            review
            / template_unit_manifest["orientationCapsule"]["path"]
        )
        template_path = load_jsonl(review / "paths.jsonl")[0]

        paths = []
        for index in range(1, unit_count + 1):
            path_row = copy.deepcopy(template_path)
            path_row["path"] = f"src/component_{index:04d}.py"
            path_row["contentId"] = f"content-{index:04d}"
            path_row["subsystem"] = f"component-{index:04d}"
            paths.append(path_row)
        paths.sort(key=lambda row: row["path"].encode("utf-8"))
        baseline_hash = canonical_identity(paths)
        run["baselineContentSetHash"] = baseline_hash

        replacements: dict[str, bytes] = {}
        units = []
        architecture_hash = digest_bytes(
            (review / "architecture.md").read_bytes()
        )
        reference_hash = digest_bytes(
            (review / "tooling/reference/manifest.json").read_bytes()
        )
        for index, path_row in enumerate(paths, 1):
            work_id = f"WORK-{index:04d}"
            attempt_id = f"ATTEMPT-{index:04d}"
            subsystem = path_row["subsystem"]
            tier = "A" if index <= tier_a_count else "B"
            requirement = {
                "id": f"SR-{index:04d}",
                "angle": 3,
                "scope": {"kind": "whole_unit"},
            }
            requirements = [requirement] if tier == "A" else []
            unit_content_hash = canonical_identity([path_row])

            capsule = copy.deepcopy(template_capsule)
            capsule.update(
                {
                    "capsuleId": f"CAPSULE-{index:04d}",
                    "baselineContentSetHash": baseline_hash,
                    "subsystem": subsystem,
                    "role": f"Representative component {index}",
                    "entryPoints": [path_row["path"]],
                    "evidenceLocations": [f"{path_row['path']}:1"],
                    "architectureHash": architecture_hash,
                    "referenceManifestHash": reference_hash,
                }
            )
            capsule_path = f"assignments/capsules/{subsystem}.json"
            capsule_bytes = canonical_bytes(capsule)

            unit_manifest = copy.deepcopy(template_unit_manifest)
            unit_manifest.update(
                {
                    "workId": work_id,
                    "riskTier": tier,
                    "contentSetHash": unit_content_hash,
                    "paths": [
                        {
                            "path": path_row["path"],
                            "contentId": path_row["contentId"],
                        }
                    ],
                    "subsystem": subsystem,
                    "orientationCapsule": {
                        "path": capsule_path,
                        "hash": digest_bytes(capsule_bytes),
                    },
                    "requiredSecondReviews": requirements,
                }
            )
            unit_manifest_path = (
                f"assignments/{work_id}/MANIFEST-0001.json"
            )
            unit_manifest_bytes = canonical_bytes(unit_manifest)
            unit_manifest_hash = digest_bytes(unit_manifest_bytes)

            attempt_manifest = copy.deepcopy(template_attempt_manifest)
            attempt_manifest.update(
                {
                    "workId": work_id,
                    "attemptId": attempt_id,
                    "unitManifest": unit_manifest_path,
                    "unitManifestHash": unit_manifest_hash,
                    "reviewerExecutionId": f"EXEC-PRIMARY-{index:04d}",
                    "reviewerPrincipalId": f"PRINCIPAL-PRIMARY-{index:04d}",
                    "assignedScope": {
                        "paths": [path_row["path"]],
                        "symbols": [],
                        "angles": unit_manifest[
                            "requiredAngleDispositions"
                        ],
                    },
                    "outputDirectory": (
                        f"agents/{work_id}/{attempt_id}"
                    ),
                }
            )
            attempt_manifest_path = (
                f"assignments/{work_id}/{attempt_id}.json"
            )
            attempt_manifest_bytes = canonical_bytes(attempt_manifest)
            attempt_manifest_hash = digest_bytes(attempt_manifest_bytes)

            unit = copy.deepcopy(template_unit)
            unit.update(
                {
                    "id": work_id,
                    "currentManifest": unit_manifest_path,
                    "currentManifestHash": unit_manifest_hash,
                    "manifestHistory": [
                        {
                            "revision": 1,
                            "path": unit_manifest_path,
                            "hash": unit_manifest_hash,
                            "supersedes": None,
                            "reason": "initial",
                            "preservedAttemptManifestHashes": [],
                        }
                    ],
                    "contentSetHash": unit_content_hash,
                    "paths": [path_row["path"]],
                    "title": f"component {index}",
                    "subsystem": subsystem,
                    "riskTier": tier,
                    "criticalReasons": (
                        [
                            {
                                "code": "durability_recovery",
                                "locations": [
                                    {
                                        "path": path_row["path"],
                                        "startLine": 1,
                                    }
                                ],
                                "invariant": (
                                    "The representative component preserves "
                                    "recorded state."
                                ),
                                "materialConsequence": (
                                    "The representative component loses "
                                    "recorded state."
                                ),
                                "whyTierBInsufficient": (
                                    "The component models the Tier-A "
                                    "boundaries observed in issue 6."
                                ),
                            }
                        ]
                        if tier == "A"
                        else []
                    ),
                    "reviewAttempts": [
                        {
                            "attemptId": attempt_id,
                            "manifest": attempt_manifest_path,
                            "manifestHash": attempt_manifest_hash,
                            "unitManifestHash": unit_manifest_hash,
                            "packetType": "primary_semantic",
                            "reviewerExecutionId": (
                                f"EXEC-PRIMARY-{index:04d}"
                            ),
                            "reviewerPrincipalId": (
                                f"PRINCIPAL-PRIMARY-{index:04d}"
                            ),
                            "independentFromAttemptIds": [],
                            "status": "assigned",
                            "resultHash": None,
                            "attemptEvidenceHash": None,
                            "importDisposition": "pending",
                        }
                    ],
                    "requiredSecondReviews": requirements,
                    "completedSecondReviews": [],
                }
            )
            units.append(unit)
            replacements[capsule_path] = capsule_bytes
            replacements[unit_manifest_path] = unit_manifest_bytes
            replacements[attempt_manifest_path] = attempt_manifest_bytes

        replacements.update(
            {
                "run.json": canonical_bytes(run),
                "paths.jsonl": jsonl_bytes(paths),
                "work-units.jsonl": jsonl_bytes(units),
            }
        )
        transact(
            review,
            replacements,
            operation="mutate",
            actor="test",
            timestamp="2026-01-01T00:00:10Z",
            expected_digest=state_digest(review),
        )

    def test_issue_six_topology_replays_77_units_and_34_tier_a_requirements(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            self._install_issue_six_topology(review)
            run = load_json(review / "run.json")
            units = load_jsonl(review / "work-units.jsonl")
            diagnostics = pilot_diagnostics(
                run,
                units,
                run["diagnosticAcknowledgements"],
            )
            checked = check_review(review, check_generated=False)
            self.assertEqual(len(units), 77)
            self.assertEqual(
                sum(unit["riskTier"] == "A" for unit in units),
                34,
            )
            self.assertEqual(
                sum(len(unit["requiredSecondReviews"]) for unit in units),
                34,
            )
            self.assertIn("34/77", diagnostics["warning"])
            self.assertFalse(diagnostics["bulkDispatchAllowed"])
            self.assertTrue(checked["ok"], checked["issues"])
            self.assertTrue(
                any("34/77" in warning for warning in checked["warnings"]),
                checked["warnings"],
            )

    def test_model_based_state_transition_fuzz_is_deterministic(self):
        work_statuses = list(WORK_TRANSITIONS)
        angle_statuses = list(ANGLE_TRANSITIONS)
        new_work_values = [*work_statuses, "unknown", None, {"bad": True}]
        new_angle_values = [
            *angle_statuses,
            "unknown",
            None,
            {"bad": True},
        ]

        def exercise(seed: int) -> list[tuple[str, str, str, str, bool]]:
            generator = random.Random(seed)
            trace = []
            for _ in range(1_000):
                old_work = generator.choice(work_statuses)
                new_work = generator.choice(new_work_values)
                old_angle = generator.choice(angle_statuses)
                new_angle = generator.choice(new_angle_values)
                old = {
                    "WORK-0001": {
                        "status": old_work,
                        "securityLevel": "off",
                        "reviewAttempts": [],
                        "angles": {"1": {"status": old_angle}},
                    }
                }
                new = {
                    "WORK-0001": {
                        "status": new_work,
                        "securityLevel": "off",
                        "reviewAttempts": [],
                        "angles": {"1": {"status": new_angle}},
                    }
                }
                expected = (
                    isinstance(new_work, str)
                    and new_work in WORK_TRANSITIONS[old_work]
                    and isinstance(new_angle, str)
                    and new_angle in ANGLE_TRANSITIONS[old_angle]
                )
                if expected:
                    _validate_work_unit_transitions(old, new)
                else:
                    with self.assertRaises(ReviewToolError):
                        _validate_work_unit_transitions(old, new)
                trace.append(
                    (
                        old_work,
                        repr(new_work),
                        old_angle,
                        repr(new_angle),
                        expected,
                    )
                )
            return trace

        first = exercise(0x5EED)
        second = exercise(0x5EED)
        self.assertEqual(first, second)
        self.assertTrue(any(item[-1] for item in first))
        self.assertTrue(any(not item[-1] for item in first))

    def test_transaction_fault_injection_recovers_every_commit_boundary(self):
        failpoints = (
            "before_commit",
            "first_target",
            "second_target",
            "event_append",
            "completion_marker",
        )
        for failpoint in failpoints:
            with self.subTest(failpoint=failpoint):
                with tempfile.TemporaryDirectory() as temporary:
                    review = new_review(Path(temporary))
                    original_architecture = (
                        review / "architecture.md"
                    ).read_bytes()
                    original_run = load_json(review / "run.json")
                    original_events = (
                        review / "state-events.jsonl"
                    ).read_text(encoding="utf-8").splitlines()
                    replacement_run = copy.deepcopy(original_run)
                    replacement_run["checkpointReason"] = failpoint
                    replacement_architecture = (
                        f"# Architecture after {failpoint}\n".encode()
                    )
                    replacements = {
                        "architecture.md": replacement_architecture,
                        "run.json": canonical_bytes(replacement_run),
                    }

                    from review_tool import transactions

                    original_atomic_write = transactions.atomic_write
                    failed = False

                    def injected_atomic_write(path: Path, data: bytes) -> None:
                        nonlocal failed
                        path = Path(path)
                        resolved = path.resolve(strict=False)
                        should_fail = {
                            "before_commit": path.name == "manifest.json",
                            "first_target": resolved
                            == (review / "architecture.md").resolve(),
                            "second_target": resolved
                            == (review / "run.json").resolve(),
                            "event_append": resolved
                            == (review / "state-events.jsonl").resolve(),
                            "completion_marker": path.name == "COMPLETE",
                        }[failpoint]
                        if should_fail and not failed:
                            failed = True
                            raise OSError(f"injected failure at {failpoint}")
                        original_atomic_write(path, data)

                    with patch(
                        "review_tool.transactions.atomic_write",
                        side_effect=injected_atomic_write,
                    ):
                        with self.assertRaisesRegex(
                            OSError,
                            f"injected failure at {failpoint}",
                        ):
                            transact(
                                review,
                                replacements,
                                operation="mutate",
                                actor="test",
                                timestamp="2026-01-01T00:00:20Z",
                                expected_digest=state_digest(review),
                            )
                    self.assertTrue(failed)
                    recovery = recover(review)

                    if failpoint == "before_commit":
                        self.assertEqual(recovery["quarantined"], 1)
                        self.assertEqual(
                            (review / "architecture.md").read_bytes(),
                            original_architecture,
                        )
                        self.assertEqual(
                            load_json(review / "run.json")[
                                "checkpointReason"
                            ],
                            original_run["checkpointReason"],
                        )
                        expected_event_count = len(original_events)
                    else:
                        self.assertEqual(recovery["rolledForward"], 1)
                        self.assertEqual(
                            (review / "architecture.md").read_bytes(),
                            replacement_architecture,
                        )
                        self.assertEqual(
                            load_json(review / "run.json")[
                                "checkpointReason"
                            ],
                            failpoint,
                        )
                        expected_event_count = len(original_events) + 1

                    events = (
                        review / "state-events.jsonl"
                    ).read_text(encoding="utf-8").splitlines()
                    self.assertEqual(len(events), expected_event_count)
                    checked = check_review(review, check_generated=False)
                    self.assertTrue(checked["ok"], checked["issues"])


if __name__ == "__main__":
    unittest.main()
