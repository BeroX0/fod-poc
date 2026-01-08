#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import textwrap
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


REQUIRED_EVENT_FIELDS = ("event_id", "video_filename", "start_time_s", "end_time_s", "representative_bbox")


@dataclass
class RunResult:
    ok: bool
    summary: str
    demo_zip: Optional[Path] = None
    demo_zip_sha256: Optional[Path] = None
    events_json: Optional[Path] = None
    input_mp4: Optional[Path] = None


def die(msg: str, code: int = 2) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def run_cmd(cmd: List[str], env: Dict[str, str], cwd: Optional[Path] = None) -> Tuple[int, str]:
    p = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return p.returncode, p.stdout


def which_or_die(tool: str) -> None:
    if shutil.which(tool) is None:
        die(f"Missing required tool on PATH: {tool}. Install it and retry.")


def repo_root_from_this_file() -> Path:
    return Path(__file__).resolve().parents[1]


def default_evidence_dir() -> Path:
    return Path(os.environ.get("EVIDENCE_DIR", str(Path.home() / "evidence_builder"))).resolve()


def ensure_dirs(evidence_dir: Path) -> Tuple[Path, Path]:
    input_dir = evidence_dir / "input"
    output_dir = evidence_dir / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    return input_dir, output_dir


def safe_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def load_events(events_path: Path) -> List[Dict[str, Any]]:
    try:
        data = json.loads(events_path.read_text(encoding="utf-8"))
    except Exception as e:
        die(f"Failed to parse JSON: {events_path} ({e})")

    if not isinstance(data, list):
        die(f"events.json must be a JSON array. Found: {type(data).__name__}")

    for i, ev in enumerate(data):
        if not isinstance(ev, dict):
            die(f"events.json element #{i} must be an object. Found: {type(ev).__name__}")
        for k in REQUIRED_EVENT_FIELDS:
            if k not in ev:
                die(f"events.json element #{i} missing required field: {k}")
        bbox = ev.get("representative_bbox")
        if not (isinstance(bbox, list) and len(bbox) == 4 and all(isinstance(x, (int, float)) for x in bbox)):
            die(f"events.json element #{i} has invalid representative_bbox (expected [x1,y1,x2,y2] numeric).")
    return data


def maybe_fix_video_filename(events: List[Dict[str, Any]], mp4_basename: str, enable_fix: bool) -> bool:
    changed = False
    for ev in events:
        if ev.get("video_filename") != mp4_basename:
            if not enable_fix:
                die(
                    f"events.json video_filename mismatch: found '{ev.get('video_filename')}', "
                    f"expected '{mp4_basename}'. Re-export/correct or use --fix-video-filename."
                )
            ev["video_filename"] = mp4_basename
            changed = True
    return changed


