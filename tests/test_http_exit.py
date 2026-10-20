import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import Mock, patch

from qingji import app


class HttpExitTests(unittest.TestCase):
    def test_shutdown_requires_token_and_releases_server(self):
        original_exit = app.EXIT_REQUESTED
        original_mode = app.STATE["mode"]
        app.EXIT_REQUESTED = False
        app.STATE["mode"] = "untouched"
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        port = server.server_port
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        phone = Mock()
        phone.snapshot.return_value = {}
        try:
            with (
                patch.object(app, "PORT", port),
                patch.object(app, "PHONE", phone),
                patch.object(app, "command") as command,
            ):
                worker.start()
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                connection.request(
                    "POST", "/api/shutdown", body="{}", headers={"Content-Type": "application/json"}
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 403)
                response.read()
                connection.close()
                self.assertTrue(worker.is_alive())
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                connection.request(
                    "POST",
                    "/api/shutdown",
                    body="{}",
                    headers={"Content-Type": "application/json", "X-Local-Token": app.TOKEN},
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertTrue(json.loads(response.read())["ok"])
                connection.close()
                worker.join(timeout=3)
                self.assertFalse(worker.is_alive())
                command.assert_not_called()
        finally:
            server.shutdown()
            server.server_close()
            app.EXIT_REQUESTED = original_exit
            app.STATE["mode"] = original_mode


if __name__ == "__main__":
    unittest.main()
