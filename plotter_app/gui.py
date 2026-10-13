"""Haupt-GUI der 3D-Drucker-Plotter-App (tkinter)."""
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import tools
from .calibration import Calibration
from .gcode import plot_command_groups
from .network import PrinterConnectionError, create_connection
from .gcode import save_gcode
from .pen import PenSettings
from .profiles import load_builtin, load_printer_profile
from . import settings
from .svg import load_svg


class PlotterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("3D-Drucker Plotter App")
        self.geometry("1100x750")
        self.printers = load_builtin()
        self.calibration = Calibration()
        self.pen = PenSettings()
        self.paths = []          # aktuelle Design-Pfade
        self.current_printer = None
        self.connection = None    # aktive IP-Verbindung

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)
        self._build_connection_tab()
        self._build_printer_tab()
        self._build_calibration_tab()
        self._build_design_tab()
        self._build_export_tab()

    # ---------------- Verbindung (IP) ----------------
    def _build_connection_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="0. Verbindung")

        form = ttk.Frame(tab)
        form.pack(pady=8)
        ttk.Label(form, text="Typ:").grid(row=0, column=0, padx=4)
        self.conn_kind = tk.StringVar(value="moonraker")
        ttk.Radiobutton(form, text="Klipper/Moonraker", value="moonraker", variable=self.conn_kind).grid(row=0, column=1)
        ttk.Radiobutton(form, text="OctoPrint", value="octoprint", variable=self.conn_kind).grid(row=0, column=2)

        ttk.Label(form, text="IP/Host:").grid(row=1, column=0, padx=4, sticky="e")
        self.conn_host = ttk.Entry(form, width=24)
        self.conn_host.insert(0, "192.168.1.50")
        self.conn_host.grid(row=1, column=1, padx=4)
        ttk.Label(form, text="API-Key (optional bei Moonraker):").grid(row=1, column=2, padx=4)
        self.conn_key = ttk.Entry(form, width=24)
        self.conn_key.grid(row=1, column=3, padx=4)

        ttk.Button(tab, text="Verbinden", command=self._connect_printer).pack(pady=5)
        self.conn_status = ttk.Label(tab, text="Status: nicht verbunden")
        self.conn_status.pack(pady=3)

        # Jog-Steuerung
        jog = ttk.LabelFrame(tab, text="Stift bewegen (Jog)")
        jog.pack(pady=10, padx=10, fill="x")
        ttk.Label(jog, text="Schrittweite (mm):").grid(row=0, column=0, rowspan=2, padx=6)
        self.jog_step = tk.DoubleVar(value=10.0)
        for i, (val, col) in enumerate([(0.1, 1), (1.0, 2), (10.0, 3), (50.0, 4)]):
            ttk.Radiobutton(jog, text=f"{val:g}", value=val, variable=self.jog_step).grid(row=i % 2, column=col)

        btns = ttk.Frame(jog)
        btns.grid(row=0, column=4, rowspan=2, padx=12)
        for text, cmd in [
            ("Y+", lambda: self._jog(0, +1)),
            ("X-", lambda: self._jog(-1, 0)),
            ("X+", lambda: self._jog(+1, 0)),
            ("Y-", lambda: self._jog(0, -1)),
            ("Z+", lambda: self._jog(0, 0, +1)),
            ("Z-", lambda: self._jog(0, 0, -1)),
            ("Home XY", lambda: self._net("home", "XY")),
            ("Home Z", lambda: self._net("home_z")),
            ("Home XYZ", lambda: self._net("home", "XYZ")),
        ]:
            ttk.Button(btns, text=text, command=cmd, width=6).pack(side="left", padx=2)

        ttk.Label(jog, text="Tastatur: W/S = Y±, A/D = X±, R/F = Z± (Schrittweite oben)").grid(
            row=4, column=0, columnspan=5, pady=(4, 0))
        self.bind("<Key>", self._on_key)

        self.pos_label = ttk.Label(jog, text="Position: –")
        self.pos_label.grid(row=2, column=0, columnspan=5, pady=4)
        ttk.Button(jog, text="Position aktualisieren", command=self._refresh_position).grid(row=3, column=0, columnspan=5, pady=2)

        # Automatisches Positions-Polling
        self.after(1000, self._poll_position)

    def _connect_printer(self):
        host = self.conn_host.get().strip()
        if not host:
            messagebox.showerror("Fehler", "Bitte IP/Host angeben.")
            return
        try:
            self.connection = create_connection(self.conn_kind.get(), host, self.conn_key.get().strip())
            pos = self.connection.get_position()
            self.conn_status.config(text=f"Status: verbunden mit {host} ✓")
            self.pos_label.config(text=f"Position: X={pos[0]:.2f} Y={pos[1]:.2f} Z={pos[2]:.2f}")
        except PrinterConnectionError as e:
            self.connection = None
            self.conn_status.config(text="Status: Verbindung fehlgeschlagen")
            messagebox.showerror("Fehler", str(e))

    def _jog(self, dx, dy, dz=0):
        step = self.jog_step.get()
        self._net("jog", x=step * dx if dx else None,
                  y=step * dy if dy else None,
                  z=step * dz if dz else None)
        self.after(300, self._refresh_position)

    def _on_key(self, event):
        """WASD/RF-Steuerung – aktiv, außer der Fokus ist in einem Textfeld mit Inhalt."""
        widget = self.focus_get()
        if isinstance(widget, (ttk.Entry, tk.Entry, tk.Text)):
            return
        key = (event.keysym or "").lower()
        mapping = {
            "w": (0, +1, 0),
            "s": (0, -1, 0),
            "a": (-1, 0, 0),
            "d": (+1, 0, 0),
            "r": (0, 0, +1),
            "f": (0, 0, -1),
        }
        if key in mapping and self.connection:
            dx, dy, dz = mapping[key]
            self._jog(dx, dy, dz)
            self.after(300, self._refresh_position)

    def _bed_geometry(self):
        """Bett-Bounds in mm und Skalierung für die Vorschau."""
        if self.current_printer:
            bw, bh = float(self.current_printer["bed_x"]), float(self.current_printer["bed_y"])
        else:
            bw, bh = 250.0, 250.0
        xs = [p[0] for p in self.calibration.points] or [0]
        ys = [p[1] for p in self.calibration.points] or [0]
        bw = max(bw, max(xs) + 10)
        bh = max(bh, max(ys) + 10)
        w = max(self.bed_canvas.winfo_width() - 20, 10)
        h = max(self.bed_canvas.winfo_height() - 20, 10)
        scale = min(w / bw, h / bh)
        ox = (w - bw * scale) / 2 + 10
        oy = (h - bh * scale) / 2 + 10
        return bw, bh, scale, ox, oy

    def _draw_bed_preview(self):
        c = self.bed_canvas
        c.delete("all")
        bw, bh, scale, ox, oy = self._bed_geometry()
        # Bett als Rechteck (Ursprung unten links)
        c.create_rectangle(ox, oy, ox + bw * scale, oy + bh * scale,
                            outline="#333", width=2, fill="white")
        # Raster alle 50 mm
        for gx in range(0, int(bw) + 1, 50):
            c.create_line(ox + gx * scale, oy, ox + gx * scale, oy + bh * scale, fill="#ddd")
        for gy in range(0, int(bh) + 1, 50):
            c.create_line(ox, oy + (bh - gy) * scale, ox + bw * scale, oy + (bh - gy) * scale, fill="#ddd")
        # Ecken einzeichnen
        pts = self.calibration.points
        if not pts:
            c.create_text(ox + bw * scale / 2, oy + bh * scale / 2,
                          text="Noch keine Ecken erfasst", fill="#888")
            return
        canvas_pts = [(ox + px * scale, oy + (bh - py) * scale) for (px, py) in pts]
        if self.calibration.is_complete:
            poly = canvas_pts + [canvas_pts[0]]
            flat = [v for p in poly for v in p]
            c.create_polygon(*flat, fill="#2e7d32", stipple="gray50", outline="")
        if len(canvas_pts) > 1:
            c.create_line(*[v for p in canvas_pts for v in p], fill="#1565c0", width=2)
        for i, (cx, cy) in enumerate(canvas_pts, 1):
            c.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill="#e53935", outline="")
            c.create_text(cx + 8, cy - 8, text=str(i), fill="#b71c1c", font=("TkDefaultFont", 9, "bold"))
        last = canvas_pts[-1]
        c.create_oval(last[0] - 6, last[1] - 6, last[0] + 6, last[1] + 6, outline="#e53935", width=2)

    def _refresh_position(self):
        if not self.connection:
            return
        try:
            pos = self.connection.get_position()
            self.pos_label.config(text=f"Position: X={pos[0]:.2f} Y={pos[1]:.2f} Z={pos[2]:.2f}")
            self.cal_x.delete(0, "end")
            self.cal_x.insert(0, f"{pos[0]:.2f}")
            self.cal_y.delete(0, "end")
            self.cal_y.insert(0, f"{pos[1]:.2f}")
            if len(pos) > 2:
                self.cal_z.delete(0, "end")
                self.cal_z.insert(0, f"{pos[2]:.2f}")
            # Stift-Position live in der Bett-Vorschau anzeigen
            bw, bh, scale, ox, oy = self._bed_geometry()
            self.bed_canvas.delete("penpos")
            cx, cy = ox + pos[0] * scale, oy + (bh - pos[1]) * scale
            self.bed_canvas.create_oval(cx - 5, cy - 5, cx + 5, cy + 5,
                                        fill="#ff9800", outline="#e65100", tags="penpos")
        except PrinterConnectionError:
            pass

    def _poll_position(self):
        if self.connection and self.conn_kind.get() == "moonraker":
            try:
                pos = self.connection.get_position()
                if len(pos) > 2:
                    self.pos_label.config(text=f"Position: X={pos[0]:.2f} Y={pos[1]:.2f} Z={pos[2]:.2f}")
                else:
                    self.pos_label.config(text=f"Position: X={pos[0]:.2f} Y={pos[1]:.2f}")
            except PrinterConnectionError:
                # erst nach 3 Fehlversuchen in Folge die Verbindung fallen lassen
                self._poll_fail = getattr(self, "_poll_fail", 0) + 1
                if self._poll_fail >= 3:
                    self.conn_status.config(text="Status: Verbindung verloren")
                    self.connection = None
                    self._poll_fail = 0
            else:
                self._poll_fail = 0
        self.after(1000, self._poll_position)

    def _net(self, action, *args, **kwargs):
        if not self.connection:
            messagebox.showerror("Fehler", "Keine Verbindung – bitte zuerst im Tab 'Verbindung' verbinden.")
            return False
        try:
            getattr(self.connection, action)(*args, **kwargs)
            return True
        except PrinterConnectionError as e:
            messagebox.showerror("Netzwerkfehler", str(e))
            return False

    # ---------------- Drucker ----------------
    def _build_printer_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="1. Drucker")

        ttk.Label(tab, text=f"Verfügbare Drucker ({len(self.printers)} Modelle aus OrcaSlicer)").pack(pady=5)

        search_frame = ttk.Frame(tab)
        search_frame.pack(fill="x", padx=20)
        ttk.Label(search_frame, text="Suchen:").pack(side="left", padx=(0, 4))
        self.printer_search = tk.StringVar()
        self.printer_search.trace_add("write", lambda *_: self._filter_printers())
        search_entry = ttk.Entry(search_frame, textvariable=self.printer_search)
        search_entry.pack(side="left", fill="x", expand=True)

        self.printer_list = tk.Listbox(tab, height=10)
        self.printer_list.pack(fill="x", padx=20, pady=5)
        self.printer_list.bind("<Double-1>", self._select_printer)
        self.printer_list.bind("<<ListboxSelect>>", self._select_printer)
        self._filter_printers()
        search_entry.focus_set()

        ttk.Button(tab, text="OrcaSlicer-Profil importieren (.json)", command=self._import_profile).pack(pady=5)
        ttk.Label(tab, text="Profil aus OrcaSlicer: Hilfe → Profilkurator → Export").pack(pady=2)

    def _filter_printers(self):
        """Filtert die Druckerliste; merkt sich Index-Mapping zur Gesamtliste."""
        query = self.printer_search.get().strip().lower()
        self.printer_list.delete(0, "end")
        self._printer_map = []
        for i, p in enumerate(self.printers):
            if query and query not in p["name"].lower() and query not in p.get("vendor", "").lower():
                continue
            self.printer_list.insert("end", f"{p['name']} — Bett {p['bed_x']}x{p['bed_y']}x{p['bed_z']} mm")
            self._printer_map.append(i)

    def _select_printer(self, _event=None):
        sel = self.printer_list.curselection()
        if not sel:
            return
        real_idx = self._printer_map[sel[0]]
        self.current_printer = self.printers[real_idx]
        try:
            self._draw_bed_preview()
        except AttributeError:
            pass

    def _import_profile(self):
        path = filedialog.askopenfilename(filetypes=[("OrcaSlicer Profil", "*.json"), ("Alle Dateien", "*.*")])
        if not path:
            return
        try:
            prof = load_printer_profile(path)
        except Exception as e:
            messagebox.showerror("Fehler", f"Profil konnte nicht geladen werden:\n{e}")
            return
        self.printers.append(prof)
        self.printer_list.insert("end", f"{prof['name']} — Bett {prof['bed_x']}x{prof['bed_y']}x{prof['bed_z']} mm")

    # ---------------- Kalibrierung ----------------
    def _build_calibration_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="2. Kalibrieren")

        top = ttk.Frame(tab)
        top.pack(fill="x", pady=5)
        ttk.Label(top, text="Stift an die Ecken des Papiers bewegen (im Uhrzeigersinn!) und mit 'Ecke übernehmen' einlesen.\n"
                            "Beliebig viele Ecken möglich (mindestens 3).").pack(pady=5)

        form = ttk.Frame(tab)
        form.pack(pady=5)
        ttk.Label(form, text="X (mm):").grid(row=0, column=0)
        self.cal_x = ttk.Entry(form, width=10)
        self.cal_x.grid(row=0, column=1, padx=5)
        ttk.Label(form, text="Y (mm):").grid(row=0, column=1 + 0)
        self.cal_y = ttk.Entry(form, width=10)
        self.cal_y.grid(row=0, column=2, padx=5)
        ttk.Label(form, text="Z-Höhe (mm):").grid(row=0, column=3, padx=5)
        self.cal_z = ttk.Entry(form, width=10)
        self.cal_z.grid(row=0, column=4, padx=5)


        ttk.Button(tab, text="Ecke übernehmen", command=self._add_corner).pack(pady=3)
        ttk.Label(tab, text="Tipp: Stift mit W/S/A/D (X/Y) und R/F (Z) bewegen – funktioniert auch hier.").pack()
        ttk.Button(tab, text="Letzte Ecke löschen", command=self._pop_corner).pack(pady=3)
        ttk.Button(tab, text="Alle Ecken löschen", command=self._clear_corners).pack(pady=3)

        self.corner_list = tk.Listbox(tab, height=6)
        self.corner_list.pack(fill="x", padx=20, pady=5)

        # Kalibrierung: aktuelle Position über IP übernehmen
        net = ttk.LabelFrame(tab, text="Über IP")
        net.pack(fill="x", pady=8, padx=10)
        ttk.Label(net, text="Stift mit Jog (Tab 'Verbindung') an die Ecke fahren, dann:").pack(pady=2)
        ttk.Button(net, text="Aktuelle Position auslesen", command=self._refresh_position).pack(pady=3)

        # Live-Vorschau der Ecken auf dem Bett
        prev = ttk.LabelFrame(tab, text="Bett-Vorschau (Ecken live)")
        prev.pack(fill="both", expand=True, pady=8, padx=10)
        self.bed_canvas = tk.Canvas(prev, bg="#f0f0f0", height=260)
        self.bed_canvas.pack(fill="both", expand=True, padx=6, pady=6)
        self.bed_canvas.bind("<Configure>", lambda _e: self._draw_bed_preview())

        self.cal_status = ttk.Label(tab, text="Status: nicht kalibriert")
        self.cal_status.pack()

        zform = ttk.Frame(tab)
        zform.pack(pady=8)
        self._z_vars = {}
        for i, (label, attr) in enumerate([
            ("Stift hoch Z (mm)", "pen_up_z"),
            ("Stift Zeichen-Z (mm)", "pen_draw_z"),
            ("Stift-Offset zur Nozzle (mm, negativ = tiefer)", "pen_offset_z"),
            ("Eilgang F (mm/s)", "travel_speed"),
            ("Zeichen-F (mm/s)", "draw_speed"),
            ("Hub zwischen Pfaden (mm)", "z_lift_between_paths"),
        ]):
            ttk.Label(zform, text=label).grid(row=i, column=0, sticky="w", padx=5)
            var = tk.DoubleVar(value=getattr(self.pen, attr))
            ent = ttk.Entry(zform, textvariable=var, width=10)
            ent.grid(row=i, column=1)
            var.trace_add("write", lambda *_: self._update_pen())
            self._z_vars[attr] = var

        wiz = ttk.LabelFrame(tab, text="Stift-Höhe erkennen (Assistent)")
        wiz.pack(fill="x", pady=8, padx=10)
        ttk.Label(wiz, text="Stift-Montage:").pack(pady=(6, 2))
        mount = ttk.Frame(wiz)
        mount.pack()
        ttk.Button(mount, text="Preset: Stift auf Nozzle-Niveau",
                   command=lambda: self._set_mount_preset(0.0)).pack(side="left", padx=4)
        ttk.Button(mount, text="Preset: Stift unter Nozzle",
                   command=lambda: self._set_mount_preset(-2.5)).pack(side="left", padx=4)

        ttk.Label(wiz, text=(
            "1. Nozzle homen (Home XYZ),\n"
            "2. Papier auf Bett,\n"
            "3. Stift mit R/F ganz vorsichtig auf das Papier senken (bis er gerade berührt)\n"
            "→ dann 'Aktuelle Stift-Höhe als Zeichen-Z übernehmen'.\n"
            "Alternativ Nozzle-Papier-Test machen und dessen Z eintragen.")).pack(pady=3)
        ttk.Button(wiz, text="Aktuelle Stift-Höhe als Zeichen-Z übernehmen",
                   command=self._adopt_pen_height).pack(pady=3)
        ttk.Label(wiz, text="Nozzle-Papier-Z (mm):", ).pack(pady=(5, 0))
        self.paper_z_entry = ttk.Entry(wiz, width=10)
        self.paper_z_entry.pack(pady=2)
        ttk.Button(wiz, text="Aus Nozzle-Papier-Z berechnen",
                   command=self._calc_from_paper_z).pack(pady=3)

    def _set_mount_preset(self, offset):
        """Preset für die Stift-Halterung: Offset + typische Z-Werte."""
        self.pen.pen_offset_z = offset
        if offset == 0.0:
            # Stift auf Nozzle-Niveau (z. B. Halter, der den Stift neben der Nozzle hält)
            self.pen.pen_draw_z = 0.0
            self.pen.pen_up_z = 5.0
        else:
            self.pen.pen_draw_z = offset
            self.pen.pen_up_z = offset + 5.0
        self._sync_pen_vars()

    def _adopt_pen_height(self):
        """Übernimmt die aktuelle Z-Position als Stift-Zeichen-Höhe."""
        if not self.connection:
            messagebox.showerror("Fehler", "Keine Verbindung – zuerst im Tab 'Verbindung' verbinden.")
            return
        try:
            pos = self.connection.get_position()
        except PrinterConnectionError as e:
            messagebox.showerror("Fehler", str(e))
            return
        z = pos[2] if len(pos) > 2 else None
        if z is None:
            messagebox.showerror("Fehler", "Z-Position nicht lesbar.")
            return
        self.pen.auto_from_pen_touch(z)
        self._sync_pen_vars()
        messagebox.showinfo("Stift-Höhe",
                            f"Zeichen-Z = {z:.2f} mm übernommen.\nStift hoch = {self.pen.pen_up_z:.2f} mm.")

    def _calc_from_paper_z(self):
        """Berechnet Stift-Z aus Nozzle-Papier-Test + Stift-Offset."""
        try:
            paper_z = float(self.paper_z_entry.get())
        except ValueError:
            messagebox.showerror("Fehler", "Bitte Nozzle-Papier-Z als Zahl eingeben.")
            return
        self.pen.auto_from_paper_z(paper_z)
        self._sync_pen_vars()
        messagebox.showinfo("Stift-Höhe",
                            (f"Papier-Z {paper_z:.2f} + Offset {self.pen.pen_offset_z:.2f} "
                             f"→ Zeichen-Z {self.pen.pen_draw_z:.2f}, Stift hoch {self.pen.pen_up_z:.2f}"))

    def _sync_pen_vars(self):
        """GUI-Felder mit berechneten Pen-Werten synchronisieren."""
        self._updating_pen = True
        self._z_vars["pen_up_z"].set(self.pen.pen_up_z)
        self._z_vars["pen_draw_z"].set(self.pen.pen_draw_z)
        self._updating_pen = False

    def _update_pen(self):
        if getattr(self, "_updating_pen", False):
            return
        for attr, var in self._z_vars.items():
            try:
                setattr(self.pen, attr, var.get())
            except (tk.TclError, ValueError):
                pass

    def _add_corner(self):
        try:
            x = float(self.cal_x.get())
            y = float(self.cal_y.get())
            z = float(self.cal_z.get()) if self.cal_z.get().strip() else None
        except ValueError:
            messagebox.showerror("Fehler", "Bitte X und Y (und optional Z) als Zahl eingeben.")
            return
        self.calibration.add_point(x, y, z)
        self._refresh_corners()
        self.focus_set()

    def _pop_corner(self):
        self.calibration.pop_point()
        self._refresh_corners()

    def _clear_corners(self):
        self.calibration.clear()
        self._refresh_corners()

    def _refresh_corners(self):
        self.corner_list.delete(0, "end")
        for i, (x, y) in enumerate(self.calibration.points, 1):
            z = self.calibration.heights[i - 1] if i <= len(self.calibration.heights) else None
            ztxt = f"  Z={z:.2f}" if z is not None else ""
            self.corner_list.insert("end", f"Ecke {i}: X={x:.2f}  Y={y:.2f}{ztxt}")
        status = f"Status: {len(self.calibration.points)} Ecken"
        if self.calibration.is_complete:
            status += " — kalibriert ✓"
        self.cal_status.config(text=status)
        self._draw_bed_preview()

    # ---------------- Design ----------------
    def _build_design_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="3. Design")

        self.canvas = tk.Canvas(tab, bg="white")
        self.canvas.pack(fill="both", expand=True, padx=10, pady=10)

        panel = ttk.Frame(tab)
        panel.pack(fill="x", pady=5)
        ttk.Label(panel, text="Tool:").pack(side="left", padx=4)
        self.tool_var = tk.StringVar(value="rect")
        for name, label in [("rect", "Rechteck"), ("circle", "Kreis"), ("ellipse", "Ellipse"),
                            ("star", "Stern"), ("polygon", "n-Eck"),
                            ("spiral", "Spirale"), ("wave", "Welle"), ("heart", "Herz"),
                            ("grid", "Raster"), ("text", "Text"),
                            ("image", "Bild"), ("free", "Freihand")]:
            ttk.Radiobutton(panel, text=label, value=name, variable=self.tool_var).pack(side="left", padx=2)

        params = ttk.Frame(tab)
        params.pack(fill="x", pady=4)
        self.param_entries = {}
        for i, (key, default) in enumerate([
            ("x", "0.1"), ("y", "0.1"), ("w/h", "0.5"), ("r", "0.2"),
            ("nx/ny", "5"), ("text", "PLOT"), ("size", "0.1"), ("n", "6")]):
            ttk.Label(params, text=key).grid(row=0, column=i * 2, padx=2)
            e = ttk.Entry(params, width=8)
            e.insert(0, default)
            e.grid(row=0, column=i * 2 + 1, padx=2)
            self.param_entries[key] = e

        ttk.Button(tab, text="Zeichnen", command=self._add_shape).pack(pady=3)
        ttk.Button(tab, text="Bild laden & tracer", command=self._load_image).pack(pady=3)
        ttk.Button(tab, text="SVG importieren", command=self._load_svg).pack(pady=3)
        ttk.Button(tab, text="Alles löschen", command=lambda: (self.paths.clear(), self._redraw())).pack(pady=3)

        preset = ttk.LabelFrame(tab, text="Fertige Vorlagen")
        preset.pack(fill="x", pady=4, padx=10)
        ttk.Button(preset, text="Höhen-Test (klein)", command=lambda: self._add_preset("test")).pack(side="left", padx=4, pady=3)
        ttk.Button(preset, text="Kalibrier-Raster", command=lambda: self._add_preset("calgrid")).pack(side="left", padx=4, pady=3)
        self._do_optimize = tk.BooleanVar(value=True)
        ttk.Checkbutton(preset, text="Pfade optimieren (beim Export)", variable=self._do_optimize).pack(side="left", padx=8)

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self._free_path = None

    def _load_svg(self):
        path = filedialog.askopenfilename(filetypes=[("SVG", "*.svg"), ("Alle", "*.*")])
        if not path:
            return
        bed_w = self.current_printer["bed_x"] if self.current_printer else 200
        bed_h = self.current_printer["bed_y"] if self.current_printer else 200
        try:
            paths = load_svg(path, bed_w=bed_w, bed_h=bed_h)
        except Exception as e:
            messagebox.showerror("Fehler", f"SVG konnte nicht geladen werden:\n{e}")
            return
        if not paths:
            messagebox.showwarning("SVG", "Keine Pfad-Daten im SVG gefunden (nur paths/polylines/rects/circles werden unterstützt).")
            return
        self.paths.extend(paths)
        self._redraw()
        messagebox.showinfo("SVG", f"{len(paths)} Pfade importiert.")

    def _add_preset(self, kind):
        if kind == "test":
            self.paths.extend(tools.test_plot())
        elif kind == "calgrid":
            self.paths.extend(tools.calibration_grid())
        self._redraw()

    def _add_shape(self):
        def get(key):
            return self.param_entries[key].get()
        tool = self.tool_var.get()
        try:
            x, y = float(get("x")), float(get("y"))
            size = float(get("size"))
            r = float(get("r"))
            wh = [float(v) for v in get("w/h").replace(",", " ").split()]
            nxny = [int(v) for v in get("nx/ny").replace(",", " ").split()]
        except ValueError:
            messagebox.showerror("Fehler", "Ungültige Parameter.")
            return
        try:
            if tool == "rect":
                self.paths.append(tools.rect(x, y, wh[0], wh[1]))
            elif tool == "circle":
                self.paths.append(tools.circle(x, y, r))
            elif tool == "star":
                self.paths.append(tools.star(x, y, r, r * 0.4))
            elif tool == "spiral":
                self.paths.append(tools.spiral(x, y, r))
            elif tool == "ellipse":
                self.paths.append(tools.ellipse(x, y, r, r * 0.6))
            elif tool == "polygon":
                n = int(get("n")) if get("n").strip() else 6
                self.paths.append(tools.polygon(x, y, r, n))
            elif tool == "wave":
                self.paths.append(tools.wave(x, y, wh[0] if wh else 0.5, r, 5))
            elif tool == "heart":
                self.paths.append(tools.heart(x, y, r * 2))
            elif tool == "grid":
                self.paths.extend(tools.grid(x, y, wh[0], wh[1], nxny[0], nxny[1]))
            elif tool == "text":
                self.paths.extend(tools.text_paths(get("text"), x, y, size))
            elif tool == "image":
                self._load_image()
        except (IndexError, ValueError):
            messagebox.showerror("Fehler", "Parameter unvollständig (w/h bzw. nx/ny als 'a b' eingeben).")
            return
        self._redraw()

    def _load_image(self):
        path = filedialog.askopenfilename(filetypes=[("Bilder", "*.png *.jpg *.jpeg *.gif *.bmp"), ("Alle", "*.*")])
        if not path:
            return
        try:
            self.paths.extend(tools.trace_image(path, resolution=64))
        except RuntimeError as e:
            messagebox.showerror("Fehler", str(e))
            return
        self._redraw()

    def _on_press(self, event):
        if self.tool_var.get() == "free":
            self._free_path = [(event.x / max(self.canvas.winfo_width(), 1),
                                1 - event.y / max(self.canvas.winfo_height(), 1))]
    def _on_drag(self, event):
        if self._free_path is not None:
            self._free_path.append((event.x / max(self.canvas.winfo_width(), 1),
                                    1 - event.y / max(self.canvas.winfo_height(), 1)))
            self._redraw()
    def _on_release(self, _event):
        if self._free_path and len(self._free_path) > 1:
            self.paths.append(self._free_path)
        self._free_path = None
        self._redraw()

    def _redraw(self):
        self.canvas.delete("all")
        w = max(self.canvas.winfo_width(), 1)
        h = max(self.canvas.winfo_height(), 1)
        self._draw_paper()
        for path in self.paths + ([self._free_path] if self._free_path else []):
            if not path:
                continue
            pts = [p for (px, py) in path for p in (px * w, (1 - py) * h)]
            if len(pts) >= 4:
                self.canvas.create_line(*pts, fill="black", width=2)

    def _draw_paper(self):
        """Stellt das Papier als Blatt dar: exakt dort, wo die kalibrierten Ecken liegen."""
        c = self.canvas
        w = max(c.winfo_width(), 1)
        h = max(c.winfo_height(), 1)
        cal = self.calibration
        if cal.is_complete:
            # Papier = die kalibrierte Fläche (Ecken 0..1 im Papier-Koordinatensystem)
            corners = [(0, 0), (1, 0), (1, 1), (0, 1)]
            flat = [p for (px, py) in corners for p in (px * w, (1 - py) * h)]
            c.create_polygon(flat, fill="#fff8e1", outline="#c0a040", width=2)
            c.create_text(w - 60, h - 12, text="Papier", fill="#a08020", anchor="e")
        else:
            # Ohne Kalibrierung: gesamtes Blatt als Papier andeuten
            c.create_rectangle(2, 2, w - 2, h - 2, fill="#fff8e1", outline="#c0a040", width=2)
            c.create_text(w / 2, h - 14, text="Papier (unkalibriert – gesamte Fläche)", fill="#a08020")

    # ---------------- Export ----------------
    def _build_export_tab(self):
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="4. Export")
        ttk.Label(tab, text="G-Code für den Plotter erzeugen").pack(pady=10)
        ttk.Label(tab, text="Datei auf SD-Karte/Drucker laden und starten.\n"
                            "Davor prüfen: Kalibrierung aktiv, Stift korrekt montiert.").pack(pady=5)
        self.export_label = ttk.Label(tab, text="Pfade: 0")
        self.export_label.pack(pady=5)
        ttk.Button(tab, text="G-Code speichern unter...", command=self._export).pack(pady=10)
        ttk.Button(tab, text="Direkt über IP plotten", command=self._plot_over_ip).pack(pady=5)
        self.plot_ip_label = ttk.Label(tab, text="")
        self.plot_ip_label.pack(pady=3)

    def _export(self):
        if not self.paths:
            messagebox.showwarning("Warnung", "Kein Design vorhanden.")
            return
        if not self.calibration.is_complete:
            messagebox.showerror("Fehler", "Bitte zuerst kalibrieren (mindestens 3 Ecken).")
            return
        path = filedialog.asksaveasfilename(defaultextension=".gcode",
                                            filetypes=[("G-Code", "*.gcode *.g *.nc")])
        if not path:
            return
        save_gcode(path, self.paths, self.calibration, self.pen)
        messagebox.showinfo("Export", f"G-Code gespeichert:\n{path}\n({len(self.paths)} Pfade)")

    def _plot_over_ip(self):
        if not self.paths:
            messagebox.showwarning("Warnung", "Kein Design vorhanden.")
            return
        if not self.calibration.is_complete:
            messagebox.showerror("Fehler", "Bitte zuerst kalibrieren (mindestens 3 Ecken).")
            return
        if not self.connection:
            messagebox.showerror("Fehler", "Keine Verbindung – bitte zuerst im Tab 'Verbindung' verbinden.")
            return
        if not messagebox.askyesno("Plot starten", "Plotten jetzt über IP starten?\nStift montiert und Papier aufgelegt?"):
            return
        paths = tools.optimize_paths(self.paths) if self._do_optimize.get() else self.paths
        groups = plot_command_groups(paths, self.calibration, self.pen)

        def cb(ok, err):
            if err:
                self.plot_ip_label.config(text="")
                messagebox.showerror("Netzwerkfehler", str(err))
            else:
                self.plot_ip_label.config(text="Plot beendet ✓")
        self.plot_ip_label.config(text="Plot läuft (Befehle werden live gesendet) …")
        self.connection.plot_groups(groups, callback=cb)


    def _emergency_stop(self):
        """Sofort-Notaus über Moonraker (direkt, nicht via G-Code-Warteschlange)."""
        if self.connection and hasattr(self.connection, "emergency_stop"):
            try:
                self.connection.emergency_stop()
                self.conn_status.config(text="Status: NOTAUS ausgelöst!")
                return
            except PrinterConnectionError:
                pass
        messagebox.showwarning("Notaus", "Keine aktive Verbindung – Drucker ggf. manuell stoppen!")

    def _load_settings(self):
        """Gespeicherte Einstellungen laden (automatisch beim Start)."""
        data = settings.load()
        if not data:
            return
        settings.apply_to(data, self.calibration, self.pen)
        self._saved_printer = data.get("printer")
        self._saved_host = data.get("host", "")
        self._saved_kind = data.get("conn_kind", "moonraker")

    def _save_settings(self):
        try:
            settings.save(self.calibration, self.pen,
                          self.current_printer["name"] if self.current_printer else None,
                          self.conn_host.get() if hasattr(self, "conn_host") else "",
                          self.conn_kind.get() if hasattr(self, "conn_kind") else "moonraker")
        except OSError:
            pass

    def on_close(self):
        self._save_settings()
        self.destroy()


def main():
    app = PlotterApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    main()