def write_events(events_path: Path, events: List[Dict[str, Any]]) -> None:
    events_path.write_text(json.dumps(events, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def unzip_bundle(bundle_zip: Path, tmp_dir: Path) -> Tuple[Path, Path]:
    with zipfile.ZipFile(bundle_zip, "r") as z:
        z.extractall(tmp_dir)

    mp4_candidates = list(tmp_dir.rglob("*.mp4"))
    json_candidates = [p for p in tmp_dir.rglob("*.json") if p.name.lower() == "events.json"]

    if len(mp4_candidates) != 1:
        die(f"Bundle must contain exactly 1 .mp4. Found: {len(mp4_candidates)}")
    if len(json_candidates) != 1:
        die(f"Bundle must contain exactly 1 events.json. Found: {len(json_candidates)}")

    return mp4_candidates[0], json_candidates[0]


def run_evidence_builder(repo_root: Path, evidence_dir: Path, env: Dict[str, str]) -> Tuple[bool, str]:
    runner = repo_root / "pc_wsl" / "evidence_builder" / "run_demo_pack_wsl.sh"
    if not runner.is_file():
        die(f"Missing EB runner script: {runner}")

    eb_env = dict(env)
    eb_env["EVIDENCE_DIR"] = str(evidence_dir)

    rc, out = run_cmd(["bash", str(runner)], env=eb_env, cwd=repo_root)
    ok = (rc == 0)
    return ok, out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent(
            """\
            Single entrypoint runner for all 4 PoC profiles.

            Examples:
              Profile 1 (Offline COCO):
                python3 tools/run_profile.py --profile 1 --mp4 /path/to/video.mp4

              Profile 2 (Offline FOD):
                python3 tools/run_profile.py --profile 2 --mp4 /path/to/video.mp4 --model /path/to/fod.pt

              Profile 3/4 (Live post-transfer):
                python3 tools/run_profile.py --profile 3 --mp4 /path/to/video.mp4 --events-json /path/to/events.json --fix-video-filename
                python3 tools/run_profile.py --profile 4 --bundle /path/to/live_bundle.zip --fix-video-filename
            """
        ),
    )
    p.add_argument("--profile", type=int, choices=[1, 2, 3, 4], required=True)
    p.add_argument("--evidence-dir", type=Path, default=default_evidence_dir())
    p.add_argument("--mp4", type=Path, default=None)
    p.add_argument("--events-json", type=Path, default=None)
    p.add_argument("--bundle", type=Path, default=None, help="Zip containing exactly: 1x .mp4 and 1x events.json")
    p.add_argument("--model", type=Path, default=None, help="Optional override model path. Defaults: Profile 1 -> /home/beros/projects/fod_poc/models/yolov8n.pt, Profile 2 -> /home/beros/projects/fod_poc/models/fod_1class_best.pt")
    p.add_argument("--roi", type=Path, default=None, help="Optional ROI argument passed to offline scripts if supported.")
    p.add_argument("--fix-video-filename", action="store_true", help="Auto-fix events.json video_filename to match MP4 basename.")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = repo_root_from_this_file()

    which_or_die("ffmpeg")
    which_or_die("ffprobe")

    evidence_dir = args.evidence_dir.resolve()
    input_dir, _ = ensure_dirs(evidence_dir)

    env = dict(os.environ)
    env["PYTHONNOUSERSITE"] = "1"

    tmp_dir = evidence_dir / "tmp_profile_runner"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    src_mp4: Optional[Path] = None
    src_events: Optional[Path] = None

    if args.bundle:
        if args.mp4 or args.events_json:
            die("Use either --bundle OR (--mp4 + --events-json), not both.")
        bundle_zip = args.bundle.resolve()
        if not bundle_zip.is_file():
            die(f"Bundle zip not found: {bundle_zip}")
        src_mp4, src_events = unzip_bundle(bundle_zip, tmp_dir)

    if src_mp4 is None:
        if args.mp4 is None:
            die("--mp4 is required when --bundle is not provided.")
        src_mp4 = args.mp4.resolve()
        if not src_mp4.is_file():
            die(f"MP4 not found: {src_mp4}")

    mp4_basename = src_mp4.name
    dst_mp4 = (input_dir / mp4_basename).resolve()

    if dst_mp4 != src_mp4:
        safe_copy(src_mp4, dst_mp4)

    events_out = (input_dir / "events.json").resolve()

    if args.profile in (1, 2):
        offline_dir = repo_root / "pc_wsl" / "offline"
        script = offline_dir / ("offline_detect_run_coco.py" if args.profile == 1 else "offline_detect_run.py")

        if not script.is_file():
            die(f"Offline script not found: {script}")

        cmd = [sys.executable, str(script), "--video", str(dst_mp4)]
        if args.profile == 1:
            model_path = (args.model.resolve() if args.model is not None else Path("/home/beros/projects/fod_poc/models/yolov8n.pt"))
        else:
            model_path = (args.model.resolve() if args.model is not None else Path("/home/beros/projects/fod_poc/models/fod_1class_best.pt"))
        if not model_path.is_file():
            die(f"Model not found: {model_path}")
        cmd += ["--model", str(model_path)]
        cmd += ["--events_out", str(events_out)]
        if args.roi is not None:
            cmd += ["--roi", str(args.roi.resolve())]

        if args.dry_run:
            print("DRY RUN: would execute:")
            print(" ".join(cmd))
        else:
            rc, out = run_cmd(cmd, env=env, cwd=repo_root)
            print(out)
            if rc != 0:
                die(f"Offline event generation failed (rc={rc}). See output above.")

    else:
        if src_events is None:
            if args.events_json is None:
                die("Profile 3/4 requires --events-json when not using --bundle.")
            src_events = args.events_json.resolve()
            if not src_events.is_file():
                die(f"events.json not found: {src_events}")
        safe_copy(src_events, events_out)

    events = load_events(events_out)
    changed = maybe_fix_video_filename(events, mp4_basename, enable_fix=args.fix_video_filename)
    if changed:
        write_events(events_out, events)
        print(f"NOTE: events.json video_filename normalized to '{mp4_basename}'")

    if args.dry_run:
        print("DRY RUN: would run Evidence Builder.")
        return 0

    ok, eb_out = run_evidence_builder(repo_root, evidence_dir, env)
    print(eb_out)

    demo_zip = (evidence_dir / "demo_pack.zip").resolve()
    demo_sha = (evidence_dir / "demo_pack.zip.sha256").resolve()

    if not demo_zip.is_file():
        die(f"Expected demo_pack.zip not found: {demo_zip}")
    if not demo_sha.is_file():
        die(f"Expected demo_pack.zip.sha256 not found: {demo_sha}")

    print("\n=== PROFILE RUN SUMMARY ===")
    print(f"profile: {args.profile}")
    print(f"evidence_dir: {evidence_dir}")
    print(f"input mp4: {dst_mp4}")
    print(f"events.json: {events_out}")
    print(f"demo_pack.zip: {demo_zip}")
    print(f"demo_pack.zip.sha256: {demo_sha}")
    print(f"status: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
