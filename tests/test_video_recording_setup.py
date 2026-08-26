from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import reset_video_demo


ROOT = Path(__file__).resolve().parents[1]


class VideoRecordingResetTests(unittest.TestCase):
    def test_purge_removes_only_fixture_review_transactions(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as directory:
            root = Path(directory)
            target = root / "video_demo_repo"
            target.mkdir()
            outside = root / "real_project" / "app.py"
            ledger = root / "change-transactions.json"
            ledger.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "next_index": 3,
                        "changes": [
                            {"id": "demo", "file_path": str(target / "garden.py")},
                            {"id": "keep", "file_path": str(outside)},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(reset_video_demo, "TARGET", target), mock.patch.object(
                reset_video_demo, "CHANGE_LEDGER", ledger
            ):
                removed = reset_video_demo.purge_recording_change_transactions()

            payload = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(removed, 1)
            self.assertEqual([change["id"] for change in payload["changes"]], ["keep"])
            self.assertEqual(payload["next_index"], 3)


if __name__ == "__main__":
    unittest.main()
