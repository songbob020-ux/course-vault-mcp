from __future__ import annotations

import argparse
import json
import os
from typing import Any

from .config import load_config
from .service import CourseVaultService


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Course Vault MCP local workflow CLI")
    root.add_argument("--config", required=True, help="absolute path to course-vault TOML")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    commands.add_parser("refresh")
    commands.add_parser("next")
    listing = commands.add_parser("list")
    listing.add_argument("--status")
    listing.add_argument("--limit", type=int, default=100)
    legacy = commands.add_parser("import-legacy")
    legacy.add_argument("lesson_id")
    legacy.add_argument("--commit", action="store_true")
    legacy_audit = commands.add_parser("audit-legacy")
    legacy_audit.add_argument("--limit", type=int, default=500)
    approval = commands.add_parser("approve")
    approval.add_argument("lesson_id")
    approval.add_argument("--reviewer-note", required=True)
    approval.add_argument("--confirm-source-check", action="store_true")
    acknowledge = commands.add_parser("acknowledge-source-change")
    acknowledge.add_argument("lesson_id")
    acknowledge.add_argument("--note", required=True)
    acknowledge.add_argument("--confirm-recapture", action="store_true")
    revision = commands.add_parser("request-revision")
    revision.add_argument("lesson_id")
    revision.add_argument("--reason", required=True)
    validation = commands.add_parser("validate")
    validation.add_argument("lesson_id")
    preview = commands.add_parser("preview-sync")
    preview.add_argument("lesson_id")
    sync = commands.add_parser("sync")
    sync.add_argument("lesson_id")
    sync.add_argument("--commit", action="store_true")
    sync.add_argument("--confirm-publish", action="store_true")
    return root


def run_command(args: argparse.Namespace, service: CourseVaultService) -> None:
    if args.command == "doctor":
        print_json(service.status())
    elif args.command == "refresh":
        print_json(service.refresh())
    elif args.command == "next":
        print_json(service.next_action())
    elif args.command == "list":
        print_json(service.list_lessons(args.status, args.limit))
    elif args.command == "import-legacy":
        if args.commit:
            print_json(service.import_legacy_card(args.lesson_id))
        else:
            print_json(service.preview_legacy_card_import(args.lesson_id))
    elif args.command == "audit-legacy":
        print_json(service.audit_legacy_cards(args.limit))
    elif args.command == "approve":
        if not args.confirm_source_check:
            raise SystemExit("approve requires --confirm-source-check after local human review")
        print_json(service.approve_draft(args.lesson_id, args.reviewer_note))
    elif args.command == "acknowledge-source-change":
        if not args.confirm_recapture:
            raise SystemExit(
                "acknowledge-source-change requires --confirm-recapture after local inspection"
            )
        print_json(service.acknowledge_source_change(args.lesson_id, args.note))
    elif args.command == "request-revision":
        print_json(service.request_revision(args.lesson_id, args.reason))
    elif args.command == "validate":
        print_json(service.validate_draft(args.lesson_id))
    elif args.command == "preview-sync":
        print_json(service.preview_sync(args.lesson_id, include_local_path=True))
    elif args.command == "sync":
        if not args.commit or not args.confirm_publish:
            raise SystemExit(
                "sync requires --commit and --confirm-publish after reviewing preview-sync"
            )
        print_json(service.sync(args.lesson_id))


def main() -> None:
    args = parser().parse_args()
    os.environ["COURSE_VAULT_CONFIG"] = args.config
    try:
        service = CourseVaultService(load_config(args.config))
        run_command(args, service)
    except ValueError as exc:
        raise SystemExit(f"error: {exc}") from None


if __name__ == "__main__":
    main()
