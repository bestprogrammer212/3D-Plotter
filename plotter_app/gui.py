"""Haupt-GUI der 3D-Drucker-Plotter-App (tkinter)."""
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import tools
from .calibration import Calibration
from .gcode import export_gcode
from .network import PrinterConnectionError, create_connection
from .gcode import save_gcode
from .pen import PenSettings
from .profiles import load_builtin, load_printer_profile


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
        for i, (val, col) in enumerate([(1.0, 1), (10.0, 2), (50.0, 3)]):
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
        ]:
            ttk.Button(btns, text=text, command=cmd, width=6).pack(side="left", padx=2)

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
            self.pos_label.config(text=f"Position: X={pos[0]:.2f} Y={pos[1]:.2f}")
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

    def _refresh_position(self):
        if not self.connection:
            return
        try:
            pos = self.connection.get_position()
            self.pos_label.config(text=f"Position: X={pos[0]:.2f} Y={pos[1]:.2f}")
            self.cal_x.delete(0, "end")
            self.cal_x.insert(0, f"{pos[0]:.2f}")
            self.cal_y.delete(0, "end")
            self.cal_y.insert(0, f"{pos[1]:.2f}")
        except PrinterConnectionError:
            pass

    def _poll_position(self):
        if self.connection and self.conn_kind.get() == "moonraker":
            try:
                pos = self.connection.get_position()
                self.pos_label.config(text=f"Position: X={pos[0]:.2f} Y={pos[1]:.2f}")
            except PrinterConnectionError:
                self.conn_status.config(text="Status: Verbindung verloren")
                self.connection = None
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

        ttk.Label(tab, text="Verfügbare Drucker (OrcaSlicer-Import oder Liste)").pack(pady=5)
        self.printer_list = tk.Listbox(tab, height=8)
        self.printer_list.pack(fill="x", padx=20, pady=5)
        for p in self.printers:
            self.printer_list.insert("end", f"{p['name']} — Bett {p['bed_x']}x{p['bed_y']}x{p['bed_z']} mm")
        self.printer_list.bind("<Double-1>", self._select_printer)

        ttk.Button(tab, text="OrcaSlicer-Profil importieren (.json)", command=self._import_profile).pack(pady=5)
        ttk.Label(tab, text="Profil aus OrcaSlicer: Hilfe → Profilkurator → Export").pack(pady=2)

    def _select_printer(self, _event=None):
        sel = self.printer_list.curselection()
        if sel:
            self.current_printer = self.printers[sel[0]]
            messagebox.showinfo("Drucker", f"Ausgewählt: {self.current_printer['name']}")

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

        ttk.Button(tab, text="Ecke übernehmen", command=self._add_corner).pack(pady=3)
        ttk.Button(tab, text="Letzte Ecke löschen", command=self._pop_corner).pack(pady=3)
        ttk.Button(tab, text="Alle Ecken löschen", command=self._clear_corners).pack(pady=3)

        self.corner_list = tk.Listbox(tab, height=6)
        self.corner_list.pack(fill="x", padx=20, pady=5)

        # Kalibrierung: aktuelle Position über IP übernehmen
        net = ttk.LabelFrame(tab, text="Über IP")
        net.pack(fill="x", pady=8, padx=10)
        ttk.Label(net, text="Stift mit Jog (Tab 'Verbindung') an die Ecke fahren, dann:").pack(pady=2)
        ttk.Button(net, text="Aktuelle Position auslesen", command=self._refresh_position).pack(pady=3)
        self.cal_status = ttk.Label(tab, text="Status: nicht kalibriert")
        self.cal_status.pack()

        zform = ttk.Frame(tab)
        zform.pack(pady=8)
        self._z_vars = {}
        for i, (label, attr) in enumerate([
            ("Stift hoch Z (mm)", "pen_up_z"),
            ("Stift Zeichen-Z (mm)", "pen_draw_z"),
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

    def _update_pen(self):
        for attr, var in self._z_vars.items():
            try:
                setattr(self.pen, attr, var.get())
            except (tk.TclError, ValueError):
                pass

    def _add_corner(self):
        try:
            x = float(self.cal_x.get())
            y = float(self.cal_y.get())
        except ValueError:
            messagebox.showerror("Fehler", "Bitte X und Y als Zahl eingeben (Stift dort positionieren, Wert ablesen).")
            return
        self.calibration.add_point(x, y)
        self._refresh_corners()

    def _pop_corner(self):
        self.calibration.pop_point()
        self._refresh_corners()

    def _clear_corners(self):
        self.calibration.clear()
        self._refresh_corners()

    def _refresh_corners(self):
        self.corner_list.delete(0, "end")
        for i, (x, y) in enumerate(self.calibration.points, 1):
            self.corner_list.insert("end", f"Ecke {i}: X={x:.2f}  Y={y:.2f}")
        status = f"Status: {len(self.calibration.points)} Ecken"
        if self.calibration.is_complete:
            status += " — kalibriert ✓"
        self.cal_status.config(text=status)

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
        for name, label in [("rect", "Rechteck"), ("circle", "Kreis"), ("star", "Stern"),
                            ("spiral", "Spirale"), ("grid", "Raster"), ("text", "Text"),
                            ("image", "Bild"), ("free", "Freihand")]:
            ttk.Radiobutton(panel, text=label, value=name, variable=self.tool_var).pack(side="left", padx=2)

        params = ttk.Frame(tab)
        params.pack(fill="x", pady=4)
        self.param_entries = {}
        for i, (key, default) in enumerate([
            ("x", "0.1"), ("y", "0.1"), ("w/h", "0.5"), ("r", "0.2"),
            ("nx/ny", "5"), ("text", "PLOT"), ("size", "0.1")]):
            ttk.Label(params, text=key).grid(row=0, column=i * 2, padx=2)
            e = ttk.Entry(params, width=8)
            e.insert(0, default)
            e.grid(row=0, column=i * 2 + 1, padx=2)
            self.param_entries[key] = e

        ttk.Button(tab, text="Zeichnen", command=self._add_shape).pack(pady=3)
        ttk.Button(tab, text="Bild laden & tracer", command=self._load_image).pack(pady=3)
        ttk.Button(tab, text="Alles löschen", command=lambda: (self.paths.clear(), self._redraw())).pack(pady=3)

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self._free_path = None

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
        for path in self.paths + ([self._free_path] if self._free_path else []):
            if not path:
                continue
            pts = [p for (px, py) in path for p in (px * w, (1 - py) * h)]
            if len(pts) >= 4:
                self.canvas.create_line(*pts, fill="black", width=2)

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
        gcode = export_gcode(self.paths, self.calibration, self.pen, header_comment="IP Plot Job")
        try:
            self.connection.upload_and_start(gcode)
            self.plot_ip_label.config(text="Plot gestartet ✓")
            messagebox.showinfo("Plot", "Plot wurde über IP gestartet.")
        except PrinterConnectionError as e:
            self.plot_ip_label.config(text="")
            messagebox.showerror("Netzwerkfehler", str(e))


def main():
    app = PlotterApp()
    app.mainloop()


if __name__ == "__main__":
    main()
