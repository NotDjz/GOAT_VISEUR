@echo off
echo.
echo   ======================================
echo       BUILDING SCREEN SCOPE
echo   ======================================
echo.
py -m pip install pyinstaller
py -m PyInstaller --noconfirm --onefile --windowed --name ScreenScope --icon screenscope.ico --hidden-import pystray._win32 crosshair.pyw
echo.
echo   Compilation terminee !
echo   L'executable se trouve dans le dossier "dist".
echo.
pause
