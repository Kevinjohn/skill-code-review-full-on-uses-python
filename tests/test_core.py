from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.helpers import PACK, clean_unit, new_review
from review_tool.checks import check_review
from review_tool.errors import ReviewToolError
from review_tool.io import canonical_bytes, load_json, load_jsonl, normalize_relative, safe_child, state_digest
from review_tool.operations import apply_mutation, deterministic_sample, generate
from review_tool.references import extract_reference, mandatory_block
from review_tool.transactions import recover, simulate_transaction


class CoreTests(unittest.TestCase):
    def test_json_and_jsonl_loading(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "one.json").write_text('{"a":1}')
            (root / "many.jsonl").write_text('{"a":1}\n{"b":2}\n')
            self.assertEqual(load_json(root / "one.json"), {"a": 1})
            self.assertEqual(load_jsonl(root / "many.jsonl"), [{"a": 1}, {"b": 2}])
            (root / "many.jsonl").write_text('{bad}\n')
            with self.assertRaisesRegex(ReviewToolError, "invalid JSONL"):
                load_jsonl(root / "many.jsonl")

    def test_exact_extraction_and_mandatory_block(self):
        source = PACK.read_bytes()
        extracts = {item.filename: item for item in extract_reference(source)}
        self.assertEqual(len([name for name in extracts if name.startswith("angle-") and name != "angle-index.md"]), 10)
        self.assertTrue(extracts["angle-01.md"].data.startswith(b"### Angle 1"))
        start, end = mandatory_block(source)
        self.assertTrue(source[start:end].startswith(b"> Review the entire assigned manifest."))
        self.assertNotIn(b"BEGIN MANDATORY", source[start:end])

    def test_path_normalization_and_containment(self):
        self.assertEqual(normalize_relative("a/b.json"), "a/b.json")
        for unsafe in ("../a", "/tmp/a", "a/../b", "a\\b"):
            with self.assertRaises(ReviewToolError):
                normalize_relative(unsafe)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "link").symlink_to(Path(temporary).parent)
            with self.assertRaisesRegex(ReviewToolError, "symlink traversal|escapes review directory"):
                safe_child(root, "link/escape")

    def test_state_digest_ignores_agent_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            before = state_digest(review)
            agent = review / "agents/WORK-0001/ATTEMPT-0001"
            agent.mkdir(parents=True)
            (agent / "result.json").write_text("{}")
            self.assertEqual(before, state_digest(review))

    def test_transaction_staging_and_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            run = load_json(review / "run.json")
            run["checkpointReason"] = "recovered"
            staged = simulate_transaction(review, {"run.json": canonical_bytes(run)}, committed=False)
            result = recover(review)
            self.assertEqual(result["quarantined"], 1)
            self.assertFalse(staged.exists())
            committed = simulate_transaction(review, {"run.json": canonical_bytes(run)}, committed=True)
            result = recover(review)
            self.assertEqual(result["rolledForward"], 1)
            self.assertTrue((committed / "COMPLETE").exists())
            self.assertEqual(load_json(review / "run.json")["checkpointReason"], "recovered")

    def test_specification_epoch_migration(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            clean_unit(review)
            result = apply_mutation(review, state_digest(review), None, (PACK.parent / "contract.md", PACK, ["R9/Angle 1"], [1]))
            self.assertIn("stateDigest", result)
            run = load_json(review / "run.json")
            unit = load_jsonl(review / "work-units.jsonl")[0]
            self.assertEqual(run["specEpoch"], "SPEC-0002")
            self.assertEqual(unit["specEpoch"], "SPEC-0002")
            self.assertEqual(unit["status"], "needs_revalidation")
            generate(review)
            self.assertEqual(check_review(review)["issues"], [])

    def test_generated_view_freshness(self):
        with tempfile.TemporaryDirectory() as temporary:
            review = new_review(Path(temporary))
            generate(review)
            self.assertTrue(check_review(review)["ok"])
            (review / "README.md").write_text("stale")
            self.assertTrue(any("generated output changed" in issue for issue in check_review(review)["issues"]))

    def test_deterministic_audit_sampling(self):
        units = [{"id": f"WORK-{index:04d}", "riskTier": "B", "status": "complete"} for index in range(1, 101)]
        first = deterministic_sample(units, "baseline", "work")
        second = deterministic_sample(list(reversed(units)), "baseline", "work")
        self.assertEqual(first, second)
        self.assertEqual(len(first), 25)


if __name__ == "__main__":
    unittest.main()
