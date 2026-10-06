"""Build deterministic ARM64 ZIPs from the locked live dependencies; no evaluator files."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]


def main():
    build = ROOT / ".tools/p05-build"
    build.mkdir(parents=True, exist_ok=True)
    uv = str(ROOT / ".tools/uv.exe") if os.name == "nt" else "uv"
    requirements = build / "requirements.txt"
    subprocess.run(
        [
            uv,
            "export",
            "--frozen",
            "--extra",
            "live",
            "--no-dev",
            "--no-emit-project",
            "--output-file",
            str(requirements),
        ],
        cwd=ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()[:16]
    dependencies = build / ("deps-" + digest)
    if not (dependencies / ".complete").exists():
        subprocess.run(
            [
                uv,
                "pip",
                "install",
                "--python-platform",
                "aarch64-manylinux2014",
                "--python-version",
                "3.12",
                "--only-binary",
                ":all:",
                "--target",
                str(dependencies),
                "--require-hashes",
                "-r",
                str(requirements),
            ],
            cwd=ROOT,
            check=True,
        )
        (dependencies / ".complete").touch()
    payload = {}
    for path in dependencies.rglob("*"):
        if (
            path.is_file()
            and not any(p in {"__pycache__", "bin", "Scripts"} for p in path.parts)
            and path.name != ".complete"
        ):
            payload[path.relative_to(dependencies).as_posix()] = path.read_bytes()
    for path in (ROOT / "src/incident_demo").rglob("*.py"):
        payload[path.relative_to(ROOT / "src").as_posix()] = path.read_bytes()
    for path in (ROOT / "prompts").glob("*.txt"):
        payload[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    payload["main.py"] = b"from incident_demo.live.runtime import main\nmain()\n"
    telemetry, mapping = {}, {}
    manifest = json.loads((ROOT / "evals/case-manifest.json").read_text())
    for case in manifest["cases"]:
        if case["split"] != "development":
            continue
        fixture = json.loads((ROOT / case["fixture_path"]).read_text())
        identifier = hashlib.sha256(json.dumps(fixture, sort_keys=True).encode()).hexdigest()[:24]
        # Only observations are deployed, never case labels, expected answers or retrieval IDs.
        telemetry[identifier] = {"responses": fixture["responses"]}
        mapping[case["case_id"]] = identifier
    payload["telemetry.json"] = json.dumps(telemetry, sort_keys=True).encode()
    archive = build / "live.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED, compresslevel=6) as zip_file:
        for name, data in sorted(payload.items()):
            info = ZipInfo(name, date_time=(2026, 10, 5, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            zip_file.writestr(info, data, compress_type=ZIP_DEFLATED, compresslevel=6)
    if sum(map(len, payload.values())) >= 250 * 1024**2:
        raise ValueError("Lambda uncompressed package limit exceeded")
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    target = build / f"live-{sha}.zip"
    shutil.copyfile(archive, target)
    result = {
        "sha256": sha,
        "zip": str(target),
        "zipped_bytes": archive.stat().st_size,
        "unzipped_bytes": sum(map(len, payload.values())),
        "development_telemetry": mapping,
    }
    (build / "package.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
