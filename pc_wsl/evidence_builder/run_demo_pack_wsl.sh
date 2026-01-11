#!/usr/bin/env bash
set -euo pipefail

EVIDENCE_DIR="${EVIDENCE_DIR:-$HOME/evidence_builder}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "SCRIPT_DIR=$SCRIPT_DIR"
echo "EVIDENCE_DIR=$EVIDENCE_DIR"
# Fail fast if EVIDENCE_DIR is read-only (common when running against frozen bundles)
if [ ! -w "$EVIDENCE_DIR" ]; then
  echo "ERROR: EVIDENCE_DIR is not writable: $EVIDENCE_DIR" >&2
  echo "Hint: rerun using a writable workspace, e.g.:" >&2
  echo "  EVIDENCE_DIR=$HOME/projects/fod_poc/workspace/eb_reruns/<run> bash $0" >&2
  exit 2
fi


[ -d "$EVIDENCE_DIR" ] || { echo "ERROR: EVIDENCE_DIR not found: $EVIDENCE_DIR"; exit 2; }
[ -f "$EVIDENCE_DIR/input/events.json" ] || { echo "ERROR: Missing $EVIDENCE_DIR/input/events.json"; exit 2; }

cd "$EVIDENCE_DIR"

# Clean previous outputs (runtime only)
rm -rf output/clips output/snapshots output/index.csv demo_pack demo_pack.zip demo_pack.zip.sha256
mkdir -p output

# Run repo scripts directly with CWD set to EVIDENCE_DIR
python3 "$SCRIPT_DIR/batch_evidence.py"
python3 "$SCRIPT_DIR/make_demo_pack.py"

# Record checksum deterministically
sha256sum demo_pack.zip | tee demo_pack.zip.sha256
