"""Design-Tools: Erzeugen von Papier-Pfaden (Koordinaten 0..1) aus Formen, Text und Bildern."""
import math
import os

PAPER_W = 1.0
PAPER_H = 1.0


def rect(x, y, w, h, steps=64):
    """Rechteck, (x,y) = untere linke Ecke in Papier-Einheiten."""
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]


def circle(cx, cy, r, steps=96):
    pts = []
    for i in range(steps + 1):
        a = 2 * math.pi * i / steps
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def star(cx, cy, r_out, r_in, points=5):
    pts = []
    for i in range(points * 2):
        a = math.pi * i / points - math.pi / 2
        r = r_out if i % 2 == 0 else r_in
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    pts.append(pts[0])
    return pts


def spiral(cx, cy, r_max, turns=4, steps=400):
    pts = []
    for i in range(steps + 1):
        t = i / steps
        a = 2 * math.pi * turns * t
        r = r_max * t
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def ellipse(cx, cy, rx, ry, steps=96):
    pts = []
    for i in range(steps + 1):
        a = 2 * math.pi * i / steps
        pts.append((cx + rx * math.cos(a), cy + ry * math.sin(a)))
    return pts


def heart(cx, cy, s, steps=120):
    pts = []
    for i in range(steps + 1):
        t = 2 * math.pi * i / steps
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((cx + s * x / 32, cy + s * y / 32))
    return pts


def wave(x, y, width, amplitude, cycles=5, steps=200):
    pts = []
    for i in range(steps + 1):
        t = i / steps
        pts.append((x + width * t, y + amplitude * math.sin(2 * math.pi * cycles * t)))
    return pts


def polygon(cx, cy, r, n, rotation=0.0):
    """Regelmäßiges n-Eck."""
    pts = []
    for i in range(n + 1):
        a = 2 * math.pi * i / n + rotation
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def polyline(points):
    return [tuple(p) for p in points]


def smooth_curve(points, iterations=3, closed=True):
    """Chaikin-Eckenrunder: macht kantige Konturen zu weichen Kurven.

    Jede Iteration ersetzt Segmente durch zwei neue Punkte bei 25 %/75 % –
    Ecken werden dadurch kurvig gerundet, ohne die Form zu verzerren.
    """
    pts = list(points)
    if len(pts) < 3:
        return pts
    for _ in range(iterations):
        if closed and pts[0] == pts[-1]:
            ring = pts[:-1]
            if len(ring) < 3:
                return pts
            new = []
            n = len(ring)
            for i in range(n):
                a = ring[i]
                b = ring[(i + 1) % n]
                new.append((0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]))
                new.append((0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1]))
            pts = new + [new[0]]
        else:
            new = [pts[0]]
            for i in range(len(pts) - 1):
                a, b = pts[i], pts[i + 1]
                new.append((0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]))
                new.append((0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1]))
            new.append(pts[-1])
            pts = new
    return pts


def _poly_bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _point_in_poly(pt, poly):
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if xin > x:
                inside = not inside
    return inside


