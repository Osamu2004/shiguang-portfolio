@echo off
setlocal
cd /d "%~dp0"
python -m pip install -r requirements-desktop.txt pyinstaller
if errorlevel 1 exit /b 1
python -m PyInstaller --noconfirm --clean --windowed --name Shiguang --collect-all webview --add-data "static;static" desktop.py
if errorlevel 1 exit /b 1
echo Windows app ready: dist\Shiguang\Shiguang.exe
