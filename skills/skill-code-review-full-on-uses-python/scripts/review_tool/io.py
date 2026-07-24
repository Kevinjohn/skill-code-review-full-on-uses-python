"""Safe filesystem, canonical serialization, and identity helpers."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .errors import ReviewToolError

CANONICAL_FILES = (
    "run.json",
    "paths.jsonl",
    "work-units.jsonl",
    "observations.jsonl",
    "validations.jsonl",
    "audit-objections.jsonl",
    "architecture.md",
)


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_identity(value: Any) -> str:
    """Identity of canonical JSON without the file-format trailing newline."""
    return digest_bytes(canonical_bytes(value).removesuffix(b"\n"))


def parse_json_bytes(data: bytes, label: str) -> Any:
    try:
        return json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewToolError(f"invalid JSON in {label}: {exc}") from exc


def parse_jsonl_bytes(data: bytes, label: str) -> list[dict[str, Any]]:
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise ReviewToolError(f"cannot read {label}: {exc}") from exc
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReviewToolError(
                f"invalid JSONL in {label}:{number}: {exc.msg}"
            ) from exc
        if not isinstance(row, dict):
            raise ReviewToolError(
                f"invalid JSONL in {label}:{number}: row must be an object"
            )
        rows.append(row)
    return rows


def load_json(path: Path) -> Any:
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise ReviewToolError(f"missing JSON file: {path}") from exc
    except OSError as exc:
        raise ReviewToolError(f"cannot read {path}: {exc}") from exc
    return parse_json_bytes(data, str(path))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise ReviewToolError(f"missing JSONL file: {path}") from exc
    except OSError as exc:
        raise ReviewToolError(f"cannot read {path}: {exc}") from exc
    return parse_jsonl_bytes(data, str(path))


def jsonl_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
    return b"".join(canonical_bytes(row) for row in rows)


def normalize_relative(value: str) -> str:
    if not value or "\\" in value:
        raise ReviewToolError(f"unsafe relative path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ReviewToolError(f"unsafe relative path: {value!r}")
    return path.as_posix()


def safe_child(root: Path, relative: str) -> Path:
    relative = normalize_relative(relative)
    root_resolved = root.resolve()
    candidate = root_resolved.joinpath(*PurePosixPath(relative).parts)
    parent = candidate.parent.resolve(strict=False)
    try:
        parent.relative_to(root_resolved)
    except ValueError as exc:
        raise ReviewToolError(f"path escapes review directory: {relative}") from exc
    cursor = root_resolved
    for part in PurePosixPath(relative).parts[:-1]:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ReviewToolError(f"symlink traversal is not allowed: {cursor}")
    return candidate


def ensure_review_root(path: Path, *, create: bool = False) -> Path:
    path = path.expanduser()
    if create:
        path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ReviewToolError(f"review directory cannot be a symlink: {path}")
    return path.resolve()


def fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        # Platforms such as Windows cannot open directories at all.
        return
    try:
        os.fsync(fd)
    except OSError as exc:
        # Filesystems that cannot fsync a directory are acceptable; real
        # write failures (EIO, ENOSPC) must surface.
        if exc.errno not in (errno.EINVAL, errno.ENOTSUP):
            raise
    finally:
        os.close(fd)


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ReviewToolError(f"refusing to replace symlink: {path}")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def state_files(root: Path) -> list[Path]:
    files = [root / name for name in CANONICAL_FILES if (root / name).is_file()]
    assignments = root / "assignments"
    if assignments.exists():
        files.extend(path for path in assignments.rglob("*") if path.is_file() and not path.is_symlink())
    return sorted(files, key=lambda path: path.relative_to(root).as_posix().encode("utf-8"))


def content_for_state(path: Path, root: Path) -> bytes:
    relative = path.relative_to(root).as_posix()
    data = path.read_bytes()
    if relative == "run.json":
        value = json.loads(data)
        value.pop("stateEventHead", None)
        return canonical_bytes(value)
    return data


def state_digest(root: Path, overrides: dict[str, bytes] | None = None) -> str:
    mapping: dict[str, str] = {}
    override_map = {
        name: data for name, data in (overrides or {}).items()
        if name in CANONICAL_FILES or name.startswith("assignments/")
    }
    names = {path.relative_to(root).as_posix() for path in state_files(root)} | set(override_map)
    for name in sorted(names, key=lambda item: item.encode("utf-8")):
        if name in override_map:
            data = override_map[name]
            if name == "run.json":
                value = json.loads(data)
                value.pop("stateEventHead", None)
                data = canonical_bytes(value)
        else:
            data = content_for_state(root / name, root)
        mapping[name] = digest_bytes(data)
    return digest_bytes(canonical_bytes(mapping))