def infill_lines(polygon, spacing=0.05, angle=0.0, bbox_clip=None):
    """Fuell-Linien (Hatching) fuer ein geschlossenes Polygon.

    angle=0: horizontale Linien; andere Winkel in Radiant drehen das Raster.
    Liefert Pfad-Segmente [(x1,y1),(x2,y2)], geschnitten mit dem Polygon.
    """
    if len(polygon) < 3:
        return []
    ring = polygon[:-1] if polygon[0] == polygon[-1] else polygon
    x0, y0, x1, y1 = _poly_bbox(ring)
    w = x1 - x0
    h = y1 - y0
    if w <= 0 or h <= 0:
        return []
    ca, sa = math.cos(angle), math.sin(angle)
    # Raster im gedrehten Raum erzeugen, dann zurueckdrehen
    diag = math.hypot(w, h)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    segs = []
    d = -diag / 2
    while d <= diag / 2:
        # Linie im gedrehten Raum: von -diag/2..diag/2 entlang, Offset d
        ax, ay = -diag / 2, d
        bx, by = diag / 2, d
        # zurueck ins Weltkoordinaten-System
        pax = cx + ax * ca - ay * sa
        pay = cy + ax * sa + ay * ca
        pbx = cx + bx * ca - by * sa
        pby = cy + bx * sa + by * ca
        # Schnittpunkte der Linie mit allen Polygonkanten sammeln
        ts = []
        n = len(ring)
        for i in range(n):
            qx1, qy1 = ring[i]
            qx2, qy2 = ring[(i + 1) % n]
            dx, dy = qx2 - qx1, qy2 - qy1
            den = (pbx - pax) * dy - (pby - pay) * dx
            if abs(den) < 1e-12:
                continue
            t = ((qx1 - pax) * dy - (qy1 - pay) * dx) / den
            u = ((qx1 - pax) * (pby - pay) - (qy1 - pay) * (pbx - pax)) / den
            if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
                ts.append(t)
        if len(ts) >= 2:
            ts.sort()
            for k in range(0, len(ts) - 1, 2):
                a = (pax + (pbx - pax) * ts[k], pay + (pby - pay) * ts[k])
                b = (pax + (pbx - pax) * ts[k + 1], pay + (pby - pay) * ts[k + 1])
                if math.hypot(b[0] - a[0], b[1] - a[1]) > 1e-4:
                    segs.append([a, b])
        d += spacing
    return segs


def infill_cross(polygon, spacing=0.05):
    """Kreuz-Fuellung: horizontale + vertikale Linien (Kreuz-Infill)."""
    segs = infill_lines(polygon, spacing, 0.0)
    segs += infill_lines(polygon, spacing, math.pi / 2)
    return segs


def infill_zigzag(polygon, spacing=0.05):
    """Zickzack-Fuellung: horizontale Linien, verbunden zu einer Serpentine."""
    rows = infill_lines(polygon, spacing, 0.0)
    if not rows:
        return []
    rows.sort(key=lambda s: s[0][1])
    path = []
    for i, seg in enumerate(rows):
        if i % 2 == 1:
            seg = [seg[1], seg[0]]
        if path and path[-1] != seg[0]:
            # Verbindungsstueck anfreihen (Stift bleibt unten beim Gravieren)
            path.append(seg[0])
        path.extend(seg)
    return [path]


def simplify(points, tolerance=0.002):
    """Douglas-Peucker: reduziert Punkte, ohne die Form merkbar zu ändern."""
    if len(points) < 3:
        return list(points)

    def perp_dist(p, a, b):
        ax, ay = a
        bx, by = b
        px, py = p
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy)
        if L < 1e-12:
            return math.hypot(px - ax, py - ay)
        return abs(dy * px - dx * py + bx * ay - by * ax) / L

    start, end = points[0], points[-1]
    max_d, max_i = 0.0, 0
    for i in range(1, len(points) - 1):
        d = perp_dist(points[i], start, end)
        if d > max_d:
            max_d, max_i = d, i
    if max_d > tolerance:
        left = simplify(points[:max_i + 1], tolerance)
        right = simplify(points[max_i:], tolerance)
        return left[:-1] + right
    return [start, end]


def optimize_paths(paths):
    """Sortiert Pfade nach nächstem Nachbarn: weniger Stift-Hübe, schnellere Plots."""
    if not paths:
        return []
    remaining = [p for p in paths if len(p) >= 2]
    ordered = [remaining.pop(0)]
    while remaining:
        last = ordered[-1][-1]
        best_i = min(range(len(remaining)),
                     key=lambda i: (remaining[i][0][0] - last[0]) ** 2 + (remaining[i][0][1] - last[1]) ** 2)
        ordered.append(remaining.pop(best_i))
    return ordered


