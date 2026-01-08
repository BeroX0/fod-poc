#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<EOF
USAGE:
  $0 --jetson-url <http://HOST:PORT/\> --bundle <ABS_BUNDLE_PATH> --mode <coco|fod>

Example:
  $0 --jetson-url http://100.119.10.42:8000/ \
     --bundle /home/beros/projects/fod_poc/workspace/freeze_bundles/freeze_20260108_r5/live_coco \
     --mode coco

Notes:
- Downloads: events.json, SHA256SUMS.txt, (optional index.html), and the MP4 referenced by events.json["video_filename"].
- Verifies raw hashes using SHA256SUMS.txt (basename-based matching).
- Runs EB with: EVIDENCE_DIR=<bundle>/eb bash pc_wsl/evidence_builder/run_demo_pack_wsl.sh
- Writes SHA256SUMS_BUNDLE.txt (excludes itself), then locks bundle read-only.
EOF
}

JETSON_URL=""
BUNDLE=""
MODE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --jetson-url) JETSON_URL="${2:-}"; shift 2;;
    --bundle)     BUNDLE="${2:-}"; shift 2;;
    --mode)       MODE="${2:-}"; shift 2;;
    -h|--help)    usage; exit 0;;
    *) echo "ERROR: unknown arg: $1"; usage; exit 2;;
  esac
done

[[ -n "$JETSON_URL" ]] || { echo "ERROR: --jetson-url required"; usage; exit 2; }
[[ -n "$BUNDLE" ]]    || { echo "ERROR: --bundle required"; usage; exit 2; }
[[ "$MODE" == "coco" || "$MODE" == "fod" ]] || { echo "ERROR: --mode must be coco|fod"; usage; exit 2; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EB_RUNNER="$REPO_ROOT/pc_wsl/evidence_builder/run_demo_pack_wsl.sh"

command -v curl >/dev/null || { echo "ERROR: curl not found"; exit 2; }
command -v sha256sum >/dev/null || { echo "ERROR: sha256sum not found"; exit 2; }
command -v python3 >/dev/null || { echo "ERROR: python3 not found"; exit 2; }

# Normalize URL to end with /
[[ "$JETSON_URL" == */ ]] || JETSON_URL="${JETSON_URL}/"

if [[ -e "$BUNDLE" ]]; then
  echo "ERROR: bundle destination already exists: $BUNDLE" >&2
  echo "Hint: choose a new freeze id (r5/r6/...) or delete the old destination intentionally." >&2
  exit 2
fi

BUNDLE_PARENT="$(dirname "$BUNDLE")"
mkdir -p "$BUNDLE_PARENT"

TMP="$(mktemp -d "${BUNDLE}.tmp.XXXX")"
RAW="$TMP/raw_from_jetson"
EB="$TMP/eb"
mkdir -p "$RAW" "$EB/input"

echo "[freeze] REPO_ROOT=$REPO_ROOT"
echo "[freeze] MODE=$MODE"
echo "[freeze] JETSON_URL=$JETSON_URL"
echo "[freeze] TMP=$TMP"
echo "[freeze] FINAL=$BUNDLE"

cleanup() {
  # Only clean temp if we did not move it successfully.
  if [[ -d "$TMP" ]]; then
    rm -rf "$TMP"
  fi
}
trap cleanup EXIT

echo "[download] events.json + SHA256SUMS.txt (index.html optional)"
curl -fsSL "${JETSON_URL}events.json" -o "$RAW/events.json"
curl -fsSL "${JETSON_URL}SHA256SUMS.txt" -o "$RAW/SHA256SUMS.txt"
curl -fsSL "${JETSON_URL}index.html" -o "$RAW/index.html" 2>/dev/null || true

VIDEO_NAME="$(python3 - <<PY
import json
from pathlib import Path
p = Path("$RAW/events.json")
d = json.loads(p.read_text())
if not isinstance(d, list) or not d:
    raise SystemExit("ERROR: events.json must be a non-empty list")
vf = d[0].get("video_filename")
if not vf:
    raise SystemExit("ERROR: video_filename missing in first event")
print(vf)
PY
)"

