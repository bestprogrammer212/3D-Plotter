# 3D-Drucker Plotter App

Desktop-App (Python/tkinter), mit der ein normaler 3D-Drucker als Stift-Plotter genutzt werden kann.

## Funktionen

1. **Drucker** – Eingebettete OrcaSlicer-Druckerdatenbank mit **291 Modellen**
   (Afinia, Anker, Anycubic, Artillery, Bambu Lab, BIQU, Creality, Elegoo, Flashforge,
   Prusa, Qidi, Voron, …) aus den offiziellen [OrcaSlicer-Profilen](https://github.com/OrcaSlicer/OrcaSlicer/tree/main/resources/profiles)
   + Import eigener OrcaSlicer-Maschinenprofile (JSON). In OrcaSlicer: *Hilfe → Profilkurator → Export*.
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

## Projektstruktur / benötigte .py-Dateien

Alle Python-Dateien, die das Projekt benötigt:

| Datei | Zweck |
|---|---|
| `main.py` | Einstiegspunkt – startet die GUI |
| `plotter_app/__init__.py` | Paket-Metadaten (Version) |
| `plotter_app/gui.py` | tkinter-Oberfläche: Verbindung (IP), Drucker, Kalibrierung mit Bett-Vorschau, Design, Export |
| `plotter_app/profiles.py` | Lädt die OrcaSlicer-Druckerdatenbank + JSON-Profilimport |
| `plotter_app/calibration.py` | Ecken-Kalibrierung (Uhrzeigersinn, beliebig viele Ecken) → Papierkoordinaten |
| `plotter_app/pen.py` | Stift-Höhen & Bewegungsregeln (Pen up/down, Hübe, Geschwindigkeiten) |
| `plotter_app/tools.py` | Design-Werkzeuge: Formen, Stern, Spirale, Raster, Stroke-Font-Text, Bild-Tracing |
| `plotter_app/gcode.py` | G-Code-Export (G0/G1, Z-Hub, Speeds) |
| `plotter_app/network.py` | IP-Anbindung: Moonraker (Klipper) & OctoPrint – Jog, Position, Upload & Start |
| `scripts/extract_orcaslicer.py` | Extrahiert Druckerdaten aus den OrcaSlicer-Profilen in `data/printers.json` (optional, nur für Aktualisierung) |
| `tests/test_core.py` | Unittests für Kalibrierung, G-Code und Netzwerk |

Daten: `data/printers.json` – die 291 Drucker aus OrcaSlicer (automatisch von der App geladen).

## Hinweise

- Erste Version: Werte im Kalibrierungs-Tab werden manuell vom Drucker-Display abgelesen.
  Eine direkte serielle Anbindung (z. B. via `pyserial`) ist als nächster Ausbauschritt geplant.
- Immer zuerst eine Testfahrt mit angehobenem Stift machen.
