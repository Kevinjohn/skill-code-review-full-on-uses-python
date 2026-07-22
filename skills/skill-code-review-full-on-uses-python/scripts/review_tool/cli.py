"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .checks import check_review
from .errors import ReviewToolError
from .io import ensure_review_root, state_digest
from .operations import apply_mutation, audit, generate, import_audit, import_specialist, initialize
from .transactions import recover


def _review_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--review-dir", type=Path, required=True, help="Review directory to read or update")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="review-tool", description="Portable transactional state utility for exhaustive repository reviews")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Initialize a review and snapshot editable specifications")
    _review_dir(init)
    init.add_argument("--contract", type=Path, required=True)
    init.add_argument("--reference-pack", type=Path, required=True)
    init.add_argument("--runtime-capability", choices=("continuous", "persistent_task", "external_supervisor", "none"), default="none")

    check = sub.add_parser("check", help="Validate canonical state and integrity invariants")
    _review_dir(check)
    check.add_argument("--skip-generated", action="store_true", help="Do not require generated views to be current")
    check.add_argument("--json", action="store_true", help="Emit machine-readable output")

    mutate = sub.add_parser("mutate", help="Commit an atomic canonical state replacement or specification migration")
    _review_dir(mutate)
    mutate.add_argument("--expected-digest", required=True)
    mutate.add_argument("--changes", type=Path, help="JSON object mapping canonical paths to complete replacement values")
    mutate.add_argument("--migrate-spec", action="store_true", help="Start a new specification epoch")
    mutate.add_argument("--contract", type=Path)
    mutate.add_argument("--reference-pack", type=Path)
    mutate.add_argument("--changed-section", action="append", default=[])
    mutate.add_argument("--affected-angle", type=int, choices=range(1, 11), action="append", default=[])

    specialist = sub.add_parser("import", help="Atomically import one specialist attempt")
    _review_dir(specialist)
    specialist.add_argument("--work-id", required=True)
    specialist.add_argument("--attempt-id", required=True)
    specialist.add_argument("--expected-digest", required=True)

    final = sub.add_parser("import-audit", help="Atomically import one independent final-auditor attempt")
    _review_dir(final)
    final.add_argument("--attempt-id", required=True)
    final.add_argument("--expected-digest", required=True)

    generate_parser = sub.add_parser("generate", help="Regenerate all human-readable views from canonical state")
    _review_dir(generate_parser)

    audit_parser = sub.add_parser("audit", help="Run a checkpoint, completion, or incomplete-handoff gate")
    _review_dir(audit_parser)
    audit_parser.add_argument("--mode", choices=("checkpoint", "completion", "incomplete-handoff"), required=True)
    audit_parser.add_argument("--json", action="store_true", help="Emit machine-readable output only")
    return parser


def _print_result(result: dict, *, json_only: bool = False) -> None:
    if json_only:
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return
    if "ok" in result:
        print("check: PASS" if result["ok"] else "check: FAIL")
        for issue in result.get("issues", []):
            print(f"- {issue}")
    elif "passed" in result:
        print(f"{result['mode']} audit: {'PASS' if result['passed'] else 'FAIL'}")
        for issue in result.get("issues", []):
            print(f"- {issue}")
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(result, sort_keys=True, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            result = initialize(args.review_dir, args.contract, args.reference_pack, args.runtime_capability)
        else:
            root = ensure_review_root(args.review_dir)
            recovery = recover(root)
            if args.command == "check":
                result = check_review(root, check_generated=not args.skip_generated)
                result["recovery"] = recovery
                _print_result(result, json_only=args.json)
                return 0 if result["ok"] else 1
            if args.command == "mutate":
                migration = None
                if args.migrate_spec:
                    if not args.contract or not args.reference_pack:
                        raise ReviewToolError("--migrate-spec requires --contract and --reference-pack")
                    migration = (args.contract, args.reference_pack, args.changed_section, args.affected_angle)
                result = apply_mutation(root, args.expected_digest, args.changes, migration)
            elif args.command == "import":
                result = import_specialist(root, args.work_id, args.attempt_id, args.expected_digest)
            elif args.command == "import-audit":
                result = import_audit(root, args.attempt_id, args.expected_digest)
            elif args.command == "generate":
                result = generate(root)
            elif args.command == "audit":
                result = audit(root, args.mode)
                _print_result(result, json_only=args.json)
                return 0 if result["passed"] else 1
        _print_result(result)
        return 0
    except ReviewToolError as exc:
        print(f"review-tool: error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"review-tool: filesystem error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
