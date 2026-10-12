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

    def up_gcode(self):
        return [f"G1 Z{self.pen_up_z:.2f} F{self.travel_speed * 60:.0f}"]

    def down_gcode(self):
        return [f"G1 Z{self.pen_draw_z:.2f} F{self.travel_speed * 60:.0f}"]

    def lift_gcode(self):
        if self.z_lift_between_paths > 0:
            return [f"G1 Z{self.pen_draw_z + self.z_lift_between_paths:.2f} F{self.travel_speed * 60:.0f}"]
        return self.up_gcode()
