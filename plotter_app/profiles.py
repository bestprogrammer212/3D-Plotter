"""Druckerprofile: OrcaSlicer-Datenbank (data/printers.json) und JSON-Import."""
import json
import os

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "printers.json")

BUILTIN_PRINTERS = [
    {"name": "Bambu Lab A1", "bed_x": 256, "bed_y": 256, "bed_z": 256, "max_speed": 500},
    {"name": "Bambu Lab P1S", "bed_x": 256, "bed_y": 256, "bed_z": 256, "max_speed": 500},
    {"name": "Bambu Lab X1C", "bed_x": 256, "bed_y": 256, "bed_z": 256, "max_speed": 500},
    {"name": "Creality Ender 3", "bed_x": 220, "bed_y": 220, "bed_z": 250, "max_speed": 180},
    {"name": "Creality Ender 3 V3", "bed_x": 220, "bed_y": 220, "bed_z": 250, "max_speed": 250},
    {"name": "Prusa MK4", "bed_x": 250, "bed_y": 210, "bed_z": 220, "max_speed": 200},
    {"name": "Prusa MINI", "bed_x": 180, "bed_y": 180, "bed_z": 180, "max_speed": 200},
    {"name": "Voron 2.4 300", "bed_x": 300, "bed_y": 300, "bed_z": 300, "max_speed": 350},
    {"name": "Voron Trident 300", "bed_x": 300, "bed_y": 300, "bed_z": 250, "max_speed": 350},
]


def load_builtin():
    """Lädt alle Drucker aus der eingebetteten OrcaSlicer-Datenbank (291 Modelle)."""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return list(BUILTIN_PRINTERS)


def _as_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def load_printer_profile(path):
    """OrcaSlicer machine-JSON einlesen; erkennt gängige Feldnamen."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    def pick(*keys, default=0):
        for k in keys:
            for dk, dv in data.items():
                if k.lower() in dk.lower():
                    return dv
        return default

    name = pick("printer_model", "printer_model_id", default=os.path.basename(path))

    # OrcaSlicer "printable_area" ist eine LISTE von Ecken [[0,0],[220,0],...]
    # -> bed_x = max x, bed_y = max y daraus extrahieren.
    bed_x = bed_y = None
    area = pick("printable_area", default=None)
    if isinstance(area, list) and area:
        xs, ys = [], []
        for corner in area:
            if isinstance(corner, (list, tuple)) and len(corner) >= 2:
                xs.append(_as_float(corner[0]))
                ys.append(_as_float(corner[1]))
        if xs:
            bed_x = max(xs)
        if ys:
            bed_y = max(ys)
    if bed_x is None:
        bed_x = _as_float(pick("x_size", "bed_size", default=200), 200)
    if bed_y is None:
        bed_y = _as_float(pick("y_size", "bed_size", default=200), 200)

    return {
        "name": str(name),
        "bed_x": bed_x,
        "bed_y": bed_y,
        "bed_z": _as_float(pick("printable_height", "z_size", default=200), 200),
        "max_speed": _as_float(pick("max_speed", default=180), 180),
    }
