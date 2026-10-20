"""Opt-in LAN receiver for a user-run iPhone Shortcut; no device-control routes."""

import html
import io
import ipaddress
import json
import math
import secrets
import socket
import subprocess
import sys
import threading
import time
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .paths import WEB_DIR


def local_addresses():
    try:
        values = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        return []
    return sorted({v for v in values if usable_address(v)})


def usable_address(value):
    try:
        address = ipaddress.IPv4Address(value)
        return address.is_private and not (
            address.is_loopback or address.is_link_local or address.is_unspecified
        )
    except ipaddress.AddressValueError:
        return False


@lru_cache(maxsize=4)
def network_options(addresses):
    aliases = {}
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; Get-NetIPAddress -AddressFamily IPv4 | Select-Object IPAddress,InterfaceAlias | ConvertTo-Json -Compress",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8-sig",
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            records = json.loads(result.stdout)
            for row in records if isinstance(records, list) else [records]:
                aliases[row["IPAddress"]] = row["InterfaceAlias"]
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
            pass
    options = []
    for address in addresses:
        alias = aliases.get(address, "网络地址")
        wifi = any(name in alias.lower() for name in ("wlan", "wi-fi", "wifi", "无线"))
        options.append({"address": address, "label": f"{alias} · {address}", "preferred": wifi})
    return sorted(options, key=lambda row: not row["preferred"])


def parse_report(data):
    if not isinstance(data, dict):
        raise ValueError("需要 JSON 对象。")
    result = {}
    for name, limit in [("latitude", 90), ("longitude", 180)]:
        raw = data.get(name)
        if raw is None or isinstance(raw, bool) or not str(raw).strip():
            raise ValueError("缺少有效的纬度或经度。")
        try:
            number = float(raw)
        except (ValueError, TypeError):
            raise ValueError("纬度和经度应为数字。")
        if not math.isfinite(number) or abs(number) > limit:
            raise ValueError("纬度或经度超出范围。")
        result[name] = number
    return result


class PhoneBridge:
    def __init__(self, mode=lambda: "untouched"):
        self.mode = mode
        self.lock = threading.RLock()
        self.server = None
        self.token = secrets.token_urlsafe(24)
        self.address = None
        self.expires = 0
        self.report = None

    def start(self, address, port=8766):
        if address not in local_addresses():
            raise ValueError("请选择本机的有效局域网地址。")
        with self.lock:
            if self.server and self.address != address:
                raise ValueError("请先关闭回传接收，再切换网络地址。")
            if not self.server:
                self.address = address
                bridge = self

                class Receiver(BaseHTTPRequestHandler):
                    def setup(self):
                        super().setup()
                        self.connection.settimeout(10)

                    def reply(self, code, payload, kind="application/json; charset=utf-8"):
                        body = (
                            payload
                            if isinstance(payload, bytes)
                            else json.dumps(payload, ensure_ascii=False).encode()
                        )
                        self.send_response(code)
                        self.send_header("Content-Type", kind)
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("Referrer-Policy", "no-referrer")
                        self.send_header("X-Content-Type-Options", "nosniff")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)

                    def authorized(self, prefix):
                        expected = prefix + bridge.token
                        return (
                            secrets.compare_digest(self.path, expected)
                            and time.monotonic() < bridge.expires
                        )

                    def do_GET(self):
                        if self.path == "/":
                            return self.reply(
                                200,
                                '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><h1>轻迹：手机已能访问电脑</h1><p>连接测试成功。请返回电脑页面重新扫码，打开快捷指令设置说明。</p>'.encode(),
                                "text/html; charset=utf-8",
                            )
                        if not self.authorized("/pair/"):
                            return self.reply(
                                403, {"error": "配对已关闭、过期或地址无效，请在电脑页面重新开启。"}
                            )
                        page = (WEB_DIR / "phone_help.html").read_text(encoding="utf-8")
                        page = page.replace(
                            "__ENDPOINT__", html.escape(bridge.snapshot()["endpoint"])
                        )
                        self.reply(200, page.encode("utf-8"), "text/html; charset=utf-8")

                    def do_POST(self):
                        # Shortcuts makes a native request. Websites cannot send to this receiver.
                        if self.headers.get("Origin") or not self.authorized("/location/"):
                            return self.reply(403, {"error": "配对已关闭、过期或地址无效。"})
                        try:
                            if (
                                self.headers.get("Content-Type", "").split(";")[0].lower()
                                != "application/json"
                            ):
                                raise ValueError("请选择 JSON 请求体。")
                            size = int(self.headers.get("Content-Length", "0"))
                            if not 0 < size <= 4096:
                                raise ValueError("请求大小无效。")
                            payload = json.loads(self.rfile.read(size))
                            bridge.accept(payload, self.path[len("/location/") :])
                            self.reply(
                                200,
                                {"ok": True, "message": "电脑已收到手机上报位置，未修改手机定位。"},
                            )
                        except (ValueError, OSError) as error:
                            self.reply(400, {"error": str(error)})

                    def log_message(self, *_):
                        pass

                self.server = ThreadingHTTPServer((address, port), Receiver)
                threading.Thread(target=self.server.serve_forever, daemon=True).start()
            self.expires = time.monotonic() + 600
        return self.snapshot()

    def accept(self, data, token):
        with self.lock:
            if (
                not self.server
                or not secrets.compare_digest(token, self.token)
                or time.monotonic() >= self.expires
            ):
                raise ValueError("回传接收未开启或已过期。")
            point = parse_report(data)
            point.update(
                received_at=time.time(), mode_at_receive=self.mode(), source="iphone-shortcut"
            )
            self.report = point

    def snapshot(self):
        with self.lock:
            addresses = local_addresses()
            network_changed = bool(self.server and self.address not in addresses)
            active = bool(self.server and not network_changed and time.monotonic() < self.expires)
            base = f"http://{self.address}:{self.server.server_port}" if self.server else None
            return {
                "active": active,
                "remaining_seconds": max(0, int(self.expires - time.monotonic())) if active else 0,
                "addresses": addresses,
                "address": self.address,
                "network_options": network_options(tuple(addresses)),
                "network_changed": network_changed,
                "endpoint": f"{base}/location/{self.token}" if active else None,
                "guide_url": f"{base}/pair/{self.token}" if active else None,
                "report": self.report,
            }

    def qr_svg(self, target="guide"):
        state = self.snapshot()
        if not state["active"]:
            raise ValueError("请先开启手机回传接收。")
        import qrcode
        import qrcode.image.svg

        output = io.BytesIO()
        if target not in ("guide", "endpoint"):
            raise ValueError("二维码类型无效。")
        qrcode.make(
            state["endpoint"] if target == "endpoint" else state["guide_url"],
            image_factory=qrcode.image.svg.SvgPathImage,
            border=3,
        ).save(output)
        return output.getvalue()

    def stop(self):
        with self.lock:
            server = self.server
            self.server = None
            self.expires = 0
            self.token = secrets.token_urlsafe(24)
        if server:
            server.shutdown()
            server.server_close()
