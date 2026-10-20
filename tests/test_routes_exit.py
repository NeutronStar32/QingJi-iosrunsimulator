import copy
import tempfile
import unittest
from unittest.mock import patch

from qingji import app
from qingji.route_store import RouteStore, validate_route


class RouteTests(unittest.TestCase):
    def test_curve_and_track_metadata_survive_save_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            store = RouteStore(folder)
            route = {
                "name": "曲线",
                "closed": True,
                "points": [[31, 121], [31.001, 121], [31.001, 121.001]],
            }
            editors = [
                {"mode": "smooth", "control_points": route["points"]},
                {
                    "mode": "track",
                    "track": {"center": [31, 121], "length": 160, "width": 80, "angle": 25},
                },
            ]
            for editor in editors:
                saved = store.save({**route, "editor": editor})
                self.assertEqual(saved["editor"], editor)
                self.assertIn(saved, store.list())
            for editor in (
                {"mode": "other"},
                {
                    "mode": "track",
                    "track": {"center": [True, 121], "length": 160, "width": 80, "angle": 0},
                },
            ):
                with self.assertRaises(ValueError):
                    store.save({**route, "editor": editor})

    def test_save_reload_update_and_delete(self):
        with tempfile.TemporaryDirectory() as folder:
            store = RouteStore(folder)
            data = {
                "name": "操场",
                "closed": True,
                "points": [[31, 121], [31.001, 121], [31.001, 121.001]],
            }
            first = store.save(data)
            self.assertEqual(RouteStore(folder).list()[0], first)
            changed = store.save({**first, "name": "操场改名"})
            self.assertEqual(changed["id"], first["id"])
            self.assertEqual(len(store.list()), 1)
            store.delete(first["id"])
            self.assertEqual(store.list(), [])

    def test_invalid_closed_route_and_coordinates(self):
        for points in (
            [[31, 121], [31, 121]],
            [[31, 121], [31.1, 121]],
            [[True, 121], [31, 121], [32, 122]],
            [[91, 0], [31, 121], [32, 122]],
            [[float("nan"), 0], [31, 121], [32, 122]],
        ):
            with self.subTest(points=points), self.assertRaises(ValueError):
                validate_route({"name": "test", "closed": True, "points": points})

    def test_identifiers_cannot_escape_storage(self):
        with tempfile.TemporaryDirectory() as folder:
            store = RouteStore(folder)
            for bad in ("../app", "..\\app", "", None, "a" * 31):
                with self.assertRaises(ValueError):
                    store.delete(bad)


class ExitTests(unittest.TestCase):
    def setUp(self):
        self.state = copy.deepcopy(app.STATE)
        self.exit = app.EXIT_REQUESTED
        app.EXIT_REQUESTED = False
        app.STATE.update(mode="untouched", logs=[])

    def tearDown(self):
        app.STATE.clear()
        app.STATE.update(self.state)
        app.EXIT_REQUESTED = self.exit

    @patch("qingji.app.command")
    def test_idle_exit_never_contacts_phone(self, command):
        app.operate("shutdown", {})
        self.assertTrue(app.EXIT_REQUESTED)
        command.assert_not_called()

    @patch("qingji.app.detect", return_value="phone-a")
    @patch("qingji.app.command", return_value="")
    def test_simulated_exit_attempts_clear(self, command, _):
        app.STATE.update(mode="simulating", target_device=None)
        app.operate("shutdown", {})
        self.assertEqual(app.STATE["mode"], "cleared")
        self.assertTrue(app.EXIT_REQUESTED)
        self.assertIn("clear", command.call_args.args[0])

    @patch("qingji.app.detect", side_effect=ValueError("手机未连接"))
    def test_failed_restore_keeps_program_running(self, _):
        app.STATE["mode"] = "simulating"
        with self.assertRaises(ValueError):
            app.operate("shutdown", {})
        self.assertFalse(app.EXIT_REQUESTED)

    @patch("qingji.app.command")
    def test_explicit_force_exit_does_not_claim_gps_restored(self, command):
        app.STATE["mode"] = "unknown"
        app.operate("shutdown", {"force": True})
        self.assertTrue(app.EXIT_REQUESTED)
        self.assertEqual(app.STATE["mode"], "unknown")
        command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
