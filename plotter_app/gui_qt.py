"""Moderne PySide6/Qt-Oberfläche der Plotter-App (ersetzt die tkinter-GUI)."""
import math
import sys

from PySide6 import QtCore, QtGui, QtWidgets

from . import settings, tools
from .calibration import Calibration
from .gcode import export_gcode, save_gcode
from .network import PrinterConnectionError, create_connection
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
        self.setWindowTitle("3D-Plotter")
        self.resize(1180, 760)
        self.calibration = Calibration()
        self.pen = PenSettings()
        self.printers = load_builtin()
        self.current_printer = None
        self.connection = None
        self.paths = []
        self.free_path = None
        self.pen_pos = None
        self._poll_fail = 0
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
        self._start_polling()

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

        jog = QtWidgets.QGroupBox("Stift bewegen (WASD = X/Y, R/F = Z)")
        jf = QtWidgets.QGridLayout(jog)
        self.step_combo = QtWidgets.QComboBox()
        for s in ("0.1", "1", "10", "50"):
            self.step_combo.addItem(f"{s} mm", float(s))
        self.step_combo.setCurrentIndex(2)
        jf.addWidget(QtWidgets.QLabel("Schritt:"), 0, 0, 1, 2)
        jf.addWidget(self.step_combo, 0, 2)
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
        self.tabs.addTab(tab, f"Drucker ({len(self.printers)})")

    def _filter_printers(self):
        q = self.printer_search.text().strip().lower()
        self.printer_list.clear()
        for p in self.printers:
            if q and q not in p["name"].lower() and q not in p.get("vendor", "").lower():
                continue
            self.printer_list.addItem(f"{p['name']}  —  Bett {p['bed_x']}×{p['bed_y']}×{p['bed_z']} mm")

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
        form.addWidget(add_btn, 1, 3, 1, 3)
        self.corner_list = QtWidgets.QListWidget()
        form.addWidget(self.corner_list, 2, 0, 1, 6)
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
        wf.addWidget(QtWidgets.QLabel("Zeichen-Z:"), 2, 0)
        self.pen_draw_spin = self._dspin(-50, 200, self.pen.pen_draw_z)
        self.pen_draw_spin.setValue(self.pen.pen_draw_z)
        self.pen_draw_spin.valueChanged.connect(self._pen_spin_changed)
        wf.addWidget(self.pen_draw_spin, 2, 1)
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

    def _sync_pen_spins(self):
        self.pen_draw_spin.setValue(self.pen.pen_draw_z)
        self.pen_up_spin.setValue(self.pen.pen_up_z)

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

        self.paper_canvas = PaperCanvas(self)
        layout.addWidget(self.paper_canvas, 3)
        self.tabs.addTab(tab, "Design")

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
        self.paths.extend(m[name]())
        self.paper_canvas.update()

    def _add_preset(self, kind):
        if kind == "test":
            self.paths.extend(tools.test_plot())
        else:
            self.paths.extend(tools.calibration_grid())
        self.paper_canvas.update()

    def _clear_design(self):
        self.paths.clear()
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
        self.paths.extend(paths)
        self.paper_canvas.update()
        self.statusBar().showMessage(f"{len(paths)} SVG-Pfade importiert", 5000)

    def _load_image(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Bild öffnen", "", "Bilder (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        try:
            self.paths.extend(tools.trace_image(path, resolution=64))
        except RuntimeError as e:
            QtWidgets.QMessageBox.critical(self, "Fehler", str(e))
            return
        self.paper_canvas.update()

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
        layout.addStretch()
        self.tabs.addTab(tab, "Export")

    def _export_file(self):
        if not self._validate_for_export():
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "G-Code speichern", "plot.gcode", "G-Code (*.gcode *.g *.nc)")
        if not path:
            return
        paths = tools.optimize_paths(self.paths) if self.optimize_check.isChecked() else self.paths
        save_gcode(path, paths, self.calibration, self.pen)
        self.statusBar().showMessage("G-Code gespeichert", 5000)

    def _plot_over_ip(self):
        if not self._validate_for_export() or not self.connection:
            return
        if self.connection.is_printing():
            QtWidgets.QMessageBox.warning(self, "Plot", "Der Drucker druckt bereits.")
            return
        btn = QtWidgets.QMessageBox.question(self, "Plot starten", "Jetzt über IP plotten?")
        if btn != QtWidgets.QMessageBox.Yes:
            return
        paths = tools.optimize_paths(self.paths) if self.optimize_check.isChecked() else self.paths
        gcode = export_gcode(paths, self.calibration, self.pen, header_comment="IP Plot Job")
        try:
            self.connection.upload_and_start(gcode)
            self.statusBar().showMessage("Plot gestartet", 5000)
        except PrinterConnectionError as e:
            QtWidgets.QMessageBox.critical(self, "Netzwerkfehler", str(e))

    def _validate_for_export(self):
        if not self.paths:
            QtWidgets.QMessageBox.warning(self, "Export", "Kein Design vorhanden.")
            return False
        if not self.calibration.is_complete:
            QtWidgets.QMessageBox.warning(self, "Export", "Bitte zuerst kalibrieren (mindestens 3 Ecken).")
            return False
        return True

    # ---------- Netzwerk / Aktionen ----------
    def _connect(self):
        kind = "moonraker" if self.kind_combo.currentIndex() == 0 else "octoprint"
        host = self.host_edit.text().strip()
        if not host:
            QtWidgets.QMessageBox.warning(self, "Verbindung", "Bitte IP/Host angeben.")
            return
        try:
            self.connection = create_connection(kind, host, self.key_edit.text().strip())
            pos = self.connection.get_position()
            self._show_pos(pos)
            self.conn_label.setText(f"Verbunden mit {host} ✓")
            self.conn_label.setStyleSheet("color:#66bb6a;")
        except PrinterConnectionError as e:
            self.connection = None
            self.conn_label.setText("Verbindung fehlgeschlagen")
            self.conn_label.setStyleSheet("color:#ef5350;")
            QtWidgets.QMessageBox.critical(self, "Fehler", str(e))

    def _get_pos(self):
        if not self.connection:
            QtWidgets.QMessageBox.warning(self, "Verbindung", "Keine Verbindung.")
            return None
        try:
            return self.connection.get_position()
        except PrinterConnectionError as e:
            QtWidgets.QMessageBox.critical(self, "Fehler", str(e))
            return None

    def _refresh_position(self):
        pos = self._get_pos()
        if not pos:
            return
        self.cal_x.setValue(pos[0])
        self.cal_y.setValue(pos[1])
        if len(pos) > 2:
            self.cal_z.setValue(pos[2])
        self._show_pos(pos)

    def _show_pos(self, pos):
        z = f"  Z={pos[2]:.2f}" if len(pos) > 2 else ""
        self.status_position.setText(f"X={pos[0]:.2f}  Y={pos[1]:.2f}{z}")
        self.pen_pos = (pos[0], pos[1])
        if hasattr(self, "bed_canvas"):
            self.bed_canvas.update()

    def _jog(self, dx, dy, dz):
        if not self.connection:
            return
        step = self.step_combo.currentData()
        try:
            self.connection.jog(x=step * dx if dx else None,
                                y=step * dy if dy else None,
                                z=step * dz if dz else None)
            QtCore.QTimer.singleShot(250, self._refresh_position)
        except PrinterConnectionError as e:
            QtWidgets.QMessageBox.critical(self, "Fehler", str(e))

    def _home(self, what):
        if not self.connection:
            return
        try:
            if what == "Home XY":
                self.connection.home("XY")
            elif what == "Home Z":
                self.connection.home_z()
            else:
                self.connection.home("XYZ")
        except PrinterConnectionError as e:
            QtWidgets.QMessageBox.critical(self, "Fehler", str(e))

    def _emergency_stop(self):
        if self.connection and hasattr(self.connection, "emergency_stop"):
            try:
                self.connection.emergency_stop()
                self.conn_label.setText("NOTAUS ausgelöst!")
                self.conn_label.setStyleSheet("color:#ef5350;")
                return
            except PrinterConnectionError:
                pass
        QtWidgets.QMessageBox.warning(self, "Notaus", "Keine aktive Verbindung – Drucker manuell stoppen!")

    def _keyPressEvent(self, e):
        if isinstance(self.focusWidget(), (QtWidgets.QLineEdit, QtWidgets.QSpinBox,
                                          QtWidgets.QDoubleSpinBox, QtWidgets.QComboBox)):
            return
        key = e.text().lower()
        mapping = {"w": (0, 1, 0), "s": (0, -1, 0), "a": (-1, 0, 0),
                   "d": (1, 0, 0), "r": (0, 0, 1), "f": (0, 0, -1)}
        if key in mapping:
            self._jog(*mapping[key])

    def _start_polling(self):
        def poll():
            if self.connection:
                try:
                    self._show_pos(self.connection.get_position())
                    self._poll_fail = 0
                except PrinterConnectionError:
                    self._poll_fail += 1
                    if self._poll_fail >= 3:
                        self.conn_label.setText("Verbindung verloren")
                        self.conn_label.setStyleSheet("color:#ef5350;")
                        self.connection = None
                        self._poll_fail = 0
            QtCore.QTimer.singleShot(1000, poll)
        QtCore.QTimer.singleShot(1000, poll)

    # ---------- Settings ----------
    def _load_settings(self):
        data = settings.load()
        if not data:
            self._saved_kind, self._saved_host = "moonraker", ""
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
        self._save_settings()


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setStyleSheet(DARK)
    win = PlotterWindow()
    win.show()
    sys.exit(app.exec())
