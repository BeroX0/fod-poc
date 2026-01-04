#!/usr/bin/env bash
set -euo pipefail

# Default workdir is ~/evidence_builder (symlink OK)
EVIDENCE_DIR="${EVIDENCE_DIR:-$HOME/evidence_builder}"

echo "EVIDENCE_DIR=$EVIDENCE_DIR"
cd "$EVIDENCE_DIR"

rm -rf output/clips output/snapshots output/index.csv demo_pack demo_pack.zip
mkdir -p output

python3 batch_evidence.py
python3 make_demo_pack.py

sha256sum demo_pack.zip
