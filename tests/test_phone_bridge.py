import json
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from qingji.phone_bridge import PhoneBridge, parse_report


class ReportTests(unittest.TestCase):
    def test_coordinate_validation(self):
        self.assertEqual(
            parse_report({"latitude": "0", "longitude": "-180"}), {"latitude": 0, "longitude": -180}
        )
        for data in (
            None,
            [],
            {},
            {"latitude": True, "longitude": 1},
            {"latitude": "NaN", "longitude": 1},
            {"latitude": 91, "longitude": 1},
            {"latitude": 0, "longitude": 181},
        ):
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse_report(data)

    def test_unarmed_receiver_rejects_reports(self):
        bridge = PhoneBridge()
        with self.assertRaises(ValueError):
            bridge.accept({"latitude": 1, "longitude": 2}, bridge.token)


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.addresses = patch("qingji.phone_bridge.local_addresses", return_value=["127.0.0.1"])
        self.addresses.start()
        self.bridge = PhoneBridge(mode=lambda: "simulating")
        self.state = self.bridge.start("127.0.0.1", 0)

    def tearDown(self):
        self.bridge.stop()
        self.addresses.stop()

    def request(self, url=None, payload=None, extra=None):
        return urlopen(
            Request(
                url or self.state["endpoint"],
                data=json.dumps(payload or {"latitude": 31.23, "longitude": 121.47}).encode(),
                headers={"Content-Type": "application/json", **(extra or {})},
            ),
            timeout=3,
        )

    def test_success_preserves_source_and_simulation_warning(self):
        with self.request() as response:
            self.assertTrue(json.load(response)["ok"])
        report = self.bridge.snapshot()["report"]
        self.assertEqual(report["latitude"], 31.23)
        self.assertEqual(report["mode_at_receive"], "simulating")
        self.assertEqual(report["source"], "iphone-shortcut")
        self.assertLess(abs(report["received_at"] - time.time()), 2)

    def test_bad_token_and_web_origin_are_rejected(self):
        for url, headers in [
            (self.state["endpoint"] + "x", {}),
            (self.state["endpoint"], {"Origin": "http://untrusted.example"}),
        ]:
            with self.assertRaises(HTTPError) as error:
                self.request(url, extra=headers)
            self.assertEqual(error.exception.code, 403)
        self.assertIsNone(self.bridge.report)

    def test_receiver_never_exposes_device_controls(self):
        base = self.state["endpoint"].split("/location/")[0]
        for route in ["/api/set", "/api/clear", "/api/status"]:
            with self.assertRaises(HTTPError) as error:
                self.request(base + route)
            self.assertEqual(error.exception.code, 403)

    def test_expiry_rejects_new_data_and_rearm_keeps_url(self):
        self.bridge.expires = time.monotonic() - 1
        self.assertFalse(self.bridge.snapshot()["active"])
        with self.assertRaises(HTTPError) as error:
            self.request()
        self.assertEqual(error.exception.code, 403)
        self.assertEqual(self.bridge.start("127.0.0.1", 0)["endpoint"], self.state["endpoint"])

    def test_guide_and_qr_are_local_and_available(self):
        with urlopen(self.state["guide_url"], timeout=3) as response:
            text = response.read().decode()
        self.assertIn(self.state["endpoint"], text)
        self.assertIn("POST", text)
        self.assertIn(b"<svg", self.bridge.qr_svg())

    def test_connectivity_page_needs_no_pairing_token(self):
        base = self.state["endpoint"].split("/location/")[0]
        with urlopen(base + "/", timeout=3) as response:
            self.assertIn("手机已能访问电脑", response.read().decode())

    def test_network_change_marks_old_listener_inactive(self):
        with patch("qingji.phone_bridge.local_addresses", return_value=["192.168.2.4"]):
            state = self.bridge.snapshot()
        self.assertTrue(state["network_changed"])
        self.assertFalse(state["active"])
        self.assertIsNone(state["guide_url"])

    def test_invalid_coordinate_does_not_replace_report(self):
        with self.assertRaises(HTTPError) as error:
            self.request(payload={"latitude": 91, "longitude": 2})
        self.assertEqual(error.exception.code, 400)
        self.assertIsNone(self.bridge.report)


if __name__ == "__main__":
    unittest.main()
