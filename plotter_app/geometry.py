"""Geometrie-Helfer fuer Auswahl und Fuellung (Qt-frei, gut testbar)."""


def seg_dist_sq(pt, a, b):
    """Quadrat des Abstands Punkt->Segment(a,b)."""
    ax, ay = a
    bx, by = b
    px, py = pt
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return (px - ax) ** 2 + (py - ay) ** 2
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    qx, qy = ax + t * dx, ay + t * dy
    return (px - qx) ** 2 + (py - qy) ** 2


def segs_intersect(p1, p2, p3, p4):
    """Schneiden sich Segment p1p2 und p3p4? (Orientation-Test)"""
    def orient(a, b, c):
        v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        return 0 if abs(v) < 1e-12 else (1 if v > 0 else -1)
    o1, o2 = orient(p1, p2, p3), orient(p1, p2, p4)
    o3, o4 = orient(p3, p4, p1), orient(p3, p4, p2)
    return o1 != o2 and o3 != o4


def point_in_poly(pt, poly):
    """Punkt-im-Polygon (Raycast); poly offen oder geschlossen."""
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
