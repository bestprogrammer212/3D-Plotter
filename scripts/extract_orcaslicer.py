#!/usr/bin/env python3
"""Extrahiert alle Druckerdaten aus den OrcaSlicer-Profilen in eine JSON-Datei."""
import json
import os
import re
import sys

PROFILES_DIR = os.path.join(os.path.dirname(__file__), "..", "resources", "profiles")
if len(sys.argv) > 1:
    PROFILES_DIR = sys.argv[1]

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "printers.json")


def parse_area(area_str):
    if isinstance(area_str, list):
        pts = []
        for p in area_str:
            try:
                a, b = str(p).split("x")
                pts.append((float(a), float(b)))
            except (ValueError, AttributeError):
                continue
        if not pts:
            return None, None
        return max(x for x, _ in pts), max(y for _, y in pts)
    m = re.findall(r"(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)", str(area_str or ""))
    if not m:
        return None, None
    xs = [float(a) for a, b in m]
    ys = [float(b) for a, b in m]
    return max(xs), max(ys)


def main():
    printers = []
    for vendor_file in sorted(os.listdir(PROFILES_DIR)):
        if not vendor_file.endswith(".json") or vendor_file in ("blacklist.json",):
            continue
        vendor = vendor_file[:-5]
        vendor_path = os.path.join(PROFILES_DIR, vendor_file)
        try:
            with open(vendor_path, encoding="utf-8") as f:
                vdata = json.load(f)
        except Exception:
            continue
        machine_dir = os.path.join(PROFILES_DIR, vendor, "machine")
        if not os.path.isdir(machine_dir):
            continue
        models = vdata.get("machine_model_list") or []
        for model in models:
            sub = model.get("sub_path", "")
            # sub_path kann Unterverzeichnisse enthalten, z. B. "machine/EN4SERIES/..."
            rel = sub[len("machine/"):] if sub.startswith("machine/") else sub
            stem = rel[:-len(".json")] if rel.endswith(".json") else rel
            machine_file = os.path.join(machine_dir, *stem.split("/")) + ".json"
            nozzle_file = os.path.join(machine_dir, *(stem.split("/")[:-1] + [f"{stem.split('/')[-1]} 0.4 nozzle"])) + ".json"
            mdata = None
            for candidate in (nozzle_file, machine_file):
                if os.path.exists(candidate):
                    try:
                        with open(candidate, encoding="utf-8") as f:
                            mdata = json.load(f)
                            break
                    except Exception:
                        continue
            if not mdata:
                continue
            w, h = parse_area(mdata.get("printable_area", ""))
            if not w:
                continue
            printers.append({
                "name": model.get("name", stem.split("/")[-1]),
                "vendor": vendor,
                "model_id": model.get("model_id", ""),
                "bed_x": w,
                "bed_y": h,
                "bed_z": float(mdata.get("printable_height", 200) or 200),
            })
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(printers, f, ensure_ascii=False, indent=1)
    print(f"{len(printers)} Drucker extrahiert -> {OUT}")


if __name__ == "__main__":
    main()
