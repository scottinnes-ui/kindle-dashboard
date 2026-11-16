@echo off
cd /d "%~dp0"
python -m pip install --quiet pillow tzdata
python dashboard.py --demo --once preview_today.png --batt 85
python dashboard.py --demo --once preview_10d.png --view 10d --batt 85
echo Wrote preview_today.png and preview_10d.png
pause
