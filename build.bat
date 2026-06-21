@echo off
echo.
echo   ======================================
echo       COMPILATION DU VISEUR
echo   ======================================
echo.
py -m pip install pyinstaller
py -m PyInstaller --noconfirm --onefile --windowed --name Viseur --icon viseur.ico --hidden-import pystray._win32 crosshair.pyw
echo.
echo   Compilation terminee !
echo   L'executable se trouve dans le dossier "dist".
echo.
pause
