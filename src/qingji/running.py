"""Acknowledged device streaming and a monotonic route playback controller."""

import bisect
import json
import math
import subprocess
import sys
import threading
import time
from pathlib import Path

from .calibration import Calibration
from .calibration import select as select_calibration
from .motion import RunMotion
from .route_store import validate_route


def distance(a, b):
    lat1, lat2 = map(math.radians, (a[0], b[0]))
    dlat = lat2 - lat1
    dlon = math.radians(b[1] - a[1])
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371000 * 2 * math.atan2(math.sqrt(value), math.sqrt(max(0, 1 - value)))


class RunPlan:
    def __init__(self, data):
        if not isinstance(data, dict):
            raise ValueError("跑步参数格式无效。")
        source = data.get("route")
        if not isinstance(source, dict):
            raise ValueError("请先规划或加载一条路线。")
        route = validate_route({**source, "name": source.get("name") or "当前路线"})
        pace = data.get("pace_seconds")
        laps = data.get("laps", 1)
        if (
            isinstance(pace, bool)
            or not isinstance(pace, (int, float))
            or not math.isfinite(pace)
            or not 60 <= pace <= 1800
        ):
            raise ValueError("配速范围为 1:00～30:00 分钟／公里。")
        if isinstance(laps, bool) or not isinstance(laps, int) or not 0 <= laps <= 10000:
            raise ValueError("圈数需为 1～10000；0 表示无限循环。")
        if not route["closed"] and laps != 1:
            raise ValueError("多圈或无限循环需要先将路线闭环，避免终点跳回起点。")
        self.route = route
        self.pace = pace
        self.laps = laps
        self.speed = 1000 / pace
        self.pace_variation = data.get("pace_variation_seconds", 0)
        self.trajectory_offset = data.get("trajectory_offset_m", 0)
        for value, maximum, name in (
            (self.pace_variation, 120, "配速浮动（0～120 秒／公里）"),
            (self.trajectory_offset, 3, "轨迹偏移（0～3 米）"),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= maximum
            ):
                raise ValueError(name + "参数无效。")
        self.points = route["points"] + ([route["points"][0]] if route["closed"] else [])
        self.calibration = select_calibration(self.points, data.get("calibration_enabled", True))
        device_points = [self.calibration.apply(p) for p in self.points]
        self.cumulative = [0.0]
        for a, b in zip(device_points, device_points[1:]):
            self.cumulative.append(self.cumulative[-1] + distance(a, b))
        self.length = self.cumulative[-1]
        if self.length < 5:
            raise ValueError("路线长度至少需要 5 米。")
        self.total = self.length * laps if laps else None

    def point_at(self, meters):
        if self.total is not None and meters >= self.total:
            return list(self.points[-1])
        position = meters % self.length
        index = min(len(self.points) - 2, bisect.bisect_right(self.cumulative, position) - 1)
        segment = self.cumulative[index + 1] - self.cumulative[index]
        fraction = (position - self.cumulative[index]) / segment if segment else 0
        a, b = self.points[index], self.points[index + 1]
        dlon = (b[1] - a[1] + 180) % 360 - 180
        return [a[0] + (b[0] - a[0]) * fraction, (a[1] + dlon * fraction + 180) % 360 - 180]


class DeviceStream:
    def __init__(self, udid):
        self.ready = threading.Event()
        self.pending = {}
        self.lock = threading.Lock()
        self.send_lock = threading.Lock()
        self.sequence = 0
        self.lines = []
        self.failure = None
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-u",
                str(Path(__file__).parent / "device_cli.py"),
                "developer",
                "dvt",
                "simulate-location",
                "stream",
                "--udid",
                udid,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        threading.Thread(target=self._read, daemon=True).start()
        if not self.ready.wait(90) or self.failure:
            self.close()
            raise ValueError(
                "跑步定位连接未就绪。请先准备设备。\n"
                + str(self.failure or "".join(self.lines)[-1800:])
            )

    def _read(self):
        try:
            for line in self.process.stdout:
                self.lines = (self.lines + [line])[-40:]
                if not line.startswith("QINGJI_EVENT "):
                    continue
                try:
                    event = json.loads(line[len("QINGJI_EVENT ") :])
                except ValueError:
                    continue
                if event.get("event") == "ready":
                    self.ready.set()
                with self.lock:
                    pending = self.pending.get(event.get("id"))
                    if pending:
                        pending["result"] = event
                        pending["done"].set()
        finally:
            self.failure = "设备连接已结束。\n" + "".join(self.lines)[-1200:]
            self.ready.set()
            with self.lock:
                for job in self.pending.values():
                    job["done"].set()

    def set(self, point):
        with self.send_lock:
            if self.process.poll() is not None:
                raise ValueError(self.failure or "设备连接已断开。")
            with self.lock:
                self.sequence += 1
                key = self.sequence
                job = {"done": threading.Event(), "result": None}
                self.pending[key] = job
            try:
                self.process.stdin.write(
                    json.dumps({"id": key, "action": "set", "point": point}) + "\n"
                )
                self.process.stdin.flush()
                if not job["done"].wait(20):
                    raise ValueError("设备更新定位超时；已停止推进路线，请检查连接并恢复定位。")
                event = job["result"]
                if not event or not event.get("ok"):
                    raise ValueError(
                        (event or {}).get("error") or self.failure or "定位指令未确认。"
                    )
            except OSError as error:
                raise ValueError("设备连接已断开：" + str(error))
            finally:
                with self.lock:
                    self.pending.pop(key, None)

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.write(json.dumps({"action": "stop"}) + "\n")
                self.process.stdin.flush()
                self.process.wait(timeout=4)
            except (OSError, subprocess.TimeoutExpired):
                self.process.kill()
                self.process.wait(timeout=4)


