@echo off
cd /d "%~dp0"

if not exist venv (
    python -m venv venv
)

call venv\Scripts\activate.bat

python -c "import requests, tqdm" 2>nul || pip install requests tqdm

python chzzk_chat.py %*

echo.
pause
