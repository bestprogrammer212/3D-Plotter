"""Druckerprofile: Einlesen von OrcaSlicer-Profilen (.json) und Fallback-Liste."""
import json
import os

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
    return list(BUILTIN_PRINTERS)


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
    return {
        "name": str(name),
        "bed_x": pick("printable_area", "bed_size", "x_size", default=200),
        "bed_y": pick("bed_size", "y_size", default=200),
        "bed_z": pick("printable_height", "z_size", default=200),
        "max_speed": pick("max_speed", default=180),
    }