def optimize_paths_colored(paths, colors):
    """Wie optimize_paths, aber haelt die Farben parallel mit (Tupel-Rueckgabe).

    Pfade gleicher Farbe werden dabei bevorzugt hintereinander sortiert,
    damit der Stift seltener gewechselt werden muss.
    """
    if not paths:
        return [], []
    pairs = [(p, colors[i] if i < len(colors) else None)
             for i, p in enumerate(paths) if len(p) >= 2]
    if not pairs:
        return [], []
    ordered = [pairs.pop(0)]
    while pairs:
        last = ordered[-1][0][-1]
        cur_color = ordered[-1][1]
        def cost(pair):
            p, c = pair
            d = (p[0][0] - last[0]) ** 2 + (p[0][1] - last[1]) ** 2
            return (d if c == cur_color else d + 100.0, d)
        ordered.append(pairs.pop(min(range(len(pairs)), key=lambda i: cost(pairs[i]))))
    return [p for p, _ in ordered], [c for _, c in ordered]


def test_plot(size=0.3):
    """Höhen-Test: kleine Linien, Quadrate und einen Kreis – sieht man sofort,
    ob der Stift richtig aufsetzt bzw. kratzt."""
    cx, cy = 0.5, 0.5
    s = size / 2
    return [
        [(cx - s, cy - s), (cx - s, cy + s)],
        [(cx - s, cy + s), (cx + s, cy + s)],
        [(cx + s, cy + s), (cx + s, cy - s)],
        [(cx + s, cy - s), (cx - s, cy - s)],
        circle(cx, cy, s * 0.7, steps=48),
    ]


def calibration_grid(x=0.1, y=0.1, w=0.8, h=0.8, nx=5, ny=5):
    """Kalibrier-Raster mit Nummern, um Papier-Maßstab zu prüfen."""
    paths = grid(x, y, w, h, nx, ny)
    for i in range(nx + 1):
        gx = x + w * i / nx
        paths.extend(text_paths(str(i % 10), gx + 0.01, y + h + 0.03, 0.05))
    return paths


def grid(x, y, w, h, nx, ny):
    """Liniengitter als Pfade."""
    paths = []
    for i in range(nx + 1):
        gx = x + w * i / max(nx, 1)
        paths.append([(gx, y), (gx, y + h)])
    for j in range(ny + 1):
        gy = y + h * j / max(ny, 1)
        paths.append([(x, gy), (x + w, gy)])
    return paths


