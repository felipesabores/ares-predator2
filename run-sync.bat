@echo off
cd /d "%~dp0"
python sync.py >> sync.log 2>&1
