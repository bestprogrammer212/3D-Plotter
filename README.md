# 3D-Drucker Plotter App

Desktop-App (Python/tkinter), mit der ein normaler 3D-Drucker als Stift-Plotter genutzt werden kann.

## Funktionen

1. **Drucker** – Vordefinierte Liste gängiger Drucker + Import von OrcaSlicer-Maschinenprofilen (JSON).
   In OrcaSlicer: *Hilfe → Profilkurator → Export*.
2. **Kalibrieren** – Der am Extruder befestigte Stift wird nacheinander an die Ecken des Papiers
   gefahren (im **Uhrzeigersinn**, beliebig viele Ecken, mindestens 3) und die angezeigten
   X/Y-Werte werden eingetragen. Daraus berechnet die App das Papier-Koordinatensystem.
3. **Stift-Höhe** – Frei einstellbar: Z hoch (Freifahrt), Z beim Zeichnen, Eilgang- und
   Zeichengeschwindigkeit, kleiner Hub zwischen Pfaden.
4. **Design** – Werkzeuge: Rechteck, Kreis, Stern, Spirale, Raster, Text (Stroke-Font),
   Bild-Tracing (Pillow) und Freihand-Zeichnen auf der Leinwand.
5. **Export** – Erzeugt G-Code (`G0`/`G1`, Stift hoch/runter über Z), speicherbar als `.gcode`.

## Installation

```bash
pip install pillow   # nur für Bild-Tracing nötig
python main.py
```

## Ablauf (Workflow)

1. Tab *Drucker*: Gerät auswählen oder OrcaSlicer-Profil importieren.
2. Stift am Extruder montieren (z. B. mit Klemme), Papier auf das Bett legen.
3. Tab *Kalibrieren*: Stift nacheinander an jede Papier-Ecke fahren (Uhrzeigersinn),
   den auf dem Drucker-Display angezeigten X/Y-Wert übernehmen. Stift-Z-Höhen einstellen.
4. Tab *Design*: Formen/Text/Bild platzieren oder freihändig zeichnen.
5. Tab *Export*: G-Code speichern, auf den Drucker übertragen und starten.

## Projektstruktur

```
plotter_app/
  gui.py          tkinter-Oberfläche (4 Tabs)
  profiles.py     Druckerprofile + OrcaSlicer-Import
  calibration.py  Ecken-Kalibrierung → Papierkoordinaten
  pen.py          Stift-Höhen & Bewegungsregeln
  tools.py        Design-Werkzeuge (Formen, Text, Bild-Tracing)
  gcode.py        G-Code-Export
main.py           Einstiegspunkt
```

## Hinweise

- Erste Version: Werte im Kalibrierungs-Tab werden manuell vom Drucker-Display abgelesen.
  Eine direkte serielle Anbindung (z. B. via `pyserial`) ist als nächster Ausbauschritt geplant.
- Immer zuerst eine Testfahrt mit angehobenem Stift machen.