class RunController:
    def __init__(self, session_factory=DeviceStream):
        self.session_factory = session_factory
        self.lock = threading.RLock()
        self.io_lock = threading.Lock()
        self.session = None
        self.plan = None
        self.state = "idle"
        self.meters = 0
        self.moving_seconds = 0
        self.position = None
        self.message = "尚未开始跑步。"
        self.last_tick = 0
        self.thread = None
        self.cancel = threading.Event()
        self.calibration = Calibration()
        self.motion = None
        self.current_speed = 0

    def hold(self, point, udid, calibration=None):
        self.close()
        calibration = calibration or Calibration()
        session = self.session_factory(udid)
        try:
            session.set(calibration.apply(point))
        except Exception:
            session.close()
            raise
        with self.lock:
            self.session = session
            self.plan = None
            self.position = list(point)
            self.state = "holding"
            self.calibration = calibration
            self.motion = None
            self.current_speed = 0
            self.meters = 0
            self.moving_seconds = 0
            self.message = "单点定位持续保持中；恢复真实定位后停止。"
        self._start_loop()

    def _start_loop(self):
        self.cancel = threading.Event()
        self.thread = threading.Thread(target=self._loop, args=(self.cancel,), daemon=True)
        self.thread.start()

    def start(self, plan, udid):
        self.close()
        motion = RunMotion(plan)
        session = self.session_factory(udid)
        try:
            session.set(plan.calibration.apply(plan.point_at(0)))
        except Exception:
            session.close()
            raise
        with self.lock:
            self.session = session
            self.plan = plan
            self.meters = 0
            self.moving_seconds = 0
            self.position = plan.point_at(0)
            self.state = "running"
            self.message = "正在沿路线移动。"
            self.last_tick = time.monotonic()
            self.calibration = plan.calibration
            self.motion = motion
            self.current_speed = 1000 / motion.lap_pace(0)
        self._start_loop()

    def _loop(self, cancel):
        while not cancel.wait(0.5):
            with self.io_lock:
                with self.lock:
                    if cancel.is_set() or not self.session:
                        return
                    if self.state not in ("running", "paused", "holding", "stopped", "completed"):
                        return
                    moving = self.state == "running"
                    # Avoid a large catch-up jump after a suspended computer or a stalled device.
                    now = time.monotonic()
                    dt = max(0, min(1.5, now - self.last_tick))
                    self.last_tick = now
                    if moving:
                        target, seconds, speed = self.motion.advance(
                            self.meters, self.moving_seconds, self.current_speed, dt
                        )
                        point = self.motion.point_at(target, seconds)
                    else:
                        point = list(self.position)
                    session = self.session
                try:
                    session.set(self.calibration.apply(point))
                except Exception as error:
                    with self.lock:
                        self.state = "error"
                        self.message = "持续定位已中断，手机定位状态待确认：" + str(error)
                    return
                with self.lock:
                    if moving:
                        self.moving_seconds = seconds
                        self.current_speed = speed
                        self.meters = target
                        self.position = point
                    if moving and self.plan.total is not None and target >= self.plan.total:
                        self.state = "completed"
                        self.message = "已完成设定圈数，正在持续保持终点定位；恢复真实定位后停止。"

    def pause(self):
        with self.io_lock, self.lock:
            if self.state != "running":
                raise ValueError("当前没有正在进行的跑步。")
            self.state = "paused"
            self.message = "已暂停，定位保持原地，运动计时停止。"

    def resume(self):
        with self.io_lock, self.lock:
            if self.state != "paused":
                raise ValueError("当前跑步未暂停。")
            self.last_tick = time.monotonic()
            self.state = "running"
            self.message = "已继续，从暂停的位置沿路线移动。"

    def stop(self):
        with self.io_lock, self.lock:
            if self.state in ("running", "paused"):
                self.state = "stopped"
                self.message = "已结束跑步，正在持续保持当前位置；恢复真实定位后停止。"

    def close(self):
        self.cancel.set()
        with self.io_lock, self.lock:
            if self.session:
                self.session.close()
                self.session = None
            if self.state != "error":
                self.state = "stopped" if self.plan else "idle"
                self.message = "持续定位已停止。"
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)

    def snapshot(self):
        with self.lock:
            plan = self.plan
            done = (
                min(plan.laps, int((self.meters + 1e-6) / plan.length))
                if plan and plan.laps
                else int(self.meters / plan.length)
                if plan
                else 0
            )
            return {
                "status": self.state,
                "message": self.message,
                "distance_m": self.meters,
                "moving_seconds": self.moving_seconds,
                "position": list(self.position) if self.position else None,
                "completed_laps": done,
                "current_lap": done if self.state == "completed" else done + 1 if plan else 0,
                "lap_length_m": plan.length if plan else 0,
                "laps": plan.laps if plan else 0,
                "pace_seconds": plan.pace if plan else None,
                "connected": self.session is not None,
                "lap_pace_seconds": self.motion.lap_pace(self.meters) if self.motion else None,
                "current_pace_seconds": 1000 / self.current_speed if self.current_speed else None,
                "pace_variation_seconds": plan.pace_variation if plan else 0,
                "trajectory_offset_m": plan.trajectory_offset if plan else 0,
                "holding": self.session is not None
                and self.state in ("holding", "paused", "stopped", "completed"),
                "device_position": self.calibration.apply(self.position) if self.position else None,
                "calibration": self.calibration.snapshot(),
                "route": plan.route if plan else None,
            }