echo "[download] referenced video: $VIDEO_NAME"
curl -fL "${JETSON_URL}${VIDEO_NAME}" -o "$RAW/$VIDEO_NAME"

echo "[guard] mode validation ($MODE)"
python3 - <<PY
import json
from pathlib import Path

mode = "$MODE"
d = json.loads(Path("$RAW/events.json").read_text())

def get_label(e):
    # accept a few schema variants
    return (e.get("class") or e.get("class_name") or e.get("label") or "").strip()

labels = [get_label(e) for e in d]
if not labels:
    raise SystemExit("ERROR: no events to validate")

# Normalize empties to ""
labels_norm = [x if x is not None else "" for x in labels]

if mode == "fod":
    bad = [x for x in labels_norm if x != "FOD"]
    if bad:
        raise SystemExit(f"ERROR: mode=fod but found non-FOD labels: {sorted(set(bad))[:10]}")
else:
    # coco mode must not be "all FOD"
    if all(x == "FOD" for x in labels_norm):
        raise SystemExit("ERROR: mode=coco but all event labels are FOD (likely wrong served export)")
print("OK: mode guard passed. sample labels:", sorted(set(labels_norm))[:10])
PY

echo "[verify] raw SHA256SUMS.txt (basename-based match)"
python3 - <<PY
import hashlib
from pathlib import Path

raw = Path("$RAW")
sums = (raw / "SHA256SUMS.txt").read_text().splitlines()

want = {}
for line in sums:
    line = line.strip()
    if not line:
        continue
    parts = line.split()
    if len(parts) < 2:
        continue
    h = parts[0]
    name = Path(parts[-1]).name
    want[name] = h

def sha256(p: Path) -> str:
    m = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            m.update(chunk)
    return m.hexdigest()

must = ["events.json", "SHA256SUMS.txt", "$VIDEO_NAME"]
for fn in must:
    p = raw / fn
    if not p.exists():
        raise SystemExit(f"ERROR: missing raw file: {p}")
    if fn in want:
        got = sha256(p)
        exp = want[fn]
        if got != exp:
            raise SystemExit(f"ERROR: sha mismatch for {fn}\n  expected: {exp}\n  got:      {got}")
    else:
        # SHA256SUMS was created with absolute paths sometimes; basename mapping should still find it
        # If not present, we warn but do not fail for that file.
        print(f"WARNING: {fn} not listed in SHA256SUMS.txt basenames; skipping strict check")

print("OK: raw hashes verified where possible.")
PY

echo "[stage] EB input (events.json + mp4 only)"
cp -v "$RAW/events.json" "$EB/input/events.json"
cp -v "$RAW/$VIDEO_NAME" "$EB/input/"

echo "[eb] run Evidence Builder into bundle/eb"
EVIDENCE_DIR="$EB" bash "$EB_RUNNER"

echo "[bundle] write SHA256SUMS_BUNDLE.txt (exclude itself, deterministic order)"
(
  cd "$TMP"
  LC_ALL=C find . -type f ! -name SHA256SUMS_BUNDLE.txt -print0 \
    | LC_ALL=C sort -z \
    | xargs -0 sha256sum > SHA256SUMS_BUNDLE.txt
)

echo "[bundle] lock read-only"
chmod -R a-w "$TMP"

echo "[bundle] validate SHA256SUMS_BUNDLE.txt"
(
  cd "$TMP"
  sha256sum -c SHA256SUMS_BUNDLE.txt
)

echo "[finalize] move temp -> final"
mv "$TMP" "$BUNDLE"
# prevent trap cleanup from deleting moved dir
TMP=""

echo "FREEZE COMPLETE: $BUNDLE"
ls -la "$BUNDLE"
