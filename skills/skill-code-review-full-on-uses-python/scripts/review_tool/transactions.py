"""Recoverable multi-file transactions and append-only state events."""

from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from .errors import ReviewToolError
from .io import atomic_write, canonical_bytes, digest_bytes, fsync_directory, load_json, safe_child, state_digest

VALID_OPERATIONS = ("init", "mutate", "import", "import_audit")


@contextmanager
def state_lock(root: Path) -> Iterator[None]:
    """Exclusive advisory lock serializing every state-writing operation."""
    base = root / "tooling"
    base.mkdir(parents=True, exist_ok=True)
    lock_path = base / "LOCK"
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ReviewToolError(
            f"another review-tool operation holds {lock_path}; wait for it to "
            "finish, and delete the lock file only if no other process is running"
        ) from None
    try:
        os.write(fd, f"{os.getpid()}\n".encode())
    finally:
        os.close(fd)
    try:
        yield
    finally:
        try:
            os.unlink(lock_path)
        except FileNotFoundError:
            pass


def _event_hash(event: dict) -> str:
    unsigned = dict(event)
    unsigned.pop("eventHash", None)
    return digest_bytes(canonical_bytes(unsigned))


def _append_event(root: Path, event_data: bytes) -> None:
    path = root / "state-events.jsonl"
    existing = path.read_bytes() if path.exists() else b""
    if existing and not existing.endswith(b"\n"):
        existing += b"\n"
    event = json.loads(event_data)
    rows = [json.loads(line) for line in existing.splitlines() if line]
    if any(row.get("eventHash") == event.get("eventHash") for row in rows):
        return
    atomic_write(path, existing + event_data)


def _materialize(root: Path, transaction: Path) -> None:
    manifest = load_json(transaction / "manifest.json")
    for relative in manifest["targets"]:
        source = safe_child(transaction / "replacements", relative)
        target = safe_child(root, relative)
        atomic_write(target, source.read_bytes())
    _append_event(root, (transaction / "event.json").read_bytes())
    atomic_write(transaction / "COMPLETE", b"complete\n")


def _quarantine(base: Path, transaction: Path) -> None:
    quarantine = base / "quarantine"
    quarantine.mkdir(exist_ok=True)
    destination = quarantine / transaction.name
    if destination.exists():
        destination = quarantine / f"{transaction.name}-{uuid.uuid4().hex[:8]}"
    os.replace(transaction, destination)


def _recover_locked(root: Path) -> dict[str, int]:
    base = root / "tooling" / "transactions"
    if not base.exists():
        return {"rolledForward": 0, "quarantined": 0}
    rolled = quarantined = 0
    pending: list[tuple[int, str, Path]] = []
    for transaction in sorted(base.iterdir()):
        if not transaction.is_dir() or transaction.name == "quarantine":
            continue
        if (transaction / "COMPLETE").exists():
            continue
        if not (transaction / "COMMIT").exists():
            _quarantine(base, transaction)
            quarantined += 1
            continue
        try:
            sequence = load_json(transaction / "event.json").get("sequence")
        except ReviewToolError:
            sequence = None
        if isinstance(sequence, int) and not isinstance(sequence, bool):
            pending.append((sequence, transaction.name, transaction))
        else:
            _quarantine(base, transaction)
            quarantined += 1
    # Committed transactions replay in event-sequence order, never in
    # directory-name order: transaction names are random hex.
    for _, _, transaction in sorted(pending, key=lambda item: (item[0], item[1])):
        _materialize(root, transaction)
        rolled += 1
    return {"rolledForward": rolled, "quarantined": quarantined}


def recover(root: Path) -> dict[str, int]:
    with state_lock(root):
        return _recover_locked(root)


def transact(
    root: Path,
    replacements: dict[str, bytes],
    *,
    operation: str,
    actor: str,
    timestamp: str,
    expected_digest: str | None,
    validator: Callable[[Path, dict[str, bytes]], None] | None = None,
) -> dict:
    if operation not in VALID_OPERATIONS:
        raise ReviewToolError(f"invalid state-event operation: {operation!r}")
    with state_lock(root):
        return _transact_locked(
            root,
            replacements,
            operation=operation,
            actor=actor,
            timestamp=timestamp,
            expected_digest=expected_digest,
            validator=validator,
        )


