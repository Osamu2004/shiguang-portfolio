#!/usr/bin/env bash
set -eu
python3 -m pip install -r requirements-desktop.txt pyinstaller
pyinstaller --noconfirm --windowed --name Shiguang --add-data "static:static" desktop.py