def text_paths(text, x, y, size=0.1):
    """Sehr einfacher Stroke-Font (nur Großbuchstaben, Ziffern, Grundzeichen)."""
    strokes = {
        "A": [[(0,1),(0.5,0),(1,1)],[(0.25,0.6),(0.75,0.6)]],
        "B": [[(0,0),(0,1),(0.6,1),(0.8,0.85),(0.6,0.7),(0,0.7)],[(0,0.35),(0.6,0.35),(0.8,0.2),(0.6,0),(0,0)]],
        "C": [[(0.8,0.85),(0.6,1),(0.2,1),(0,0.8),(0,0.2),(0.2,0),(0.6,0),(0.8,0.15)]],
        "D": [[(0,0),(0,1),(0.5,1),(0.8,0.8),(0.8,0.2),(0.5,0),(0,0)]],
        "E": [[(0.8,1),(0,1),(0,0),(0.8,0)],[(0,0.5),(0.6,0.5)]],
        "F": [[(0.8,1),(0,1),(0,0)],[(0,0.5),(0.6,0.5)]],
        "G": [[(0.8,0.85),(0.6,1),(0.2,1),(0,0.8),(0,0.2),(0.2,0),(0.6,0),(0.8,0.2),(0.8,0.4),(0.4,0.4)]],
        "H": [[(0,0),(0,1)],[(1,0),(1,1)],[(0,0.5),(1,0.5)]],
        "I": [[(0.5,0),(0.5,1)],[(0.2,1),(0.8,1)],[(0.2,0),(0.8,0)]],
        "J": [[(1,1),(1,0.2),(0.8,0),(0.2,0),(0,0.2)]],
        "K": [[(0,0),(0,1)],[(1,1),(0,0.5)],[(0.3,0.6),(1,0)]],
        "L": [[(0,1),(0,0),(0.8,0)]],
        "M": [[(0,0),(0,1),(0.5,0.5),(1,1),(1,0)]],
        "N": [[(0,0),(0,1),(1,0),(1,1)]],
        "O": [circle(0.5,0.5,0.5,steps=16)],
        "P": [[(0,0),(0,1),(0.6,1),(0.8,0.85),(0.6,0.65),(0,0.65)]],
        "Q": [circle(0.5,0.5,0.5,steps=16) + [(0.7,0.3),(1.0,0.0)]],
        "R": [[(0,0),(0,1),(0.6,1),(0.8,0.85),(0.6,0.65),(0,0.65)],[(0.35,0.65),(1,0)]],
        "S": [[(0.8,0.85),(0.6,1),(0.2,1),(0,0.85),(0.2,0.65),(0.6,0.65),(0.8,0.5),(0.6,0.3),(0.2,0.3),(0,0.15),(0.2,0),(0.6,0),(0.8,0.15)]],
        "T": [[(0,1),(1,1)],[(0.5,1),(0.5,0)]],
        "U": [[(0,1),(0,0.2),(0.2,0),(0.8,0),(1,0.2),(1,1)]],
        "V": [[(0,1),(0.5,0),(1,1)]],
        "W": [[(0,1),(0.25,0),(0.5,0.6),(0.75,0),(1,1)]],
        "X": [[(0,0),(1,1)],[(0,1),(1,0)]],
        "Y": [[(0,1),(0.5,0.5),(1,1)],[(0.5,0.5),(0.5,0)]],
        "Z": [[(0,1),(1,1),(0,0),(1,0)]],
        "0": [circle(0.5,0.5,0.5,steps=16)],
        "1": [[(0.2,0.8),(0.5,1),(0.5,0)],[(0.25,0),(0.75,0)]],
        "2": [[(0,0.8),(0.2,1),(0.8,1),(1,0.8),(0,0)],[(0,0),(1,0)]],
        "3": [[(0,0.9),(0.2,1),(0.8,1),(1,0.85),(0.4,0.5)],[(0.4,0.5),(1,0.2),(0.8,0),(0.2,0),(0,0.15)]],
        "4": [[(0.8,1),(0.8,0)],[(0,0.3),(0.9,0.3)]],
        "5": [[(1,1),(0.2,1),(0,0.65),(0.2,0.55),(0.8,0.55),(1,0.4),(0.8,0),(0.2,0),(0,0.15)]],
        "6": [[(0.8,1),(0.2,1),(0,0.5),(0,0.2),(0.2,0),(0.8,0),(1,0.2),(0,0.4)]],
        "7": [[(0,1),(1,1),(0.4,0)]],
        "8": [circle(0.5,0.75,0.25,steps=12), circle(0.5,0.25,0.25,steps=12)],
        "9": [[(1,0.2),(0.8,0),(0.2,0),(0,0.2),(0,0.6),(0.8,1),(1,0.6),(0.2,0.4)]],
        " ": [],
        "-": [[(0,0.5),(1,0.5)]],
        ".": [[(0.5,0),(0.5,0.05),(0.5,0)]],
    }
    paths = []
    cx = x
    for ch in text.upper():
        glyph = strokes.get(ch)
        if glyph:
            for stroke in glyph:
                scaled = [((cx + s * size), (y + t * size)) for (s, t) in stroke]
                paths.append(scaled)
        cx += size * 1.2
    return paths


