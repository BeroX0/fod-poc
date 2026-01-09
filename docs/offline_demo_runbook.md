# Offline Golden Demo Runbook (FOD PoC)

This runbook reproduces the offline demo evidence packs deterministically from “golden bundles” that live **outside git**.

## What you get
For each bundle (run_103012 and run_106012), the repo produces:

- `demo_pack.zip` + `demo_pack.zip.sha256`
- Evidence Builder output:
  - `output/index.csv`
  - `output/clips/*`
  - `output/snapshots/*`
- Verification log:
  - `verification/verify_log.txt`

The pack contains clips + snapshots + bbox overlays for each detected FOD “event”.

## Prerequisites (WSL/Ubuntu)
- `bash`, `tar`, `sha256sum`
- `ffmpeg`
- Python venv that contains: `numpy`, `ultralytics`
- Repo scripts (source-of-truth) available:
  - `tools/verify_offline_fod_pack.sh`
  - `tools/run_demo_offline_from_bundles.sh`
  - `pc_wsl/offline/offline_detect_run_coco.py`
  - `pc_wsl/evidence_builder/run_demo_pack_wsl.sh`

Important:
- Run scripts with **bash** (even if your shell is zsh).
- Prefer to activate venv and export `VENV_PY` so the verify tool uses the correct Python.

## Golden bundle format (directory)
Each extracted bundle directory contains:
- `run_*.mp4`
- `fod_1class_best.pt`
- `roi_1080p_12mm_roadonly_v1.json`
- `events.json`
- `index.csv`
- `demo_pack.zip` + `.sha256`
- `verify_log.txt`
- `SHA256SUMS.txt`

Bundles are “checksum frozen” and must contain **no symlinks**.

## Demo Day: Fast path (recommended)
1) Extract the two tarballs (or ensure you have extracted directories)
2) Run the bundle demo runner which calls the repo verification tool for each bundle.

### Example
```bash
cd /path/to/repo/sep400-standby-fod-poc
source /home/beros/projects/fod_poc/venv/pc_train/bin/activate
export PYTHONNOUSERSITE=1
export VENV_PY="$(python3 -c 'import sys; print(sys.executable)')"

bash tools/run_demo_offline_from_bundles.sh \
  --bundle103 /path/to/offline_fod_run_103012 \
  --bundle106 /path/to/offline_fod_run_106012 \
  --out /tmp/demo_run
Success criteria
Both runs end with:

index validation PASS: N/N rows resolved

demo_pack.zip: OK

Output artifacts:

/tmp/demo_run/work_run_103012/demo_pack.zip

/tmp/demo_run/work_run_106012/demo_pack.zip

Single-bundle verification (if needed)
bash
Kopiera kod
source /home/beros/projects/fod_poc/venv/pc_train/bin/activate
export PYTHONNOUSERSITE=1
export VENV_PY="$(python3 -c 'import sys; print(sys.executable)')"

WORK="/tmp/verify_one_$(date +%Y%m%d_%H%M%S)"
bash tools/verify_offline_fod_pack.sh \
  --video /path/to/run_103012.mp4 \
  --model /path/to/fod_1class_best.pt \
  --roi   /path/to/roi_1080p_12mm_roadonly_v1.json \
  --work  "$WORK"
Troubleshooting
“missing deps (numpy, ultralytics)”

Activate venv and set VENV_PY:

source .../venv/pc_train/bin/activate

export VENV_PY="$(python3 -c 'import sys; print(sys.executable)')"

“Run with bash”

Execute using: bash tools/<script>.sh ...
