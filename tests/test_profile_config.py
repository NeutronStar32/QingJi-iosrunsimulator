import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from qingji import calibration as module
from qingji.calibration import configuration_snapshot, initialize_profiles, load_profiles, select

from .fixtures import PROFILE


class ProfileConfigTests(unittest.TestCase):
    def setUp(self):
        for name, value in (("_profiles", ()), ("_config_error", None)):
            patcher = patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_missing_profile_uses_original_coordinates(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(load_profiles(Path(directory) / "missing.json"), ())
        with patch("qingji.calibration.configured_profiles", return_value=()):
            calibration = select([[30, 120]])
            self.assertFalse(calibration.active)
            self.assertEqual(calibration.apply([30, 120]), [30, 120])
            self.assertIn("尚未配置", calibration.snapshot()["message"])

    def test_profile_load_and_validation(self):
        valid = {
            "origin_lat_lng": [PROFILE.latitude, PROFILE.longitude],
            "axis_scales": [PROFILE.scale_east, PROFILE.scale_north],
            "shift_east_north_m": [PROFILE.shift_east, PROFILE.shift_north],
            "radius_m": PROFILE.radius_m,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calibration.json"
            path.write_text(json.dumps(valid), encoding="utf-8")
            self.assertEqual(load_profiles(path), (PROFILE,))
            for changes in (
                {"radius_m": 0},
                {"axis_scales": [-1, 1]},
                {"origin_lat_lng": [91, 0]},
                {"origin_lat_lng": [30, 120, 1]},
                {"radius_m": True},
            ):
                path.write_text(json.dumps({**valid, **changes}), encoding="utf-8")
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    load_profiles(path)

    def test_multiple_profiles_switches_and_startup_snapshot(self):
        a = replace(PROFILE, name="A")
        b = replace(PROFILE, latitude=30.0005, name="B")
        with patch("qingji.calibration.configured_profiles", return_value=(a, b)):
            self.assertEqual(select([[30.0005, 120]]).profile, b)
        with patch(
            "qingji.calibration.configured_profiles", return_value=(a, replace(b, enabled=False))
        ):
            self.assertEqual(select([[30.0005, 120]]).profile, a)
        with patch(
            "qingji.calibration.configured_profiles", return_value=(a, replace(a, name="C"))
        ):
            self.assertEqual(select([[30, 120]]).profile, a)
        with patch(
            "qingji.calibration.configured_profiles",
            return_value=(replace(a, radius_m=20), replace(b, radius_m=20)),
        ):
            self.assertFalse(select([[30, 120], [30.0005, 120]]).active)

    def test_configuration_is_read_only_on_initialize(self):
        data = {
            "profiles": [
                {
                    "name": "A",
                    "enabled": True,
                    "origin_lat_lng": [30, 120],
                    "axis_scales": [1, 1],
                    "shift_east_north_m": [2, -3],
                    "radius_m": 250,
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calibration.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            initialize_profiles(path)
            selected = select([[30, 120]])
            self.assertTrue(selected.active)
            self.assertEqual(selected.snapshot()["name"], "A")
            data["profiles"][0]["enabled"] = False
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertTrue(select([[30, 120]]).active)
            initialize_profiles(path)
            self.assertFalse(select([[30, 120]]).active)
            self.assertTrue(selected.active)
            self.assertEqual(configuration_snapshot()["loaded_count"], 1)
            self.assertEqual(configuration_snapshot()["enabled_count"], 0)

    def test_bad_switch_or_duplicate_names_rejected(self):
        entry = {
            "name": "A",
            "enabled": True,
            "origin_lat_lng": [30, 120],
            "axis_scales": [1, 1],
            "shift_east_north_m": [0, 0],
            "radius_m": 250,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calibration.json"
            for entries in ([{**entry, "enabled": "false"}], [entry, entry]):
                path.write_text(json.dumps({"profiles": entries}), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_profiles(path)
                initialize_profiles(path)
                self.assertIsNotNone(configuration_snapshot()["error"])
                with self.assertRaises(ValueError):
                    select([[30, 120]])
                self.assertFalse(select([[30, 120]], False).active)
