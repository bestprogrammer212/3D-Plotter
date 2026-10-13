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


def trace_image_colored(filename, resolution=64, max_colors=6, paper_w=1.0, paper_h=1.0):
    """Farbigen Bild-Tracing: quantisiert das Bild (wie PicTraces Bild-Ansatz)
    auf wenige Farben und erzeugt je Farbe Scan-Zeilen-Pfade.

    Liefert (paths, colors) mit parallel laufender Farbbox pro Pfad ('#rrggbb').
    Weissnahe Farben werden uebersprungen (Papier bleibt frei).
    """
    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError("Für Bild-Tracing bitte 'pip install pillow' ausführen.")

    img = Image.open(filename).convert("RGB")
    img = img.resize((resolution, max(1, int(resolution * img.height / img.width))))
    quant = img.quantize(colors=max_colors)
    pal = quant.getpalette()[:max_colors * 3]
    px = quant.load()
    w, h = quant.size

    paths, colors = [], []
    for ci in range(max_colors):
        r, g, b = pal[ci * 3], pal[ci * 3 + 1], pal[ci * 3 + 2]
        if r > 230 and g > 230 and b > 230:
            continue
        hexcol = f"#{r:02x}{g:02x}{b:02x}"
        for y in range(h):
            run = None
            for x in range(w + 1):
                match = x < w and px[x, y] == ci
                if match and run is None:
                    run = x
                elif not match and run is not None:
                    if x - run >= 1:
                        paths.append([(run / w * paper_w, y / h * paper_h),
                                      (x / w * paper_w, y / h * paper_h)])
                        colors.append(hexcol)
                    run = None
    return paths, colors
