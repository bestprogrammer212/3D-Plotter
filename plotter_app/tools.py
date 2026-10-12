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
