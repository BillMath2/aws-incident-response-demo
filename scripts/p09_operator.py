"""Launch the localhost operator screen; saved-evidence replay is the default."""

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

from incident_demo.operator.server import OperatorServer, load_examples

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cloud", action="store_true", help="Enable the signed AWS API bridge")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    backend = None
    if args.cloud:
        from incident_demo.operator.cloud import CloudOperator

        sys.path.insert(0, str(ROOT / "infra"))
        from budget import LEDGER, reserve

        def reserve_once(run_id):
            ledger = json.loads(LEDGER.read_text()) if LEDGER.exists() else {"reservations": []}
            if not any(row["batch_id"] == run_id for row in ledger["reservations"]):
                reserve(run_id, Decimal("0.75"))

        outputs = json.loads((ROOT / "infra/cdk.out/workflow-outputs.json").read_text())[
            "incident-demo-workflow"
        ]
        backend = CloudOperator(outputs, reserve_once)
    with OperatorServer(args.port, backend, load_examples(ROOT)) as server:
        print(
            f"Operator screen: {server.origin} ({'cloud' if backend else 'saved replay'})",
            flush=True,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
