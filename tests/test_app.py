"""Regression checks for device selection and truthful location status."""

import copy
import json
import unittest
from unittest.mock import patch

from qingji import app
from qingji.calibration import select as select_calibration


class LocationTests(unittest.TestCase):
    def setUp(self):
        self.saved = copy.deepcopy(app.STATE)
        app.STATE.clear()
        app.STATE.update(mode="untouched", target=None, device=None, message="未修改", logs=[])

    def tearDown(self):
        app.STATE.clear()
        app.STATE.update(self.saved)

    def test_initial_state_does_not_claim_a_real_coordinate(self):
        self.assertEqual(app.STATE["mode"], "untouched")
        self.assertIsNone(app.STATE["target"])

    def test_coordinates_reject_missing_nonfinite_and_out_of_range(self):
        for value in (None, "", " ", True, "NaN", "inf", "91", "abc"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                app.coordinates({"latitude": value, "longitude": 0})
        with self.assertRaises(ValueError):
            app.coordinates({"latitude": 0, "longitude": 181})
        self.assertEqual(app.coordinates({"latitude": "0", "longitude": "-180"}), [0, -180])

    @patch("qingji.app.command")
    def test_detection_never_sets_location(self, command):
        command.return_value = json.dumps([{"Identifier": "phone-a", "ProductVersion": "27.0"}])
        app.operate("detect", {})
        self.assertEqual(app.STATE["mode"], "untouched")
        command.assert_called_once_with(["usbmux", "list", "--usb"])

    @patch("qingji.app.command")
    def test_zero_or_multiple_devices_cannot_be_modified(self, command):
        for devices in ([], [{"Identifier": "a"}, {"Identifier": "b"}]):
            command.return_value = json.dumps(devices)
            with self.assertRaises(ValueError):
                app.operate("set", {"latitude": 1, "longitude": 2})
            self.assertEqual(app.STATE["mode"], "untouched")

    @patch("qingji.app.command")
    def test_invalid_coordinates_do_not_touch_device(self, command):
        with self.assertRaises(ValueError):
            app.operate("set", {"latitude": "", "longitude": ""})
        command.assert_not_called()

    @patch("qingji.app.detect", return_value="phone-a")
    @patch("qingji.app.RUNNER.hold")
    def test_only_acknowledged_hold_marks_simulation_active(self, hold, _):
        hold.side_effect = lambda *_, **kw: self.assertEqual(app.STATE["mode"], "unknown")
        app.operate("set", {"latitude": 30, "longitude": 120})
        self.assertEqual(app.STATE["mode"], "simulating")
        self.assertEqual(app.STATE["target"], [30, 120])
        hold.assert_called_once_with(
            [30, 120], "phone-a", calibration=select_calibration([[30, 120]])
        )

    @patch("qingji.app.detect", return_value="phone-a")
    @patch("qingji.app.RUNNER.hold", side_effect=ValueError("not acknowledged"))
    def test_hold_failure_never_claims_position_is_active(self, hold, _):
        with self.assertRaises(ValueError):
            app.operate("set", {"latitude": 30, "longitude": 120})
        self.assertEqual(app.state_snapshot()["mode"], "unknown")

    @patch("qingji.app.detect", return_value="phone-a")
    @patch("qingji.app.RUNNER.close")
    @patch("qingji.app.command")
    def test_restore_stops_keepalive_before_device_clear(self, command, close, _):
        calls = []
        close.side_effect = lambda: calls.append("stop")
        command.side_effect = lambda *a, **k: calls.append("clear")
        app.operate("clear", {})
        self.assertEqual(calls, ["stop", "clear"])

    @patch("qingji.app.detect", return_value="phone-a")
    @patch("qingji.app.command", side_effect=ValueError("clear failed"))
    def test_failed_clear_never_claims_restored(self, command, _):
        app.STATE["mode"] = "simulating"
        with self.assertRaises(ValueError):
            app.operate("clear", {})
        self.assertEqual(app.STATE["mode"], "unknown")
        self.assertIn("尚未确认", app.STATE["message"])

    @patch("qingji.app.detect", return_value="phone-b")
    @patch("qingji.app.command")
    def test_switching_phones_cannot_clear_wrong_device(self, command, _):
        app.STATE["target_device"] = "phone-a"
        with self.assertRaises(ValueError):
            app.operate("clear", {})
        command.assert_not_called()

    @patch("qingji.app.detect", return_value="phone-a")
    @patch("qingji.app.command", return_value="")
    def test_clear_records_request_not_gps_readback(self, command, _):
        app.operate("clear", {})
        self.assertEqual(app.STATE["mode"], "cleared")
        self.assertIsNone(app.STATE["target"])
        self.assertIn("手机地图确认", app.STATE["message"])


if __name__ == "__main__":
    unittest.main()
