"""Security-profile definitions shared by review state operations."""

from __future__ import annotations

from typing import Any


SECURITY_LEVELS = ("off", "low", "medium", "high")
VALIDATION_CLASSES = ("ordinary", "security_static", "security_dynamic_isolated")
ALLOWED_VALIDATION_CLASSES = {
    "off": {"ordinary"},
    "low": {"ordinary"},
    "medium": {"ordinary", "security_static"},
    "high": set(VALIDATION_CLASSES),
}


def security_profile(run: dict[str, Any]) -> dict[str, Any]:
    """Return the declared v2 profile, or an empty invalid profile."""
    declared = run.get("securityProfile")
    if isinstance(declared, dict):
        return declared
    return {}


def security_level(run: dict[str, Any]) -> str:
    return str(security_profile(run).get("level", ""))


def has_declared_security_profile(run: dict[str, Any]) -> bool:
    return isinstance(run.get("securityProfile"), dict)


def validation_class_allowed(level: str, validation_class: str) -> bool:
    return validation_class in ALLOWED_VALIDATION_CLASSES.get(level, set())


def permitted_validation_classes(level: str) -> list[str]:
    """Return a stable manifest-ready list of validation classes for a level."""
    allowed = ALLOWED_VALIDATION_CLASSES.get(level, set())
    return [validation_class for validation_class in VALIDATION_CLASSES if validation_class in allowed]
