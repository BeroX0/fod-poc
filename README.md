# FOD PoC (SEP400 × Standby AB)

This repository contains a Proof-of-Concept (PoC) pipeline for **Foreign Object Debris (FOD) detection on roads** using:

- **Jetson Orin Nano** camera pack for data capture (Arducam IMX477 + CS lenses)
- **PC/WSL offline pipeline** for inference and event extraction
- **Evidence Builder** that converts an `events.json` + video into demo-ready artifacts:
  - event clips
  - representative snapshots
  - bbox overlays
  - deterministic demo pack ZIP (`demo_pack.zip` + checksum)

> Note (PoC scope): The focus is pipeline validation, reproducibility, and deterministic demo artifacts. Thresholds/models may yield false positives/negatives.

---

## Repository Structure (high level)

- `jetson/` — Jetson camera tuning/recording notes and capture references
- `pc_wsl/` — PC/WSL tooling (offline inference, event extraction, Evidence Builder)
- `tools/` — Reproducibility + demo runners
- `docs/` — Runbooks, checklists, and contracts
- `tests/` — Smoke tests / guardrails

---

## Quickstart (recommended): Offline Golden Demo (two bundles)

Use the **checksum-frozen golden bundles (outside git)** and reproduce demo artifacts deterministically.

Docs:
- Runbook: `docs/offline_demo_runbook.md`
- Demo checklist: `docs/demo_day_checklist.md`

Run:
```bash
cd /path/to/sep400-standby-fod-poc

# Activate venv (example path used in our environment)
source /home/beros/projects/fod_poc/venv/pc_train/bin/activate
export PYTHONNOUSERSITE=1
export VENV_PY="$(python3 -c 'import sys; print(sys.executable)')"

OUT="/tmp/fod_demo_$(date +%Y%m%d_%H%M%S)"

bash tools/run_demo_offline_from_bundles.sh \
  --bundle103 /path/to/offline_fod_run_103012 \
  --bundle106 /path/to/offline_fod_run_106012 \
  --out "$OUT"
````

Expected outputs:

* `$OUT/work_run_103012/demo_pack.zip`
* `$OUT/work_run_106012/demo_pack.zip`

Each run should end with:

* `index validation PASS: N/N rows resolved`
* `demo_pack.zip: OK`

---

## Verify a single offline run (deterministic pack builder)

This tool runs:
offline detector → normalizes to Evidence Builder schema → runs Evidence Builder → verifies ZIP checksum.

```bash
cd /path/to/sep400-standby-fod-poc

source /home/beros/projects/fod_poc/venv/pc_train/bin/activate
export PYTHONNOUSERSITE=1
export VENV_PY="$(python3 -c 'import sys; print(sys.executable)')"

WORK="/tmp/verify_one_$(date +%Y%m%d_%H%M%S)"

bash tools/verify_offline_fod_pack.sh \
  --video /path/to/run_103012.mp4 \
  --model /path/to/fod_1class_best.pt \
  --roi   /path/to/roi_1080p_12mm_roadonly_v1.json \
  --work  "$WORK"
```

Outputs inside `$WORK`:

* `demo_pack.zip` + `demo_pack.zip.sha256`
* `output/index.csv`, `output/clips/*`, `output/snapshots/*`
* `verification/verify_log.txt`

---

## Evidence Builder only (when you already have events.json)

If you already have:

* `EVIDENCE_DIR/input/<video>.mp4`
* `EVIDENCE_DIR/input/events.json`

Run:

```bash
cd /path/to/sep400-standby-fod-poc

export EVIDENCE_DIR="/path/to/evidence_dir"
bash pc_wsl/evidence_builder/run_demo_pack_wsl.sh
```

Evidence Builder outputs:

* `output/index.csv`
* `output/clips/*`
* `output/snapshots/*` including `*_bbox.jpg`
* `demo_pack/` and `demo_pack.zip` (+ `.sha256`)

---

## Golden bundles (outside git)

Golden bundles are stored **outside git** and are intended to be “checksum frozen” demo inputs.

A typical extracted bundle directory contains:

* `run_*.mp4`
* `fod_1class_best.pt`
* `roi_*.json`
* `events.json`
* `index.csv`
* `demo_pack.zip` + `demo_pack.zip.sha256`
* `verify_log.txt`
* `SHA256SUMS.txt`

See:

* `docs/offline_demo_runbook.md`
* `docs/demo_day_checklist.md`

---

## Environment notes

* Tools under `tools/` are **bash scripts** (even if you use zsh, run them with `bash ...`).
* Offline pipeline requires Python deps such as `numpy` and `ultralytics`.
* `tools/verify_offline_fod_pack.sh` prefers:

  * `VENV_PY=/path/to/venv/python3`, or
  * an activated `VIRTUAL_ENV`.

---

## Documentation index

* Offline demo runbook: `docs/offline_demo_runbook.md`
* Demo day checklist: `docs/demo_day_checklist.md`
* Evidence Builder contract: `docs/evidence_builder.md`
