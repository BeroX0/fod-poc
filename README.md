# FOD PoC

This repository contains a Proof-of-Concept (PoC) pipeline for **Foreign Object Debris (FOD) detection on roads** using:
- A **Jetson Orin Nano** camera pack for data capture (Arducam IMX477 + CS lenses),
- A **PC/WSL offline pipeline** for inference and event extraction,
- An **Evidence Builder** that converts an `events.json` + videos into demo-ready artifacts (clips, snapshots, bbox overlays, and a deterministic demo pack ZIP).

> Note: This is a PoC. Some detections may use **proxy COCO classes** (e.g., “bottle”) even when the physical object is not literally that class. The goal here is pipeline validation and reproducibility.

---

## Repository Structure (high level)

- `jetson/`
  - Camera tuning and recording notes/scripts for the Jetson capture setup.
- `pc_wsl/`
  - WSL/PC-side tooling: inference, events pipeline, Evidence Builder, and reproducibility helpers.
- `docs/`
  - Documentation for data layout, environments, reproducibility steps, and script conventions/tests.
- `tests/`
  - Smoke tests to validate critical paths and prevent regressions.

---

## Quickstart: Build a Demo Pack (Evidence Builder)

The Evidence Builder produces:
- `output/index.csv` (runtime index)
- `output/clips/*`
- `output/snapshots/*` including `*_bbox.jpg`
- `demo_pack/` (pack layout for demo)
- `demo_pack.zip` (compressed demo deliverable)

### Prerequisites
- Ubuntu on WSL2 (or Linux)
- `ffmpeg` and `ffprobe` available on PATH
- `python3` available (tested with Python 3.12.x)

### One-command run (WSL)
From the repo root:

```bash
cd ~/projects/sep400-standby-fod-poc
bash pc_wsl/evidence_builder/run_demo_pack_wsl.sh

```
## Documentation

- Evidence Builder contract + reproduction: `docs/evidence_builder.md`
