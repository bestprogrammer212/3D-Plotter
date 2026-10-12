"""Smoke-Tests: Kalibrierung, G-Code, Netzwerk-Verbindungen (mit Mock-Server)."""
import http.server
import json
import threading
import unittest

from plotter_app.calibration import Calibration
from plotter_app.gcode import export_gcode
from plotter_app.network import MoonrakerConnection, PrinterConnectionError, create_connection
from plotter_app.pen import PenSettings


class TestCalibration(unittest.TestCase):
    def test_rect_calibration(self):
        cal = Calibration()
        for p in [(10, 10), (110, 10), (110, 110), (10, 110)]:
            cal.add_point(*p)
        self.assertTrue(cal.is_complete)
        mx, my = cal.paper_to_machine(0.5, 0.5)
        self.assertAlmostEqual(mx, 60, places=3)
        self.assertAlmostEqual(my, 60, places=3)
        mx, my = cal.paper_to_machine(0.0, 0.0)
        self.assertAlmostEqual(mx, 10, places=3)

    def test_many_corners(self):
        import math
        cal = Calibration()
        for i in range(6):
            a = 2 * math.pi * i / 6
            cal.add_point(50 + 40 * math.cos(a), 50 + 40 * math.sin(a))
        self.assertTrue(cal.is_complete)
        mx, my = cal.paper_to_machine(0.5, 0.5)
        self.assertAlmostEqual(mx, 50, delta=1.0)
        self.assertAlmostEqual(my, 50, delta=1.0)


class TestGcode(unittest.TestCase):
    def test_export(self):
        cal = Calibration()
        for p in [(0, 0), (100, 0), (100, 100), (0, 100)]:
            cal.add_point(*p)
        pen = PenSettings()
        g = export_gcode([[(0.1, 0.1), (0.9, 0.1), (0.9, 0.9)]], cal, pen)
        self.assertIn("G90", g)
        self.assertIn("G1 Z20.00", g)  # pen up
        self.assertIn("G1 Z0.00", g)   # pen down
        self.assertIn("X10.00", g)
        self.assertIn("X90.00", g)


class TestNetwork(unittest.TestCase):
    def test_create_unknown(self):
        with self.assertRaises(PrinterConnectionError):
            create_connection("bogus", "x")

    def test_moonraker_get_position(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                self.rfile.read(length)
                body = json.dumps({"result": {"status": {"toolhead": {"position": [12.5, 34.7, 0, 0]}}}}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            conn = MoonrakerConnection(f"http://127.0.0.1:{srv.server_address[1]}")
            pos = conn.get_position()
            self.assertEqual(pos, (12.5, 34.7, 0.0))
        finally:
            srv.shutdown()


class TestQueuedConnection(unittest.TestCase):
    def test_queue_order_and_reconnect(self):
        """Befehle kommen serialisiert an; nach Abbruch reconnectet die Queue."""
        import time
        from plotter_app.queue import QueuedConnection

        received = []
        fail_first = {"n": 0}

        class FakeConn:
            def jog(self, x=None, y=None, z=None):
                received.append((x, y, z))
                if fail_first["n"] < 1:
                    fail_first["n"] += 1
                    raise PrinterConnectionError("Simulierter Abbruch")

            def get_position(self):
                return (1.0, 2.0, 3.0)

        qc = QueuedConnection.__new__(QueuedConnection)
        qc.kind = "moonraker"
        qc.host = "fake"
        qc.api_key = ""
        qc.on_status = lambda t, ok: None
        qc._queue = __import__("queue").Queue()
        qc._pos_cache = (0, 0, 0)
        qc._connected = True
        qc._stop = False
        qc._lock = threading.Lock()
        qc._conn = FakeConn()
        qc._make_connection = lambda: FakeConn()
        qc._connect = lambda: setattr(qc, "_connected", True) or True
        qc.start()

        results = []
        qc.jog(x=5, callback=lambda r, e: results.append((r, e)))
        qc.jog(y=3, callback=lambda r, e: results.append((r, e)))
        deadline = time.time() + 20  # Reconnect-Backoff beruecksichtigen
        while len(received) < 2 and time.time() < deadline:
            time.sleep(0.05)
        qc.stop()
        # beide Befehle kamen an, Reihenfolge bleibt erhalten
        self.assertEqual(received, [(5, None, None), (None, 3, None)])


if __name__ == "__main__":
    unittest.main()
