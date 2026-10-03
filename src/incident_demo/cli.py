"""Synthetic local incident walkthrough and offline corpus maintenance."""

import argparse
from pathlib import Path

from pydantic import ValidationError

from incident_demo.contracts.local import LocalRunRecord
from incident_demo.contracts.records import (
    ActionReceipt,
    Approval,
    Evaluation,
    Evidence,
    ExecuteRollback,
    Investigation,
    Proposal,
    Request,
    Run,
)
from incident_demo.contracts.tools import CALL_ADAPTER
from incident_demo.corpus import Fixture, KnowledgeCatalog, Manifest, json_document, validate_corpus
from incident_demo.local_cli import run_demo
from incident_demo.local_tools import VerificationFixtures
from incident_demo.workflow.local import LOCAL_ROLES

SCHEMAS = (
    Request,
    Run,
    Evidence,
    Investigation,
    Proposal,
    Approval,
    ExecuteRollback,
    ActionReceipt,
    Evaluation,
    Fixture,
    KnowledgeCatalog,
    Manifest,
    LocalRunRecord,
    VerificationFixtures,
)


def export_schemas(root: Path, check: bool = False) -> None:
    schemas = {model.__name__: model.model_json_schema() for model in SCHEMAS}
    schemas["InvestigatorCall"] = CALL_ADAPTER.json_schema()
    folder = root / "schemas"
    if not check:
        folder.mkdir(parents=True, exist_ok=True)
    for name, schema in schemas.items():
        path = folder / f"{name}.json"
        expected = json_document(schema)
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != expected:
                raise ValueError(f"schema missing or out of date: {path}")
        else:
            path.write_text(expected, encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate-corpus", help="check fixture, split and corpus integrity offline")
    schemas = sub.add_parser("schemas", help="export versioned JSON Schemas")
    schemas.add_argument("--check", action="store_true", help="fail on schema drift")
    demo = sub.add_parser("demo", help="run a labeled, single-process local stub walkthrough")
    demo.add_argument(
        "--case",
        choices=[f"case-{n:03}" for n in range(1, 9)],
        default="case-001",
        help="development fixture only (default: case-001)",
    )
    demo.add_argument(
        "--decision",
        choices=["approve", "reject", "pending"],
        help="script a simulated decision; omitted means interactive review",
    )
    demo.add_argument(
        "--actor",
        choices=list(LOCAL_ROLES),
        default="local-approver",
        help="simulated identity; this is not real authentication",
    )
    demo.add_argument("--reason", default="Reviewed the synthetic local proposal")
    demo.add_argument(
        "--verification",
        choices=["recovered", "unhealthy", "missing"],
        default="recovered",
        help="independent synthetic health profile",
    )
    demo.add_argument(
        "--output", type=Path, help="new JSON evidence file; existing files are refused"
    )
    args = parser.parse_args()
    try:
        if args.command == "validate-corpus":
            counts = validate_corpus(args.root)
            print(f"Offline corpus valid: {counts}")
        elif args.command == "schemas":
            export_schemas(args.root, args.check)
            print("Schemas verified." if args.check else "Schemas exported.")
        else:
            parser.exit(run_demo(args))
    except ValidationError:
        parser.exit(1, "Validation failed: input does not match the contract.\n")
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Validation failed: {exc}\n")


if __name__ == "__main__":
    main()
