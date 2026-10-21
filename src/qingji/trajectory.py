"""Seeded preview-compatible trajectory generation and bounded batch playback."""

import bisect
import math
from collections import OrderedDict


def ease(t):
    t = max(0, min(1, t))
    return t * t * (3 - 2 * t)


def validate_settings(value):
    if not isinstance(value, dict):
        raise ValueError("随机轨迹设置无效。")
    result = {}
    for key, low, high, integer in (
        ("laps", 1, 10, True),
        ("jitter", 0, 2, False),
        ("width", 0, 6, False),
        ("lanes", 0, 2, True),
        ("seed", 0, 4294967295, True),
    ):
        v = value.get(key)
        if (
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            or not low <= v <= high
            or (integer and not isinstance(v, int))
        ):
            raise ValueError("随机轨迹参数超出范围：" + key)
        result[key] = v
    if not isinstance(value.get("inside"), bool):
        raise ValueError("弯道内切设置无效。")
    result["inside"] = value["inside"]
    anchor = value.get("anchor")
    if anchor is not None and (
        not isinstance(anchor, list)
        or len(anchor) != 2
        or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            for v in anchor
        )
        or abs(anchor[0]) > 90
        or abs(anchor[1]) > 180
    ):
        raise ValueError("随机轨迹起点无效。")
    result["anchor"] = list(anchor) if anchor else None
    return result


