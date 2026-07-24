"""Shared parsing for permanent and attempt-local identifiers."""

from __future__ import annotations

import re

from .errors import ReviewToolError


def attempt_token(attempt_id: str) -> str:
    match = re.fullmatch(r"ATTEMPT-(\d{4})", attempt_id)
    if not match:
        raise ReviewToolError(
            f"invalid attempt identifier {attempt_id!r}; expected ATTEMPT-NNNN "
            "with exactly four digits"
        )
    return f"A{int(match.group(1))}"
