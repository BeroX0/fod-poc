#!/usr/bin/env python3
import json
from pathlib import Path

# Paths
FOD_OUTPUTS = Path.home() / "projects" / "fod_outputs"
OUT_PATH = Path.home() / "evidence_builder" / "input" / "events_all.json"

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
