#!/bin/bash
cd "$(dirname "$0")"

if ! command -v yt-dlp >/dev/null; then
    echo "yt-dlp가 필요합니다. 설치: brew install yt-dlp"
    exit 1
fi

if [ ! -d venv ]; then
    python3 -m venv venv
fi

source venv/bin/activate

if ! python3 -c "import requests, tqdm" 2>/dev/null; then
    pip install requests tqdm
fi

python3 archive.py "$@"
