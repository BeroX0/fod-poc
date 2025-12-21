import json
import shutil
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "pc_wsl" / "events" / "events_from_detections.py"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "detections_min.jsonl"

class TestEventsRunnerSmoke(unittest.TestCase):
    def test_events_runner_smoke(self):
        self.assertTrue(RUNNER.exists(), f"Missing runner: {RUNNER}")
        self.assertTrue(FIXTURE.exists(), f"Missing fixture: {FIXTURE}")

        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "run_sample__test"
            run_dir.mkdir(parents=True, exist_ok=True)

            # events_from_detections.py expects detections.jsonl in run folder
            shutil.copy2(FIXTURE, run_dir / "detections.jsonl")

            # Minimal ROI: full-frame polygon for 1080p
            roi = {
                "roi_id": "roi_test_fullframe_v1",
                "image_width": 1920,
                "image_height": 1080,
                "polygon": [[0,0],[1919,0],[1919,1079],[0,1079]],
                "provenance": {"note": "synthetic test ROI"}
            }
            roi_path = run_dir / "roi_test_fullframe_v1.json"
            roi_path.write_text(json.dumps(roi), encoding="utf-8")

            cmd = [
                sys.executable, str(RUNNER),
                "--run-folder", str(run_dir),
                "--roi", str(roi_path),
                "--conf", "0.10",
                "--dist-px", "99999",
                "--gap-frames", "0",
                "--track-mode", "any",
                "--persist-mode", "consecutive",
                "--n-consec", "1",
            ]

            r = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(
                r.returncode, 0,
                f"Runner failed:\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
            )

            out_dir = run_dir / "events" / "roi_test_fullframe_v1"
            self.assertTrue(out_dir.exists(), f"Missing output dir: {out_dir}")
            self.assertTrue((out_dir / "events.csv").exists(), "Missing events.csv")
            self.assertTrue((out_dir / "metrics.json").exists(), "Missing metrics.json")

if __name__ == "__main__":
    unittest.main()
