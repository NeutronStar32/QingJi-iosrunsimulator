"""Local-only iPhone location control. Startup never changes device location."""

import json
import math
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .assets import build_ui
from .calibration import configuration_snapshot, initialize_profiles
from .calibration import select as select_calibration
from .paths import DATA_DIR, LOG_DIR
from .paths import PROJECT_ROOT as ROOT
from .phone_bridge import PhoneBridge
from .route_store import RouteStore
from .running import RunController, RunPlan

TOKEN = secrets.token_urlsafe(32)
LOCK = threading.Lock()
STATE = {
    "mode": "untouched",
    "target": None,
    "device": None,
    "message": "本次启动尚未修改手机定位。真实坐标暂未读取，请在手机地图中查看。",
    "logs": [],
}
PORT = 8765
PHONE = PhoneBridge(mode=lambda: STATE["mode"])
ROUTES = RouteStore(ROOT / "data" / "routes")
EXIT_REQUESTED = False
RUNNER = RunController()


def log(message):
    STATE["logs"] = (STATE["logs"] + [time.strftime("%H:%M:%S") + "  " + message])[-30:]


def command(args, timeout=45):
    try:
        p = subprocess.run(
            [sys.executable, "-u", str(Path(__file__).with_name("device_cli.py")), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        raise ValueError("手机操作超时，状态未确认。请解锁手机、确认信任此电脑后重试。")
    if p.returncode:
        detail = (p.stderr + "\n" + p.stdout).strip()[-2500:]
        raise ValueError("手机连接组件执行失败。请查看下方详细信息。\n" + detail)
    return p.stdout


def detect():
    output = command(["usbmux", "list", "--usb"])
    try:
        devices = json.loads(output)
    except json.JSONDecodeError:
        raise ValueError("无法解析设备信息：" + output[-1500:])
    if len(devices) != 1:
        STATE["device"] = None
        raise ValueError(
            "未检测到已信任的 USB 设备，请连接并解锁 iPhone，点击「信任此电脑」。"
            if not devices
            else "请只连接一部 iPhone，避免修改到其他设备。"
        )
    d = devices[0]
    udid = d.get("UniqueDeviceID") or d.get("Identifier") or d.get("UDID")
    if not udid:
        raise ValueError("设备信息缺少标识，无法安全选择设备：" + output[-1500:])
    STATE["device"] = {
        "name": d.get("DeviceName", "iPhone"),
        "version": d.get("ProductVersion", "未知"),
        "model": d.get("ProductType", "未知"),
        "udid": udid,
    }
    return udid


def stop_session():
    RUNNER.close()


def coordinates(data):
    values = []
    for field, limit in (("latitude", 90), ("longitude", 180)):
        value = data.get(field)
        if isinstance(value, bool) or value is None or str(value).strip() == "":
            raise ValueError("请完整输入纬度和经度。")
        try:
            value = float(value)
        except (ValueError, TypeError):
            raise ValueError("坐标必须是十进制数字。")
        if not math.isfinite(value) or not -limit <= value <= limit:
            raise ValueError("纬度范围为 -90～90，经度范围为 -180～180。")
        values.append(value)
    return values


def operate(action, data):
    global EXIT_REQUESTED
    if EXIT_REQUESTED:
        raise ValueError("程序正在退出。")
    if action == "shutdown":
        # Preserve the running program if recovery fails, unless the user explicitly forces exit.
        if data.get("force") is not True and (
            RUNNER.snapshot()["connected"] or STATE["mode"] in ("simulating", "unknown")
        ):
            operate("clear", {})
        EXIT_REQUESTED = True
        log("程序正在退出。")
        return
    if action == "run-start":
        plan = RunPlan(data)
        if RUNNER.snapshot()["status"] in ("running", "paused"):
            raise ValueError("请先结束当前跑步，再开始新任务。")
        udid = detect()
        if STATE.get("target_device") and STATE["target_device"] != udid:
            raise ValueError("请连接原手机并恢复定位后再切换设备。")
        stop_session()
        STATE.update(
            mode="unknown", target_device=udid, message="正在建立跑步连接，手机定位状态待确认。"
        )
        RUNNER.start(plan, udid)
        STATE.update(
            mode="simulating",
            target=plan.point_at(0),
            message="跑步模拟已开始，手机已设置到路线起点。",
        )
        log("已开始跑步模拟。")
        log(plan.calibration.snapshot()["message"])
        return
    if action in ("run-pause", "run-resume", "run-stop"):
        {"run-pause": RUNNER.pause, "run-resume": RUNNER.resume, "run-stop": RUNNER.stop}[action]()
        log(RUNNER.snapshot()["message"])
        return
    if action == "phone-start":
        PHONE.start(data.get("address"))
        log("已开启手机位置回传接收，10 分钟后过期；未修改手机定位。")
        return
    if action == "phone-stop":
        PHONE.stop()
        log("已关闭手机位置回传接收。")
        return
    if action == "detect":
        detect()
        log("已识别 USB 设备；未修改定位。")
        return
    if action not in ("prepare", "set", "clear"):
        raise ValueError("未知操作。")
    coords = coordinates(data) if action == "set" else None
    calibration = (
        select_calibration([coords], data.get("calibration_enabled", True)) if coords else None
    )
    if action in ("set", "prepare") and RUNNER.snapshot()["status"] in ("running", "paused"):
        raise ValueError("跑步正在运行或暂停，请先结束跑步；恢复真实定位可直接停止跑步并清除模拟。")
    previous_device = STATE.get("target_device")
    udid = detect()
    if previous_device and udid != previous_device:
        raise ValueError("当前连接的手机与上次模拟的手机不同。请连接原手机并恢复定位后再切换。")
    if action == "prepare":
        if RUNNER.snapshot()["connected"]:
            raise ValueError("请先恢复真实定位，再准备设备。")
        command(["mounter", "auto-mount", "--udid", udid], timeout=300)
        log("开发者镜像准备完成；未设置模拟坐标。")
    elif action == "clear":
        STATE.update(mode="unknown", message="正在清除模拟定位，恢复结果尚未确认。")
        stop_session()
        command(["developer", "dvt", "simulate-location", "clear", "--udid", udid], timeout=90)
        STATE.update(
            mode="cleared",
            target=None,
            target_device=None,
            message="已发送清除模拟定位指令。请在手机地图确认真实位置恢复，坐标更新可能需要等待。",
        )
        log("清除模拟定位指令执行成功，请在手机端确认。")
    else:
        stop_session()
        STATE.update(
            mode="unknown",
            target_device=udid,
            message="设置定位结果尚未确认。请在手机地图查看，必要时点击恢复真实定位。",
        )
        RUNNER.hold(coords, udid, calibration=calibration)
        STATE.update(
            mode="simulating",
            target=coords,
            message="设备已接受模拟坐标，正在持续保持定位。点击恢复真实定位后停止；请保持程序运行和 USB 连接。",
        )
        log("模拟定位已设置，持续保持已开启。")
        log(calibration.snapshot()["message"])


def state_snapshot(base=None):
    state = dict(STATE if base is None else base)
    running = RUNNER.snapshot()
    if running["connected"] and running["position"]:
        state.update(
            mode="unknown" if running["status"] == "error" else "simulating",
            target=running["position"],
            message=running["message"],
        )
    return {
        **state,
        "phone": PHONE.snapshot(),
        "run": running,
        "calibration_config": configuration_snapshot(),
    }


class Handler(BaseHTTPRequestHandler):
    def send(self, status, body, kind="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def allowed(self):
        return self.headers.get("Host") == f"127.0.0.1:{PORT}"

    def do_GET(self):
        if not self.allowed():
            return self.send(403, {"error": "仅允许本机访问"})
        if self.path == "/":
            page = (DATA_DIR / "ui.html").read_text(encoding="utf-8").replace("__TOKEN__", TOKEN)
            return self.send(200, page.encode("utf-8"), "text/html; charset=utf-8")
        if self.path == "/api/status":
            with LOCK:
                state = dict(STATE)
            return self.send(200, state_snapshot(state))
        if self.path in ("/api/phone-qr", "/api/phone-qr?kind=endpoint"):
            try:
                return self.send(
                    200,
                    PHONE.qr_svg("endpoint" if self.path.endswith("?kind=endpoint") else "guide"),
                    "image/svg+xml",
                )
            except ValueError as error:
                return self.send(400, {"error": str(error)})
        if self.path == "/api/routes":
            with LOCK:
                return self.send(200, {"routes": ROUTES.list()})
        self.send(404, {"error": "未找到页面"})

    def do_POST(self):
        if (
            not self.allowed()
            or self.headers.get("X-Local-Token") != TOKEN
            or self.headers.get("Origin") not in (None, f"http://127.0.0.1:{PORT}")
        ):
            return self.send(403, {"error": "请求来源校验失败，请刷新页面。"})
        if not LOCK.acquire(blocking=False):
            return self.send(409, {"error": "正在执行手机操作，请稍候。"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 256000:
                raise ValueError("请求大小无效。")
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError("请求格式无效。")
            if not self.path.startswith("/api/"):
                raise ValueError("未知操作。")
            action = self.path[5:]
            if EXIT_REQUESTED:
                raise ValueError("程序正在退出。")
            if action == "route-save":
                route = ROUTES.save(data)
                return self.send(200, {"ok": True, "route": route, "routes": ROUTES.list()})
            if action == "route-delete":
                ROUTES.delete(data.get("id"))
                return self.send(200, {"ok": True, "routes": ROUTES.list()})
            operate(action, data)
            self.send(200, {"ok": True, "state": state_snapshot()})
            if action == "shutdown":
                self.wfile.flush()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
        except (ValueError, OSError) as error:
            log(str(error))
            self.send(400, {"error": str(error), "state": state_snapshot()})
        finally:
            LOCK.release()

    def log_message(self, *_):
        pass


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None:
        sys.stdout = open(LOG_DIR / "server.log", "a", encoding="utf-8")
        sys.stderr = open(LOG_DIR / "server-error.log", "a", encoding="utf-8")
    import webbrowser

    def open_browser():
        webbrowser.open(f"http://127.0.0.1:{PORT}", new=2)

    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        if "--open" in sys.argv:
            open_browser()
            sys.exit(0)
        raise
    initialize_profiles()
    build_ui()
    print(
        f"打开浏览器：http://127.0.0.1:{PORT}\n退出前请先在网页点击「恢复真实定位」。", flush=True
    )
    if "--open" in sys.argv:
        threading.Timer(0.6, open_browser).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        # Disconnecting is not proof of restoring the GPS; never report it as such.
        stop_session()
        PHONE.stop()
        server.server_close()
