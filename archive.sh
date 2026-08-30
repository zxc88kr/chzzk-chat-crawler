#!/bin/bash
cd "$(dirname "$0")"

if ! command -v yt-dlp >/dev/null; then
    echo "yt-dlp가 필요합니다. 설치: brew install yt-dlp"
    exit 1
fi

python3 archive.py "$@"
