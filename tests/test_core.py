"""Smoke-Tests: Kalibrierung, G-Code, Netzwerk-Verbindungen (mit Mock-Server)."""
import http.server
import json
import math
import os
import tempfile
import threading
import time
import unittest

from plotter_app.calibration import Calibration
from plotter_app.gcode import export_gcode, plot_command_groups
from plotter_app.network import MoonrakerConnection, OctoPrintConnection, PrinterConnectionError, create_connection
from plotter_app.pen import PenSettings
from plotter_app.profiles import load_printer_profile
from plotter_app.svg import load_svg


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

    def test_gcode_order_z_up_before_g0(self):
        """Reihenfolge: Z hoch -> G0 -> Z runter -> G1 (fuer JEDEN Pfad)."""
        cal = Calibration()
        for p in [(0, 0), (100, 0), (100, 100), (0, 100)]:
            cal.add_point(*p)
        pen = PenSettings()
        g = export_gcode([[(0.1, 0.1), (0.9, 0.9)], [(0.2, 0.8), (0.8, 0.2)]], cal, pen)
        lines = [l.strip() for l in g.strip().splitlines()]
        # fuer jeden Pfad: up -> G0 -> down -> G1
        self.assertEqual(lines.count("G1 Z20.00 F4800"), 3)  # 2 Pfade + Ende
        idx_up = lines.index("G1 Z20.00 F4800")
        idx_g0 = next(i for i, l in enumerate(lines) if l.startswith("G0 X"))
        idx_down = lines.index("G1 Z0.00 F4800")
        idx_g1 = next(i for i, l in enumerate(lines) if l.startswith("G1 X"))
        self.assertLess(idx_up, idx_g0)
        self.assertLess(idx_g0, idx_down)
        self.assertLess(idx_down, idx_g1)
        # zweiter Pfad: erneut volles up_gcode vor G0 (kein 1-mm-Hub)
        second_up = lines.index("G1 Z20.00 F4800", idx_up + 1)
        second_g0 = next(i for i, l in enumerate(lines) if i > second_up and l.startswith("G0 X"))
        self.assertLess(second_up, second_g0)
        self.assertNotIn(f"G1 Z{pen.pen_draw_z + pen.z_lift_between_paths:.2f}", g)  # kein lift zwischen Pfaden


    def test_plot_command_groups_pen_safe(self):
        """Live-Plot: nur XY homen, Stift HOCH als erstes Kommando."""
        cal = Calibration()
        for p in [(0, 0), (100, 0), (100, 100), (0, 100)]:
            cal.add_point(*p)
        pen = PenSettings()
        groups = plot_command_groups([[(0.1, 0.1), (0.9, 0.1)]], cal, pen)
        head = groups[0]
        self.assertIn("G28 X Y", head)
        self.assertNotIn("G28\n", "\n".join(head))  # kein Home-All (Z-Crash-Gefahr)
        # pen-up kommt VOR jeder Bewegung: keine G0/G1-X/Y-Zeile davor
        idx_up = head.index(f"G1 Z{pen.pen_up_z:.2f} F{pen.travel_speed * 60:.0f}")
        self.assertFalse(any(l.startswith(("G0 ", "G1 X", "G1 Y")) for l in head[:idx_up]))
        # die erste Fahrt (Gruppe 1) beginnt mit pen-up
        self.assertTrue(groups[1][0].startswith(f"G1 Z{pen.pen_up_z:.2f}"))
        # eine Gruppe pro Pfad + head + finale Gruppe
        self.assertEqual(len(groups), 3)
        self.assertIn("M84", groups[-1][-1])

    def test_pen_xy_offset_in_gcode(self):
        """Stift-X/Y-Offset: die Nozzle faehrt um den Offset versetzt,
        damit die Stiftspitze am kalibrierten Punkt landet."""
        cal = Calibration()
        for p in [(0, 0), (100, 0), (100, 100), (0, 100)]:
            cal.add_point(*p)
        pen = PenSettings()
        pen.pen_offset_x = 10.0
        pen.pen_offset_y = -5.0
        g = export_gcode([[(0.1, 0.1), (0.9, 0.1)]], cal, pen)
        # kalibriert: (0.1,0.1) -> (10,10); mit Offset -> X0.00 Y15.00
        self.assertIn("G0 X0.00 Y15.00", g)
        self.assertIn("G1 X80.00 Y15.00", g)



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

    def test_moonraker_upload_starts_print(self):
        """Nach dem Upload wird der Druck EXPLIZIT gestartet
        (POST /printer/print/start), nicht nur hochgeladen."""
        requests_seen = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def _read_and_respond(self, body_obj):
                length = int(self.headers.get("Content-Length", 0))
                data = self.rfile.read(length)
                requests_seen.append((self.command, self.path, data))
                body = json.dumps(body_obj).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                if "upload" in self.path:
                    self._read_and_respond({"result": {"item": {"path": "plot.gcode"}}})
                else:
                    self._read_and_respond({"result": "ok"})

            def log_message(self, *_):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            conn = MoonrakerConnection(f"http://127.0.0.1:{srv.server_address[1]}")
            conn.upload_and_start("G28\n", "plot_20250101_120000.gcode")
            paths = [r[1] for r in requests_seen]
            self.assertTrue(any("upload" in p for p in paths))
            self.assertIn("/printer/print/start", paths)
            start_body = next(json.loads(r[2]) for r in requests_seen
                               if r[1] == "/printer/print/start")
            self.assertEqual(start_body["filename"], "plot_20250101_120000.gcode")
        finally:
            srv.shutdown()

    def test_octoprint_get_position_three_tuple(self):
        """OctoPrint liefert IMMER ein 3-Tupel (z=None wenn unbekannt)."""
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({"x": 10.0, "y": 20.0}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            conn = OctoPrintConnection(f"http://127.0.0.1:{srv.server_address[1]}", "key")
            pos = conn.get_position()
            self.assertEqual(len(pos), 3)
            self.assertEqual(pos[:2], (10.0, 20.0))
            self.assertIsNone(pos[2])
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

    def test_error_callback_only_once_after_replay(self):
        """replay=True: Fehler-Callback feuert NICHT sofort, sondern erst nach Erfolg."""
        from plotter_app.queue import QueuedConnection

        attempts = {"home": 0}
        results = []

        class FakeConn:
            def home(self, axes="XY"):
                attempts["home"] += 1
                if attempts["home"] < 2:
                    raise PrinterConnectionError("Simulierter Abbruch")
                return True

        qc = QueuedConnection.__new__(QueuedConnection)
        qc.kind = "moonraker"
        qc.host = "fake"
        qc.api_key = ""
        qc.on_status = lambda t, ok: None
        qc._queue = __import__("queue").Queue()
        qc._pos_cache = (0, 0, None)
        qc._connected = True
        qc._stop = False
        qc._lock = threading.Lock()
        qc._conn = FakeConn()
        qc._make_connection = lambda: FakeConn()
        qc._connect = lambda: setattr(qc, "_connected", True) or True
        qc.start()
        qc.home("XY", callback=lambda r, e: results.append((r, e)))
        deadline = time.time() + 25
        while len(results) < 1 and time.time() < deadline:
            time.sleep(0.05)
        qc.stop()
        self.assertEqual(len(results), 1)      # genau EIN Callback
        self.assertEqual(results[0], (True, None))  # und zwar Erfolg, kein Fehler davor


def _svg_root(name):
    import xml.etree.ElementTree as ET
    return ET.parse(name).getroot()



class TestSvgImport(unittest.TestCase):
    def _write_svg(self, content):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".svg", delete=False, encoding="utf-8")
        f.write(content)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_group_transform_and_arc(self):
        """<g transform="translate(...) rotate(...)"> wird vererbt; Arc A wird gezeichnet."""
        name = self._write_svg(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<g transform="translate(10,10) rotate(45)">'
            '<path d="M0 0 L20 0 A20 20 0 0 1 40 20 Z"/>'
            '</g></svg>')
        paths = load_svg(name, bed_w=100, bed_h=100)
        self.assertEqual(len(paths), 1)
        path = paths[0]
        # Arc als Polygon-Naeherung: deutlich mehr Punkte als M + L + Z allein
        self.assertGreater(len(path), 5)
        # alle Koordinaten im Bereich 0..1
        for (x, y) in path:
            self.assertGreaterEqual(x, 0.0)
            self.assertLessEqual(x, 1.0)
            self.assertGreaterEqual(y, 0.0)
            self.assertLessEqual(y, 1.0)
        # Transform numerisch pruefen: Punkt (20,0) -> rotate(45) -> translate(10,10)
        # = (10 + 20*cos45, 10 + 20*sin45) ~ (24.14, 24.14)
        # Ohne Vererbung waere der L-Endpunkt bei (20, 0) -> andere Normalisierung.
        pts = self._raw_points(name)
        lx, ly = pts[1]  # erster Punkt nach M ist der L-Endpunkt
        self.assertAlmostEqual(lx, 10 + 20 * math.cos(math.radians(45)), delta=1e-6)
        self.assertAlmostEqual(ly, 10 + 20 * math.sin(math.radians(45)), delta=1e-6)

    def _raw_points(self, name):
        """SVG-Koordinaten (vor Normalisierung) ueber _iter_elements extrahieren."""
        from plotter_app.svg import _identity, _iter_elements
        out = []
        _iter_elements(_svg_root(name), _identity(), out)
        return out[0]

    def test_polygon_closed(self):
        name = self._write_svg(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<polygon points="0,0 10,0 5,10"/></svg>')
        paths = load_svg(name, bed_w=100, bed_h=100)
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0][0], paths[0][-1])  # geschlossen

    def test_y_flipped(self):
        """Y wird gespiegelt: SVG-oben (y=0) -> Papier-y hoch."""
        name = self._write_svg(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<rect x="0" y="0" width="10" height="10"/></svg>')
        (path,) = load_svg(name, bed_w=100, bed_h=100)
        self.assertGreater(path[0][1], path[2][1])  # Ecke oben (SVG y=0) hat groesseres Papier-y


class TestProfilesImport(unittest.TestCase):
    def test_printable_area_list(self):
        """OrcaSlicer printable_area als Eckliste -> bed_x/bed_y = max x/y."""
        data = {
            "printer_model": "Test Printer",
            "printable_area": [[0, 0], [220, 0], [220, 220], [0, 220]],
            "printable_height": 250,
        }
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(data, f)
        f.close()
        self.addCleanup(os.unlink, f.name)
        prof = load_printer_profile(f.name)
        self.assertEqual(prof["name"], "Test Printer")
        self.assertEqual(prof["bed_x"], 220)
        self.assertEqual(prof["bed_y"], 220)
        self.assertEqual(prof["bed_z"], 250)
        self.assertIsInstance(prof["bed_x"], (int, float))


if __name__ == "__main__":
    unittest.main()
