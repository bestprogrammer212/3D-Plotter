"""Moderne PySide6/Qt-Oberfläche der Plotter-App (ersetzt die tkinter-GUI)."""
import math
import sys

from PySide6 import QtCore, QtGui, QtWidgets

from datetime import datetime

from . import settings, tools
from .calibration import Calibration
from .gcode import plot_command_groups, save_gcode
from .network import PrinterConnectionError
from .queue import QueuedConnection
from .pen import PenSettings
from .profiles import load_builtin, load_printer_profile
from .svg import load_svg

DARK = """
QWidget { background-color: #1e1f22; color: #e6e6e6; font-size: 13px; }
QMainWindow, QDialog { background-color: #1e1f22; }
QLabel { color: #bababa; }
QPushButton { background-color: #2b2d31; border: 1px solid #3f4147; border-radius: 6px;
              padding: 6px 14px; color: #e6e6e6; }
QPushButton:hover { background-color: #3a3d44; }
QPushButton:pressed { background-color: #464a53; }
QPushButton#estop { background-color: #c62828; color: white; font-weight: bold; border: none; border-radius: 6px; }
QPushButton#estop:hover { background-color: #e53935; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: #2b2d31; border: 1px solid #3f4147; border-radius: 4px; padding: 4px 6px; }
QListWidget, QTreeWidget { background-color: #26272b; border: 1px solid #3f4147; border-radius: 4px; }
QTabWidget::pane { border: 1px solid #3f4147; border-radius: 4px; }
QTabBar::tab { background: #2b2d31; padding: 8px 18px; margin-right: 2px;
               border-top-left-radius: 4px; border-top-right-radius: 4px; }
QTabBar::tab:selected { background: #35383f; color: white; }
QGroupBox { border: 1px solid #3f4147; border-radius: 6px; margin-top: 8px;
            padding-top: 14px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #9aa0aa; }
QSlider::groove:horizontal { height: 4px; background: #3f4147; border-radius: 2px; }
QSlider::handle:horizontal { background: #4f8cff; width: 14px; margin: -5px 0; border-radius: 7px; }
QRadioButton { color: #e6e6e6; }
QCheckBox { color: #e6e6e6; }
QStatusBar { background: #26272b; color: #9aa0aa; }
"""


class _MainThreadRelay(QtCore.QObject):
    """Signal-Relay: Signale aus beliebigem Thread werden (queued) im
    GUI-Thread ausgefuehrt. QTimer.singleShot funktioniert NICHT aus dem
    Queue-/Netzwerk-Thread (kein Qt-Event-Loop dort)."""
    call = QtCore.Signal(object)

    def __init__(self):
        super().__init__()
        self.call.connect(self._run_call)

    def _run_call(self, fn):
        fn()


_RELAY = None


def on_main_thread(fn):
    """Fuehrt fn im GUI-Thread aus (thread-sicher aus jedem Thread).

    Das Relay MUSS vorher im GUI-Thread initialisiert worden sein
    (init_main_thread_relay in PlotterWindow.__init__ / main()) – ein
    QObject darf nicht aus dem Netzwerk-Thread erzeugt werden.
    """
    _RELAY.call.emit(fn)


def init_main_thread_relay():
    """Relay im GUI-Thread anlegen (vor jedem Thread-Start aufrufen)."""
    global _RELAY
    if _RELAY is None:
        _RELAY = _MainThreadRelay()


class PaperCanvas(QtWidgets.QWidget):
    """Canvas mit Papier, Design-Pfaden und (optional) Stift-Position."""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setMinimumSize(400, 300)
        self.setMouseTracking(True)

    def paintEvent(self, _event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QtGui.QColor("#151619"))

        # Papier
        margin = 24
        pw, ph = w - 2 * margin, h - 2 * margin
        p.setPen(QtGui.QPen(QtGui.QColor("#8a7a30"), 2))
        p.setBrush(QtGui.QColor("#fff8e1"))
        p.drawRect(margin, margin, pw, ph)
        p.setPen(QtGui.QPen(QtGui.QColor("#efe3b8"), 1))
        for i in range(1, 10):
            x = margin + pw * i / 10
            y = margin + ph * i / 10
            p.drawLine(int(x), margin, int(x), int(margin + ph))
            p.drawLine(margin, int(y), int(margin + pw), int(y))

        # Design-Pfade
        p.setPen(QtGui.QPen(QtGui.QColor("#1565c0"), 2))
        paths = self.app.paths + ([self.app.free_path] if self.app.free_path else [])
        for path in paths:
            if len(path) < 2:
                continue
            poly = QtGui.QPolygonF()
            for (px, py) in path:
                poly.append(QtCore.QPointF(margin + px * pw, margin + (1 - py) * ph))
            p.drawPolyline(poly)

        # Stift-Position
        if self.app.pen_pos:
            px, py = self.app.pen_pos
            p.setPen(QtGui.QPen(QtGui.QColor("#e65100"), 2))
            p.setBrush(QtGui.QColor("#ff9800"))
            cx, cy = margin + px * pw, margin + (1 - py) * ph
            p.drawEllipse(QtCore.QPointF(cx, cy), 6, 6)

    def mousePressEvent(self, e):
        margin = 24
        pw, ph = self.width() - 2 * margin, self.height() - 2 * margin
        x = (e.position().x() - margin) / pw
        y = 1 - (e.position().y() - margin) / ph
        if 0 <= x <= 1 and 0 <= y <= 1:
            self.app.free_path = [(x, y)]
            self.update()

    def mouseMoveEvent(self, e):
        if self.app.free_path is None:
            return
        margin = 24
        pw, ph = self.width() - 2 * margin, self.height() - 2 * margin
        x = max(0.0, min(1.0, (e.position().x() - margin) / pw))
        y = max(0.0, min(1.0, 1 - (e.position().y() - margin) / ph))
        self.app.free_path.append((x, y))
        self.update()

    def mouseReleaseEvent(self, _e):
        if self.app.free_path and len(self.app.free_path) > 1:
            self.app.paths.append(self.app.free_path)
        self.app.free_path = None
        self.update()


def _point_in_polygon(pt, poly):
    """Standard-Raycasting-Test: liegt pt im (geschlossenen) Polygon poly?"""
    if len(poly) < 3:
        return False
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xin:
                inside = not inside
    return inside


