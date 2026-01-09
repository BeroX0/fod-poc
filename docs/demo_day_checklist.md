cat > docs/demo_day_checklist.md <<'MD'

Demo Day Checklist (Offline Golden Demo)
Before the demo (5–10 minutes)

Confirm repo is clean:

git status --porcelain should be empty (or only expected local notes)

Confirm venv is available:

source /home/beros/projects/fod_poc/venv/pc_train/bin/activate

python3 -c "import numpy, ultralytics; print('OK')"

Inputs ready

Two extracted bundle directories exist (outside git):

offline_fod_run_103012/

offline_fod_run_106012/

Optional: verify bundle integrity:

sha256sum -c offline_fod_run_103012.tar.gz.sha256

sha256sum -c offline_fod_run_106012.tar.gz.sha256

Run the demo
export PYTHONNOUSERSITE=1
export VENV_PY="$(python3 -c 'import sys; print(sys.executable)')"

OUT="/tmp/fod_demo_$(date +%Y%m%d_%H%M%S)"

bash tools/run_demo_offline_from_bundles.sh \
  --bundle103 /path/to/offline_fod_run_103012 \
  --bundle106 /path/to/offline_fod_run_106012 \
  --out "$OUT"

What to show

Terminal proof:

index validation PASS: 10/10 and demo_pack.zip: OK

index validation PASS: 3/3 and demo_pack.zip: OK

Open packs:

$OUT/work_run_103012/demo_pack/

$OUT/work_run_106012/demo_pack/

Show a few events:

demo_pack/events/event_000X/clip.mp4

demo_pack/events/event_000X/snapshot_bbox.jpg

After the demo

Keep the produced $OUT/ directory for audit/replay.
