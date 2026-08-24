@echo off
py -m pip install -r requirements-desktop.txt pyinstaller
pyinstaller --noconfirm --windowed --name Shiguang --add-data "static;static" desktop.py
