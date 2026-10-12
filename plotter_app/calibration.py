"""Kalibrierung: beliebig viele Papier-Ecken (Uhrzeigersinn) -> Papier-Koordinatensystem."""
import math


class Calibration:
    """Hält gemessene Maschinenkoordinaten der Papier-Ecken (im Uhrzeigersinn)."""

    def __init__(self):
        self.points = []          # Liste (x, y) in Maschinen-mm, Uhrzeigersinn
        self.pen_up_z = 20.0      # Stift hoch (Freifahrt)
        self.pen_draw_z = 0.0     # Stift auf Papier
        self.travel_speed = 80.0
        self.draw_speed = 40.0

    def add_point(self, x, y):
        self.points.append((float(x), float(y)))

    def pop_point(self):
        return self.points.pop() if self.points else None

    def clear(self):
        self.points = []

    @property
    def is_complete(self):
        return len(self.points) >= 3

    @property
    def polygon(self):
        """Ecken als geschlossenes Polygon."""
        if not self.is_complete:
            return []
        return self.points + [self.points[0]]

    def bounds(self):
        if not self.points:
            return (0, 0, 0, 0)
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return (min(xs), min(ys), max(xs), max(ys))

    def paper_to_machine(self, px, py):
        """Bildet Papier-Einheiten (0..1 in X, 0..1 in Y, Ursprung unten links)
        auf das Papier-Polygon. Nutzt bilineare Interpolation über das Polygon."""
        if not self.is_complete:
            raise ValueError("Kalibrierung unvollständig (mindestens 3 Ecken nötig)")

        pts = self.points
        n = len(pts)
        if n == 3:
            # Dreieck: baryzentrisch, mit projizierter vierter Ecke
            pts = pts + [self._edge_midpoint(pts[0], pts[2])]
        # pts: [A(0,0) B(1,0) C(1,1) D(0,1)] bzw. interpoliert
        if n > 4:
            # Mehr als 4 Ecken: N-Ecken auf Einheitsquadrat-Rand mappen (Uhrzeigersinn)
            return self._map_many(px, py)
        return self._bilinear(pts[0], pts[1], pts[2], pts[3], px, py)

    def _edge_midpoint(self, a, b):
        return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)

    def _bilinear(self, a, b, c, d, u, v):
        """a=(0,0), b=(1,0), c=(1,1), d=(0,1) -> Punkt (u,v)"""
        def lerp(p, q, t):
            return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)

        top = lerp(a, b, u)    # Kante A->B (v=0)
        bot = lerp(d, c, u)    # Kante D->C (v=1)
        return lerp(top, bot, v)

    def _map_many(self, u, v):
        """Für >4 Ecken: Algorithmus vonMapper auf Polygonrand (Uhrzeigersinn)."""
        pts = self.points
        n = len(pts)
        # Einheitsquadrat-Rand gegen Uhrzeigersinn parametrisieren und Polygonrand matchen
        # Wir gehen davon aus: Ecken im Uhrzeigersinn -> Quadrand im Uhrzeigersinn.
        quad = [(0, 0), (1, 0), (1, 1), (0, 1)]

        # Mittelpunkt als Ursprung
        cx = sum(p[0] for p in pts) / n
        cy = sum(p[1] for p in pts) / n

        def poly_point(u, v):
            # Winkel im Einheitsquadrat (relativ zu Zentrum)
            ang = math.atan2(v - 0.5, u - 0.5) if (u, v) != (0.5, 0.5) else 0.0
            # Radius, wo Quadrand diesen Winkel schneidet
            r = self._quad_radius(ang, 0.5)
            scale = math.hypot(u - 0.5, v - 0.5) / r if r else 0.0
            # Polygonradius im selben Winkel (Uhrzeigersinn-Punkte)
            px, py = self._poly_radius(pts, ang, cx, cy)
            return (cx + (px - cx) * scale, cy + (py - cy) * scale)

        return poly_point(u, v)

    def _quad_radius(self, ang, half):
        c = math.cos(ang)
        s = math.sin(ang)
        rx = half / abs(c) if abs(c) > 1e-9 else float("inf")
        ry = half / abs(s) if abs(s) > 1e-9 else float("inf")
        return min(rx, ry)

    def _poly_radius(self, pts, ang, cx, cy):
        """Erster Schnittpunkt des Strahls (Winkel ang ab Zentrum) mit dem Polygon."""
        dx, dy = math.cos(ang), math.sin(ang)
        best = None
        n = len(pts)
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            ex, ey = x2 - x1, y2 - y1
            den = dx * ey - dy * ex
            if abs(den) < 1e-12:
                continue
            t = ((x1 - cx) * ey - (y1 - cy) * ex) / den
            s = ((x1 - cx) * dy - (y1 - cy) * dx) / den
            if t >= 1e-9 and 0 <= s <= 1:
                p = (cx + dx * t, cy + dy * t)
                if best is None or t < best[0]:
                    best = (t, p)
        if best:
            return best[1]
        return (cx, cy)
