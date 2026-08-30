import json
import os
import sys
import urllib.request

API_BASE = "https://api.chzzk.naver.com/service"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"

def load_config():
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    try:
        with open(config_path, encoding="utf-8") as f:
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
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def fetch_chats(video_id):
    video_data = get_json(f"{API_BASE}/v2/videos/{video_id}")
    if video_data["code"] != 200:
        print(f"영상 '{video_id}'에 대한 데이터를 불러오지 못했습니다: {video_data['message']}")
        return None

    content = video_data["content"]
    # 업로드 영상은 liveOpenDate가 없으므로 publishDate로 대체
    date_str = content["liveOpenDate"] or content["publishDate"]
    live_open_date = date_str.split()[0]

    chats = []
    player_message_time = 0
    while True:
        chat_data = get_json(
            f"{API_BASE}/v1/videos/{video_id}/chats"
            f"?playerMessageTime={player_message_time}&previousVideoChatSize=50"
        )
        if chat_data["code"] != 200:
            print(f"채팅 데이터를 불러오지 못했습니다 (playerMessageTime: {player_message_time}): {chat_data['message']}")
            break

        content = chat_data["content"]
        chats.extend(content["videoChats"])

        if content["nextPlayerMessageTime"] is None:
            break
        player_message_time = content["nextPlayerMessageTime"]
    return chats, live_open_date


def format_timestamp(ms, fps=60):
    hours = ms // 3600000
    minutes = ms // 60000 % 60
    seconds = ms // 1000 % 60
    frames = ms % 1000 * fps // 1000
    return f"{hours:02}:{minutes:02}:{seconds:02}:{frames:02}"


def format_chat(chat, highlight_users):
    if not chat.get("profile") or chat.get("userIdHash") in BOT_USERS:
        return None
    nickname = json.loads(chat["profile"])["nickname"]
    if highlight_users and chat["userIdHash"] in highlight_users:
        nickname = f"<u>{nickname}</u>"
    timestamp = format_timestamp(chat["playerMessageTime"])
    return f"[{timestamp}] {nickname} ({chat['userIdHash']}) - {chat['content']}"


def save_chats(path, chats, video_id, highlight_users=None):
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"---\nvideo: {video_id}\n---\n")
        for chat in chats:
            line = format_chat(chat, highlight_users)
            if line:
                f.write(line + "\n")


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
    dirs = [os.path.join("logs", live_open_date)]
    vault_path = get_obsidian_vault_path()
    if vault_path:
        dirs.append(os.path.join(vault_path, "치지직", "로그", live_open_date))
    return dirs


def process_video(video_id):
    result = fetch_chats(video_id)
    if result is None:
        return
    chats, live_open_date = result

    filtered_chats = [c for c in chats if any(m in c["content"] for m in FILTER_MESSAGES)] if FILTER_MESSAGES else chats
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


def parse_video_id(user_input):
    try:
        return int(user_input.rstrip("/").split("/")[-1])
    except ValueError:
        return None


def main():
    for arg in sys.argv[1:]:
        video_id = parse_video_id(arg)
        if video_id is None:
            print(f"유효한 영상 ID 또는 URL이 아닙니다: {arg}")
            continue
        process_video(video_id)
    if sys.argv[1:]:
        return

    while True:
        try:
            user_input = input("영상 ID 또는 URL을 입력하세요 (종료: q 또는 빈 입력): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input or user_input.lower() in ("q", "quit", "exit", "종료"):
            break

        video_id = parse_video_id(user_input)
        if video_id is None:
            print("유효한 영상 ID 또는 URL을 입력하세요.")
            continue

        process_video(video_id)
        print()


if __name__ == "__main__":
    main()
