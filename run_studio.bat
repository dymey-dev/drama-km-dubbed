@echo off
title VANTA Khmer Dubbing Studio
cd /d "%~dp0"
echo ===================================================
echo     VANTA KHMER DUBBING STUDIO (FastAPI + Tailwind)
echo ===================================================
echo Starting Studio Web Server on http://127.0.0.1:7860...
python server.py
pause
