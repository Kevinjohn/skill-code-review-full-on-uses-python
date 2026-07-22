# Contributing

Thank you for improving `skill-code-review-full-on-uses-python`.

Use Python 3.11 or newer. No installation step is required; run the complete suite with:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Keep changes focused and dependency-free. Preserve agent-neutral language in the canonical Skill, references, runtime scripts, schemas, and generated reports. Product-specific installation notes belong only in the root README.

Reference documents are deliberately editable. When changing headings used by deterministic extraction, update the extractor and exact-range tests together. Schema changes need compatibility reasoning, transition tests, broken-state coverage, and an explanation of which existing review dispositions require revalidation. Do not introduce expected source-document digests or a document-matching manifest.

Pull requests should explain the user-visible effect, include tests for behavior and failure modes, pass the local Skill validator, and keep generated or temporary review output out of the repository.
