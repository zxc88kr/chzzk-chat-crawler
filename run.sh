#!/bin/bash
cd "$(dirname "$0")"

if [ ! -d venv ]; then
    python3 -m venv venv
fi

source venv/bin/activate

if ! python3 -c "import requests, tqdm" 2>/dev/null; then
    pip install requests tqdm
fi

python3 chzzk_chat.py "$@"

echo
read -p "종료하려면 Enter 키를 누르세요..."
