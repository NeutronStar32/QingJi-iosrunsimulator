"""Local visual alignment profiles are private runtime data, not source code."""

import json
import math
from dataclasses import dataclass
from pathlib import Path

from .paths import DATA_DIR

METERS_LAT = 111195.0


@dataclass(frozen=True)
class Profile:
    latitude: float
    longitude: float
    scale_east: float
    scale_north: float
    shift_east: float
    shift_north: float
    radius_m: float
    name: str = "默认校准"
    enabled: bool = True

    @property
    def meters_lon(self):
        return METERS_LAT * max(0.01, abs(math.cos(math.radians(self.latitude))))

    def distance_to(self, point):
        return math.hypot(
            (point[0] - self.latitude) * METERS_LAT, (point[1] - self.longitude) * self.meters_lon
        )

    def inside(self, point):
        return self.distance_to(point) <= self.radius_m


def parse_profile(data, index=0):
    for key in ("origin_lat_lng", "axis_scales", "shift_east_north_m"):
        if not isinstance(data[key], list) or len(data[key]) != 2:
            raise ValueError("Calibration coordinate pairs must contain two values")
    values = [
        *data["origin_lat_lng"],
        *data["axis_scales"],
        *data["shift_east_north_m"],
        data["radius_m"],
    ]
    if any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
        for v in values
    ):
        raise ValueError("Invalid calibration values")
    name = data.get("name", "默认校准" if index == 0 else f"修正点 {index + 1}")
    enabled = data.get("enabled", True)
    if (
        not isinstance(name, str)
        or not 1 <= len(name.strip()) <= 80
        or not isinstance(enabled, bool)
    ):
        raise ValueError("Invalid calibration name or enabled flag")
    profile = Profile(*values, name.strip(), enabled)
    if (
        abs(profile.latitude) > 90
        or abs(profile.longitude) > 180
        or min(profile.scale_east, profile.scale_north, profile.radius_m) <= 0
    ):
        raise ValueError("Invalid calibration range")
    return profile


def load_profiles(path=None):
    path = DATA_DIR / "calibration.json" if path is None else Path(path)
    if not path.exists():
        return ()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        # The original single-profile format remains readable.
        entries = data["profiles"] if isinstance(data, dict) and "profiles" in data else [data]
        if not isinstance(entries, list) or len(entries) > 1000:
            raise ValueError("Invalid profile list")
        profiles = tuple(parse_profile(entry, i) for i, entry in enumerate(entries))
        if len({p.name for p in profiles}) != len(profiles):
            raise ValueError("Duplicate profile names")
        return profiles
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(
            "本地校准配置无效，请检查 data/calibration.json 中的格式、名称和 enabled 开关。"
        ) from error


_profiles = ()
_config_error = None


def initialize_profiles(path=None):
    """Read once at startup; ongoing sessions keep their own immutable profile."""
    global _profiles, _config_error
    try:
        _profiles = load_profiles(path)
        _config_error = None
    except ValueError as error:
        _profiles = ()
        _config_error = str(error)


def configured_profiles():
    if _config_error:
        raise ValueError(_config_error)
    return _profiles


def configuration_snapshot():
    enabled = [p.name for p in _profiles if p.enabled]
    message = f"启动时从 data/calibration.json 读取 {len(_profiles)} 组，启用 {len(enabled)} 组"
    if enabled:
        message += "：" + "、".join(enabled)
    return {
        "file": "data/calibration.json",
        "loaded_count": len(_profiles),
        "enabled_count": len(enabled),
        "enabled_names": enabled,
        "error": _config_error,
        "message": _config_error or message + "。修改文件后请重启程序。",
    }


@dataclass(frozen=True)
class Calibration:
    enabled: bool = False
    active: bool = False
    profile: Profile | None = None
    available_count: int = 0

    def apply(self, point):
        if not self.active or not self.profile:
            return list(point)
        p = self.profile
        return [
            p.latitude + (point[0] - p.latitude) * p.scale_north + p.shift_north / METERS_LAT,
            p.longitude + (point[1] - p.longitude) * p.scale_east + p.shift_east / p.meters_lon,
        ]

    def unapply(self, point):
        if not self.active or not self.profile:
            return list(point)
        p = self.profile
        return [
            p.latitude + (point[0] - p.latitude - p.shift_north / METERS_LAT) / p.scale_north,
            p.longitude + (point[1] - p.longitude - p.shift_east / p.meters_lon) / p.scale_east,
        ]

    def snapshot(self):
        if self.active:
            message = f"本次定位已应用偏移修正：{self.profile.name}。"
        elif not self.enabled:
            message = "本次定位未启用偏移修正。"
        elif not self.available_count:
            message = "尚未配置或没有启用的本地校准，本次使用原坐标。"
        else:
            message = "没有一组已启用修正能覆盖整个目标或路线，本次使用原坐标。"
        return {
            "enabled": self.enabled,
            "active": self.active,
            "name": self.profile.name if self.active and self.profile else None,
            "file": "data/calibration.json",
            "radius_m": self.profile.radius_m if self.profile else None,
            "message": message,
        }


def select(points, enabled=True):
    if not isinstance(enabled, bool):
        raise ValueError("偏移修正开关格式无效。")
    profiles = [p for p in configured_profiles() if p.enabled] if enabled else []
    candidates = [p for p in profiles if points and all(p.inside(point) for point in points)]
    # Closest center to the start wins; equal distances keep file order.
    profile = min(candidates, key=lambda p: p.distance_to(points[0])) if candidates else None
    return Calibration(enabled, profile is not None, profile, len(profiles))