class DesignCanvas(QtWidgets.QWidget):
    """Druckplatte mit kalibriertem Papier-Polygon und den Design-Pfaden
    in ihrer echten Plot-Position auf dem Bett. Formen lassen sich mit
    der Maus verschieben (Drag & Drop)."""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setMinimumHeight(320)
        self.setMouseTracking(True)
        self._drag = None   # (pfad-indizes, start-paper-x, start-paper-y, backups)
        self._lasso = None  # aktuelle Lasso-Punkte (Bildschirm)

    def _paper_pos(self, e):
        """Maus-Punkt -> Papier-Koordinaten (0..1); None wenn ausserhalb."""
        cal = self.app.calibration
        bw = self.app.current_printer["bed_x"] if self.app.current_printer else 220.0
        bh = self.app.current_printer["bed_y"] if self.app.current_printer else 220.0
        margin = 16
        scale = min((self.width() - 2 * margin) / bw, (self.height() - 2 * margin) / bh)
        ox = (self.width() - bw * scale) / 2
        oy = (self.height() - bh * scale) / 2
        x = (e.position().x() - ox) / (bw * scale)
        y = 1 - (e.position().y() - oy) / (bh * scale)
        if cal.is_complete:
            # Maschinen-Koordinate zurueck in Papier-Koordinaten
            try:
                mx = (e.position().x() - ox) / scale
                my = bh - (e.position().y() - oy) / scale
                # naechstliegenden Papier-Punkt invertieren: Raster-Suche
                best, bd = None, 1e9
                for i in range(21):
                    for j in range(21):
                        cx, cy = cal.paper_to_machine(i / 20, j / 20)
                        d = (cx - mx) ** 2 + (cy - my) ** 2
                        if d < bd:
                            bd, best = d, (i / 20, j / 20)
                # Fein-Interpolation: 5x5 um den besten Punkt
                bi, bj = best
                for di in range(-2, 3):
                    for dj in range(-2, 3):
                        px = min(1.0, max(0.0, bi + di / 100))
                        py = min(1.0, max(0.0, bj + dj / 100))
                        cx, cy = cal.paper_to_machine(px, py)
                        d = (cx - mx) ** 2 + (cy - my) ** 2
                        if d < bd:
                            bd, best = d, (px, py)
                return best
            except ValueError:
                return None
        if 0 <= x <= 1 and 0 <= y <= 1:
            return (x, y)
        return None

    def _hit_path(self, pt):
        """Index des Pfades unter dem Punkt (naechster Punkt < 0.02 Abstand)."""
        for idx in range(len(self.app.paths) - 1, -1, -1):
            for (px, py) in self.app.paths[idx]:
                if (px - pt[0]) ** 2 + (py - pt[1]) ** 2 < 0.02 ** 2:
                    return idx
        # Flaeche: Punkt im Inneren? Polygon-Test gegen die Pfad-Huelle
        for idx in range(len(self.app.paths) - 1, -1, -1):
            poly = self.app.paths[idx]
            if _point_in_polygon(pt, poly):
                return idx
        return None

    def mousePressEvent(self, e):
        pt = self._paper_pos(e)
        if pt is None:
            return
        if e.modifiers() & QtCore.Qt.ControlModifier or self.app.lasso_mode:
            # Lasso-Start: Auswahl aufziehen
            self._lasso = [pt]
            if not (e.modifiers() & QtCore.Qt.ShiftModifier) and not self.app.lasso_mode:
                self.app.selected.clear()
            return
        idx = self._hit_path(pt)
        if idx is not None:
            if e.modifiers() & QtCore.Qt.ShiftModifier:
                self.app.selected ^= {idx}
            elif idx not in self.app.selected:
                self.app.selected = {idx}
            idxs = sorted(self.app.selected) or [idx]
            self._drag = (idxs, pt[0], pt[1],
                          {i: list(self.app.paths[i]) for i in idxs})
            self.setCursor(QtCore.Qt.ClosedHandCursor)
        else:
            self.app.selected.clear()
        self.update()

    def mouseMoveEvent(self, e):
        if self._lasso is not None:
            pt = self._paper_pos(e)
            if pt is not None:
                self._lasso.append(pt)
                self._update_lasso_selection()
            self.update()
            return
        if self._drag is None:
            pt = self._paper_pos(e)
            if pt is not None and self._hit_path(pt) is not None:
                self.setCursor(QtCore.Qt.OpenHandCursor)
            else:
                self.setCursor(QtCore.Qt.ArrowCursor)
            return
        pt = self._paper_pos(e)
        if pt is None:
            return
        idxs, sx, sy, backups = self._drag
        dx, dy = pt[0] - sx, pt[1] - sy
        for i in idxs:
            self.app.paths[i] = [(min(1.0, max(0.0, x + dx)),
                                  min(1.0, max(0.0, y + dy))) for (x, y) in backups[i]]
        self.update()

    def _update_lasso_selection(self):
        """Alle Pfade whlen, deren Punkte im Lasso-Polygon liegen."""
        if not self._lasso or len(self._lasso) < 3:
            return
        poly = self._lasso
        self.app.selected = {
            i for i, path in enumerate(self.app.paths)
            if any(_point_in_polygon(p, poly) for p in path)}

    def mouseReleaseEvent(self, _e):
        if self._lasso is not None:
            self._update_lasso_selection()
            self._lasso = None
        self._drag = None
        self.setCursor(QtCore.Qt.ArrowCursor)
        self.update()

    def paintEvent(self, _event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QtGui.QColor("#151619"))

        cal = self.app.calibration
        bw = self.app.current_printer["bed_x"] if self.app.current_printer else 220.0
        bh = self.app.current_printer["bed_y"] if self.app.current_printer else 220.0

        margin = 16
        scale = min((w - 2 * margin) / bw, (h - 2 * margin) / bh)
        ox = (w - bw * scale) / 2
        oy = (h - bh * scale) / 2

        # Druckplatte
        p.setPen(QtGui.QPen(QtGui.QColor("#555"), 2))
        p.setBrush(QtGui.QColor("#202226"))
        p.drawRect(QtCore.QRectF(ox, oy, bw * scale, bh * scale))
        p.setPen(QtGui.QPen(QtGui.QColor("#333"), 1))
        for g in range(0, int(bw) + 1, 50):
            x = ox + g * scale
            p.drawLine(QtCore.QLineF(x, oy, x, oy + bh * scale))
        for g in range(0, int(bh) + 1, 50):
            y = oy + (bh - g) * scale
            p.drawLine(QtCore.QLineF(ox, y, ox + bw * scale, y))

        # Papier-Polygon (falls kalibriert): Design in echter Position zeichnen
        paths = self.app.paths + ([self.app.free_path] if self.app.free_path else [])
        colors = list(self.app.path_colors) + [None] * (len(paths) - len(self.app.path_colors))
        if cal.is_complete:
            poly = QtGui.QPolygonF()
            for (x, y) in cal.polygon:
                poly.append(QtCore.QPointF(ox + x * scale, oy + (bh - y) * scale))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor(255, 243, 32, 60))
            p.drawPolygon(poly)
            p.setPen(QtGui.QPen(QtGui.QColor("#c6a700"), 1, QtCore.Qt.DashLine))
            p.drawPolygon(poly)

            # Design-Pfade auf das kalibrierte Papier gemappt (in Pfad-Farbe)
            for pi, path in enumerate(paths):
                if len(path) < 2:
                    continue
                col = QtGui.QColor(colors[pi] or "#1565c0")
                if pi in self.app.selected:
                    p.setPen(QtGui.QPen(col, 3))
                else:
                    p.setPen(QtGui.QPen(col, 2))
                poly2 = QtGui.QPolygonF()
                for (px, py) in path:
                    mx, my = cal.paper_to_machine(px, py)
                    poly2.append(QtCore.QPointF(ox + mx * scale, oy + (bh - my) * scale))
                p.drawPolyline(poly2)
        else:
            p.setPen(QtGui.QPen(QtGui.QColor("#9aa0aa")))
            p.drawText(QtCore.QRectF(ox, oy, bw * scale, bh * scale),
                       QtCore.Qt.AlignCenter,
                       "Noch nicht kalibriert\nDesign wird erst nach der\nEcken-Kalibrierung "
                       "auf dem Bett angezeigt.")
            # Design ohne Kalibrierung klein andeuten
            for pi, path in enumerate(paths):
                if len(path) < 2:
                    continue
                col = QtGui.QColor(colors[pi] or "#1565c0")
                pen_w = 2 if pi in self.app.selected else 1
                p.setPen(QtGui.QPen(col, pen_w, QtCore.Qt.DashLine))
                poly2 = QtGui.QPolygonF()
                for (px, py) in path:
                    poly2.append(QtCore.QPointF(ox + px * bw * scale,
                                                oy + (1 - py) * bh * scale))
                p.drawPolyline(poly2)

        # Lasso-Umrandung zeichnen
        if self._lasso and len(self._lasso) >= 2:
            lasso_poly = QtGui.QPolygonF()
            for (px, py) in self._lasso:
                lasso_poly.append(QtCore.QPointF(ox + px * bw * scale,
                                                oy + (1 - py) * bh * scale))
            p.setPen(QtGui.QPen(QtGui.QColor("#4f8cff"), 1, QtCore.Qt.DashLine))
            p.setBrush(QtGui.QColor(79, 140, 255, 40))
            p.drawPolygon(lasso_poly)

        # Stift-Position (klein)
        if self.app.pen_pos:
            px, py = self.app.pen_pos
            p.setPen(QtGui.QPen(QtGui.QColor("#e65100"), 2))
            p.setBrush(QtGui.QColor("#ff9800"))
            p.drawEllipse(QtCore.QPointF(ox + px * scale, oy + (bh - py) * scale), 5, 5)
        p.end()


