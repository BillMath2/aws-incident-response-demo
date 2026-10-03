"""P01 maintenance CLI. Investigation and execution arrive in P02."""

import argparse
from pathlib import Path

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
    args = parser.parse_args()
    try:
        if args.command == "validate-corpus":
            counts = validate_corpus(args.root)
            print(f"Offline corpus valid: {counts}")
        else:
            export_schemas(args.root, args.check)
            print("Schemas verified." if args.check else "Schemas exported.")
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Validation failed: {exc}\n")


if __name__ == "__main__":
    main()