def generate(route, options):
    """Keep arithmetic and PRNG order in sync with web/trajectory-variation.js."""
    first = route["points"][0]
    longitude = 111195 * max(0.01, abs(math.cos(math.radians(first[0]))))

    def xy(p):
        return [((p[1] - first[1] + 540) % 360 - 180) * longitude, (p[0] - first[0]) * 111195]

    def geo(p):
        return [first[0] + p[1] / 111195, (first[1] + p[0] / longitude + 540) % 360 - 180]

    points = [xy(p) for p in route["points"]]
    rng = options["seed"]

    def random():
        nonlocal rng
        rng = (rng + 0x6D2B79F5) & 0xFFFFFFFF
        t = ((rng ^ (rng >> 15)) * (1 | rng)) & 0xFFFFFFFF
        t ^= (t + (((t ^ (t >> 7)) * (61 | t)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296

    segments, ends = [], []
    length = 0
    for a, b in zip(points, points[1:] + points[:1]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        size = math.hypot(dx, dy)
        if size < 1e-6:
            continue
        segments.append((a, dx, dy, size, length))
        length += size
        ends.append(length)
    if not 10 <= length <= 50000:
        raise ValueError("随机轨迹支持每圈 10 米～50 公里。")

    def at(s):
        s %= length
        a, dx, dy, size, start = segments[min(len(segments) - 1, bisect.bisect_right(ends, s))]
        t = (s - start) / size
        return [a[0] + dx * t, a[1] + dy * t]

    anchor = options.get("anchor")
    origin = xy(anchor) if anchor else points[0]
    start, closest = 0, math.inf
    for a, dx, dy, size, begin in segments:
        t = max(0, min(1, ((origin[0] - a[0]) * dx + (origin[1] - a[1]) * dy) / size**2))
        d = math.hypot(origin[0] - a[0] - dx * t, origin[1] - a[1] - dy * t)
        if d < closest:
            closest, start = d, begin + size * t
    if closest > 25:
        raise ValueError("当前位置距路线超过 25 米，请调整路线或恢复定位后重新生成。")
    total = length * options["laps"]

    def noise(spacing):
        values = [random() * 2 - 1 for _ in range(math.ceil(total / spacing) + 2)]

        def sample(s):
            i = math.floor(s / spacing)
            return values[i] + (values[i + 1] - values[i]) * ease(s / spacing - i)

        return sample

    fine, medium, drift = noise(3.5), noise(11), noise(38)
    events = []
    width, lanes = options["width"], options["lanes"]
    if lanes:
        s = 15 + random() * 30
        while s < total:
            events.append((s, 9 + random() * 10, 10 + random() * 25, (random() * 2 - 1) * width))
            s += (45 + random() * 70) / lanes
    base = at(start)
    correction = [origin[i] - base[i] for i in range(2)]
    count = math.ceil(length / max(0.8, total / 30000))
    result = []
    for lap in range(options["laps"]):
        path = []
        for j in range(count + 1):
            s = lap * length + j * length / count
            q, a, b = at(start + s), at(start + s - 3), at(start + s + 3)
            dx, dy = b[0] - a[0], b[1] - a[1]
            norm = math.hypot(dx, dy) or 1
            lateral = options["jitter"] * (0.7 * fine(s) + 0.3 * medium(s)) + width * 0.25 * drift(
                s
            )
            for begin, ramp, hold, amount in events:
                t = s - begin
                if 0 <= t <= 2 * ramp + hold:
                    lateral += amount * ease(t / ramp) * (1 - ease((t - ramp - hold) / ramp))
            if options["inside"] and route.get("editor", {}).get("mode") == "track":
                turn = (q[0] - a[0]) * (b[1] - q[1]) - (q[1] - a[1]) * (b[0] - q[0])
                curvature = turn / max(
                    1e-6,
                    math.hypot(q[0] - a[0], q[1] - a[1]) * math.hypot(b[0] - q[0], b[1] - q[1]),
                )
                lateral += max(-1, min(1, curvature * 15)) * width * 0.3 * (0.65 + 0.35 * medium(s))
            lateral = width * math.tanh(lateral / width) * ease(s / 15) if width else 0
            fade = 1 - ease(s / 25)
            path.append(
                geo(
                    [
                        q[0] - dy / norm * lateral + correction[0] * fade,
                        q[1] + dx / norm * lateral + correction[1] * fade,
                    ]
                )
            )
        result.append(path)
    result[0][0] = list(anchor or first)
    return result


class TrajectoryPath:
    """Generate new batches on demand; retain only a few batches of coordinates."""

    def __init__(self, route, settings, laps, calibration, distance):
        if not route["closed"]:
            raise ValueError("随机变道轨迹需要闭环路线。")
        self.route, self.settings, self.laps = route, validate_settings(settings), laps
        self.calibration, self.distance = calibration, distance
        self.ends = [0.0]
        self.meta, self.cache = [], OrderedDict()
        self._append()

    @property
    def total(self):
        return self.ends[-1] if self.laps and len(self.ends) - 1 >= self.laps else None

    def _batch(self, index):
        if index not in self.cache:
            paths = generate(self.route, self.meta[index])
            batch = []
            for path in paths:
                cumulative = [0.0]
                device = [self.calibration.apply(p) for p in path]
                for a, b in zip(device, device[1:]):
                    cumulative.append(cumulative[-1] + self.distance(a, b))
                if cumulative[-1] < 5:
                    raise ValueError("随机轨迹每圈至少需要 5 米。")
                batch.append((path, cumulative))
            self.cache[index] = batch
        self.cache.move_to_end(index)
        while len(self.cache) > 3:
            self.cache.popitem(last=False)
        return self.cache[index]

    def _append(self):
        index = len(self.meta)
        settings = dict(self.settings)
        if index:
            settings["anchor"] = list(self._batch(index - 1)[-1][0][-1])
            settings["seed"] = (settings["seed"] + index * 104729) & 0xFFFFFFFF
        # Keep the full preview horizon even when the task ends earlier.
        self.meta.append(settings)
        for _, cumulative in self._batch(index):
            if self.laps and len(self.ends) - 1 >= self.laps:
                break
            self.ends.append(self.ends[-1] + cumulative[-1])

    def prepare(self, meters):
        while meters >= self.ends[-1] and self.total is None:
            self._append()

    def lap_index(self, meters):
        self.prepare(meters)
        return min(len(self.ends) - 2, bisect.bisect_right(self.ends, meters) - 1)

    def part(self, meters):
        lap = self.lap_index(meters)
        batch, within = divmod(lap, self.settings["laps"])
        path, cumulative = self._batch(batch)[within]
        return lap, path, cumulative

    def point_at(self, meters):
        lap, path, cumulative = self.part(meters)
        s = max(0, min(cumulative[-1], meters - self.ends[lap]))
        i = min(len(path) - 2, bisect.bisect_right(cumulative, s) - 1)
        size = cumulative[i + 1] - cumulative[i]
        t = (s - cumulative[i]) / size if size else 0
        a, b = path[i], path[i + 1]
        return [
            a[0] + (b[0] - a[0]) * t,
            (a[1] + ((b[1] - a[1] + 180) % 360 - 180) * t + 180) % 360 - 180,
        ]
