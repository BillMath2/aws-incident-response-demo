"""Build a separate P07 asset without changing the frozen AgentCore deployment package."""

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = json.loads((ROOT / ".tools/p05-build/package.json").read_text())
    build = ROOT / ".tools/p07-build"
    build.mkdir(exist_ok=True)
    with ZipFile(source["zip"]) as previous:
        payload = {
            n: previous.read(n) for n in previous.namelist() if not n.startswith("incident_demo/")
        }
    for path in (ROOT / "src/incident_demo").rglob("*.py"):
        payload[path.relative_to(ROOT / "src").as_posix()] = path.read_bytes()
    archive = build / "workflow.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED, compresslevel=6) as target:
        for name, data in sorted(payload.items()):
            info = ZipInfo(name, date_time=(2026, 10, 6, 0, 0, 0))
            info.create_system, info.external_attr = 3, 0o100644 << 16
            target.writestr(info, data, compress_type=ZIP_DEFLATED, compresslevel=6)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    final = build / f"workflow-{digest}.zip"
    if not final.exists():
        final.write_bytes(archive.read_bytes())
    request = {
        "batch_id": "p07-dev-01",
        "telemetry_id": source["development_telemetry"]["case-001"],
        "incident": json.loads((ROOT / "fixtures/cases/case-001.json").read_text())["incident"],
        "variant": "V1",
        "settings": {"model": "us.amazon.nova-lite-v1:0"},
    }
    manifest = {"zip": str(final), "sha256": digest, "live_request": request}
    (build / "package.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"sha256": digest, "bytes": final.stat().st_size}))


if __name__ == "__main__":
    main()
