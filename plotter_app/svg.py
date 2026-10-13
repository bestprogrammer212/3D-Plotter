"""SVG-Import: SVG-Pfade in Papier-Pfade (0..1) umwandeln – ohne externe Abhängigkeiten."""
import math
import re
import xml.etree.ElementTree as ET


def _nums(s):
    return [float(v) for v in re.findall(r"[-+]?(?:\d*\.?\d+|\d+\.?)(?:[eE][-+]?\d+)?", s or "")]


# ---------- Transform-Matrizen ----------

def _identity():
    return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _mat_mul(m, n):
    """Verkettet zwei Matrizen (m * n): Punkt wird erst n, dann m transformiert."""
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (a1 * a2 + c1 * b2,
            b1 * a2 + d1 * b2,
            a1 * c2 + c1 * d2,
            b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1,
            b1 * e2 + d1 * f2 + f1)


def _apply_mat(m, pt):
    a, b, c, d, e, f = m
    x, y = pt
    return (a * x + c * y + e, b * x + d * y + f)


def _parse_transform(tf):
    """Parst eine transform-Attribut-Zeichenkette in eine Matrix (Verkettung)."""
    m = _identity()
    if not tf:
        return m
    for name, arg in re.findall(r"([a-zA-Z]+)\s*\(([^)]*)\)", tf):
        vals = _nums(arg)
        name = name.strip().lower()
        if name == "matrix" and len(vals) >= 6:
            t = (vals[0], vals[1], vals[2], vals[3], vals[4], vals[5])
        elif name == "translate":
            tx = vals[0] if len(vals) > 0 else 0.0
            ty = vals[1] if len(vals) > 1 else 0.0
            t = (1, 0, 0, 1, tx, ty)
        elif name == "scale":
            sx = vals[0] if len(vals) > 0 else 1.0
            sy = vals[1] if len(vals) > 1 else sx
            t = (sx, 0, 0, sy, 0, 0)
        elif name == "rotate":
            ang = math.radians(vals[0])
            cx = vals[1] if len(vals) > 1 else 0.0
            cy = vals[2] if len(vals) > 2 else 0.0
            cos, sin = math.cos(ang), math.sin(ang)
            rot = (cos, sin, -sin, cos, 0, 0)
            # rotate(cx, cy) = translate(cx,cy) * rotate * translate(-cx,-cy)
            t = _mat_mul((1, 0, 0, 1, -cx, -cy), rot)
            t = _mat_mul(t, (1, 0, 0, 1, cx, cy))
        elif name == "skewx":
            t = (1, 0, math.tan(math.radians(vals[0] if vals else 0)), 1, 0, 0)
        elif name == "skewy":
            t = (1, math.tan(math.radians(vals[0] if vals else 0)), 0, 1, 0, 0)
        else:
            continue
        m = _mat_mul(m, t)
    return m


# ---------- Path-Parsing ----------

def _arc_points(x0, y0, rx, ry, phi, large, sweep, x1, y1, step_deg=10.0):
    """SVG-Arc (Endpoint-Parametrisierung) als Polygon-Näherung (~step_deg-Schritte)."""
    if x0 == x1 and y0 == y1:
        return []
    rx, ry = abs(rx), abs(ry)
    if rx == 0 or ry == 0:
        return [(x1, y1)]
    phi = math.radians(phi)
    cos_p, sin_p = math.cos(phi), math.sin(phi)
    dx2, dy2 = (x0 - x1) / 2.0, (y0 - y1) / 2.0
    x1p = cos_p * dx2 + sin_p * dy2
    y1p = -sin_p * dx2 + cos_p * dy2
    lam = x1p ** 2 / rx ** 2 + y1p ** 2 / ry ** 2
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = rx ** 2 * ry ** 2 - rx ** 2 * y1p ** 2 - ry ** 2 * x1p ** 2
    den = rx ** 2 * y1p ** 2 + ry ** 2 * x1p ** 2
    if den == 0:
        return [(x1, y1)]
    co = math.sqrt(max(0.0, num / den))
    if large == sweep:
        co = -co
    cxp = co * rx * y1p / ry
    cyp = -co * ry * x1p / rx
    cx = cos_p * cxp - sin_p * cyp + (x0 + x1) / 2.0
    cy = sin_p * cxp + cos_p * cyp + (y0 + y1) / 2.0
    ux, uy = (x1p - cxp) / rx, (y1p - cyp) / ry
    vx, vy = (-x1p - cxp) / rx, (-y1p - cyp) / ry
    theta = math.atan2(uy, ux)
    dtheta = math.acos(max(-1.0, min(1.0, (ux * vx + uy * vy) /
                                     math.sqrt((ux ** 2 + uy ** 2) * (vx ** 2 + vy ** 2)))))
    if ux * vy - uy * vx < 0:
        dtheta = -dtheta
    if not sweep and dtheta > 0:
        dtheta -= 2 * math.pi
    elif sweep and dtheta < 0:
        dtheta += 2 * math.pi
    steps = max(1, int(math.ceil(abs(dtheta) / math.radians(step_deg))))
    pts = []
    for i in range(1, steps + 1):
        t = theta + dtheta * i / steps
        px = cx + rx * math.cos(t) * cos_p - ry * math.sin(t) * sin_p
        py = cy + rx * math.cos(t) * sin_p + ry * math.sin(t) * cos_p
        pts.append((px, py))
    return pts


