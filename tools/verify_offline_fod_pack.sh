#!/usr/bin/env bash
set -euo pipefail

# Guard: must run under bash (not sourced into zsh)
[[ -n "${BASH_VERSION:-}" ]] || { echo "ERROR: Run with bash: bash tools/verify_offline_fod_pack.sh ..."; exit 2; }

# Basic help
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  sed -n '1,60p' "${BASH_SOURCE[0]}"
  exit 0
fi

# Usage:
#   bash tools/verify_offline_fod_pack.sh \
#     --video /path/to/run_103012.mp4 \
#     --model /path/to/fod_1class_best.pt \
#     --roi   /path/to/roi_1080p_12mm_roadonly_v1.json \
#     --work  /path/to/workdir
#
# Output:
#   <work>/demo_pack.zip + .sha256
#   <work>/verification/*.txt (run log)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

VIDEO=""
MODEL=""
ROI=""
WORK=""

# Python to use (prefer provided venv)
PY="${VENV_PY:-}"
if [[ -z "$PY" ]]; then
  if [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python3" ]]; then
    PY="$VIRTUAL_ENV/bin/python3"
  fi
fi
if [[ -z "$PY" ]]; then
  PY="python3"
fi

# Dependency sanity (offline detector needs numpy + ultralytics)
if ! "$PY" -c "import numpy, ultralytics" >/dev/null 2>&1; then
  echo "ERROR: Python '$PY' missing deps (numpy, ultralytics)." >&2
  echo "Fix: activate venv or export VENV_PY=/path/to/python3" >&2
  echo "Example:" >&2
  echo "  source /home/beros/projects/fod_poc/venv/pc_train/bin/activate" >&2
  echo "  export VENV_PY=\$(python3 -c 'import sys; print(sys.executable)')" >&2
  exit 2
fi

echo "PYTHON_OK: $PY"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --video) VIDEO="$2"; shift 2;;
    --model) MODEL="$2"; shift 2;;
    --roi)   ROI="$2"; shift 2;;
    --work)  WORK="$2"; shift 2;;
    *) echo "Unknown arg: $1" >&2; exit 2;;
  esac
done

if [[ -z "$VIDEO" || -z "$MODEL" || -z "$ROI" || -z "$WORK" ]]; then
  echo "ERROR: missing required args. See header usage." >&2
  exit 2
fi

# Sanity
[[ -f "$VIDEO" ]] || { echo "Missing VIDEO: $VIDEO" >&2; exit 2; }
[[ -f "$MODEL" ]] || { echo "Missing MODEL: $MODEL" >&2; exit 2; }
[[ -f "$ROI"   ]] || { echo "Missing ROI:   $ROI" >&2; exit 2; }

mkdir -p "$WORK/input" "$WORK/output" "$WORK/verification"

# copy mp4 to ensure independence
cp -av "$VIDEO" "$WORK/input/$(basename "$VIDEO")"

EVENTS_OUT="$WORK/output/events_fod_$(basename "$VIDEO" .mp4)_tuned.json"

# Run offline detector (FOD 1-class)
"$PY" "$REPO_ROOT/pc_wsl/offline/offline_detect_run_coco.py" \
  --video "$WORK/input/$(basename "$VIDEO")" \
  --model "$MODEL" \
  --roi "$ROI" \
  --events_out "$EVENTS_OUT" \
  --imgsz 1280 \
  --conf 0.05 \
  --rep_conf 0.15 \
  --confirm_n 2 \
  --end_miss_m 6 \
  --min_event_dur_s 0.30 \
  --cooldown_s 0.20 \
  --min_area 400

# Normalize to EB input schema (events.json)
"$PY" - <<PY
import json
from pathlib import Path

src = Path("$EVENTS_OUT")
events = json.loads(src.read_text())
for e in events:
    # enforce minimum EB-compatible fields
    e["class"] = e.get("class") or e.get("class_name") or "FOD"
    e["representative_time_s"] = e.get("representative_time_s", e.get("rep_time_s"))
    e["frame_size"] = e.get("frame_size") or [1920, 1080]
Path("$WORK/input/events.json").write_text(json.dumps(events, indent=2))
print("WROTE:", "$WORK/input/events.json")
print("events:", len(events))
PY

# Run Evidence Builder into the same WORK directory
EVIDENCE_DIR="$WORK" bash "$REPO_ROOT/pc_wsl/evidence_builder/run_demo_pack_wsl.sh"

# Verify zip checksum
cd "$WORK"
sha256sum -c demo_pack.zip.sha256

# Write a concise verification log
"$PY" - <<PY
from pathlib import Path
import hashlib, json, os, subprocess, datetime

work = Path("$WORK")
repo = Path("$REPO_ROOT")

def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1024*1024), b""):
            h.update(b)
    return h.hexdigest()

log = []
log.append(f"DATE: {datetime.datetime.now().astimezone().isoformat()}")
log.append(f"REPO_ROOT: {repo}")
log.append(f"GIT_HEAD: {subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD']).decode().strip()}")
log.append("")
log.append("FILES:")
for fn in ["input/events.json","output/index.csv","demo_pack.zip","demo_pack.zip.sha256"]:
    p = work / fn
    log.append(f"  {fn}  exists={p.exists()}  size={p.stat().st_size if p.exists() else 'NA'}")
log.append("")
log.append("SHA256:")
log.append(f"  input/events.json  {sha256(work/'input/events.json')}")
log.append(f"  output/index.csv   {sha256(work/'output/index.csv')}")
log.append(f"  demo_pack.zip      {sha256(work/'demo_pack.zip')}")
Path(work/"verification/verify_log.txt").write_text("\n".join(log) + "\n")
print("WROTE:", work/"verification/verify_log.txt")
PY

echo "DONE: $WORK"
echo "ZIP:  $WORK/demo_pack.zip"
