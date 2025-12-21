#!/usr/bin/env python3
"""
Batch summarize per-run events outputs.

Default behavior: read-only aggregation.
- Scans run folders for: events/<roi_id>/metrics.json
- Writes: batch_summary.csv (+ optional batch_summary.json)

Does NOT run inference or event generation unless --run-events is explicitly provided.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

__version__ = "v0.1.0 (2025-12-21)"


def _iter_run_folders(root: Path) -> List[Path]:
    # A run folder must contain detections.jsonl
    out: List[Path] = []
    if not root.exists():
        return out
    if root.is_dir() and (root / "detections.jsonl").exists():
        return [root]
    for p in sorted(root.glob("*")):
        if p.is_dir() and (p / "detections.jsonl").exists():
            out.append(p)
    return out


def _find_metrics(run_folder: Path) -> List[Tuple[str, Path]]:
    """
    Returns list of (roi_id, metrics_path) under run_folder/events/<roi_id>/metrics.json
    """
    res: List[Tuple[str, Path]] = []
    ev_root = run_folder / "events"
    if not ev_root.exists():
        return res
    for roi_dir in sorted(ev_root.glob("*")):
        if not roi_dir.is_dir():
            continue
        mp = roi_dir / "metrics.json"
        if mp.exists():
            res.append((roi_dir.name, mp))
    return res


def _load_json(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


def _flatten_row(run_folder: Path, roi_id: str, m: Dict[str, Any]) -> Dict[str, Any]:
    tool = m.get("tool", {}) or {}
    cfg = m.get("config", {}) or {}
    roi = (cfg.get("roi", {}) or {})

    thresholds = (cfg.get("thresholds", {}) or {})
    modes = (cfg.get("modes", {}) or {})

    row = {
        "run_folder": str(run_folder),
        "video_filename": m.get("video_filename"),
        "roi_id": roi.get("roi_id", roi_id),
        "roi_version": roi.get("roi_version"),
        "lens_mm": roi.get("lens_mm"),
        "duration_s": m.get("duration_s"),
        "fps_used_for_timestamps": (m.get("timestamping", {}) or {}).get("fps_used_for_timestamps"),
        "total_frames": m.get("total_frames"),
        "total_raw_detections": m.get("total_raw_detections"),
        "total_whitelist_detections": m.get("total_whitelist_detections"),
        "total_roi_pass_detections": m.get("total_roi_pass_detections"),
        "total_roi_conf_pass_detections": m.get("total_roi_conf_pass_detections"),
        "total_events": m.get("total_events"),
        "proxy_events_per_minute": m.get("proxy_events_per_minute"),
        "CONF_EVENT": thresholds.get("CONF_EVENT"),
        "DIST_PX": thresholds.get("DIST_PX"),
        "GAP_FRAMES": thresholds.get("GAP_FRAMES"),
        "TRACK_MODE": modes.get("TRACK_MODE"),
        "PERSIST_MODE": modes.get("PERSIST_MODE"),
        "N_CONSEC": modes.get("N_CONSEC"),
        "HITS": modes.get("HITS"),
        "WINDOW_FRAMES": modes.get("WINDOW_FRAMES"),
        "tool_version": tool.get("version"),
        "git_commit": tool.get("git_commit"),
        "git_describe": tool.get("git_describe"),
        "git_is_dirty": tool.get("git_is_dirty"),
    }
    return row


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        # write header-only file for consistency
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            f.write("")
        return

    # stable column order
    fieldnames = list(rows[0].keys())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main() -> None:
    ap = argparse.ArgumentParser(description="Batch summarize events outputs across run folders.")
    ap.add_argument("--root", required=True, help="Root folder containing run_*__* folders OR a single run folder.")
    ap.add_argument("--out", default=None, help="Output directory. Default: <root>/batch_summary/")
    ap.add_argument("--json", action="store_true", help="Also write batch_summary.json")
    args = ap.parse_args()

    root = Path(os.path.expanduser(args.root)).resolve()
    out_dir = Path(os.path.expanduser(args.out)).resolve() if args.out else (root / "batch_summary")

    run_folders = _iter_run_folders(root)
    rows: List[Dict[str, Any]] = []

    for rf in run_folders:
        for roi_id, mp in _find_metrics(rf):
            try:
                m = _load_json(mp)
                rows.append(_flatten_row(rf, roi_id, m))
            except Exception as e:
                rows.append({
                    "run_folder": str(rf),
                    "video_filename": None,
                    "roi_id": roi_id,
                    "error": f"Failed reading {mp}: {e}"
                })

    # stable ordering
    def sort_key(r: Dict[str, Any]) -> Tuple:
        return (str(r.get("video_filename") or ""), str(r.get("roi_id") or ""))

    rows = sorted(rows, key=sort_key)

    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "batch_summary.csv"
    _write_csv(csv_path, rows)
    print("Wrote:", csv_path)

    if args.json:
        json_path = out_dir / "batch_summary.json"
        json_path.write_text(json.dumps({
            "tool": {"name": "batch_summarize_events.py", "version": __version__},
            "root": str(root),
            "runs_found": len(run_folders),
            "rows": rows
        }, indent=2), encoding="utf-8")
        print("Wrote:", json_path)


if __name__ == "__main__":
    main()
