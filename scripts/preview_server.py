"""Isolated browser-test server: phone operations are always disabled."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qingji import app
from qingji.assets import build_ui
from qingji.calibration import initialize_profiles
from qingji.route_store import RouteStore


def main():
    initialize_profiles()
    build_ui()
    app.PORT = 8767
    app.ROUTES = RouteStore(app.ROOT / ".local" / "testing" / "routes")
    operate = app.operate

    def preview_operate(action, data):
        if action != "shutdown":
            raise ValueError("测试预览不允许连接或修改手机。")
        return operate(action, data)

    app.operate = preview_operate
    server = app.ThreadingHTTPServer(("127.0.0.1", app.PORT), app.Handler)
    print("Isolated preview: http://127.0.0.1:8767", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop_session()
        app.PHONE.stop()
        server.server_close()


if __name__ == "__main__":
    main()
