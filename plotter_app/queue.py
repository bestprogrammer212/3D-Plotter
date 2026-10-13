"""Thread-sichere Befehlswarteschlange + Auto-Reconnect für die Druckerverbindung.

Alle Aktionen (Jog, Home, Plot) laufen über einen seriellen FIFO-Sender:
- keine verlorenen Befehle, keine falsche Reihenfolge
- die UI blockiert nie (Antworten kommen per Callback zurück)
- bei Verbindungsabbruch: automatischer Reconnect mit Backoff
"""
import json
import queue
import threading
import time
import urllib.error
import urllib.request

from .network import MoonrakerConnection, OctoPrintConnection, PrinterConnectionError

RECONNECT_DELAYS = [1, 2, 3, 5, 5, 10, 10, 15]


class QueuedConnection:
    """Wrapper um eine Drucker-Verbindung mit Warteschlange und Auto-Reconnect."""

    def __init__(self, kind, host, api_key="", on_status=None):
        self.kind = kind
        self.host = host
        self.api_key = api_key
        self.on_status = on_status or (lambda text, ok: None)
        self._queue = queue.Queue()
        self._pos_cache = (0.0, 0.0, 0.0)
        self._conn = None
        self._connected = False
        self._stop = False
        self._thread = None
        self._lock = threading.Lock()
        # KEIN Verbindungsaufbau im Konstruktor (blockiert sonst die GUI
        # bis zu 15 s); der _run-Thread verbindet beim ersten Durchlauf.

    # ---------- Aufbau / Reconnect ----------

    def _make_connection(self):
        if self.kind == "moonraker":
            return MoonrakerConnection(self.host, self.api_key)
        if self.kind == "octoprint":
            return OctoPrintConnection(self.host, self.api_key)
        raise PrinterConnectionError(f"Unbekannter Typ: {self.kind}")

    def _connect(self):
        self.on_status(f"Verbinde mit {self.host} …", False)
        try:
            conn = self._make_connection()
            pos = conn.get_position()  # Test-Abfrage
            with self._lock:
                self._conn = conn
                self._connected = True
                self._pos_cache = pos
            self.on_status(f"Verbunden mit {self.host} ✓", True)
            return True
        except PrinterConnectionError as e:
            self.on_status(f"Verbindung fehlgeschlagen: {e}", False)
            return False

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop = True

    # ---------- Hauptschleife ----------

    def _run(self):
        first_attempt = True
        reconnect_try = 0
        while not self._stop:
            # Erst reconnectieren, wenn die Verbindung weg ist
            if not self.is_connected():
                if first_attempt:
                    # Erster Versuch: sofort ohne Delay
                    first_attempt = False
                else:
                    reconnect_try += 1
                    delay = RECONNECT_DELAYS[min(reconnect_try - 1, len(RECONNECT_DELAYS) - 1)]
                    self.on_status(f"Reconnect in {delay}s … ({reconnect_try}. Versuch)", False)
                    deadline = time.time() + delay
                    while time.time() < deadline and not self._stop:
                        time.sleep(0.1)
                if self._stop:
                    return
                if self._connect():
                    reconnect_try = 0
                    continue  # Task jetzt erneut versuchen
                continue  # naechster Reconnect-Versuch

            try:
                task = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            action, args, kwargs, callback, replay = task
            try:
                conn = self._get_conn()
                result = getattr(conn, action)(*args, **kwargs)
                if action == "get_position":
                    with self._lock:
                        self._pos_cache = result
                reconnect_try = 0
                if callback:
                    callback(result, None)
            except PrinterConnectionError as e:
                with self._lock:
                    self._connected = False
                self.on_status(f"Verbindung verloren: {e}", False)
                # Nur idempotente Befehle wiederholen (kein Jog!)
                if replay:
                    # Task zurueck in die Queue und KEIN Fehler-Callback:
                    # der Callback feuert erst nach erfolgreicher Ausfuehrung,
                    # sonst erhielte der Aufrufer Fehler UND Erfolg.
                    self._queue.put(task)
                elif callback:
                    callback(None, str(e))
            except Exception as e:
                # Unerwarteter Fehler (z. B. defekte Server-Antwort):
                # nicht crashen, sondern als Fehler melden
                if callback:
                    callback(None, str(e))

    def _get_conn(self):
        with self._lock:
            if not self._connected:
                raise PrinterConnectionError("Nicht verbunden")
            return self._conn

    def is_connected(self):
        with self._lock:
            return self._connected

    # ---------- Öffentliche API (nicht blockierend) ----------

    def _submit(self, action, *args, callback=None, replay=True, **kwargs):
        self._queue.put((action, args, kwargs, callback, replay))

    def jog(self, x=None, y=None, z=None, callback=None):
        # Relative Bewegung: NICHT wiederholen (Verdopplungs-Gefahr)
        self._submit("jog", x=x, y=y, z=z, callback=callback, replay=False)

    def home(self, axes="XY", callback=None):
        self._submit("home", axes, callback=callback)

    def home_z(self, callback=None):
        self._submit("home_z", callback=callback)

    def move_absolute(self, x, y, callback=None):
        self._submit("move_absolute", x, y, callback=callback)

    def emergency_stop(self, callback=None):
        """Notaus: blockierend und sofort (kein Queue-Umweg für maximale Sicherheit)."""
        try:
            conn = self._get_conn()
            conn.emergency_stop()
            if callback:
                callback(True, None)
        except PrinterConnectionError as e:
            if callback:
                callback(None, str(e))

    def plot_items(self, items, callback=None, on_color_pause=None, on_progress=None):
        """Live-Plot mit Pause/Stopp-Steuerung.

        items: Liste aus Befehls-Listen (G-Code-Zeilen) und ('pause', farbe)-
        Markern. Bei einem Farbwechsel stoppt der Plot, bis resume_plot()
        aufgerufen wird (on_color_pause(farbe) informiert die GUI).
        stop_plot() bricht ab: laufende Bewegung wird abgebrochen, Stift hoch.
        """
        state = {"i": 0, "done": False, "paused": False, "stopped": False,
                 "waiting": False, "items": items}
        self._plot_state = state

        def finish(ok, err):
            if state["done"]:
                return
            state["done"] = True
            self._plot_state = None
            if callback:
                callback(ok, err)

        def send_next():
            if state["stopped"] or state["done"]:
                return
            if state["paused"]:
                return
            i = state["i"]
            if i >= len(items):
                finish(True, None)
                return
            item = items[i]
            if isinstance(item, tuple) and len(item) == 2 and item[0] == "pause":
                state["paused"] = True
                if on_color_pause:
                    on_color_pause(item[1])
                return
            def group_cb(ok, err):
                if state["stopped"] or state["done"]:
                    return
                if err:
                    finish(None, err)
                    return
                if on_progress:
                    on_progress(state["i"])  # Index des fertigen Items
                state["i"] += 1
                send_next()
            self._submit("send_script", "\n".join(item), callback=group_cb, replay=False)

        send_next()
        state["advance"] = send_next

    def _send_now_safe(self, script):
        """G-Code SOFORT und ohne Queue senden – crasht nie: Verbindungs-
        oder Serverfehler werden geschluckt (GUI bleibt stabil)."""
        try:
            conn = self._get_conn()
            conn.send_script(script)
        except Exception:
            pass

    def pause_plot(self):
        """SOFORT-Pause: laufende Bewegung anhalten (Klipper: PAUSE + Stift hoch,
       _octoprint: aktuelles G-Code abbrechen) und keine weiteren Gruppen senden.
        """
        st = getattr(self, "_plot_state", None)
        if st and not st["done"]:
            st["paused"] = True
        # Bewegung SOFORT anhalten + Stift anheben (beide APIs)
        self._send_now_safe("PAUSE")
        self._send_now_safe("G91\nG1 Z5\nG90")

    def resume_plot(self):
        """Pause/Farbwechsel bestaetigt: weiterplotten."""
        st = getattr(self, "_plot_state", None)
        if st and st.get("paused") and not st["done"]:
            st["paused"] = False
            if st["i"] < len(st["items"]) and isinstance(st["items"][st["i"]], tuple):
                st["i"] += 1  # Farbwechsel-Marker verwerfen
            # RESUME schadet nicht, wenn gar nicht pausiert war (Klipper
            # ignoriert es dann); verhindert haengende Pause-Reste.
            self._send_now_safe("RESUME")
            try:
                st["advance"]()
            except Exception:
                pass

    def stop_plot(self):
        """Plot ABBRECHEN: Bewegung sofort stoppen, Stift hoch, alles verwerfen."""
        st = getattr(self, "_plot_state", None)
        if st:
            st["stopped"] = True
            st["paused"] = False
        self._send_now_safe("CANCEL_PRINT")
        try:
            conn = self._get_conn()
            conn.cancel_print()
        except Exception:
            pass
        self._send_now_safe("G91\nG1 Z10\nG90")
        self._queue = queue.Queue()  # wartende Befehle verwerfen
        if st and not st["done"]:
            st["done"] = True
            self._plot_state = None

    def plot_groups(self, groups, callback=None):
        """Plot per Einzelbefehlen statt G-Code-Upload: eine Gruppe pro Pfad.

        Die Gruppen werden verkettet einzeln gesendet: erst wenn eine Gruppe
        erfolgreich war, wird die naechste geschickt. Bei einem Fehler stoppt
        der Plot sofort (kein unkontrolliertes Weiterzeichnen nach Reconnect);
        der finale Callback feuert genau einmal mit dem Fehler.
        """
        state = {"i": 0, "done": False}

        def send_next():
            i = state["i"]
            if i >= len(groups):
                if callback and not state["done"]:
                    state["done"] = True
                    callback(True, None)
                return

            def group_cb(ok, err):
                if state["done"]:
                    return
                if err:
                    state["done"] = True
                    if callback:
                        callback(None, err)
                    return
                state["i"] += 1
                send_next()

            self._submit("send_script", "\n".join(groups[i]), callback=group_cb, replay=False)

        send_next()

    def upload_and_start(self, gcode, filename="plot_job.gcode", callback=None):
        """Upload blockiert bewusst (große Datenmenge), aber mit Callback-Ergebnis."""
        def work():
            try:
                conn = self._get_conn()
                conn.upload_and_start(gcode, filename)
                if callback:
                    callback(True, None)
            except PrinterConnectionError as e:
                if callback:
                    callback(None, str(e))
            except Exception as e:  # unerwartete Fehler duerfen den Thread nicht toeten
                if callback:
                    callback(None, f"Upload-Fehler: {e}")
        threading.Thread(target=work, daemon=True).start()

    def is_printing(self, callback):
        """Asynchron pruefen, ob gerade ein Druck laeuft (kein GUI-Block)."""
        self._submit("is_printing", callback=callback, replay=False)

    def request_position(self, callback):
        """Position asynchron abfragen; Ergebnis kommt über callback."""
        self._submit("get_position", callback=callback)

    def get_cached_position(self):
        with self._lock:
            return self._pos_cache
