import json
from pathlib import Path

import aws_cdk as cdk
from cdk_nag import AwsSolutionsChecks

from foundation import Foundation
from settings import load_config

app = cdk.App(analytics_reporting=False)
Foundation(app, load_config())
checks = AwsSolutionsChecks(app, verbose=True)
cdk.Validations.of(app).add_plugins(checks)
assembly = app.synth()
# Keep an explicit successful scan as evidence; CDK may omit clean plugin reports.
report = checks.validate_scope(app)
summary = {
    "plugin": "AwsSolutionsChecks",
    "success": report.success,
    "violations": [v.rule_name for v in report.violations],
}
Path(assembly.directory, "nag-report.json").write_text(json.dumps(summary, indent=2) + "\n")
if not report.success:
    raise RuntimeError(f"cdk-nag rejected the foundation: {summary['violations']}")
