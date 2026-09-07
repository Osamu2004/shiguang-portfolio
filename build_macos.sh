#!/usr/bin/env bash
set -eu
python3 -m pip install -r requirements-desktop.txt pyinstaller
python3 -m PyInstaller --noconfirm --clean --windowed --name Shiguang --collect-all webview --add-data "static:static" --add-data "resources:resources" desktop.py
