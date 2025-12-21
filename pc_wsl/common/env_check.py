#!/usr/bin/env python3
import os
from pathlib import Path

def main():
    exp = os.environ.get("FOD_EXPORT_ROOT", "")
    out = os.environ.get("FOD_OUT_ROOT", "")

    print("FOD_EXPORT_ROOT:", exp or "(not set)")
    print("FOD_OUT_ROOT:", out or "(not set)")

    if exp:
        videos = Path(os.path.expandvars(exp)).expanduser() / "videos"
        print("Expected videos dir:", videos)
        if videos.exists():
            runs = sorted(videos.glob("run_*.mp4"))
            print("Found run_*.mp4:", len(runs))
            if runs:
                print("Example:", runs[0].name)
        else:
            print("MISSING videos dir")

if __name__ == "__main__":
    main()
