"""SVG-Import: SVG-Pfade in Papier-Pfade (0..1) umwandeln – ohne externe Abhängigkeiten."""
import re
import xml.etree.ElementTree as ET


def _nums(s):
    return [float(v) for v in re.findall(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", s or "")]


def _parse_path(d):
    """Parst SVG-Path-Daten (M, L, H, V, C, Q, A als Näherung, Z) in Subpfade."""
    tokens = re.findall(r"([MmLlHhVvCcSsQqTtAaZz])|([-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?)", d)
    cmds = []
    for c, num in tokens:
        if c:
            cmds.append((c, []))
        elif cmds:
            cmds[-1][1].append(float(num))

    subs = []
    cur = (0.0, 0.0)
    start = (0.0, 0.0)
    points = []

    def flush():
        if len(points) >= 2:
            subs.append(list(points))
        points.clear()

    for cmd, args in cmds:
        c = cmd
        i = 0
        if c == "M":
            flush()
            while i + 1 < len(args) or i < len(args):
                cur = (args[i], args[i + 1] if i + 1 < len(args) else cur[1])
                start = cur
                points.append(cur)
                i += 2
        elif c == "m":
            flush()
            while i + 1 < len(args) or i < len(args):
                cur = (cur[0] + args[i], cur[1] + (args[i + 1] if i + 1 < len(args) else 0))
                start = cur
                points.append(cur)
                i += 2
        elif c == "L":
            while i + 1 < len(args):
                cur = (args[i], args[i + 1])
                points.append(cur)
                i += 2
        elif c == "l":
            while i + 1 < len(args):
                cur = (cur[0] + args[i], cur[1] + args[i + 1])
                points.append(cur)
                i += 2
        elif c == "H":
            while i < len(args):
                cur = (args[i], cur[1])
                points.append(cur)
                i += 1
        elif c == "h":
            while i < len(args):
                cur = (cur[0] + args[i], cur[1])
                points.append(cur)
                i += 1
        elif c == "V":
            while i < len(args):
                cur = (cur[0], args[i])
                points.append(cur)
                i += 1
        elif c == "v":
            while i < len(args):
                cur = (cur[0], cur[1] + args[i])
                points.append(cur)
                i += 1
        elif c in ("C", "c"):
            # Bezier grob abtasten (4 Punkte je Segment)
            while i + 5 < len(args):
                if c == "C":
                    p0, p1, p2, p3 = cur, (args[i], args[i + 1]), (args[i + 2], args[i + 3]), (args[i + 4], args[i + 5])
                else:
                    p1 = (cur[0] + args[i], cur[1] + args[i + 1])
                    p2 = (cur[0] + args[i + 2], cur[1] + args[i + 3])
                    p3 = (cur[0] + args[i + 4], cur[1] + args[i + 5])
                    p0 = cur
                for t in (0.25, 0.5, 0.75, 1.0):
                    mt = 1 - t
                    x = mt ** 3 * p0[0] + 3 * mt ** 2 * t * p1[0] + 3 * mt * t ** 2 * p2[0] + t ** 3 * p3[0]
                    y = mt ** 3 * p0[1] + 3 * mt ** 2 * t * p1[1] + 3 * mt * t ** 2 * p2[1] + t ** 3 * p3[1]
                    points.append((x, y))
                cur = p3
                i += 6
        elif c == "Z" or c == "z":
            points.append(start)
            cur = start
            flush()
    flush()
    return subs


def _apply_transform(pts, tf):
    """Wendet matrix/translate/scale/rotate an (einfache Verkettung)."""
    if not tf:
        return pts
    m = re.match(r"matrix\(([^)]+)\)", tf.strip())
    if m:
        a, b, c, d, e, f = (_nums(m.group(1)) + [0] * 6)[:6]
        return [(a * x + c * y + e, b * x + d * y + f) for (x, y) in pts]
    tr = re.match(r"translate\(([^)]+)\)", tf.strip())
    if tr:
        vals = (_nums(tr.group(1)) + [0, 0])[:2]
        return [(x + vals[0], y + vals[1]) for (x, y) in pts]
    sc = re.match(r"scale\(([^)]+)\)", tf.strip())
    if sc:
        vals = (_nums(sc.group(1)) + [1, 1])[:2]
        return [(x * vals[0], y * vals[1]) for (x, y) in pts]
    return pts


def load_svg(filename, bed_w=200, bed_h=200, margin=5):
    """SVG → Papier-Pfade (0..1). Nutzt viewBox/Breite; Y wird gespiegelt."""
    tree = ET.parse(filename)
    root = tree.getroot()

    vb = _nums(root.get("viewBox", ""))
    if len(vb) == 4:
        ox, oy, vw, vh = vb
    else:
        vw, vh = 210.0, 297.0

    paths = []
    for el in root.iter():
        if el.tag.endswith("}path") or el.tag == "path":
            d = el.get("d", "")
            tf = el.get("transform", "")
            for sub in _parse_path(d):
                sub = _apply_transform(sub, tf)
                if len(sub) >= 2:
                    paths.append(sub)
        elif el.tag.endswith("}polyline") or el.tag == "polyline":
            vals = _nums(el.get("points", ""))
            pts = [(vals[i], vals[i + 1]) for i in range(0, len(vals) - 1, 2)]
            pts = _apply_transform(pts, el.get("transform", ""))
            if len(pts) >= 2:
                paths.append(pts)
        elif el.tag.endswith("}rect") or el.tag == "rect":
            x, y = float(el.get("x", 0) or 0), float(el.get("y", 0) or 0)
            w, h = float(el.get("width", 0) or 0), float(el.get("height", 0) or 0)
            pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
            pts = _apply_transform(pts, el.get("transform", ""))
            paths.append(pts)
        elif el.tag.endswith("}circle") or el.tag == "circle":
            cx, cy, r = (float(el.get(k, 0) or 0) for k in ("cx", "cy", "r"))
            import math
            pts = [(cx + r * math.cos(2 * math.pi * i / 48),
                    cy + r * math.sin(2 * math.pi * i / 48)) for i in range(49)]
            pts = _apply_transform(pts, el.get("transform", ""))
            paths.append(pts)

    if not paths:
        return []

    # Bounds und Skalierung auf 0..1 (mit Rand), Y spiegeln (SVG-Y wächst nach unten)
    xs = [p[0] for path in paths for p in path]
    ys = [p[1] for path in paths for p in path]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 1e-9)
    span_y = max(max_y - min_y, 1e-9)
    scale = min((1 - 2 * margin / bed_w) / span_x, (1 - 2 * margin / bed_h) / span_y, 1.0)
    off_x = (1 - span_x * scale) / 2
    off_y = (1 - span_y * scale) / 2

    return [[(off_x + (px - min_x) * scale, off_y + (py - min_y) * scale)
             for (px, py) in path] for path in paths]
