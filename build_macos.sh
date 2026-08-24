#!/usr/bin/env bash
set -eu
python3 -m pip install -r requirements-desktop.txt pyinstaller
pyinstaller --noconfirm --clean --windowed --name Shiguang --collect-all webview --add-data "static:static" desktop.py