def _transact_locked(
    root: Path,
    replacements: dict[str, bytes],
    *,
    operation: str,
    actor: str,
    timestamp: str,
    expected_digest: str | None,
    validator: Callable[[Path, dict[str, bytes]], None] | None,
) -> dict:
    _recover_locked(root)
    current = state_digest(root) if any((root / name).exists() for name in ("run.json", "architecture.md")) else None
    if expected_digest is not None and current != expected_digest:
        raise ReviewToolError(f"state digest precondition failed: expected {expected_digest}, actual {current}")
    for relative in replacements:
        safe_child(root, relative)
    if validator:
        validator(root, replacements)
    replacements = dict(replacements)
    post = state_digest(root, replacements)
    events_path = root / "state-events.jsonl"
    rows = []
    if events_path.exists():
        rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line]
    transaction_name = f"TXN-{uuid.uuid4().hex}"
    event = {
        "sequence": len(rows) + 1,
        "previousEventHash": rows[-1]["eventHash"] if rows else None,
        "operation": operation,
        "actor": actor,
        "timestamp": timestamp,
        "transaction": transaction_name,
        "preStateDigest": current,
        "postStateDigest": post,
        "targets": sorted(replacements),
    }
    if "run.json" in replacements:
        run = json.loads(replacements["run.json"])
    elif (root / "run.json").exists():
        run = load_json(root / "run.json")
    else:
        run = None
    event["eventHash"] = _event_hash(event)
    if run is not None:
        # stateEventHead is excluded from state digests, so injecting it
        # cannot change postStateDigest or the event identity.
        run["stateEventHead"] = event["eventHash"]
        replacements["run.json"] = canonical_bytes(run)
    transaction = root / "tooling" / "transactions" / transaction_name
    replacement_root = transaction / "replacements"
    replacement_root.mkdir(parents=True)
    for relative, data in replacements.items():
        target = safe_child(replacement_root, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        with target.open("rb") as handle:
            os.fsync(handle.fileno())
    manifest = {"targets": sorted(replacements), "operation": operation}
    atomic_write(transaction / "manifest.json", canonical_bytes(manifest))
    atomic_write(transaction / "event.json", canonical_bytes(event))
    atomic_write(transaction / "COMMIT", b"commit\n")
    fsync_directory(transaction)
    _materialize(root, transaction)
    return {"stateDigest": post, "eventHash": event["eventHash"], "transaction": transaction.name}


def simulate_transaction(root: Path, replacements: dict[str, bytes], *, committed: bool) -> Path:
    """Create an interrupted transaction for bounded recovery testing."""
    transaction = root / "tooling" / "transactions" / f"TXN-SIM-{uuid.uuid4().hex}"
    replacement_root = transaction / "replacements"
    replacement_root.mkdir(parents=True)
    for relative, data in replacements.items():
        target = safe_child(replacement_root, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    atomic_write(transaction / "manifest.json", canonical_bytes({"targets": sorted(replacements), "operation": "mutate"}))
    rows = []
    events = root / "state-events.jsonl"
    if events.exists():
        rows = [json.loads(line) for line in events.read_text().splitlines() if line]
    event = {
        "sequence": len(rows) + 1,
        "previousEventHash": rows[-1]["eventHash"] if rows else None,
        "operation": "mutate",
        "actor": "orchestrator",
        "timestamp": "1970-01-01T00:00:00Z",
        "transaction": transaction.name,
        "preStateDigest": state_digest(root),
        "postStateDigest": state_digest(root, replacements),
        "targets": sorted(replacements),
    }
    event["eventHash"] = _event_hash(event)
    atomic_write(transaction / "event.json", canonical_bytes(event))
    if committed:
        atomic_write(transaction / "COMMIT", b"commit\n")
    return transaction
