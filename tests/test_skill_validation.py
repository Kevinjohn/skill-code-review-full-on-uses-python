from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.helpers import ROOT


class SkillValidationTests(unittest.TestCase):
    def setUp(self):
        self.skill = ROOT / "skills/skill-code-review-full-on-uses-python"
        self.text = (self.skill / "SKILL.md").read_text()

    def test_frontmatter_and_name(self):
        match = re.match(r"\A---\n(.*?)\n---\n", self.text, re.DOTALL)
        self.assertIsNotNone(match)
        fields = {}
        for line in match.group(1).splitlines():
            key, value = line.split(":", 1)
            fields[key] = value.strip()
        self.assertEqual(set(fields), {"name", "description"})
        self.assertEqual(fields["name"], self.skill.name)
        self.assertRegex(fields["name"], r"^[a-z0-9-]+$")
        self.assertTrue(fields["description"])
        self.assertLess(len(fields["description"]), 1024)
        self.assertIn("Do not use", fields["description"])

    def test_resources_and_size_targets(self):
        for relative in ("references/contract.md", "references/reference-pack.md", "scripts/review-tool"):
            self.assertTrue((self.skill / relative).is_file(), relative)
        self.assertLess(len(self.text.splitlines()), 500)
        self.assertLess(len(self.text.split()), 5000)
        self.assertNotIn("/Users/", self.text)

    def test_canonical_material_is_agent_neutral(self):
        files = [
            self.skill / "SKILL.md", self.skill / "references/contract.md",
            self.skill / "references/reference-pack.md",
        ] + list((self.skill / "scripts").rglob("*.py"))
        forbidden = ("Codex", "OpenAI", "Claude", "Anthropic", "ChatGPT")
        for path in files:
            text = path.read_text()
            for term in forbidden:
                self.assertNotIn(term, text, f"{term} in {path}")

    def test_removed_document_coupling_terms(self):
        forbidden = ("Pair" + " Manifest", "review-spec" + "-pair", "--pair" + "-manifest", "contract" + "Hash", "referencePack" + "Hash", "pack" + "Hash", "Frontier" + "-class")
        runtime_files = [self.skill / "SKILL.md", self.skill / "references/contract.md", self.skill / "references/reference-pack.md"] + [path for path in (self.skill / "scripts").rglob("*") if path.is_file()]
        for path in runtime_files:
            text = path.read_text(errors="ignore")
            for term in forbidden:
                self.assertNotIn(term, text, f"{term} in {path}")

    def test_required_repository_layout(self):
        required = {
            ".github/workflows/ci.yml", ".gitignore", "CODE_OF_CONDUCT.md", "CONTRIBUTING.md",
            "LICENSE", "README.md", "SECURITY.md", "skills/skill-code-review-full-on-uses-python/SKILL.md",
            "tests/fixtures/broken-states.json",
        }
        for relative in required:
            self.assertTrue((ROOT / relative).exists(), relative)


if __name__ == "__main__":
    unittest.main()
