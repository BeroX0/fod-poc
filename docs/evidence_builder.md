# Evidence Builder (Demo Pack Generator)

## Purpose and scope
The **Evidence Builder** converts detected **events** (`$HOME/evidence_builder/input/events.json`) plus referenced **video files** into a **demo-ready evidence pack**:

- Short **clips** around each event
- **snapshots** (single extracted frame) per event
- **bbox overlay** rendered deterministically on the snapshot
- Two indices:
  - `output/index.csv` (runtime index; paths relative to `$HOME/evidence_builder/output/`)
  - `demo_pack/index.csv` (pack index; paths relative to `demo_pack/`)
- A single deliverable: `demo_pack.zip`

This is a **PoC** pipeline. Object classes can be **proxy labels** (e.g., COCO classes) and may not match the true physical object.

---

## Source-of-truth (important)
The repo contains the canonical scripts under:

`pc_wsl/evidence_builder/`

The runner `run_demo_pack_wsl.sh` **installs/copies** these repo scripts into `$HOME/evidence_builder/` before running, so local edits in the runtime folder cannot silently diverge.

---

## Prerequisites
Tested environment:
- Ubuntu (WSL2 or Linux)
- `python3` (tested with Python 3.12.x)
- `ffmpeg` and `ffprobe` available on `PATH`

Quick check:
```bash
command -v ffmpeg && ffmpeg -version | head -n 2
command -v ffprobe && ffprobe -version | head -n 2
python3 -V
