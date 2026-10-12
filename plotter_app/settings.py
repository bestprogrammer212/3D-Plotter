"""Einstellungen dauerhaft speichern/laden (Kalibrierung, Stift, Drucker, Verbindung)."""
import json
import os

APP_DIR = os.path.join(os.path.expanduser("~"), ".plotter_app")
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")


def save(calibration, pen, printer_name, host, conn_kind):
    data = {
        "corners": list(calibration.points),
        "heights": list(calibration.heights),
        "pen": {
            "pen_up_z": pen.pen_up_z,
            "pen_draw_z": pen.pen_draw_z,
            "pen_offset_z": pen.pen_offset_z,
            "paper_z": getattr(pen, "paper_z", 0.0),
            "travel_speed": pen.travel_speed,
            "draw_speed": pen.draw_speed,
            "z_lift_between_paths": pen.z_lift_between_paths,
        },
        "printer": printer_name,
        "host": host,
        "conn_kind": conn_kind,
    }
    os.makedirs(APP_DIR, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def load():
    if not os.path.exists(SETTINGS_FILE):
        return None
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def apply_to(data, calibration, pen):
    """Übernimmt geladene Werte in Calibration- und Pen-Objekte."""
    if not data:
        return
    calibration.clear()
    for (x, y) in data.get("corners", []):
        calibration.add_point(x, y)
    if data.get("heights") and len(data["heights"]) == len(data.get("corners", [])):
        calibration.heights = list(data["heights"])
    p = data.get("pen", {})
    pen.pen_up_z = p.get("pen_up_z", pen.pen_up_z)
    pen.pen_draw_z = p.get("pen_draw_z", pen.pen_draw_z)
    pen.pen_offset_z = p.get("pen_offset_z", pen.pen_offset_z)
    pen.paper_z = p.get("paper_z", 0.0)
    pen.travel_speed = p.get("travel_speed", pen.travel_speed)
    pen.draw_speed = p.get("draw_speed", pen.draw_draw_speed if hasattr(pen, "pen_draw_speed") else pen.draw_speed)
    pen.z_lift_between_paths = p.get("z_lift_between_paths", pen.z_lift_between_paths)
