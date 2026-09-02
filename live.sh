#!/bin/bash
# 라이브 녹화 - 다시보기가 올라오지 않는 방송을 대비한 보험
#
#   ./live.sh                     방송을 기다렸다가 자동 녹화
#   ./live.sh <라이브 링크>        그 채널을 감시 (--once: 한 방송만 받고 종료)
#   ./live.sh schedule 20:15      매일 정해진 시각에 터미널을 띄워 시작
#   ./live.sh schedule --status   자동 시작 설정 확인
#   ./live.sh schedule --remove   자동 시작 해제

cd "$(dirname "$0")"

REPO="$(pwd)"
LABEL="com.chzzk-vod-archiver.live"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

unload_agent() {
    launchctl bootout "gui/$UID/$LABEL" 2>/dev/null \
        || launchctl unload "$PLIST" 2>/dev/null || true
}

if [ "${1:-}" = "schedule" ]; then
    case "${2:-}" in
        --status)
            if [ -f "$PLIST" ]; then
                echo "설치됨: $PLIST"
                /usr/libexec/PlistBuddy -c "Print :StartCalendarInterval" "$PLIST" 2>/dev/null \
                    | tr -d ' ' | grep -E "Hour|Minute" | paste -sd' ' -
                launchctl print "gui/$UID/$LABEL" >/dev/null 2>&1 \
                    && echo "상태: 등록됨" || echo "상태: 파일은 있으나 등록되지 않음"
            else
                echo "자동 시작이 설정되어 있지 않습니다."
            fi
            ;;
        --remove)
            unload_agent
            rm -f "$PLIST"
            echo "자동 시작 설정을 해제했습니다."
            ;;
        *)
            TIME="${2:-}"
            if [[ ! "$TIME" =~ ^([01][0-9]|2[0-3]):([0-5][0-9])$ ]]; then
                echo "시각은 HH:MM 형식입니다 (예: ./live.sh schedule 20:15)"
                exit 1
            fi
            HOUR="${BASH_REMATCH[1]#0}"; HOUR="${HOUR:-0}"
            MIN="${BASH_REMATCH[2]#0}";  MIN="${MIN:-0}"
            mkdir -p "$HOME/Library/LaunchAgents"
            cat > "$PLIST" <<PLEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/osascript</string>
        <string>-e</string>
        <string>tell application &quot;Terminal&quot; to do script &quot;cd '$REPO' &amp;&amp; ./live.sh&quot;</string>
        <string>-e</string>
        <string>tell application &quot;Terminal&quot; to activate</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>$HOUR</integer>
        <key>Minute</key>
        <integer>$MIN</integer>
    </dict>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
PLEOF
            plutil -lint "$PLIST" >/dev/null || { echo "plist 생성 실패"; exit 1; }
            unload_agent
            launchctl bootstrap "gui/$UID" "$PLIST" 2>/dev/null || launchctl load "$PLIST"
            echo "매일 $TIME 에 터미널을 띄워 녹화 감시를 시작합니다."
            echo "  해제: ./live.sh schedule --remove"
            ;;
    esac
    exit 0
fi

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
fi

for tool in ffmpeg ffprobe; do
    if ! command -v "$tool" >/dev/null; then
        echo "$tool가 필요합니다. 설치: brew install ffmpeg"
        exit 1
    fi
done

# 감시가 길게 이어지므로 출력을 버퍼링하지 않는다 (로그로 넘겨도 바로 보이도록)
exec python3 -B -u archive.py live "$@"