def _cubic(p0, p1, p2, p3, samples=(0.25, 0.5, 0.75, 1.0)):
    pts = []
    for t in samples:
        mt = 1 - t
        x = mt ** 3 * p0[0] + 3 * mt ** 2 * t * p1[0] + 3 * mt * t ** 2 * p2[0] + t ** 3 * p3[0]
        y = mt ** 3 * p0[1] + 3 * mt ** 2 * t * p1[1] + 3 * mt * t ** 2 * p2[1] + t ** 3 * p3[1]
        pts.append((x, y))
    return pts


def _quad(p0, p1, p2, samples=(0.25, 0.5, 0.75, 1.0)):
    pts = []
    for t in samples:
        mt = 1 - t
        x = mt ** 2 * p0[0] + 2 * mt * t * p1[0] + t ** 2 * p2[0]
        y = mt ** 2 * p0[1] + 2 * mt * t * p1[1] + t ** 2 * p2[1]
        pts.append((x, y))
    return pts


def _parse_path(d):
    """Parst SVG-Path-Daten (M/L/H/V/C/S/Q/T/A/Z, auch klein) in Subpfade."""
    tokens = re.findall(r"([MmLlHhVvCcSsQqTtAaZz])|([-+]?(?:\d*\.?\d+|\d+\.?)(?:[eE][-+]?\d+)?)", d)
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
    # letzter Kontrollpunkt fuer S/T-Reflexion
    last_cubic_cp = None
    last_quad_cp = None

    def flush():
        if len(points) >= 2:
            subs.append(list(points))
        points.clear()

    for cmd, args in cmds:
        c = cmd
        i = 0
        if c in ("M", "m"):
            flush()
            while i + 1 < len(args) or i < len(args):
                if c == "M":
                    cur = (args[i], args[i + 1] if i + 1 < len(args) else cur[1])
                else:
                    cur = (cur[0] + args[i], cur[1] + (args[i + 1] if i + 1 < len(args) else 0))
                start = cur
                points.append(cur)
                i += 2
            last_cubic_cp = None
            last_quad_cp = None
        elif c in ("L", "l"):
            while i + 1 < len(args):
                if c == "L":
                    cur = (args[i], args[i + 1])
                else:
                    cur = (cur[0] + args[i], cur[1] + args[i + 1])
                points.append(cur)
                i += 2
            last_cubic_cp = None
            last_quad_cp = None
        elif c in ("H", "h"):
            while i < len(args):
                cur = (args[i] if c == "H" else cur[0] + args[i], cur[1])
                points.append(cur)
                i += 1
            last_cubic_cp = None
            last_quad_cp = None
        elif c in ("V", "v"):
            while i < len(args):
                cur = (cur[0], args[i] if c == "V" else cur[1] + args[i])
                points.append(cur)
                i += 1
            last_cubic_cp = None
            last_quad_cp = None
        elif c in ("C", "c"):
            while i + 6 <= len(args):
                if c == "C":
                    p1 = (args[i], args[i + 1])
                    p2 = (args[i + 2], args[i + 3])
                    p3 = (args[i + 4], args[i + 5])
                else:
                    p1 = (cur[0] + args[i], cur[1] + args[i + 1])
                    p2 = (cur[0] + args[i + 2], cur[1] + args[i + 3])
                    p3 = (cur[0] + args[i + 4], cur[1] + args[i + 5])
                points.extend(_cubic(cur, p1, p2, p3))
                last_cubic_cp = p2
                cur = p3
                i += 6
            last_quad_cp = None
        elif c in ("S", "s"):
            while i + 4 <= len(args):
                if c == "S":
                    p2 = (args[i], args[i + 1])
                    p3 = (args[i + 2], args[i + 3])
                else:
                    p2 = (cur[0] + args[i], cur[1] + args[i + 1])
                    p3 = (cur[0] + args[i + 2], cur[1] + args[i + 3])
                # Reflexions-Kontrollpunkt: gespiegelt am aktuellen Punkt
                if last_cubic_cp is not None:
                    p1 = (2 * cur[0] - last_cubic_cp[0], 2 * cur[1] - last_cubic_cp[1])
                else:
                    p1 = cur
                points.extend(_cubic(cur, p1, p2, p3))
                last_cubic_cp = p2
                cur = p3
                i += 4
            last_quad_cp = None
        elif c in ("Q", "q"):
            while i + 4 <= len(args):
                if c == "Q":
                    p1 = (args[i], args[i + 1])
                    p2 = (args[i + 2], args[i + 3])
                else:
                    p1 = (cur[0] + args[i], cur[1] + args[i + 1])
                    p2 = (cur[0] + args[i + 2], cur[1] + args[i + 3])
                points.extend(_quad(cur, p1, p2))
                last_quad_cp = p1
                cur = p2
                i += 4
            last_cubic_cp = None
        elif c in ("T", "t"):
            while i + 2 <= len(args):
                if c == "T":
                    p2 = (args[i], args[i + 1])
                else:
                    p2 = (cur[0] + args[i], cur[1] + args[i + 1])
                # Reflektierter Kontrollpunkt des vorherigen Q/T
                if last_quad_cp is not None:
                    p1 = (2 * cur[0] - last_quad_cp[0], 2 * cur[1] - last_quad_cp[1])
                else:
                    p1 = cur
                points.extend(_quad(cur, p1, p2))
                last_quad_cp = p1
                cur = p2
                i += 2
            last_cubic_cp = None
        elif c in ("A", "a"):
            while i + 7 <= len(args):
                rx, ry, rot, large, sweep = args[i], args[i + 1], args[i + 2], args[i + 3], args[i + 4]
                if c == "A":
                    ex, ey = args[i + 5], args[i + 6]
                else:
                    ex, ey = cur[0] + args[i + 5], cur[1] + args[i + 6]
                points.extend(_arc_points(cur[0], cur[1], rx, ry, rot,
                                          1 if large >= 0.5 else 0,
                                          1 if sweep >= 0.5 else 0, ex, ey))
                cur = (ex, ey)
                i += 7
            last_cubic_cp = None
            last_quad_cp = None
        elif c in ("Z", "z"):
            points.append(start)
            cur = start
            flush()
            last_cubic_cp = None
            last_quad_cp = None
    flush()
    return subs


