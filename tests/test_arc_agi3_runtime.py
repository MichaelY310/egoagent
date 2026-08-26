from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from arc_agi3_runtime import ArcSession, _SESSIONS, _grid_rle_text, _observation, arc_session_status


class ArcAgi3RuntimeTests(unittest.TestCase):
    def test_exact_grid_observation_tracks_change_and_repeated_states(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = ArcSession(
                "arc-test",
                root,
                "test",
                arcade=SimpleNamespace(),
                environment=SimpleNamespace(),
                run_dir=root / "run",
            )
            state = SimpleNamespace(name="NOT_FINISHED")
            first = SimpleNamespace(
                state=state,
                levels_completed=0,
                win_levels=2,
                available_actions=[1, 6],
                frame=[[[0, 1], [2, 3]]],
                model_dump=lambda mode="json": {"state": "NOT_FINISHED"},
            )

            initial = _observation(session, first, event="start")
            repeated = _observation(session, first, event="action", action={"name": "ACTION1"})

            self.assertEqual(initial["frame_text"], "[0 1]\n[2 3]")
            self.assertEqual(initial["frame_encoding"], "matrix_v1")
            self.assertEqual(initial["available_actions"], ["ACTION1", "ACTION6"])
            self.assertEqual(repeated["changed_cells"], 0)
            self.assertEqual(repeated["no_change_streak"], 1)
            self.assertEqual(repeated["state_visit_count"], 2)
            self.assertEqual(initial["scene_summary"]["background_color"], 0)
            self.assertEqual(repeated["change_summary"]["count"], 0)
            self.assertEqual(len(session.trace_path.read_text(encoding="utf-8").splitlines()), 2)

    def test_exact_row_rle_collapses_repeated_rows_without_hiding_coordinates(self):
        grid = [[3, 3, 3, 0, 0], [3, 3, 3, 0, 0], [7, 7, 7, 7, 7]]
        self.assertEqual(_grid_rle_text(grid), "r0-r1: 3*3 0*2\nr2: 7*5")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = ArcSession("arc-rle", root, "test", SimpleNamespace(), SimpleNamespace(), root / "run")
            state = SimpleNamespace(name="NOT_FINISHED")
            repeated = [[3] * 64 for _ in range(64)]
            frame = SimpleNamespace(state=state, levels_completed=0, win_levels=1, available_actions=[6], frame=[repeated])
            observation = _observation(session, frame, event="start")
            self.assertEqual(observation["frame_encoding"], "row_rle_v1")
            self.assertEqual(observation["frame_text"], "r0-r63: 3*64")
            # The durable audit trace remains lossless even when the model view is compact.
            trace = session.trace_path.read_text(encoding="utf-8")
            self.assertIn('"grids": [[[3, 3, 3', trace)

    def test_change_summary_is_exact_and_groups_regions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            session = ArcSession("arc-test", root, "test", SimpleNamespace(), SimpleNamespace(), root / "run")
            state = SimpleNamespace(name="NOT_FINISHED")
            first = SimpleNamespace(state=state, levels_completed=0, win_levels=1, available_actions=[1], frame=[[[0, 0, 0], [0, 1, 1], [0, 0, 0]]])
            second = SimpleNamespace(state=state, levels_completed=0, win_levels=1, available_actions=[1], frame=[[[0, 2, 0], [0, 2, 2], [0, 0, 0]]])
            _observation(session, first, event="start")
            changed = _observation(session, second, event="action", action={"name": "ACTION1"})
            summary = changed["change_summary"]
            self.assertEqual(summary["count"], 3)
            self.assertEqual(summary["bbox"], [0, 1, 1, 2])
            self.assertEqual(summary["transitions"], {"0->2": 1, "1->2": 2})
            self.assertEqual(summary["regions"], [{"size": 3, "bbox": [0, 1, 1, 2]}])

    def test_single_active_runtime_handle_resolves_an_omitted_or_stale_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = SimpleNamespace(name="NOT_FINISHED")
            frame = SimpleNamespace(state=state, levels_completed=0, win_levels=1, available_actions=[1], frame=[[[0]]])
            environment = SimpleNamespace(observation_space=frame)
            session = ArcSession("arc-only", root, "test", SimpleNamespace(), environment, root / "run")
            _SESSIONS[session.session_id] = session
            try:
                status = arc_session_status("forgotten-id")
                self.assertTrue(status["ok"])
                self.assertEqual(status["session_id"], "arc-only")
                self.assertEqual(status["resolved_session_id_from"], "forgotten-id")
            finally:
                _SESSIONS.pop(session.session_id, None)


if __name__ == "__main__":
    unittest.main()
