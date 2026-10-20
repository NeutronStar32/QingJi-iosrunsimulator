"""Bounded, continuous route variation, evaluated before device acknowledgement."""

import math
import random


class RunMotion:
    def __init__(self, plan, seed=None):
        self.plan = plan
        self.seed = random.SystemRandom().getrandbits(64) if seed is None else seed
        rng = random.Random(self.seed)
        self.phases = [rng.uniform(0, 2 * math.pi) for _ in range(2)]

    def lap_pace(self, meters):
        lap = int(max(0, meters) / self.plan.length)
        if self.plan.laps:
            lap = min(lap, self.plan.laps - 1)
        delta = random.Random(self.seed + lap * 104729).uniform(
            -self.plan.pace_variation, self.plan.pace_variation
        )
        return min(1800, max(60, self.plan.pace + delta))

    def advance(self, meters, seconds, speed, dt):
        # Small integration steps make lap changes gradual even on short routes.
        remaining = max(0, min(1.5, dt))
        while remaining > 1e-9:
            step = min(0.05, remaining)
            goal = 1000 / self.lap_pace(meters)
            decay = math.exp(-step / 5)
            travel = goal * step + (speed - goal) * 5 * (1 - decay)
            next_speed = goal + (speed - goal) * decay
            if self.plan.total is not None and meters + travel >= self.plan.total:
                fraction = (self.plan.total - meters) / travel if travel else 0
                return (
                    self.plan.total,
                    seconds + step * fraction,
                    speed + (next_speed - speed) * fraction,
                )
            meters += travel
            seconds += step
            speed = next_speed
            remaining -= step
        return meters, seconds, speed

    def point_at(self, meters, seconds):
        point = self.plan.point_at(meters)
        radius = self.plan.trajectory_offset
        if not radius or not seconds:
            return point
        envelope = 1 - math.exp(-seconds / 5)
        if self.plan.total is not None:
            envelope *= min(1, max(0, self.plan.total - meters) / 10)
        device = self.plan.calibration.apply(point)
        east = radius * 0.6 * envelope * math.sin(seconds / 9 + self.phases[0])
        north = radius * 0.6 * envelope * math.sin(seconds / 13 + self.phases[1])
        lat = device[0] + north / 111195
        lon = device[1] + east / (111195 * max(0.01, abs(math.cos(math.radians(device[0])))))
        if not -90 <= lat <= 90:
            return point
        return self.plan.calibration.unapply([lat, (lon + 180) % 360 - 180])
