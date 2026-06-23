"""Command line interface for the Section 18 operations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from interrogation_harness import canonical
from interrogation_harness.operations import HarnessOperations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="interrogation-harness")
    parser.add_argument("--root", default="sessions")
    sub = parser.add_subparsers(dest="command", required=True)

    _session(sub, "create-session")
    add_source = _session(sub, "add-source")
    add_source.add_argument("content", nargs="?")
    add_source.add_argument("--file")
    _session(sub, "run-initial-extraction")
    _session(sub, "show-ledger")
    _session(sub, "show-open-work")
    _session(sub, "ask-next")
    answer = _session(sub, "answer")
    answer.add_argument("answer")
    answer.add_argument("--class", dest="answer_class")
    defer = _session(sub, "defer")
    defer.add_argument("work_item_id", nargs="?")
    defer.add_argument("--reason", default="deferred")
    revise = _session(sub, "revise")
    revise.add_argument("entity_id")
    revise.add_argument("new_statement")
    revise.add_argument("--reason", default="user revised")
    _session(sub, "run-audit")
    force = _session(sub, "force-close")
    force.add_argument("--reason", default="force close requested")
    _session(sub, "generate-artifact")
    _session(sub, "rebuild-ledger")
    export = _session(sub, "export-session")
    export.add_argument("dest")
    _session(sub, "resume-session")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ops = HarnessOperations(args.root, args.session_id)
    result = _dispatch(args, ops)
    _print_result(result)
    return 0


def _session(sub, name: str):
    parser = sub.add_parser(name)
    parser.add_argument("session_id")
    return parser


def _dispatch(args, ops: HarnessOperations):
    command = args.command
    if command == "create-session":
        return ops.create_session()
    if command == "add-source":
        content = _source_content(args)
        return ops.add_source(content)
    if command == "run-initial-extraction":
        return ops.run_initial_extraction()
    if command == "show-ledger":
        return ops.show_ledger()
    if command == "show-open-work":
        return ops.show_open_work()
    if command == "ask-next":
        return ops.ask_next()
    if command == "answer":
        return ops.answer(args.answer, answer_class=args.answer_class)
    if command == "defer":
        return ops.defer(work_item_id=args.work_item_id, reason=args.reason)
    if command == "revise":
        return ops.revise(args.entity_id, args.new_statement, reason=args.reason)
    if command == "run-audit":
        return ops.run_audit()
    if command == "force-close":
        return ops.force_close(reason=args.reason)
    if command == "generate-artifact":
        return ops.generate_artifact()
    if command == "rebuild-ledger":
        return ops.rebuild_ledger()
    if command == "export-session":
        return [str(path) for path in ops.export_session(args.dest)]
    if command == "resume-session":
        return {"byte_identical": ops.resume_session()}
    raise ValueError(f"unknown command: {command}")


def _source_content(args) -> str:
    if args.file:
        return Path(args.file).read_text(encoding="utf-8")
    if args.content is not None:
        return args.content
    return sys.stdin.read()


def _print_result(result) -> None:
    if hasattr(result, "__dataclass_fields__"):
        data = {
            "accepted": result.accepted,
            "job": result.job.value,
            "errors": result.errors,
            "attempts": result.attempts,
        }
        if result.ledger is not None:
            data["ledger"] = result.ledger
        print(canonical.dumps_ledger(data), end="")
        return
    print(canonical.dumps_ledger(_jsonable(result)), end="")


def _jsonable(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value
