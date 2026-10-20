import copy
import time
import unittest
from unittest.mock import patch

from qingji import app
from qingji.calibration import METERS_LAT, select
from qingji.running import RunController, RunPlan, distance
from tests.fixtures import POINTS, PROFILE
from tests.test_running import FakeSession


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        patcher = patch("qingji.calibration.configured_profiles", return_value=(PROFILE,))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_affine_profile_and_inverse(self):
        calibration = select(POINTS)
        self.assertTrue(calibration.active)
        for point in POINTS:
            expected = [
                PROFILE.latitude
                + (point[0] - PROFILE.latitude) * PROFILE.scale_north
                + PROFILE.shift_north / METERS_LAT,
                PROFILE.longitude
                + (point[1] - PROFILE.longitude) * PROFILE.scale_east
                + PROFILE.shift_east / PROFILE.meters_lon,
            ]
            self.assertLess(distance(calibration.apply(point), expected), 0.00001)
            self.assertLess(distance(calibration.unapply(expected), point), 0.00001)

    def test_disabled_remote_and_cross_boundary_routes_use_original(self):
        remote = [PROFILE.latitude + (PROFILE.radius_m + 20) / METERS_LAT, PROFILE.longitude]
        for points, enabled in ((POINTS, False), ([remote], True), (POINTS + [remote], True)):
            calibration = select(points, enabled)
            self.assertFalse(calibration.active)
            self.assertEqual([calibration.apply(p) for p in points], points)

    def test_invalid_switch_does_not_contact_phone(self):
        with patch("qingji.app.detect") as detect:
            for invalid in ("true", 1, None):
                with self.assertRaises(ValueError):
                    app.operate(
                        "set",
                        {
                            "latitude": POINTS[0][0],
                            "longitude": POINTS[0][1],
                            "calibration_enabled": invalid,
                        },
                    )
            detect.assert_not_called()

    def test_route_storage_unchanged_and_pace_uses_sent_distance(self):
        source = {
            "route": {"name": "操场", "closed": True, "points": copy.deepcopy(POINTS)},
            "pace_seconds": 360,
            "laps": 2,
        }
        original = copy.deepcopy(source)
        plan = RunPlan(source)
        self.assertEqual(source, original)
        self.assertEqual(plan.route["points"], POINTS)
        sent = [plan.calibration.apply(p) for p in POINTS]
        expected = sum(distance(a, b) for a, b in zip(sent, sent[1:] + sent[:1]))
        self.assertAlmostEqual(plan.length, expected)
        self.assertAlmostEqual(plan.total / plan.speed, expected * 2 * 360 / 1000)
        midpoint = plan.point_at(plan.cumulative[1] / 2)
        self.assertLess(
            distance(
                plan.calibration.apply(midpoint),
                [(sent[0][0] + sent[1][0]) / 2, (sent[0][1] + sent[1][1]) / 2],
            ),
            0.001,
        )
        self.assertEqual(plan.point_at(plan.total), POINTS[0])

    def test_static_keepalive_transforms_once_and_preserves_map_target(self):
        runner = RunController(FakeSession)
        try:
            calibration = select(POINTS)
            runner.hold(POINTS[0], "fake", calibration)
            session = runner.session
            time.sleep(0.65)
            self.assertGreaterEqual(len(session.points), 2)
            self.assertTrue(all(p == calibration.apply(POINTS[0]) for p in session.points))
            self.assertEqual(runner.snapshot()["position"], POINTS[0])
            runner.close()
            count = len(session.points)
            time.sleep(0.6)
            self.assertEqual(len(session.points), count)
        finally:
            runner.close()

    def test_api_uses_map_target_and_restore_clears_without_compensation(self):
        saved = copy.deepcopy(app.STATE)
        runner = RunController(FakeSession)
        try:
            app.STATE.update(mode="untouched", target_device=None, logs=[])
            with (
                patch.object(app, "RUNNER", runner),
                patch("qingji.app.detect", return_value="fake"),
                patch("qingji.app.command") as command,
            ):
                app.operate("set", {"latitude": POINTS[0][0], "longitude": POINTS[0][1]})
                self.assertEqual(app.state_snapshot()["target"], POINTS[0])
                self.assertEqual(runner.session.points[-1], select(POINTS).apply(POINTS[0]))
                session = runner.session
                app.operate("clear", {})
                self.assertTrue(session.closed)
                self.assertEqual(app.state_snapshot()["mode"], "cleared")
                self.assertIsNone(app.state_snapshot()["target"])
                command.assert_called_once_with(
                    ["developer", "dvt", "simulate-location", "clear", "--udid", "fake"], timeout=90
                )
        finally:
            runner.close()
            app.STATE.clear()
            app.STATE.update(saved)

    def test_running_and_paused_points_apply_the_same_frozen_transform(self):
        plan = RunPlan(
            {"route": {"name": "操场", "closed": True, "points": POINTS}, "pace_seconds": 360}
        )
        runner = RunController(FakeSession)
        try:
            runner.start(plan, "fake")
            time.sleep(0.6)
            runner.pause()
            paused = runner.snapshot()
            count = len(runner.session.points)
            time.sleep(0.65)
            current = runner.snapshot()
            self.assertEqual(current["position"], paused["position"])
            self.assertEqual(current["distance_m"], paused["distance_m"])
            self.assertGreater(len(runner.session.points), count)
            self.assertEqual(runner.session.points[-1], plan.calibration.apply(paused["position"]))
            self.assertTrue(current["calibration"]["active"])
        finally:
            runner.close()


if __name__ == "__main__":
    unittest.main()
