import time
import unittest
from unittest.mock import patch

from qingji.motion import RunMotion
from qingji.running import RunController, RunPlan, distance
from tests.fixtures import POINTS, PROFILE
from tests.test_running import FakeSession, data


def plan(**overrides):
    return RunPlan(
        {**data(laps=0), "pace_variation_seconds": 15, "trajectory_offset_m": 0.8, **overrides}
    )


class MotionTests(unittest.TestCase):
    def test_lap_targets_are_stable_bounded_and_vary(self):
        p = plan()
        m = RunMotion(p, seed=42)
        values = [m.lap_pace(p.length * i + 1) for i in range(20)]
        self.assertGreater(len(set(values)), 10)
        self.assertTrue(all(345 <= v <= 375 for v in values))
        self.assertEqual(m.lap_pace(1), m.lap_pace(p.length - 1))
        for pace in (60, 1800):
            p = plan(pace_seconds=pace, pace_variation_seconds=120)
            m = RunMotion(p, 42)
            self.assertTrue(all(60 <= m.lap_pace(p.length * i) <= 1800 for i in range(20)))

    def test_disabled_effects_match_fixed_route_and_time(self):
        p = plan(pace_variation_seconds=0, trajectory_offset_m=0)
        m = RunMotion(p, 42)
        meters, seconds, speed = m.advance(0, 0, p.speed, 1.5)
        self.assertAlmostEqual(meters, 1.5 * p.speed)
        self.assertAlmostEqual(seconds, 1.5)
        self.assertEqual(m.point_at(meters, seconds), p.point_at(meters))

    def test_speed_smoothly_converges_after_lap_boundary(self):
        p = plan()
        m = RunMotion(p, 42)
        old = 1000 / m.lap_pace(0)
        goal = 1000 / m.lap_pace(p.length)
        _, _, speed = m.advance(p.length, 100, old, 0.5)
        self.assertLess(abs(speed - old), abs(goal - old))
        self.assertGreaterEqual(speed, min(old, goal))
        self.assertLessEqual(speed, max(old, goal))

    def test_offset_bounded_continuous_after_calibration_and_zero_at_end(self):
        with patch("qingji.calibration.configured_profiles", return_value=(PROFILE,)):
            p = plan(
                route={"name": "校准", "closed": True, "points": POINTS},
                trajectory_offset_m=3,
                laps=2,
            )
        self.assertTrue(p.calibration.active)
        m = RunMotion(p, 42)
        for meters in (1, p.length - 0.001, p.length, p.length + 0.001, p.total - 1):
            for seconds in (0, 10, 50, 1000):
                actual = p.calibration.apply(m.point_at(meters, seconds))
                nominal = p.calibration.apply(p.point_at(meters))
                self.assertLessEqual(distance(actual, nominal), 3.001)
        self.assertLess(distance(m.point_at(0, 0), p.points[0]), 0.000001)
        self.assertLess(distance(m.point_at(p.total, 1000), p.points[-1]), 0.00001)
        before = m.point_at(p.length - 0.001, 100)
        after = m.point_at(p.length + 0.001, 100.001)
        self.assertLess(distance(before, after), 0.02)

    def test_invalid_options_fail_before_start(self):
        for key in ("pace_variation_seconds", "trajectory_offset_m"):
            for value in (True, None, -1, float("nan"), float("inf"), 121):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    plan(**{key: value})

    def test_random_pause_freezes_point_time_and_speed(self):
        runner = RunController(FakeSession)
        try:
            runner.start(plan(), "fake")
            time.sleep(0.6)
            runner.pause()
            before = runner.snapshot()
            count = len(runner.session.points)
            time.sleep(0.65)
            after = runner.snapshot()
            for key in (
                "position",
                "distance_m",
                "moving_seconds",
                "current_pace_seconds",
                "lap_pace_seconds",
            ):
                self.assertEqual(before[key], after[key])
            self.assertGreater(len(runner.session.points), count)
            self.assertEqual(runner.session.points[-1], after["device_position"])
        finally:
            runner.close()


if __name__ == "__main__":
    unittest.main()
