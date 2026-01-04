#!/usr/bin/env bash
set -euo pipefail

# Evidence/data workspace (mp4 + events.json live here; NOT in git)
EVIDENCE_DIR="${EVIDENCE_DIR:-$HOME/evidence_builder}"

# Repo scripts live next to this runner
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "SCRIPT_DIR=$SCRIPT_DIR"
echo "EVIDENCE_DIR=$EVIDENCE_DIR"

# Sanity checks
[ -d "$EVIDENCE_DIR" ] || { echo "ERROR: EVIDENCE_DIR not found: $EVIDENCE_DIR"; exit 2; }
[ -f "$EVIDENCE_DIR/input/events.json" ] || { echo "ERROR: Missing $EVIDENCE_DIR/input/events.json"; exit 2; }

# Enforce repo as source-of-truth: refresh scripts into evidence workspace
install -m 644 "$SCRIPT_DIR/batch_evidence.py"      "$EVIDENCE_DIR/batch_evidence.py"
install -m 755 "$SCRIPT_DIR/make_demo_pack.py"      "$EVIDENCE_DIR/make_demo_pack.py"
install -m 644 "$SCRIPT_DIR/collect_all_events.py"  "$EVIDENCE_DIR/collect_all_events.py"

cd "$EVIDENCE_DIR"

rm -rf output/clips output/snapshots output/index.csv demo_pack demo_pack.zip
mkdir -p output

python3 batch_evidence.py
python3 make_demo_pack.py

sha256sum demo_pack.zip
