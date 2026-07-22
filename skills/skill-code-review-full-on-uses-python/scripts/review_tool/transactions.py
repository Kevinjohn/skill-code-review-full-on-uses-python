"""Recoverable multi-file transactions and append-only state events."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Callable

from .errors import ReviewToolError
from .io import atomic_write, canonical_bytes, digest_bytes, fsync_directory, load_json, safe_child, state_digest


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


def recover(root: Path) -> dict[str, int]:
    base = root / "tooling" / "transactions"
    if not base.exists():
        return {"rolledForward": 0, "quarantined": 0}
    rolled = quarantined = 0
    quarantine = base / "quarantine"
    for transaction in sorted(base.iterdir()):
        if not transaction.is_dir() or transaction.name == "quarantine":
            continue
        if (transaction / "COMPLETE").exists():
            continue
        if (transaction / "COMMIT").exists():
            _materialize(root, transaction)
            rolled += 1
        else:
            quarantine.mkdir(exist_ok=True)
            destination = quarantine / transaction.name
            if destination.exists():
                destination = quarantine / f"{transaction.name}-{uuid.uuid4().hex[:8]}"
            os.replace(transaction, destination)
            quarantined += 1
    return {"rolledForward": rolled, "quarantined": quarantined}


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
    recover(root)
    current = state_digest(root) if any((root / name).exists() for name in ("run.json", "architecture.md")) else None
    if expected_digest is not None and current != expected_digest:
        raise ReviewToolError(f"state digest precondition failed: expected {expected_digest}, actual {current}")
    for relative in replacements:
        safe_child(root, relative)
    if validator:
        validator(root, replacements)
    post = state_digest(root, replacements)
    events_path = root / "state-events.jsonl"
    rows = []
    if events_path.exists():
        rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line]
    event = {
        "sequence": len(rows) + 1,
        "previousEventHash": rows[-1]["eventHash"] if rows else None,
        "operation": operation,
        "actor": actor,
        "timestamp": timestamp,
        "preStateDigest": current,
        "postStateDigest": post,
        "targets": sorted(replacements),
    }
    event["eventHash"] = _event_hash(event)
    if "run.json" in replacements:
        run = json.loads(replacements["run.json"])
    elif (root / "run.json").exists():
        run = load_json(root / "run.json")
    else:
        run = None
    if run is not None:
        run["stateEventHead"] = event["eventHash"]
        replacements["run.json"] = canonical_bytes(run)
        post = state_digest(root, replacements)
        event["postStateDigest"] = post
        event["eventHash"] = _event_hash(event)
        run["stateEventHead"] = event["eventHash"]
        replacements["run.json"] = canonical_bytes(run)
    transaction = root / "tooling" / "transactions" / f"TXN-{uuid.uuid4().hex}"
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
        "preStateDigest": state_digest(root),
        "postStateDigest": state_digest(root, replacements),
        "targets": sorted(replacements),
    }
    event["eventHash"] = _event_hash(event)
    atomic_write(transaction / "event.json", canonical_bytes(event))
    if committed:
        atomic_write(transaction / "COMMIT", b"commit\n")
    return transaction
