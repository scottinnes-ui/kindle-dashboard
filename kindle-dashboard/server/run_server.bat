@echo off
cd /d "%~dp0"
python -m pip install --quiet pillow tzdata
echo Starting the Kindle dashboard server. Leave this window open.
python dashboard.py
pause
