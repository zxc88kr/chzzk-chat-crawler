import json
import os
import re
import sys
import urllib.error
import urllib.request

API_BASE = "https://api.chzzk.naver.com/service"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
FPS = 60
VAULT_SUBDIR = "치지직"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# format_chat이 만드는 한 줄 포맷의 역파싱 정규식 - 포맷 변경 시 함께 수정
CHAT_LINE = re.compile(r"^\[(\d+):(\d+):(\d+):(\d+)\] .+? \([0-9a-f]+\) - (.*)$")


def load_config():
    try:
        with open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        sys.exit("config.json이 없습니다.")


CONFIG = load_config()

# 채팅 내용 필터 (해당 문자열이 하나라도 포함되면 유지)
FILTER_MESSAGES = CONFIG["filter_messages"]
# 강조할 유저 (UID) - filtered_chats에서 닉네임에 밑줄 표시
HIGHLIGHT_USERS = CONFIG["highlight_users"]
# 제외할 봇 유저 (UID)
BOT_USERS = CONFIG["bot_users"]


def get_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        # 치지직 API는 오류도 JSON 본문(code/message)으로 주므로 살려서 반환
        try:
            return json.load(error)
        except ValueError:
            return {"code": error.code, "message": str(error)}


def fetch_video_content(video_id):
    data = get_json(f"{API_BASE}/v2/videos/{video_id}")
    if data["code"] != 200:
        print(f"영상 '{video_id}'의 정보를 불러오지 못했습니다: {data['message']}")
        return None
    return data["content"]


def broadcast_date(content):
    # 업로드 영상은 liveOpenDate가 없으므로 publishDate로 대체
    return (content["liveOpenDate"] or content["publishDate"]).split()[0]


def fetch_chats(video_id):
    chats = []
    player_message_time = 0
    while True:
        chat_data = get_json(
            f"{API_BASE}/v1/videos/{video_id}/chats"
            f"?playerMessageTime={player_message_time}&previousVideoChatSize=50"
        )
        if chat_data["code"] != 200:
            # 부분 수집본으로 기존 로그를 덮어쓰지 않도록 실패로 처리
            print(f"채팅 데이터를 불러오지 못했습니다 (playerMessageTime: {player_message_time}): {chat_data['message']}")
            return None

        content = chat_data["content"]
        chats.extend(content["videoChats"])

        if content["nextPlayerMessageTime"] is None:
            return chats
        player_message_time = content["nextPlayerMessageTime"]


def format_timestamp(ms):
    hours = ms // 3600000
    minutes = ms // 60000 % 60
    seconds = ms // 1000 % 60
    frames = ms % 1000 * FPS // 1000
    return f"{hours:02}:{minutes:02}:{seconds:02}:{frames:02}"


def format_chat(chat, highlight_users):
    nickname = json.loads(chat["profile"])["nickname"]
    if highlight_users and chat["userIdHash"] in highlight_users:
        nickname = f"<u>{nickname}</u>"
    timestamp = format_timestamp(chat["playerMessageTime"])
    return f"[{timestamp}] {nickname} ({chat['userIdHash']}) - {chat.get('content') or ''}"


def save_chats(path, chats, video_id, highlight_users=None):
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"---\nvideo: {video_id}\n---\n")
        for chat in chats:
            f.write(format_chat(chat, highlight_users) + "\n")


def read_logged_video_id(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        first, second = f.readline(), f.readline()
    if first.strip() == "---" and second.startswith("video:"):
        return second.split(":", 1)[1].strip()
    return None


def get_obsidian_vault_path():
    default_path = os.path.expanduser("~/Documents/Obsidian Vault")
    return default_path if os.path.isdir(default_path) else None


def output_dirs(live_open_date):
    dirs = [os.path.join(BASE_DIR, "logs", live_open_date)]
    vault_path = get_obsidian_vault_path()
    if vault_path:
        dirs.append(os.path.join(vault_path, VAULT_SUBDIR, "로그", live_open_date))
    return dirs


def process_video(video_id, live_open_date=None):
    if live_open_date is None:
        content = fetch_video_content(video_id)
        if content is None:
            return
        live_open_date = broadcast_date(content)

    chats = fetch_chats(video_id)
    if chats is None:
        return
    # 봇과 프로필 없는(후원·시스템성) 레코드는 로그 대상이 아님
    chats = [c for c in chats if c.get("profile") and c.get("userIdHash") not in BOT_USERS]
    filtered_chats = [c for c in chats if any(m in (c.get("content") or "") for m in FILTER_MESSAGES)] if FILTER_MESSAGES else chats
    print(f"채팅 수: {len(chats)} (필터링: {len(filtered_chats)})")

    dirs = output_dirs(live_open_date)
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        # 같은 날 다른 방송의 로그가 이미 있으면 파일명에 영상 ID를 붙여 구분
        logged_id = read_logged_video_id(os.path.join(d, "all_chats.md"))
        suffix = f"_{video_id}" if logged_id is not None and logged_id != str(video_id) else ""
        save_chats(os.path.join(d, f"all_chats{suffix}.md"), chats, video_id)
        save_chats(os.path.join(d, f"filtered_chats{suffix}.md"), filtered_chats, video_id, HIGHLIGHT_USERS)
    print("저장 위치: " + ", ".join(dirs))
    return True


def parse_video_id(user_input):
    try:
        return int(user_input.split("?")[0].split("#")[0].rstrip("/").split("/")[-1])
    except ValueError:
        return None


def run_cli(handler, prompt):
    def run(user_input):
        try:
            handler(user_input)
        except (urllib.error.URLError, TimeoutError) as error:
            print(f"네트워크 오류: {getattr(error, 'reason', error)}")

    if sys.argv[1:]:
        for arg in sys.argv[1:]:
            run(arg)
        return

    while True:
        try:
            user_input = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input or user_input.lower() in ("q", "quit", "exit", "종료"):
            break
        run(user_input)
        print()


def crawl(user_input):
    video_id = parse_video_id(user_input)
    if video_id is None:
        print(f"유효한 영상 ID 또는 URL이 아닙니다: {user_input}")
        return
    process_video(video_id)


if __name__ == "__main__":
    run_cli(crawl, "영상 ID 또는 URL을 입력하세요 (종료: q 또는 빈 입력): ")
