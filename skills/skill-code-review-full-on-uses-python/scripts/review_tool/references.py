"""Exact Markdown reference extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import ReviewToolError


@dataclass(frozen=True)
class Extract:
    filename: str
    section: str
    start: int
    end: int
    data: bytes


HEADING = re.compile(br"^(#{1,6})[ \t]+(.+?)[ \t]*\r?\n?$", re.MULTILINE)


def heading_range(source: bytes, title: str, *, include_children: bool = True) -> tuple[int, int]:
    matches = list(HEADING.finditer(source))
    selected = None
    for index, match in enumerate(matches):
        if match.group(2).decode("utf-8").strip() == title:
            selected = (index, match)
            break
    if selected is None:
        raise ReviewToolError(f"required reference heading not found: {title}")
    index, match = selected
    level = len(match.group(1))
    end = len(source)
    for later in matches[index + 1 :]:
        later_level = len(later.group(1))
        if later_level <= level if include_children else later_level == level:
            end = later.start()
            break
    return match.start(), end


def mandatory_block(source: bytes) -> tuple[int, int]:
    begin = b"<!-- BEGIN MANDATORY SPECIALIST BLOCK -->"
    end_marker = b"<!-- END MANDATORY SPECIALIST BLOCK -->"
    if source.count(begin) != 1 or source.count(end_marker) != 1:
        raise ReviewToolError("mandatory specialist block markers must each occur exactly once")
    start = source.index(b"\n", source.index(begin)) + 1
    end = source.rfind(b"\n", 0, source.index(end_marker))
    while source[start : start + 1] in (b"\n", b"\r"):
        start += 1
    return start, end + 1


def extract_reference(source: bytes) -> list[Extract]:
    definitions = [
        ("observation-categories.md", "R1. Observation categories"),
        ("schemas.md", "R2. Canonical record schemas"),
        ("specialist-result-schema.md", "Specialist `result.json` (attempt-local)"),
        ("specialist-validation-schema.md", "Specialist `validations.jsonl` (attempt-local)"),
        ("final-auditor-result-schema.md", "Final-auditor `result.json` (attempt-local)"),
        ("risk-tiers.md", "R3. Risk tiers"),
        ("cross-component.md", "R5. Phase 4 cross-component checklist"),
        ("finding-format.md", "R6. Validated finding format"),
        ("severity-confidence.md", "R7. Severity and confidence ladders"),
        ("handoff.md", "R8. Handoff contents"),
        ("installation.md", "R10. Deterministic extraction"),
    ]
    headings = {
        match.group(2).decode("utf-8").strip()
        for match in HEADING.finditer(source)
    }
    profile_index = 6
    if "R3A. Security levels" in headings:
        definitions.insert(profile_index, ("security-levels.md", "R3A. Security levels"))
        profile_index += 1
    if "R3B. Defensive assurance taxonomy" in headings:
        definitions.insert(
            profile_index,
            ("defensive-assurance.md", "R3B. Defensive assurance taxonomy"),
        )
    extracts: list[Extract] = []
    for filename, title in definitions:
        start, end = heading_range(source, title)
        extracts.append(Extract(filename, title, start, end, source[start:end]))

    r9_start, r9_end = heading_range(source, "R9. Review-angle checklists")
    angle1_start, _ = heading_range(source, "Angle 1 — Data correctness and semantics")
    extracts.append(Extract("angle-index.md", "R9. Review-angle checklists", r9_start, angle1_start, source[r9_start:angle1_start]))
    angle_titles = [
        "Data correctness and semantics", "Transactions, concurrency, and isolation",
        "Storage, durability, and crash recovery", "Distributed systems and replication",
        "Security and trust boundaries", "Resource management and reliability",
        "Performance and scalability", "Public API, protocol, and compatibility",
        "Tests, fuzzing, and verification", "Architecture, maintainability, operations, and documentation",
    ]
    for number, suffix in enumerate(angle_titles, 1):
        title = f"Angle {number} — {suffix}"
        start, end = heading_range(source, title)
        extracts.append(Extract(f"angle-{number:02d}.md", title, start, end, source[start:end]))
    start, end = mandatory_block(source)
    extracts.append(Extract("mandatory-specialist-block.md", "mandatory specialist block", start, end, source[start:end]))
    return extracts
