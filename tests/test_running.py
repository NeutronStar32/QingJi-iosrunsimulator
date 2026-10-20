import time
import unittest

from qingji.running import RunController, RunPlan, distance


def data(closed=True, laps=1, pace=360):
    return {
        "route": {
            "name": "测试",
            "closed": closed,
            "points": [[31, 121], [31.001, 121], [31.001, 121.001]],
        },
        "pace_seconds": pace,
        "laps": laps,
    }


class PlanTests(unittest.TestCase):
    def test_distance_and_loop_boundaries(self):
        plan = RunPlan(data(laps=2))
        self.assertGreater(plan.length, 300)
        self.assertLess(plan.length, 400)
        self.assertLess(distance(plan.point_at(plan.length), plan.points[0]), 0.001)
        self.assertEqual(plan.point_at(plan.total), plan.points[-1])
        self.assertAlmostEqual(plan.speed, 1000 / 360)

    def test_open_path_ends_at_endpoint_and_cannot_loop(self):
        plan = RunPlan(data(closed=False))
        self.assertEqual(plan.point_at(plan.total), [31.001, 121.001])
        for laps in (0, 2):
            with self.assertRaises(ValueError):
                RunPlan(data(closed=False, laps=laps))

    def test_invalid_parameters_rejected_before_device_access(self):
        for bad in (
            {},
            {"route": []},
            data(pace=True),
            data(pace=0),
            data(pace=float("nan")),
            data(laps=True),
            data(laps=-1),
            data(pace=1801),
        ):
            with self.subTest(data=bad), self.assertRaises(ValueError):
                RunPlan(bad)

    def test_dateline_interpolation_uses_short_path(self):
        plan = RunPlan(
            {
                "route": {"name": "测试", "closed": False, "points": [[0, 179.999], [0, -179.999]]},
                "pace_seconds": 360,
                "laps": 1,
            }
        )
        self.assertAlmostEqual(abs(plan.point_at(plan.length / 2)[1]), 180, places=6)


class FakeSession:
    def __init__(self, udid):
        self.points = []
        self.closed = False
        self.fail = False

    def set(self, point):
        if self.fail:
            raise ValueError("模拟断线")
        self.points.append(point)

    def close(self):
        self.closed = True


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.runner = RunController(session_factory=FakeSession)

    def tearDown(self):
        self.runner.close()

    def wait(self, condition, timeout=4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(0.02)
        self.fail("状态未及时到达")

    def test_pause_resume_and_stop_keep_position(self):
        self.runner.start(RunPlan(data()), "fake")
        self.wait(lambda: self.runner.snapshot()["distance_m"] > 0)
        self.runner.pause()
        paused = self.runner.snapshot()
        count = len(self.runner.session.points)
        time.sleep(0.65)
        self.assertGreater(len(self.runner.session.points), count)
        self.assertEqual(self.runner.session.points[-1], paused["position"])
        self.assertEqual(self.runner.snapshot()["distance_m"], paused["distance_m"])
        self.assertEqual(self.runner.snapshot()["moving_seconds"], paused["moving_seconds"])
        self.runner.resume()
        self.wait(lambda: self.runner.snapshot()["distance_m"] > paused["distance_m"])
        self.runner.stop()
        point = self.runner.snapshot()["position"]
        count = len(self.runner.session.points)
        time.sleep(0.55)
        self.assertEqual(self.runner.snapshot()["position"], point)
        self.assertGreater(len(self.runner.session.points), count)
        self.assertEqual(self.runner.session.points[-1], point)
        self.assertTrue(self.runner.snapshot()["connected"])

    def test_single_point_refresh_and_close_stops_all_updates(self):
        self.runner.hold([31, 121], "fake")
        session = self.runner.session
        self.wait(lambda: len(session.points) >= 3)
        self.assertTrue(all(p == [31, 121] for p in session.points))
        self.assertTrue(self.runner.snapshot()["holding"])
        self.assertEqual(self.runner.snapshot()["moving_seconds"], 0)
        self.runner.close()
        count = len(session.points)
        time.sleep(0.65)
        self.assertEqual(len(session.points), count)
        self.assertTrue(session.closed)
        self.assertFalse(self.runner.snapshot()["connected"])

    def test_replacing_point_never_resends_previous_position(self):
        self.runner.hold([31, 121], "fake")
        old = self.runner.session
        self.runner.hold([32, 122], "fake")
        count = len(old.points)
        self.wait(lambda: len(self.runner.session.points) >= 2)
        self.assertTrue(old.closed)
        self.assertEqual(len(old.points), count)
        self.assertTrue(all(p == [32, 122] for p in self.runner.session.points))

    def test_hold_connection_error_is_visible_and_updates_stop(self):
        self.runner.hold([31, 121], "fake")
        session = self.runner.session
        session.fail = True
        self.wait(lambda: self.runner.snapshot()["status"] == "error")
        self.assertIn("持续定位已中断", self.runner.snapshot()["message"])
        count = len(session.points)
        time.sleep(0.65)
        self.assertEqual(len(session.points), count)

    def test_initial_hold_failure_closes_session_and_starts_no_loop(self):
        session = FakeSession("fake")
        session.fail = True
        self.runner.session_factory = lambda _: session
        with self.assertRaises(ValueError):
            self.runner.hold([31, 121], "fake")
        self.assertTrue(session.closed)
        self.assertFalse(self.runner.snapshot()["connected"])

    def test_completion_finishes_exactly_at_final_lap(self):
        args = data(laps=2, pace=60)
        args["route"]["points"] = [[0, 0], [0.00002, 0], [0.00002, 0.00002]]
        plan = RunPlan(args)
        self.runner.start(plan, "fake")
        self.wait(lambda: self.runner.snapshot()["status"] == "completed")
        snapshot = self.runner.snapshot()
        self.assertAlmostEqual(snapshot["distance_m"], plan.total)
        self.assertEqual(snapshot["completed_laps"], 2)
        self.assertEqual(snapshot["current_lap"], 2)
        self.assertEqual(snapshot["position"], [0, 0])
        count = len(self.runner.session.points)
        self.wait(lambda: len(self.runner.session.points) > count)
        self.assertEqual(self.runner.snapshot()["distance_m"], snapshot["distance_m"])
        self.assertEqual(self.runner.snapshot()["moving_seconds"], snapshot["moving_seconds"])
        self.assertEqual(self.runner.session.points[-1], [0, 0])

    def test_failed_update_never_increments_distance(self):
        self.runner.start(RunPlan(data()), "fake")
        self.runner.session.fail = True
        self.wait(lambda: self.runner.snapshot()["status"] == "error")
        self.assertEqual(self.runner.snapshot()["distance_m"], 0)
        self.assertEqual(self.runner.snapshot()["moving_seconds"], 0)

    def test_infinite_route_does_not_complete_at_first_lap(self):
        args = data(laps=0, pace=60)
        args["route"]["points"] = [[0, 0], [0.00002, 0], [0.00002, 0.00002]]
        self.runner.start(RunPlan(args), "fake")
        self.wait(lambda: self.runner.snapshot()["completed_laps"] >= 1)
        self.assertEqual(self.runner.snapshot()["status"], "running")


if __name__ == "__main__":
    unittest.main()
