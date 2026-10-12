#!/usr/bin/env python3
import sys


def main():
    try:
        from plotter_app.gui_qt import main as run_qt
        run_qt()
    except ImportError:
        # Fallback auf tkinter, falls PySide6 nicht installiert
        from plotter_app.gui import main as run_tk
        run_tk()


if __name__ == "__main__":
    main()
