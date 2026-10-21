import bisect
import time
import unittest

from qingji.motion import RunMotion
from qingji.running import RunController, RunPlan, distance
from tests.test_running import FakeSession, data

SETTINGS = {
    "laps": 3,
    "jitter": 0.7,
    "width": 3,
    "lanes": 1,
    "inside": True,
    "seed": 23,
    "anchor": None,
}


def plan(laps=7, **extra):
    return RunPlan(
        {
            **data(laps=laps),
            "calibration_enabled": False,
            "trajectory": dict(SETTINGS),
            "trajectory_offset_m": 2,
            **extra,
        }
    )


class TrajectoryTests(unittest.TestCase):
    def test_variable_laps_distance_continuity_and_finite_endpoint(self):
        p = plan()
        path = p.trajectory
        self.assertEqual(p.trajectory_offset, 0)
        first = path.point_at(15)
        p.prepare_distance(10000)
        self.assertEqual(len(path.ends), 8)
        self.assertEqual(p.total, path.ends[-1])
        self.assertLess(distance(first, path.point_at(15)), 1e-5)
        self.assertGreater(len({round(b - a, 2) for a, b in zip(path.ends, path.ends[1:])}), 3)
        for boundary in path.ends[1:-1]:
            self.assertLess(
                distance(p.point_at(boundary - 0.001), p.point_at(boundary + 0.001)), 0.01
            )
            self.assertEqual(
                p.completed_laps(boundary), bisect.bisect_right(path.ends, boundary) - 1
            )
        m = RunMotion(p, 1)
        meters, seconds, _ = m.advance(p.total - 0.1, 100, p.speed, 1)
        self.assertEqual(meters, p.total)
        self.assertLess(seconds, 101)
        self.assertEqual(p.point_at(meters), p.point_at(meters + 100))

    def test_infinite_continues_new_batches_with_bounded_coordinate_cache(self):
        p = plan(laps=0)
        original = p.point_at(15)
        p.prepare_distance(15000)
        self.assertIsNone(p.total)
        self.assertGreater(p.lap_index(15000), 30)
        self.assertLessEqual(len(p.trajectory.cache), 3)
        self.assertGreater(len(p.trajectory.meta), 10)
        self.assertLess(distance(original, p.point_at(15)), 1e-5)

    def test_preview_horizon_does_not_change_when_task_has_fewer_laps(self):
        short, long = plan(laps=1), plan(laps=7)
        for meters in (0, 15, 100, short.total):
            self.assertLess(distance(short.point_at(meters), long.point_at(meters)), 1e-5)

    def test_generated_path_pause_holds_exact_position(self):
        runner = RunController(FakeSession)
        try:
            runner.start(plan(laps=0), "fake")
            time.sleep(0.6)
            runner.pause()
            before = runner.snapshot()
            time.sleep(0.6)
            after = runner.snapshot()
            self.assertEqual(before["position"], after["position"])
            self.assertEqual(before["distance_m"], after["distance_m"])
            self.assertEqual(after["trajectory_mode"], "generated")
            self.assertEqual(runner.session.points[-1], after["device_position"])
        finally:
            runner.close()

    def test_invalid_settings_rejected(self):
        for key, value in (
            ("seed", -1),
            ("seed", True),
            ("laps", 11),
            ("jitter", float("nan")),
            ("anchor", [999, 0]),
            ("inside", 1),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                plan(trajectory={**SETTINGS, key: value})
        with self.assertRaises(ValueError):
            plan(route=data(closed=False)["route"], laps=1)
