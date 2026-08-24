@echo off
py -m pip install -r requirements-desktop.txt pyinstaller
pyinstaller --noconfirm --clean --windowed --name Shiguang --collect-all webview --add-data "static;static" desktop.py
