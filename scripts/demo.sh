#!/usr/bin/env bash
# Offline demo with fictional data. No network, no keys.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH=src

DEMO_DIR="${1:-/tmp/findmejob-demo}"
rm -rf "$DEMO_DIR"; mkdir -p "$DEMO_DIR"

python3 - <<PY
import json, pathlib
cfg = json.loads(pathlib.Path("config.example.json").read_text())
cfg["profile"]["master_cv"] = "data/profile/master_cv.md"
cfg["search"]["sources"] = [{"type": "jsonfile", "path": str(pathlib.Path.cwd() / "sample_data/sample_jobs.json")}]
cfg["policy"]["salary_floor"] = 60000
pathlib.Path("$DEMO_DIR/config.json").write_text(json.dumps(cfg, indent=2))
PY

python3 -m findmejob.cli --dir "$DEMO_DIR" ingest --cv sample_data/master_cv.example.md
echo
echo '--- chat: find jobs ---'
python3 -m findmejob.cli --dir "$DEMO_DIR" chat find jobs
echo
echo '--- chat: status ---'
python3 -m findmejob.cli --dir "$DEMO_DIR" chat status
echo
echo '--- chat: tailor Fictional Pets ---'
python3 -m findmejob.cli --dir "$DEMO_DIR" chat "tailor Fictional Pets"
echo
echo '--- chat: what is pending ---'
python3 -m findmejob.cli --dir "$DEMO_DIR" chat "what's pending"
echo
echo "Demo data in $DEMO_DIR (tailored CVs in output/cvs, emails in output/emails)"
echo "Run the UI: findmejob --dir $DEMO_DIR ui"