class BedCanvas(QtWidgets.QWidget):
    """Bett-Vorschau mit kalibrierten Ecken (im Uhrzeigersinn) und Stift-Position."""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setMinimumHeight(260)

    def paintEvent(self, _event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QtGui.QColor("#151619"))

        bw = self.app.current_printer["bed_x"] if self.app.current_printer else 250.0
        bh = self.app.current_printer["bed_y"] if self.app.current_printer else 250.0
        cal = self.app.calibration
        if cal.points:
            xs = [pt[0] for pt in cal.points]
            ys = [pt[1] for pt in cal.points]
            bw = max(bw, max(xs) + 10)
            bh = max(bh, max(ys) + 10)

        margin = 16
        scale = min((w - 2 * margin) / bw, (h - 2 * margin) / bh)
        ox = (w - bw * scale) / 2
        oy = (h - bh * scale) / 2

        # Bett
        p.setPen(QtGui.QPen(QtGui.QColor("#555"), 2))
        p.setBrush(QtGui.QColor("#202226"))
        p.drawRect(QtCore.QRectF(ox, oy, bw * scale, bh * scale))
        p.setPen(QtGui.QPen(QtGui.QColor("#333"), 1))
        for g in range(0, int(bw) + 1, 50):
            x = ox + g * scale
            p.drawLine(QtCore.QLineF(x, oy, x, oy + bh * scale))
        for g in range(0, int(bh) + 1, 50):
            y = oy + (bh - g) * scale
            p.drawLine(QtCore.QLineF(ox, y, ox + bw * scale, y))

        # Ecken-Polygon
        if cal.is_complete:
            poly = QtGui.QPolygonF()
            for (x, y) in cal.polygon:
                poly.append(QtCore.QPointF(ox + x * scale, oy + (bh - y) * scale))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor(46, 125, 50, 90))
            p.drawPolygon(poly)
        for i, (x, y) in enumerate(cal.points, 1):
            cx, cy = ox + x * scale, oy + (bh - y) * scale
            p.setPen(QtGui.QPen(QtGui.QColor("#b71c1c"), 2))
            p.setBrush(QtGui.QColor("#e53935"))
            p.drawEllipse(QtCore.QPointF(cx, cy), 5, 5)
            p.setPen(QtGui.QPen(QtGui.QColor("#ff8a80")))
            p.drawText(QtCore.QPointF(cx + 8, cy - 6), str(i))

        if self.app.pen_pos:
            px, py = self.app.pen_pos
            cx, cy = ox + px * scale, oy + (bh - py) * scale
            p.setPen(QtGui.QPen(QtGui.QColor("#e65100"), 2))
            p.setBrush(QtGui.QColor("#ff9800"))
            p.drawEllipse(QtCore.QPointF(cx, cy), 6, 6)
        p.end()

    def _geom(self):
        """Bett-Geometrie (wie in paintEvent) fuer Maus-Konvertierung."""
        w, h = self.width(), self.height()
        bw = self.app.current_printer["bed_x"] if self.app.current_printer else 250.0
        bh = self.app.current_printer["bed_y"] if self.app.current_printer else 250.0
        cal = self.app.calibration
        if cal.points:
            xs = [pt[0] for pt in cal.points]
            ys = [pt[1] for pt in cal.points]
            bw = max(bw, max(xs) + 10)
            bh = max(bh, max(ys) + 10)
        margin = 16
        scale = min((w - 2 * margin) / bw, (h - 2 * margin) / bh)
        ox = (w - bw * scale) / 2
        oy = (h - bh * scale) / 2
        return bw, bh, scale, ox, oy

    def _pos_from_click(self, e):
        """Klick-Punkt -> Bett-Koordinaten (x, y); None wenn ausserhalb."""
        bw, bh, scale, ox, oy = self._geom()
        x = (e.position().x() - ox) / scale
        y = bh - (e.position().y() - oy) / scale
        if 0 <= x <= bw and 0 <= y <= bh:
            return (x, y)
        return None

    def mousePressEvent(self, e):
        """Klick auf das Bett = ungefaehre Position fuer Ecken-Kalibrierung;
        optional faehrt der Stift sofort dorthin."""
        pos = self._pos_from_click(e)
        if pos is None:
            return
        app = self.app
        app.cal_x.setValue(pos[0])
        app.cal_y.setValue(pos[1])
        app._move_to(pos)
        app.statusBar().showMessage(
            f"Bett-Klick: X={pos[0]:.1f} Y={pos[1]:.1f} (mit WASD/RF verfeinern)", 5000)