def trace_image(filename, resolution=64, threshold=128, paper_w=1.0, paper_h=1.0):
    """Raster-Zeilen-Tracing eines Bildes in Plotter-Pfade (ohne externe Abhängigkeiten).

    Lädt mit tkinter.PhotoImage (PNG/GIF) oder PIL, falls installiert.
    """
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise RuntimeError("Für Bild-Tracing bitte 'pip install pillow' ausführen.")

    img = Image.open(filename).convert("L")
    img = img.resize((resolution, max(1, int(resolution * img.height / img.width))))
    px = img.load()
    w, h = img.size

    paths = []
    # Horizontale Scan-Linien: Dunkle Runnen als Segmente
    for y in range(h):
        run = None
        row_paths = []
        for x in range(w + 1):
            dark = x < w and px[x, y] < threshold
            if dark and run is None:
                run = x
            elif not dark and run is not None:
                row_paths.append((run, x))
                run = None
        for (x0, x1) in row_paths:
            if x1 - x0 < 1:
                continue
            sx = (x0 / w) * paper_w
            ex = (x1 / w) * paper_w
            sy = (y / h) * paper_h
            paths.append([(sx, sy), (ex, sy)])
    # Vertikale Kanten andeuten: einfache Kontur-Spur links/rechts
    return paths


def _trace_mask_paths(mask, w, h, paper_w, paper_h, min_area=3):
    """Konturen einer binären Maske als geschlossene Polygone.

    Marching-Squares-Konturverfolgung: liefert UMRISSE statt Scan-Zeilen
    -> wenige, saubere, geschlossene Pfade (wie ein Vektorisierer).
    """
    visited = set()
    paths = []
    # Innenpixel mit Nachbar-Ausenpixel = Konturkandidaten
    def is_set(x, y):
        return 0 <= x < w and 0 <= y < h and mask[y * w + x]

    def edge_segments(x, y):
        """Kanten des Pixels (x,y) die an ein Nicht-Mask-Pixel grenzen."""
        segs = []
        # obere Kante (links->rechts)
        if not is_set(x, y - 1):
            segs.append(((x, y), (x + 1, y)))
        # rechte Kante (oben->unten)
        if not is_set(x + 1, y):
            segs.append(((x + 1, y), (x + 1, y + 1)))
        # untere Kante (rechts->links)
        if not is_set(x, y + 1):
            segs.append(((x + 1, y + 1), (x, y + 1)))
        # linke Kante (unten->oben)
        if not is_set(x - 1, y):
            segs.append(((x, y + 1), (x, y)))
        return segs

    all_edges = {}
    for y in range(h):
        for x in range(w):
            if mask[y * w + x]:
                for a, b in edge_segments(x, y):
                    all_edges.setdefault(a, []).append(b)

    while all_edges:
        # neue Kontur starten
        start = next(iter(all_edges))
        contour = [start]
        cur = start
        while True:
            nxts = all_edges.get(cur, [])
            if not nxts:
                break
            nxt = nxts.pop(0)
            if not nxts:
                del all_edges[cur]
            rev = all_edges.get(nxt, [])
            if cur in rev:
                rev.remove(cur)
                if not rev:
                    del all_edges[nxt]
            contour.append(nxt)
            cur = nxt
            if cur == start or nxt == start:
                break
        if len(contour) >= 4:
            pts = []
            for (x, y) in contour:
                px_ = (x / w) * paper_w
                py_ = (1 - y / h) * paper_h  # Bild-y invertieren
                if not pts or (abs(px_ - pts[-1][0]) > 1e-9 or abs(py_ - pts[-1][1]) > 1e-9):
                    pts.append((px_, py_))
            if len(pts) >= 4:
                paths.append(pts)
    return paths


def _contour_area(pts):
    """Geschätzte Flaeche eines Kontur-Polygons (Shoelace, Absolutwert)."""
    a = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2


