"""Stift-Höhenverwaltung und Regeln für Pen up/down während des Plottens."""
from dataclasses import dataclass


@dataclass
class PenSettings:
    pen_up_z: float = 20.0
    pen_draw_z: float = 0.0
    travel_speed: float = 80.0
    draw_speed: float = 40.0
    z_lift_between_paths: float = 1.0   # kleines Anheben zwischen Pfaden (0 = aus)
    safe_z_margin: float = 5.0          # Freifahrt über Papier hinaus

    # --- Stift-Höhen-Erkennung ---
    # Der Stift sitzt meist UNTER der Nozzle-Ebene (z. B. mit Klemme montiert).
    # pen_offset_z = Abstand Stiftspitze <-> Nozzle-Spitze (negativ = Stift tiefer).
    pen_offset_z: float = 0.0
    # paper_z = Z-Höhe der Nozzle, wenn die Nozzle das Papier berührt
    # (z. B. durch Paper-Feeler/CALIBRATE ermittelt).
    paper_z: float = 0.0

    @property
    def pen_touch_z(self):
        """Z (Nozzle-Bezug), bei dem die STIFTSPITZE das Papier berührt."""
        return self.paper_z + self.pen_offset_z

    def auto_from_paper_z(self, paper_z):
        """Setzt Z-Werte automatisch aus der gemessenen Papierberühr-Höhe der Nozzle."""
        self.paper_z = float(paper_z)
        self.pen_draw_z = self.pen_touch_z
        self.pen_up_z = self.pen_draw_z + 5.0

    def auto_from_pen_touch(self, pen_touch_z):
        """Wenn die STIFTSPITZE das Papier berührt, direkt diesen Z-Wert nutzen."""
        self.pen_draw_z = float(pen_touch_z)
        self.pen_up_z = self.pen_draw_z + 5.0

    def up_gcode(self):
        return [f"G1 Z{self.pen_up_z:.2f} F{self.travel_speed * 60:.0f}"]

    def down_gcode(self):
        return [f"G1 Z{self.pen_draw_z:.2f} F{self.travel_speed * 60:.0f}"]

    def lift_gcode(self):
        if self.z_lift_between_paths > 0:
            return [f"G1 Z{self.pen_draw_z + self.z_lift_between_paths:.2f} F{self.travel_speed * 60:.0f}"]
        return self.up_gcode()
