"""Netzwerk-Anbindung: Kalibrieren und Plotten über IP (Moonraker/Klipper und OctoPrint)."""
import io
import json
import re
import urllib.error
import uuid
import urllib.parse
import urllib.request

UPLOAD_TIMEOUT = 120  # eigenes Timeout für Uploads großer G-Code-Dateien


class PrinterConnectionError(Exception):
    pass


def sanitize_filename(name):
    """Dateinamen säubern: nur [A-Za-z0-9._-] erlaubt."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", str(name)).strip("._")
    return cleaned or "plot_job.gcode"


class PrinterConnection:
    """Basis: HTTP-Requests an die Drucker-API."""

    def __init__(self, host, api_key="", timeout=15, upload_timeout=UPLOAD_TIMEOUT):
        self.host = host.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.upload_timeout = upload_timeout

    def _url(self, path):
        return f"{self.host}{path}"

    def _request(self, method, path, data=None, headers=None):
        url = self._url(path)
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Content-Type", "application/json")
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raise PrinterConnectionError(
                f"HTTP {e.code} von {url} – {e.reason}. "
                f"Tipp: IP prüfen (ggf. mit Port angeben, z. B. 192.168.1.50:7125) "
                "und API-Key korrekt?") from e
        except (urllib.error.URLError, OSError) as e:
            raise PrinterConnectionError(
                f"Netzwerkfehler ({self.host}): {e}. "
                "Tipp: Ist der Drucker im selben Netzwerk und die IP richtig?") from e


class MoonrakerConnection(PrinterConnection):
    """Klipper über Moonraker (z. B. Fluidd/Mainsail-Reverse-Proxy auf Standard-Port)."""

    def __init__(self, host, api_key="", timeout=15):
        if "://" not in host:
            host = f"http://{host}"
        super().__init__(host, api_key, timeout)

    def _headers(self):
        h = {}
        if self.api_key:
            h["X-Api-Key"] = self.api_key
        return h

    def get_position(self):
        """Aktuelle Position; liefert IMMER (x, y, z)."""
        res = self._request("POST", "/printer/objects/query",
                            {"objects": {"toolhead": None}}, headers=self._headers())
        pos = (res.get("result", {}).get("status", {})
               .get("toolhead", {}).get("position", []))
        if len(pos) < 2:
            raise PrinterConnectionError("Position konnte nicht gelesen werden (toolhead nicht verfügbar).")
        z = pos[2] if len(pos) >= 3 else None
        return (float(pos[0]), float(pos[1]), z)

    def jog(self, x=None, y=None, z=None, speed=80):
        parts = ["G91"]
        vals = []
        if x is not None:
            vals.append(f"X{x:+.2f}")
        if y is not None:
            vals.append(f"Y{y:+.2f}")
        if z is not None:
            vals.append(f"Z{z:+.2f}")
        parts.append(f"G1 {' '.join(vals)} F{int(speed * 60)}")
        parts.append("G90")
        self._request("POST", "/printer/gcode/script", {"script": "\n".join(parts)}, headers=self._headers())

    def move_absolute(self, x, y, speed=80):
        script = f"G90\nG1 X{x:.2f} Y{y:.2f} F{int(speed * 60)}"
        self._request("POST", "/printer/gcode/script", {"script": script}, headers=self._headers())

    def home(self, axes="XY"):
        script = "G28 " + " ".join(a.upper() for a in axes)
        self._request("POST", "/printer/gcode/script", {"script": script}, headers=self._headers())

    def home_z(self):
        self.home("Z")

    def upload_and_start(self, gcode_text, filename="plot_job.gcode"):
        """G-Code hochladen und Druck EXPLIZIT starten.

        Das 'print=true'-Flag beim Upload wird von Moonraker je Konfiguration
        ignoriert oder nur in die Job-Queue gelegt. Robust ist der explizite
        Start: POST /printer/print/start {"filename": ...}.
        """
        filename = sanitize_filename(filename)
        boundary = uuid.uuid4().hex
        body = io.BytesIO()
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode())
        body.write(b"Content-Type: application/octet-stream\r\n\r\n")
        body.write(gcode_text.encode())
        body.write(f"\r\n--{boundary}--\r\n".encode())
        req = urllib.request.Request(
            self._url("/server/files/upload?root=gcodes"),
            data=body.getvalue(), method="POST")
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        if self.api_key:
            req.add_header("X-Api-Key", self.api_key)
        try:
            with urllib.request.urlopen(req, timeout=self.upload_timeout) as resp:
                resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            raise PrinterConnectionError(f"Upload fehlgeschlagen: {e}") from e
        # Druck jetzt explizit starten (Datei liegt im gcodes-Root)
        self._request("POST", "/printer/print/start",
                      {"filename": filename}, headers=self._headers())

    def emergency_stop(self):
        """Sofort-Notaus (direkt, nicht über die G-Code-Warteschlange)."""
        self._request("POST", "/printer/emergency_stop", headers=self._headers())

    def cancel_print(self):
        self._request("POST", "/printer/print/cancel", headers=self._headers())

    def get_state(self):
        """Klippy-Zustand abfragen ('ready', 'error', 'shutdown', ...)."""
        res = self._request("GET", "/printer/info", headers=self._headers())
        return res.get("result", {}).get("state", "unknown")

    def is_printing(self):
        res = self._request("POST", "/printer/objects/query",
                            {"objects": {"print_stats": None}}, headers=self._headers())
        return res.get("result", {}).get("status", {}).get("print_stats", {}).get("state") == "printing"


class OctoPrintConnection(PrinterConnection):
    """OctoPrint, Standard-Port 80 (API-Key erforderlich)."""

    def __init__(self, host, api_key="", timeout=15):
        if "://" not in host:
            host = f"http://{host}"
        super().__init__(host, api_key, timeout)
        if not self.api_key:
            raise PrinterConnectionError("OctoPrint benötigt einen API-Key (Einstellungen → API).")

    def _headers(self):
        return {"X-Api-Key": self.api_key}

    def get_position(self):
        """Position über /api/printer/printhead; liefert IMMER (x, y, z),
        z = None, wenn die Z-Höhe unbekannt ist."""
        res = self._request("GET", "/api/printer/printhead?history=false", headers=self._headers())
        def axis_val(v):
            if isinstance(v, dict):
                return v.get("current") or v.get("offset") or 0.0
            return v or 0.0
        x, y, z = axis_val(res.get("x")), axis_val(res.get("y")), res.get("z")
        if x is None or y is None:
            raise PrinterConnectionError("Position konnte nicht gelesen werden (printhead nicht verfügbar).")
        z_val = None
        if z is not None:
            z_val = float(axis_val(z))
        return (float(x), float(y), z_val)

    def jog(self, x=None, y=None, z=None, speed=80):
        cmds = []
        vals = []
        if x is not None:
            vals.append(f"X{x:+.2f}")
        if y is not None:
            vals.append(f"Y{y:+.2f}")
        if z is not None:
            vals.append(f"Z{z:+.2f}")
        cmds.append("G91")
        cmds.append(f"G1 {' '.join(vals)} F{int(speed * 60)}")
        cmds.append("G90")
        for c in cmds:
            self._request("POST", "/api/printer/command", {"commands": [c]}, headers=self._headers())

    def move_absolute(self, x, y, speed=80):
        self._request("POST", "/api/printer/command",
                      {"commands": [f"G90", f"G1 X{x:.2f} Y{y:.2f} F{int(speed * 60)}"]},
                      headers=self._headers())

    def home(self, axes="XY"):
        """Homed NUR die angegebenen Achsen (nicht immer alles)."""
        cmd = "G28 " + " ".join(a.upper() for a in axes)
        self._request("POST", "/api/printer/command", {"commands": [cmd]}, headers=self._headers())

    def upload_and_start(self, gcode_text, filename="plot_job.gcode"):
        import io
        import uuid
        filename = sanitize_filename(filename)
        boundary = uuid.uuid4().hex
        body = io.BytesIO()
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode())
        body.write(b"Content-Type: application/octet-stream\r\n\r\n")
        body.write(gcode_text.encode())
        body.write(f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="select"\r\n\r\ntrue\r\n'.encode())
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="print"\r\n\r\ntrue\r\n'.encode())
        body.write(f"--{boundary}--\r\n".encode())
        req = urllib.request.Request(self._url("/api/files/local"), data=body.getvalue(), method="POST")
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        req.add_header("X-Api-Key", self.api_key)
        try:
            with urllib.request.urlopen(req, timeout=self.upload_timeout) as resp:
                resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            raise PrinterConnectionError(f"Upload fehlgeschlagen: {e}") from e

    def is_printing(self):
        res = self._request("GET", "/api/job", headers=self._headers())
        return res.get("state") in ("printing", "pausing", "paused")


def create_connection(kind, host, api_key=""):
    if kind == "moonraker":
        return MoonrakerConnection(host, api_key)
    if kind == "octoprint":
        return OctoPrintConnection(host, api_key)
    raise PrinterConnectionError(f"Unbekannter Verbindungstyp: {kind}")
