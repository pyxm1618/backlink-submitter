import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_cold_preflight_is_readonly_and_recovers_canary_state():
    assert importlib.util.find_spec("backlink_submitter.cli") is not None, "Cold recovery entrypoint missing"
    run = subprocess.run(
        [sys.executable, "-m", "backlink_submitter.cli", "preflight", "--project", "wyrplay"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    assert run.returncode == 0, run.stderr
    report = json.loads(run.stdout)
    assert report["manifest_version"] == "3.0-final"
    assert report["submit"] == report["sheet_writes"] == report["attempt_increment"] == 0
    assert report["functional_canary"] == "FUNCTIONAL CANARY NOT YET VERIFIED"
    assert report["ready_for_controlled_rollout"] is False