# ---------- Element-Baum ----------

def _localname(tag):
    return tag.rsplit("}", 1)[-1]


def _iter_elements(el, mat, out):
    """Rekursiver Durchlauf: <g>-Transforms werden an Kinder vererbt (verkettet)."""
    child_mat = _mat_mul(mat, _parse_transform(el.get("transform", "")))
    shape_pts = _element_points(el)
    for pts in shape_pts:
        transformed = [_apply_mat(child_mat, p) for p in pts]
        if len(transformed) >= 2:
            out.append(transformed)
    for child in el:
        _iter_elements(child, child_mat, out)


def _element_points(el):
    """Liefert Punktlisten eines Shape-Elements (ohne Transform)."""
    name = _localname(el.tag)
    if name == "path":
        return _parse_path(el.get("d", ""))
    if name in ("polyline", "polygon"):
        vals = _nums(el.get("points", ""))
        pts = [(vals[i], vals[i + 1]) for i in range(0, len(vals) - 1, 2)]
        if name == "polygon" and pts and pts[0] != pts[-1]:
            pts.append(pts[0])  # geschlossen
        return [pts] if len(pts) >= 2 else []
    if name == "line":
        x1, y1 = float(el.get("x1", 0) or 0), float(el.get("y1", 0) or 0)
        x2, y2 = float(el.get("x2", 0) or 0), float(el.get("y2", 0) or 0)
        return [[(x1, y1), (x2, y2)]]
    if name == "rect":
        x, y = float(el.get("x", 0) or 0), float(el.get("y", 0) or 0)
        w, h = float(el.get("width", 0) or 0), float(el.get("height", 0) or 0)
        return [[(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]]
    if name == "circle":
        cx, cy = float(el.get("cx", 0) or 0), float(el.get("cy", 0) or 0)
        r = float(el.get("r", 0) or 0)
        return [[(cx + r * math.cos(2 * math.pi * i / 48),
                  cy + r * math.sin(2 * math.pi * i / 48)) for i in range(49)]]
    if name == "ellipse":
        cx, cy = float(el.get("cx", 0) or 0), float(el.get("cy", 0) or 0)
        rx, ry = float(el.get("rx", 0) or 0), float(el.get("ry", 0) or 0)
        return [[(cx + rx * math.cos(2 * math.pi * i / 48),
                  cy + ry * math.sin(2 * math.pi * i / 48)) for i in range(49)]]
    return []


def load_svg(filename, bed_w=200, bed_h=200, margin=5):
    """SVG → Papier-Pfade (0..1). Nutzt viewBox/Breite; Y wird gespiegelt
    (SVG-Y wächst nach unten, Papier-Y nach oben)."""
    tree = ET.parse(filename)
    root = tree.getroot()
    vb = _nums(root.get("viewBox", ""))
    if len(vb) == 4:
        _ox, _oy, vw, vh = vb
    else:
        vw, vh = 210.0, 297.0
    paths = []
    _iter_elements(root, _identity(), paths)
    if not paths:
        return []
    # Bounds und Skalierung auf 0..1 (mit Rand)
    xs = [p[0] for path in paths for p in path]
    ys = [p[1] for path in paths for p in path]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 1e-9)
    span_y = max(max_y - min_y, 1e-9)
    scale = min((1 - 2 * margin / bed_w) / span_x, (1 - 2 * margin / bed_h) / span_y, 1.0)
    off_x = (1 - span_x * scale) / 2
    off_y = (1 - span_y * scale) / 2
    # Y SPIEGELN bei der Normalisierung: Papier-Koordinaten = (x, 1 - y)
    return [[(off_x + (px - min_x) * scale, 1 - (off_y + (py - min_y) * scale))
             for (px, py) in path] for path in paths]