def trace_image_colored(filename, resolution=96, max_colors=6,
                        paper_w=1.0, paper_h=1.0, min_area=0.0004,
                        fill_mode=None, fill_spacing=0.05):
    """Farbiger Bild-Tracer mit echter KONTUR-Verfolgung.

    RGB-Quantisierung auf wenige Farben; je Farbe werden REGIONEN als
    geschlossene Umrisse nachverfolgt (Marching Squares) statt Scan-Zeilen.
    Seltene Farben (Rand-Mischpixel) werden auf die aehnlichste Hauptfarbe
    gemappt; kleine Fragmente werden verworfen -> saubere Vektor-Konturen.
    Liefert (paths, colors) mit '#rrggbb' je Pfad. Weiss bleibt frei.

    fill_mode: None = nur Kontur; 'lines'/'cross'/'zigzag' fuegt zusaetzlich
    eine Fuellung/Gravur innerhalb der Kontur hinzu (gleiche Farbe).
    """
    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError("Für Bild-Tracing bitte 'pip install pillow' ausführen.")

    img = Image.open(filename).convert("RGB")
    scale = min(1.0, resolution * 2 / max(img.width, img.height))
    if scale < 1.0:
        img = img.resize((max(1, int(img.width * scale)),
                          max(1, int(img.height * scale))), Image.LANCZOS)
    quant = img.quantize(colors=max_colors, dither=Image.Dither.NONE)
    pal = quant.getpalette()[:max_colors * 3]
    px = quant.load()
    w, h = quant.size
    n_px = w * h

    # Farbnutzung zaehlen; seltene Farben (<1.5%) auf aehnlichste Hauptfarbe
    counts = [0] * max_colors
    for y in range(h):
        for x in range(w):
            counts[px[x, y]] += 1
    def rgb(ci):
        base = ci * 3
        return (pal[base] if base < len(pal) else 0,
                pal[base + 1] if base + 1 < len(pal) else 0,
                pal[base + 2] if base + 2 < len(pal) else 0)
    main_colors = [ci for ci in range(max_colors) if counts[ci] >= 0.015 * n_px]
    remap = {}
    for ci in range(max_colors):
        if ci in main_colors:
            remap[ci] = ci
            continue
        # aehnlichste Hauptfarbe (RGB-Abstand); Weiss als Ziel vermeiden
        targets = [m for m in main_colors
                   if not (rgb(m)[0] > 230 and rgb(m)[1] > 230 and rgb(m)[2] > 230)]
        if not targets:
            remap[ci] = ci
            continue
        best = min(targets, key=lambda m: sum((a - b) ** 2 for a, b in zip(rgb(ci), rgb(m))))
        remap[ci] = best

    paths, colors = [], []
    done = set()
    for ci in range(max_colors):
        target = remap[ci]
        if target in done or target != ci and target in main_colors and target in done:
            continue
        if target in done:
            continue
        r, g, b = rgb(target)
        if r > 230 and g > 230 and b > 230:
            done.add(target)
            continue
        hexcol = f"#{r:02x}{g:02x}{b:02x}"
        mask = [remap[px[x, y]] == target for y in range(h) for x in range(w)]
        if not any(mask):
            done.add(target)
            continue
        contours = _trace_mask_paths(mask, w, h, paper_w, paper_h)
        kept = 0
        for c in contours:
            if len(c) >= 4 and _contour_area(c) >= min_area:
                simp = simplify(c, 0.003)
                if len(simp) >= 4:
                    # kurvig glaetten: Chaikin rundet die Pixel-Kanten
                    simp = smooth_curve(simp, iterations=3)
                    paths.append(simp)
                    colors.append(hexcol)
                    kept += 1
                    # Fuellung/Gravur innerhalb der Kontur (gleiche Farbe)
                    if fill_mode:
                        ring = simp[:-1] if simp[0] == simp[-1] else simp
                        if len(ring) >= 3 and _contour_area(ring) >= 4 * min_area:
                            if fill_mode == "cross":
                                fill = infill_cross(ring, fill_spacing)
                            elif fill_mode == "zigzag":
                                fill = infill_zigzag(ring, fill_spacing)
                            else:
                                fill = infill_lines(ring, fill_spacing, 0.0)
                            for f in fill:
                                if len(f) >= 2:
                                    paths.append(f)
                                    colors.append(hexcol)
        done.add(target)
    return paths, colors
