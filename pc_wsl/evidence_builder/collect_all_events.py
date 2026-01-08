#!/usr/bin/env python3
import json
import os
from pathlib import Path

def _eb_root() -> Path:
    """Resolve Evidence Builder runtime root.
    Preference: $EVIDENCE_DIR (if set), else current working directory.
    """
    env = os.environ.get("EVIDENCE_DIR")
    if env:
        return Path(env).expanduser()
    return Path.cwd()

EB_ROOT = _eb_root()

# Paths
FOD_OUTPUTS = Path.home() / "projects" / "fod_outputs"
OUT_PATH = EB_ROOT / "input" / "events_all.json"
all_events = []

print(f"Scanning: {FOD_OUTPUTS}")

for run_dir in sorted(FOD_OUTPUTS.glob("run_*")):
    if not run_dir.is_dir():
        continue

    events_root = run_dir / "events"
    if not events_root.exists():
        continue

    for roi_dir in events_root.iterdir():
        events_file = roi_dir / "events.json"
        if not events_file.exists():
            continue

        try:
            events = json.load(open(events_file))
            if not isinstance(events, list):
                continue

            for ev in events:
                ev["_run_dir"] = run_dir.name
                ev["_roi_dir"] = roi_dir.name
                all_events.append(ev)

            print(f"✓ {run_dir.name}/{roi_dir.name}: {len(events)} events")

        except Exception as e:
            print(f"✗ ERROR reading {events_file}: {e}")

print("-" * 40)
print(f"Total events collected: {len(all_events)}")

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
with open(OUT_PATH, "w") as f:
    json.dump(all_events, f, indent=2)

print(f"Saved → {OUT_PATH}")