class PlotterWindow(QtWidgets.QMainWindow):
    @staticmethod
    def _dspin(lo, hi, value, step=None, decimals=2):
        """QDoubleSpinBox-Helper, kompatibel mit allen PySide6-Versionen."""
        sb = QtWidgets.QDoubleSpinBox()
        sb.setRange(lo, hi)
        sb.setDecimals(decimals)
        if step is not None:
            sb.setSingleStep(step)
        sb.setValue(value)
        return sb

    def __init__(self):
        super().__init__()
        init_main_thread_relay()  # QObject muss im GUI-Thread erzeugt werden
        self.setWindowTitle("3D-Plotter")
        self.resize(1180, 760)
        self.calibration = Calibration()
        self.pen = PenSettings()
        self.printers = load_builtin()
        self.current_printer = None
        self.connection = None
        self.paths = []
        self.path_colors = []   # parallel zu self.paths: '#rrggbb' oder None
        self.selected = set()    # ausgewaehlte Pfad-Indizes (Lasso/Klick)
        self.design_color = "#1565c0"  # Farbe fuer neue Pfade
        self.lasso_mode = False
        self.free_path = None
        self.pen_pos = None
        self._poll_fail = 0
        self._poll_active = True
        self._load_settings()

        # Zentrale Elemente
        self.tabs = QtWidgets.QTabWidget()
        self.setCentralWidget(self.tabs)
        self._build_toolbar()
        self._build_connection_tab()
        self._build_printer_tab()
        self._build_calibration_tab()
        self._build_design_tab()
        self._build_export_tab()
        self._install_jog_shortcuts()
        self._start_polling()

    def _add_paths(self, new_paths, color=None, colors=None):
        """Pfade (und parallel Farben) ins Design aufnehmen."""
        for i, p in enumerate(new_paths):
            if len(p) < 2:
                continue
            self.paths.append(p)
            self.path_colors.append(colors[i] if colors and i < len(colors) else color)
        self.selected.clear()
        self.paper_canvas.update()

    def _remove_path(self, idx):
        self.paths.pop(idx)
        self.path_colors.pop(idx)
        self.selected = {i for i in self.selected if i != idx}
        self.selected = {i - 1 if i > idx else i for i in self.selected}

    def _set_selected_color(self, color):
        """Farbe der Auswahl setzen (leer = allen markierten)."""
        idxs = self.selected or set(range(len(self.paths)))
        for i in idxs:
            if i < len(self.path_colors):
                self.path_colors[i] = color
        self.design_color = color
        self.paper_canvas.update()

    # ---------- Toolbar ----------
    def _build_toolbar(self):
        bar = self.addToolBar("Haupt")
        bar.setMovable(False)
        estop = QtWidgets.QPushButton("⛔ NOTAUS")
        estop.setObjectName("estop")
        estop.clicked.connect(self._emergency_stop)
        bar.addWidget(estop)
        spacer = QtWidgets.QWidget()
        spacer.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        bar.addWidget(spacer)
        bar.addWidget(QtWidgets.QLabel("Schritt:"))
        self.step_combo = QtWidgets.QComboBox()
        for s in ("0.1", "1", "10", "50"):
            self.step_combo.addItem(f"{s} mm", float(s))
        self.step_combo.setCurrentIndex(2)
        bar.addWidget(self.step_combo)
        self.status_position = QtWidgets.QLabel("X –  Y –  Z –")
        bar.addWidget(self.status_position)

    # ---------- Verbindung ----------
    def _build_connection_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QGridLayout(tab)

        gb = QtWidgets.QGroupBox("Verbindung")
        form = QtWidgets.QGridLayout(gb)
        form.addWidget(QtWidgets.QLabel("Typ:"), 0, 0)
        self.kind_combo = QtWidgets.QComboBox()
        self.kind_combo.addItems(["Klipper/Moonraker", "OctoPrint"])
        self.kind_combo.setCurrentIndex(0 if getattr(self, "_saved_kind", "moonraker") == "moonraker" else 1)
        form.addWidget(self.kind_combo, 0, 1)
        form.addWidget(QtWidgets.QLabel("IP/Host:"), 1, 0)
        self.host_edit = QtWidgets.QLineEdit(getattr(self, "_saved_host", "") or "192.168.76.68")
        form.addWidget(self.host_edit, 1, 1)
        form.addWidget(QtWidgets.QLabel("API-Key:"), 2, 0)
        self.key_edit = QtWidgets.QLineEdit()
        self.key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        form.addWidget(self.key_edit, 2, 1)
        connect_btn = QtWidgets.QPushButton("Verbinden")
        connect_btn.clicked.connect(self._connect)
        form.addWidget(connect_btn, 3, 0, 1, 2)
        self.conn_label = QtWidgets.QLabel("Nicht verbunden")
        self.conn_label.setStyleSheet("color:#9aa0aa;")
        form.addWidget(self.conn_label, 4, 0, 1, 2)
        layout.addWidget(gb, 0, 0)

        jog = QtWidgets.QGroupBox("Stift bewegen (WASD = X/Y, R/F = Z – gilt ueberall, Schritt in der Toolbar)")
        jf = QtWidgets.QGridLayout(jog)
        btns = {
            "Y+": (0, 1, lambda: self._jog(0, 1, 0)), "Y-": (2, 1, lambda: self._jog(0, -1, 0)),
            "X-": (1, 0, lambda: self._jog(-1, 0, 0)), "X+": (1, 2, lambda: self._jog(1, 0, 0)),
            "Z+": (0, 4, lambda: self._jog(0, 0, 1)), "Z-": (2, 4, lambda: self._jog(0, 0, -1)),
        }
        for text, (r, c, cmd) in btns.items():
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(cmd)
            jf.addWidget(b, r, c)
        for text, col in [("Home XY", 5), ("Home Z", 6), ("Home XYZ", 7)]:
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(lambda _, t=text: self._home(t))
            jf.addWidget(b, 1, col)
        layout.addWidget(jog, 1, 0)
        layout.setRowStretch(2, 1)

        self.tabs.addTab(tab, "Verbindung")

    # ---------- Drucker ----------
    def _build_printer_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        search = QtWidgets.QHBoxLayout()
        search.addWidget(QtWidgets.QLabel("Suchen:"))
        self.printer_search = QtWidgets.QLineEdit()
        self.printer_search.setPlaceholderText("z. B. elegoo, neptune, ender …")
        self.printer_search.textChanged.connect(self._filter_printers)
        search.addWidget(self.printer_search)
        layout.addLayout(search)

        self.printer_list = QtWidgets.QListWidget()
        self.printer_list.itemClicked.connect(self._select_printer)
        layout.addWidget(self.printer_list)
        self._filter_printers()
        self._select_saved_printer()
        self.tabs.addTab(tab, f"Drucker ({len(self.printers)})")

    def _filter_printers(self):
        q = self.printer_search.text().strip().lower()
        self.printer_list.clear()
        for p in self.printers:
            if q and q not in p["name"].lower() and q not in p.get("vendor", "").lower():
                continue
            self.printer_list.addItem(f"{p['name']}  —  Bett {p['bed_x']}×{p['bed_y']}×{p['bed_z']} mm")

    def _select_saved_printer(self):
        """Gespeicherten Drucker aus den Einstellungen wieder selektieren."""
        name = getattr(self, "_saved_printer", None)
        if not name:
            return
        for row in range(self.printer_list.count()):
            if self.printer_list.item(row).text().split("  \u2014")[0] == name:
                self.printer_list.setCurrentRow(row)
                self.current_printer = next(
                    (p for p in self.printers if p["name"] == name), None)
                return

    def _select_printer(self, item):
        idx = self.printer_list.row(item)
        # Liste ist gefiltert: echtes Objekt über Namen suchen
        name = item.text().split("  —")[0]
        self.current_printer = next((p for p in self.printers if p["name"] == name), None)
        self.statusBar().showMessage(f"Drucker: {self.current_printer['name']}", 5000)

    # ---------- Kalibrierung ----------
    def _build_calibration_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(tab)

        left = QtWidgets.QVBoxLayout()
        gb = QtWidgets.QGroupBox("Ecken erfassen (im Uhrzeigersinn)")
        form = QtWidgets.QGridLayout(gb)
        self.cal_x = self._dspin(-500, 500, 0.0)
        self.cal_y = self._dspin(-500, 500, 0.0)
        self.cal_z = self._dspin(-100, 100, 0.0)
        for w in (self.cal_x, self.cal_y, self.cal_z):
            w.setFixedWidth(90)
        form.addWidget(QtWidgets.QLabel("X:"), 0, 0); form.addWidget(self.cal_x, 0, 1)
        form.addWidget(QtWidgets.QLabel("Y:"), 0, 2); form.addWidget(self.cal_y, 0, 3)
        form.addWidget(QtWidgets.QLabel("Z:"), 0, 4); form.addWidget(self.cal_z, 0, 5)
        read_btn = QtWidgets.QPushButton("Position auslesen")
        read_btn.clicked.connect(self._refresh_position)
        form.addWidget(read_btn, 1, 0, 1, 3)
        add_btn = QtWidgets.QPushButton("Ecke übernehmen")
        add_btn.clicked.connect(self._add_corner)
        form.addWidget(add_btn, 1, 3, 1, 2)
        del_btn = QtWidgets.QPushButton("Ecke löschen")
        del_btn.clicked.connect(self._delete_corner)
        form.addWidget(del_btn, 1, 5)
        self.corner_list = QtWidgets.QListWidget()
        self.corner_list.itemClicked.connect(self._corner_clicked)
        form.addWidget(self.corner_list, 2, 0, 1, 6)
        self.bed_click_moves = QtWidgets.QCheckBox("Beim Klick auf die Platte dorthin fahren")
        self.bed_click_moves.setChecked(True)
        self.bed_click_moves.setToolTip(
            "Klick auf das Bett: Stift faehrt an diese Position (bei aktiver Verbindung)\n"
            "und die Werte werden fuer die Ecke uebernommen.")
        form.addWidget(self.bed_click_moves, 3, 0, 1, 6)
        left.addWidget(gb)

        wiz = QtWidgets.QGroupBox("Stift-Höhe")
        wf = QtWidgets.QGridLayout(wiz)
        preset1 = QtWidgets.QPushButton("Preset: Stift auf Nozzle-Niveau")
        preset1.clicked.connect(lambda: self._mount_preset(0.0))
        preset2 = QtWidgets.QPushButton("Preset: Stift unter Nozzle")
        preset2.clicked.connect(lambda: self._mount_preset(-2.5))
        wf.addWidget(preset1, 0, 0)
        wf.addWidget(preset2, 0, 1)
        adopt = QtWidgets.QPushButton("Aktuelle Höhe = Zeichen-Z")
        adopt.clicked.connect(self._adopt_pen_height)
        wf.addWidget(adopt, 1, 0, 1, 2)
        xy_test_btn = QtWidgets.QPushButton("XY-Offset testen …")
        xy_test_btn.clicked.connect(self._xy_offset_test)
        wf.addWidget(xy_test_btn, 6, 0)
        z_test_btn = QtWidgets.QPushButton("Z-Höhe testen …")
        z_test_btn.clicked.connect(self._z_height_test)
        wf.addWidget(z_test_btn, 6, 1)
        wf.addWidget(QtWidgets.QLabel("Zeichen-Z:"), 2, 0)
        self.pen_draw_spin = self._dspin(-50, 200, self.pen.pen_draw_z)
        self.pen_draw_spin.setValue(self.pen.pen_draw_z)
        self.pen_draw_spin.valueChanged.connect(self._pen_spin_changed)
        wf.addWidget(self.pen_draw_spin, 2, 1)
        wf.addWidget(QtWidgets.QLabel("Stift-Offset X (mm):"), 4, 0)
        self.pen_off_x_spin = self._dspin(-100, 100, self.pen.pen_offset_x)
        self.pen_off_x_spin.setValue(self.pen.pen_offset_x)
        self.pen_off_x_spin.valueChanged.connect(self._pen_offset_changed)
        wf.addWidget(self.pen_off_x_spin, 4, 1)
        wf.addWidget(QtWidgets.QLabel("Stift-Offset Y (mm):"), 5, 0)
        self.pen_off_y_spin = self._dspin(-100, 100, self.pen.pen_offset_y)
        self.pen_off_y_spin.setValue(self.pen.pen_offset_y)
        self.pen_off_y_spin.valueChanged.connect(self._pen_offset_changed)
        wf.addWidget(self.pen_off_y_spin, 5, 1)
        wf.addWidget(QtWidgets.QLabel("Stift hoch:"), 3, 0)
        self.pen_up_spin = self._dspin(-50, 200, self.pen.pen_up_z)
        self.pen_up_spin.setValue(self.pen.pen_up_z)
        self.pen_up_spin.valueChanged.connect(self._pen_spin_changed)
        wf.addWidget(self.pen_up_spin, 3, 1)
        left.addWidget(wiz)
        left.addStretch()
        layout.addLayout(left, 1)

        self.bed_canvas = BedCanvas(self)
        layout.addWidget(self.bed_canvas, 2)
        self.tabs.addTab(tab, "Kalibrieren")

    def _pen_spin_changed(self):
        self.pen.pen_draw_z = self.pen_draw_spin.value()
        self.pen.pen_up_z = self.pen_up_spin.value()

    def _pen_offset_changed(self):
        self.pen.pen_offset_x = self.pen_off_x_spin.value()
        self.pen.pen_offset_y = self.pen_off_y_spin.value()
        if hasattr(self, "design_canvas"):
            self.design_canvas.update()

    def _sync_pen_spins(self):
        self.pen_draw_spin.setValue(self.pen.pen_draw_z)
        self.pen_up_spin.setValue(self.pen.pen_up_z)

    def _xy_offset_test(self):
        """Gefuehrter XY-Offset-Test: Stift faehrt zur Papier-Mitte,
        der Nutzer klickt auf die Platte, wo die Spitze WIRKLICH landet,
        daraus wird der X/Y-Offset berechnet."""
        if not self.connection or not self.connection.is_connected():
            QtWidgets.QMessageBox.warning(self, "XY-Test", "Keine Verbindung zum Drucker.")
            return
        if not self.calibration.is_complete:
            QtWidgets.QMessageBox.warning(
                self, "XY-Test", "Bitte zuerst die Ecken kalibrieren (mindestens 3).")
            return
        btn = QtWidgets.QMessageBox.question(
            self, "XY-Offset testen",
            "Der Stift f\u00e4hrt zur Papier-Mitte.\n\n"
            "Danach auf die Druckplatte klicken, wo die Stiftspitze WIRKLICH "
            "landet (nicht wo sie sein sollte).\n\n Fortfahren?")
        if btn != QtWidgets.QMessageBox.Yes:
            return
        cx, cy = self.calibration.paper_to_machine(0.5, 0.5)
        # Nozzle-Ziel wie beim Plotten: Sollpunkt minus aktuellem Offset
        self.connection.move_absolute(
            cx - self.pen.pen_offset_x, cy - self.pen.pen_offset_y)
        self._xy_test_target = (cx, cy)
        self._xy_test_active = True
        self.statusBar().showMessage(
            "Jetzt auf die Platte klicken, wo die Stiftspitze wirklich ist …", 15000)

    def _z_height_test(self):
        """Gefuehrter Z-Test (Papier-Feeler): Stift zur Mitte, dann in
        kleinen Schritten absenken, bis das Papier gerade noch durchgleitet.
        Diese Hoehe wird als Zeichen-Z uebernommen."""
        if not self.connection or not self.connection.is_connected():
            QtWidgets.QMessageBox.warning(self, "Z-Test", "Keine Verbindung zum Drucker.")
            return
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Z-H\u00f6he testen (Papier-Feeler)")
        v = QtWidgets.QVBoxLayout(dlg)
        info = QtWidgets.QLabel(
            "1. 'Zur Papier-Mitte' dr\u00fccken.\n"
            "2. Papier unter die Stiftspitze schieben.\n"
            "3. Mit '-0.1' / '-1' langsam absenken, bis das Papier gerade "
            "noch unter der Spitze durchgleitet ('+1' korrigiert nach oben).\n"
            "4. '\u00dcbernehmen' setzt die aktuelle H\u00f6he als Zeichen-Z "
            "(Stift hoch = Zeichen-Z + 5 mm).")
        info.setWordWrap(True)
        v.addWidget(info)
        self._ztest_label = QtWidgets.QLabel("Z \u2248 –")
        v.addWidget(self._ztest_label)
        row = QtWidgets.QHBoxLayout()

        def refresh_z():
            self.connection.request_position(
                lambda pos, err: on_main_thread(
                    lambda: self._ztest_label.setText(
                        f"Z \u2248 {pos[2]:.2f} mm"
                        if pos and pos[2] is not None else "Z unbekannt")))

        def go_center():
            if self.calibration.is_complete:
                cx, cy = self.calibration.paper_to_machine(0.5, 0.5)
                self.connection.move_absolute(
                    cx - self.pen.pen_offset_x, cy - self.pen.pen_offset_y)
                QtCore.QTimer.singleShot(500, refresh_z)

        def dz(step):
            self.connection.jog(z=step)
            QtCore.QTimer.singleShot(300, refresh_z)

        def adopt():
            def cb(pos, err):
                def apply():
                    if err or not pos or pos[2] is None:
                        QtWidgets.QMessageBox.warning(
                            self, "Z-Test", "Position konnte nicht gelesen werden.")
                        return
                    self.pen.auto_from_pen_touch(pos[2])
                    self._sync_pen_spins()
                    self.statusBar().showMessage(
                        f"Zeichen-Z = {pos[2]:.2f} mm \u00fcbernommen", 5000)
                    dlg.close()
                on_main_thread(apply)
            self.connection.request_position(cb)

        for text, cmd in (("Zur Papier-Mitte", go_center),
                          ("+1 mm", lambda: dz(1.0)),
                          ("-1 mm", lambda: dz(-1.0)),
                          ("-0.1 mm", lambda: dz(-0.1)),
                          ("\u00dcbernehmen", adopt)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(cmd)
            row.addWidget(b)
        v.addLayout(row)
        close = QtWidgets.QPushButton("Schlie\u00dfen")
        close.clicked.connect(dlg.close)
        v.addWidget(close)
        dlg.exec()

    def _mount_preset(self, offset):
        self.pen.pen_offset_z = offset
        self.pen.pen_draw_z = 0.0 if offset == 0 else offset
        self.pen.pen_up_z = self.pen.pen_draw_z + 5
        self._sync_pen_spins()

    def _adopt_pen_height(self):
        pos = self._get_pos()
        if not pos:
            return
        self.pen.auto_from_pen_touch(pos[2])
        self._sync_pen_spins()
        self.statusBar().showMessage(f"Zeichen-Z = {pos[2]:.2f} mm", 5000)

    def _delete_corner(self):
        """Markierte Ecke loeschen; keine Auswahl = letzte Ecke."""
        row = self.corner_list.currentRow()
        if row < 0 or row >= len(self.calibration.points):
            self.calibration.pop_point()
        else:
            del self.calibration.points[row]
            if row < len(self.calibration.heights):
                del self.calibration.heights[row]
        self._refresh_corners()
        if hasattr(self, "design_canvas"):
            self.design_canvas.update()

    def _corner_clicked(self, item):
        """Angeklickte Ecke in die X/Y/Z-Felder laden."""
        row = self.corner_list.row(item)
        if 0 <= row < len(self.calibration.points):
            x, y = self.calibration.points[row]
            self.cal_x.setValue(x)
            self.cal_y.setValue(y)
            z = self.calibration.heights[row] if row < len(self.calibration.heights) else None
            if z is not None:
                self.cal_z.setValue(z)

    def _add_corner(self):
        self.calibration.add_point(self.cal_x.value(), self.cal_y.value(),
                                   self.cal_z.value())
        self._refresh_corners()

    def _refresh_corners(self):
        self.corner_list.clear()
        for i, (x, y) in enumerate(self.calibration.points, 1):
            z = self.calibration.heights[i - 1] if i <= len(self.calibration.heights) else None
            self.corner_list.addItem(
                f"Ecke {i}:  X={x:.2f}  Y={y:.2f}" + (f"  Z={z:.2f}" if z is not None else ""))
        self.bed_canvas.update()

    # ---------- Design ----------
    def _build_design_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(tab)

        panel = QtWidgets.QVBoxLayout()
        shapes = QtWidgets.QGroupBox("Werkzeug")
        sf = QtWidgets.QGridLayout(shapes)
        self.shape_combo = QtWidgets.QComboBox()
        self.shape_combo.addItems(["Rechteck", "Kreis", "Ellipse", "Stern", "n-Eck",
                                   "Spirale", "Welle", "Herz", "Raster", "Text"])
        sf.addWidget(self.shape_combo, 0, 0, 1, 2)
        sf.addWidget(QtWidgets.QLabel("x / y:"), 1, 0)
        self.shape_x = self._dspin(0, 1, 0.2, 0.05)
        self.shape_y = self._dspin(0, 1, 0.2, 0.05)
        sf.addWidget(self.shape_x, 1, 1)
        sf.addWidget(self.shape_y, 1, 2)
        sf.addWidget(QtWidgets.QLabel("r / Größe:"), 2, 0)
        self.shape_r = self._dspin(0.01, 1, 0.25, 0.05)
        sf.addWidget(self.shape_r, 2, 1)
        sf.addWidget(QtWidgets.QLabel("n:"), 3, 0)
        self.shape_n = QtWidgets.QSpinBox()
        self.shape_n.setRange(3, 24)
        self.shape_n.setValue(6)
        sf.addWidget(self.shape_n, 3, 1)
        sf.addWidget(QtWidgets.QLabel("Text:"), 4, 0)
        self.text_edit = QtWidgets.QLineEdit("PLOT")
        sf.addWidget(self.text_edit, 4, 1, 1, 2)
        draw_btn = QtWidgets.QPushButton("Zeichnen")
        draw_btn.clicked.connect(self._add_shape)
        sf.addWidget(draw_btn, 5, 0, 1, 3)
        panel.addWidget(shapes)

        imp = QtWidgets.QGroupBox("Import")
        imf = QtWidgets.QVBoxLayout(imp)
        svg_btn = QtWidgets.QPushButton("SVG importieren")
        svg_btn.clicked.connect(self._load_svg)
        img_btn = QtWidgets.QPushButton("Bild tracer")
        img_btn.clicked.connect(self._load_image)
        clear_btn = QtWidgets.QPushButton("Alles löschen")
        clear_btn.clicked.connect(self._clear_design)
        for b in (svg_btn, img_btn, clear_btn):
            imf.addWidget(b)
        panel.addWidget(imp)

        sel = QtWidgets.QGroupBox("Auswahl & Farbe")
        self.lasso_check = QtWidgets.QCheckBox("Lasso-Modus (Fläche aufziehen)")
        self.lasso_check.toggled.connect(self._toggle_lasso)
        sel_btn = QtWidgets.QPushButton("Auswahl löschen")
        sel_btn.clicked.connect(lambda: (self.selected.clear(), self.paper_canvas.update()))
        del_btn = QtWidgets.QPushButton("Auswahl löschen (Pfade)")
        del_btn.clicked.connect(self._delete_selected)
        color_btn = QtWidgets.QPushButton("Farbe für Auswahl …")
        color_btn.clicked.connect(self._pick_color)
        self.color_lbl = QtWidgets.QLabel("Farbe: ")
        self._update_color_label()
        sl = QtWidgets.QVBoxLayout(sel)
        for w in (self.lasso_check, sel_btn, del_btn, color_btn, self.color_lbl):
            sl.addWidget(w)
        panel.addWidget(sel)

        presets = QtWidgets.QGroupBox("Vorlagen")
        pf = QtWidgets.QVBoxLayout(presets)
        test_btn = QtWidgets.QPushButton("Höhen-Test")
        test_btn.clicked.connect(lambda: self._add_preset("test"))
        calgrid_btn = QtWidgets.QPushButton("Kalibrier-Raster")
        calgrid_btn.clicked.connect(lambda: self._add_preset("calgrid"))
        pf.addWidget(test_btn)
        pf.addWidget(calgrid_btn)
        panel.addWidget(presets)
        panel.addStretch()
        layout.addLayout(panel)

        # Rechts: Druckplatte mit kalibriertem Papier-Polygon + Design-Pfaden
        right = QtWidgets.QVBoxLayout()
        right.addWidget(QtWidgets.QLabel(
            "Druckplatte mit Papier (gelb) und Design \u2013 das Design erscheint "
            "an der Position, an der es sp\u00e4ter geplottet wird:"), 0)
        self.design_canvas = DesignCanvas(self)
        right.addWidget(self.design_canvas, 1)
        layout.addLayout(right, 3)
        self.paper_canvas = self.design_canvas  # Kompatibilitaet: update() etc.
        self.tabs.addTab(tab, "Design")

    def _toggle_lasso(self, checked):
        self.lasso_mode = checked
        self.design_canvas.setCursor(
            QtCore.Qt.CrossCursor if checked else QtCore.Qt.ArrowCursor)

    def _update_color_label(self):
        self.color_lbl.setText(f"Farbe: {self.design_color}")
        self.color_lbl.setStyleSheet(f"color: {self.design_color};")

    def _pick_color(self):
        col = QtWidgets.QColorDialog.getColor(QtGui.QColor(self.design_color), self, "Farbe wählen")
        if not col.isValid():
            return
        self._set_selected_color(col.name())
        self._update_color_label()

    def _delete_selected(self):
        if not self.selected:
            QtWidgets.QMessageBox.information(self, "Löschen", "Nichts ausgewählt – bitte erst mit Lasso/Klick auswählen.")
            return
        for i in sorted(self.selected, reverse=True):
            self._remove_path(i)
        self.selected.clear()
        self.paper_canvas.update()

    def _add_shape(self):
        x, y = self.shape_x.value(), self.shape_y.value()
        r, n = self.shape_r.value(), self.shape_n.value()
        name = self.shape_combo.currentText()
        m = {"Rechteck": lambda: [tools.rect(x, y, r, r)],
             "Kreis": lambda: [tools.circle(x + r, y + r, r)],
             "Ellipse": lambda: [tools.ellipse(x + r, y + r, r, r * 0.6)],
             "Stern": lambda: [tools.star(x + r, y + r, r, r * 0.4)],
             "n-Eck": lambda: [tools.polygon(x + r, y + r, r, n)],
             "Spirale": lambda: [tools.spiral(x + r, y + r, r)],
             "Welle": lambda: [tools.wave(x, y + r, 2 * r, r * 0.5)],
             "Herz": lambda: [tools.heart(x + r, y + r, r)],
             "Raster": lambda: tools.grid(x, y, 2 * r, 2 * r, n, n),
             "Text": lambda: tools.text_paths(self.text_edit.text(), x, y, r)}
        self._add_paths(m[name](), color=self.design_color)

    def _add_preset(self, kind):
        if kind == "test":
            self._add_paths(tools.test_plot(), color=self.design_color)
        else:
            self._add_paths(tools.calibration_grid(), color=self.design_color)

    def _clear_design(self):
        self.paths.clear()
        self.path_colors.clear()
        self.selected.clear()
        self.paper_canvas.update()

    def _load_svg(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "SVG öffnen", "", "SVG (*.svg)")
        if not path:
            return
        bw = self.current_printer["bed_x"] if self.current_printer else 200
        bh = self.current_printer["bed_y"] if self.current_printer else 200
        try:
            paths = load_svg(path, bed_w=bw, bed_h=bh)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Fehler", f"SVG konnte nicht geladen werden:\n{e}")
            return
        if not paths:
            QtWidgets.QMessageBox.warning(self, "SVG", "Keine Pfade gefunden.")
            return
        self._add_paths(paths, color=self.design_color)
        self.statusBar().showMessage(f"{len(paths)} SVG-Pfade importiert", 5000)

    def _load_image(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Bild öffnen", "", "Bilder (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        farbig = QtWidgets.QMessageBox.question(
            self, "Bild tracer", "Farbig traceren (eine Farbe je Bild-Farbe,\nmit Farbwechsel-Pausen beim Plotten)?")
        try:
            if farbig == QtWidgets.QMessageBox.Yes:
                paths, colors = tools.trace_image_colored(path, resolution=64)
                if not paths:
                    QtWidgets.QMessageBox.warning(self, "Bild tracer", "Keine Farbbereiche gefunden.")
                    return
                self._add_paths(paths, colors=colors)
            else:
                paths = tools.trace_image(path, resolution=64)
                if not paths:
                    QtWidgets.QMessageBox.warning(self, "Bild tracer", "Keine dunklen Bereiche gefunden.")
                    return
                self._add_paths(paths, color=self.design_color)
        except RuntimeError as e:
            QtWidgets.QMessageBox.critical(self, "Fehler", str(e))
            return
        self._update_color_label()
        self.statusBar().showMessage(f"{len(paths)} Bild-Pfade importiert", 5000)

    # ---------- Export ----------
    def _build_export_tab(self):
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.setSpacing(10)
        self.optimize_check = QtWidgets.QCheckBox("Pfade optimieren (weniger Stift-Hübe)")
        self.optimize_check.setChecked(True)
        layout.addWidget(self.optimize_check)

        save_btn = QtWidgets.QPushButton("G-Code speichern unter…")
        save_btn.clicked.connect(self._export_file)
        plot_btn = QtWidgets.QPushButton("Direkt über IP plotten")
        plot_btn.setStyleSheet("font-weight: 600;")
        plot_btn.clicked.connect(self._plot_over_ip)
        layout.addWidget(save_btn)
        layout.addWidget(plot_btn)

        ctrl = QtWidgets.QGroupBox("Live-Plot Steuerung")
        cf = QtWidgets.QHBoxLayout(ctrl)
        self.pause_btn = QtWidgets.QPushButton("⏸ Pause / Weiter")
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.stop_btn = QtWidgets.QPushButton("⏹ Stopp")
        self.stop_btn.clicked.connect(self._stop_plot)
        for b in (self.pause_btn, self.stop_btn):
            cf.addWidget(b)
        layout.addWidget(ctrl)
        self.plot_status = QtWidgets.QLabel("")
        layout.addWidget(self.plot_status)
        layout.addStretch()
        self.tabs.addTab(tab, "Export")

    def _export_file(self):
        if not self._validate_for_export():
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "G-Code speichern", "plot.gcode", "G-Code (*.gcode *.g *.nc)")
        if not path:
            return
        if not path.lower().endswith((".gcode", ".g", ".nc")):
            path += ".gcode"  # fehlende Endung automatisch anhaengen
        paths = tools.optimize_paths(self.paths) if self.optimize_check.isChecked() else self.paths
        save_gcode(path, paths, self.calibration, self.pen)
        self.statusBar().showMessage("G-Code gespeichert", 5000)

    def _plot_over_ip(self):
        if not self._validate_for_export() or not self.connection:
            return
        if not self.connection.is_connected():
            QtWidgets.QMessageBox.warning(self, "Plot", "Keine Verbindung zum Drucker.")
            return
        # Warnung, wenn gerade ein Druck laeuft (asynchron abfragen, kein GUI-Block)
        def printing_cb(printing, err):
            def apply():
                if printing and QtWidgets.QMessageBox.question(
                        self, "Laufender Druck",
                        "Laufender Druck wird abgebrochen, fortfahren?") != QtWidgets.QMessageBox.Yes:
                    return
                self._start_ip_plot()
            on_main_thread(apply)
        self.connection.is_printing(printing_cb)

    def _toggle_pause(self):
        if not self.connection:
            return
        st = getattr(self.connection, "_plot_state", None)
        if st and st.get("paused"):
            self.connection.resume_plot()
            self.plot_status.setText("Plot läuft …")
        else:
            self.connection.pause_plot()
            self.plot_status.setText("Plot pausiert (Stift bleibt oben, nächste Gruppe wartet)")

    def _stop_plot(self):
        if not self.connection:
            return
        self.connection.stop_plot()
        self.plot_status.setText("Plot gestoppt – Stift hoch, Befehle verworfen.")

    def _start_ip_plot(self):
        btn = QtWidgets.QMessageBox.question(self, "Plot starten", "Jetzt über IP plotten?")
        if btn != QtWidgets.QMessageBox.Yes:
            return
        if self.optimize_check.isChecked():
            paths, colors = tools.optimize_paths_colored(self.paths, self.path_colors)
        else:
            paths, colors = self.paths, self.path_colors
        items = plot_command_groups(paths, self.calibration, self.pen, colors=colors)

        def cb(ok, err):
            def apply():
                if err:
                    QtWidgets.QMessageBox.critical(self, "Netzwerkfehler", err)
                    self.plot_status.setText("")
                else:
                    self.plot_status.setText("Plot beendet ✓")
            on_main_thread(apply)

        def color_pause(color):
            def apply():
                self.plot_status.setText(f"⏸ Farbwechsel: bitte Stift auf {color} wechseln, dann „Weiter“.")
                QtWidgets.QMessageBox.information(
                    self, "Farbwechsel",
                    f"Farbwechsel: bitte den Stift auf {color} umtauschen\nund danach „Pause / Weiter“ im Export-Tab drücken.")
            on_main_thread(apply)

        self.connection.plot_items(items, callback=cb, on_color_pause=color_pause)
        self.plot_status.setText("Plot läuft (Befehle werden live gesendet) …")

    def _validate_for_export(self):
        if not self.paths:
            QtWidgets.QMessageBox.warning(self, "Export", "Kein Design vorhanden.")
            return False
        if not self.calibration.is_complete:
            QtWidgets.QMessageBox.warning(self, "Export", "Bitte zuerst kalibrieren (mindestens 3 Ecken).")
            return False
        return True

    # ---------- Netzwerk / Aktionen ----------
    def _on_conn_status(self, text, ok):
        """Callback aus dem Verbindungs-Thread (thread-safe via QueuedConnection)."""
        def apply():
            self.conn_label.setText(text)
            self.conn_label.setStyleSheet("color:#66bb6a;" if ok else "color:#ef5350;")
        on_main_thread(apply)

    def _connect(self):
        kind = "moonraker" if self.kind_combo.currentIndex() == 0 else "octoprint"
        host = self.host_edit.text().strip()
        if not host:
            QtWidgets.QMessageBox.warning(self, "Verbindung", "Bitte IP/Host angeben.")
            return
        if self.connection:
            self.connection.stop()
        self.connection = QueuedConnection(
            kind, host, self.key_edit.text().strip(), on_status=self._on_conn_status)
        self.connection.start()
        self.connection.request_position(
            lambda pos, err: on_main_thread(lambda: self._pos_cb(pos, err)))

    def _pos_cb(self, pos, err):
        if err:
            return
        if pos:
            self._show_pos(pos)
            self.cal_x.setValue(pos[0])
            self.cal_y.setValue(pos[1])
            if pos[2] is not None:
                self.cal_z.setValue(pos[2])

    def _get_pos(self):
        if not self.connection:
            QtWidgets.QMessageBox.warning(self, "Verbindung", "Keine Verbindung.")
            return None
        return self.connection.get_cached_position()

    def _refresh_position(self):
        if not self.connection:
            return
        def cb(pos, err):
            if pos:
                def apply():
                    self._show_pos(pos)
                    self.cal_x.setValue(pos[0])
                    self.cal_y.setValue(pos[1])
                    if pos[2] is not None:
                        self.cal_z.setValue(pos[2])
                on_main_thread(apply)
        self.connection.request_position(cb)

    def _show_pos(self, pos):
        z = f"  Z={pos[2]:.2f}" if pos[2] is not None else ""
        self.status_position.setText(f"X={pos[0]:.2f}  Y={pos[1]:.2f}{z}")
        self.pen_pos = (pos[0], pos[1])
        if hasattr(self, "bed_canvas"):
            self.bed_canvas.update()

    def _move_to(self, pos):
        """Faehrt den Stift (bei aktiver Verbindung) zur Bett-Position;
        nach der Fahrt wird die Position zur Anzeige neu gelesen.

        Im XY-Test-Modus bedeutet der Klick stattdessen: 'Hier landet die
        Stiftspitte wirklich' -> daraus wird der X/Y-Offset berechnet.
        """
        if getattr(self, "_xy_test_active", False):
            self._xy_test_active = False
            tx, ty = self._xy_test_target
            # true_offset = alter_Offset + (Klick - Sollpunkt)
            off_x = self.pen.pen_offset_x + (pos[0] - tx)
            off_y = self.pen.pen_offset_y + (pos[1] - ty)
            self.pen_off_x_spin.setValue(off_x)
            self.pen_off_y_spin.setValue(off_y)
            self.statusBar().showMessage(
                f"Stift-Offset kalibriert: X={off_x:+.2f} mm  Y={off_y:+.2f} mm", 8000)
            return
        if not self.bed_click_moves.isChecked() or not self.connection:
            return
        if not self.connection.is_connected():
            self.statusBar().showMessage(
                "Keine Verbindung – Klick setzt nur die Werte", 3000)
            return
        self.connection.move_absolute(pos[0], pos[1],
                                      callback=lambda r, e: on_main_thread(self._refresh_position))
        self.statusBar().showMessage(
            f"Fahre zu X={pos[0]:.1f} Y={pos[1]:.1f} ...", 3000)

    def _jog(self, dx, dy, dz):
        if not self.connection:
            return
        step = self.step_combo.currentData()
        self.connection.jog(x=step * dx if dx else None,
                            y=step * dy if dy else None,
                            z=step * dz if dz else None)
        QtCore.QTimer.singleShot(150, self._refresh_position)

    def _home(self, what):
        if not self.connection:
            return
        if what == "Home XY":
            self.connection.home("XY")
        elif what == "Home Z":
            self.connection.home_z()
        else:
            self.connection.home("XYZ")

    def _emergency_stop(self):
        if not self.connection:
            QtWidgets.QMessageBox.warning(self, "Notaus", "Keine aktive Verbindung – Drucker manuell stoppen!")
            return
        def cb(ok, err):
            def apply():
                if err:
                    QtWidgets.QMessageBox.warning(self, "Notaus", f"Notaus fehlgeschlagen: {err}\nDrucker manuell stoppen!")
                else:
                    self.conn_label.setText("NOTAUS ausgelöst!")
                    self.conn_label.setStyleSheet("color:#ef5350;")
            on_main_thread(apply)
        self.connection.emergency_stop(callback=cb)

    def _install_jog_shortcuts(self):
        """WASD/RF als anwendungweite Shortcuts: funktionieren auch, wenn ein
        Textfeld/Spinbox den Fokus hat (diese brauchen keine Buchstaben aus
        wasdrf). Zusaetzlich 1-4 fuer den Schritt (0.1/1/10/50 mm)."""
        self._jog_shortcuts = {}
        for key, direction in (("w", (0, 1, 0)), ("s", (0, -1, 0)),
                               ("a", (-1, 0, 0)), ("d", (1, 0, 0)),
                               ("r", (0, 0, 1)), ("f", (0, 0, -1))):
            sc = QtGui.QShortcut(QtGui.QKeySequence(key), self)
            sc.setContext(QtCore.Qt.ApplicationShortcut)
            sc.activated.connect(lambda d=direction: self._jog(*d))
            sc.activated.connect(lambda d=direction: self._start_hold_jog(d))
            self._jog_shortcuts[key] = sc
        for i, step in enumerate(("0.1", "1", "10", "50")):
            sc = QtGui.QShortcut(QtGui.QKeySequence(str(i + 1)), self)
            sc.setContext(QtCore.Qt.ApplicationShortcut)
            sc.activated.connect(lambda idx=i: self.step_combo.setCurrentIndex(idx))
            self._jog_shortcuts[f"step{i}"] = sc

    def keyReleaseEvent(self, e):
        key = e.text().lower()
        if key in "wasdrf":
            self._stop_hold_jog()
        super().keyReleaseEvent(e)

    def _start_hold_jog(self, direction):
        """Gehaltene Taste: wiederholt kleine Schritte senden (smooth)."""
        self._hold_dir = direction
        if getattr(self, "_hold_timer", None):
            return  # läuft schon
        self._hold_dir = direction
        self._hold_timer = QtCore.QTimer(self)
        self._hold_timer.setInterval(150)
        self._hold_timer.timeout.connect(self._hold_tick)
        self._hold_timer.start()

    def _hold_tick(self):
        """Ein feiner Schritt pro Intervall – läuft über die Warteschlange."""
        if not self.connection:
            self._stop_hold_jog()
            return
        step = min(self.step_combo.currentData(), 1.0)
        dx, dy, dz = self._hold_dir
        self.connection.jog(x=step * dx if dx else None,
                            y=step * dy if dy else None,
                            z=step * dz if dz else None)
        self._refresh_position()

    def _stop_hold_jog(self):
        if getattr(self, "_hold_timer", None):
            self._hold_timer.stop()
            self._hold_timer.deleteLater()
            self._hold_timer = None

    def _start_polling(self):
        def poll():
            if not self._poll_active:
                return  # Polling nach Fenster-Schliessen stoppen
            if self.connection and self.connection.is_connected():
                interval = 350 if getattr(self, "_hold_timer", None) else 1000
                def cb(pos, err):
                    if pos:
                        on_main_thread(lambda: self._show_pos(pos))
                self.connection.request_position(cb)
            else:
                interval = 1000
            QtCore.QTimer.singleShot(interval, poll)
        QtCore.QTimer.singleShot(1000, poll)

    # ---------- Settings ----------
    def _load_settings(self):
        data = settings.load()
        if not data:
            self._saved_kind, self._saved_host = "moonraker", ""
            self._saved_printer = None
            return
        settings.apply_to(data, self.calibration, self.pen)
        self._saved_printer = data.get("printer")
        self._saved_kind = data.get("conn_kind", "moonraker")
        self._saved_host = data.get("host", "")

    def _save_settings(self):
        try:
            settings.save(self.calibration, self.pen,
                          self.current_printer["name"] if self.current_printer else None,
                          self.host_edit.text().strip(),
                          "moonraker" if self.kind_combo.currentIndex() == 0 else "octoprint")
        except OSError:
            pass

    def closeEvent(self, _event):
        self._poll_active = False  # Positions-Polling stoppen (keine QTimer-Callbacks mehr)
        if self.connection:
            self.connection.stop()
        self._save_settings()


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setStyleSheet(DARK)
    init_main_thread_relay()  # falls PlotterWindow woanders erzeugt wird
    win = PlotterWindow()
    win.show()
    sys.exit(app.exec())
