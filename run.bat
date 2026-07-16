@echo off
cd /d "%~dp0"

if not exist venv (
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install requests tqdm
) else (
    call venv\Scripts\activate.bat
)

python chzzk_chat.py %*
