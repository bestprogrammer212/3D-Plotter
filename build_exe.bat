@echo off
REM Baut die 3D-Plotter App als eigenstaendige .exe (dist/3D-Plotter.exe)
pip install pyinstaller -q
pyinstaller --noconfirm --windowed --name "3D-Plotter" ^
  --add-data "data;data" ^
  main.py
echo.
echo Fertig: dist\3D-Plotter.exe
pause
