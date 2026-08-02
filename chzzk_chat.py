# Copyright (c) 2026-present 마지막남은뚜또. All rights reserved.

import json
import os

import requests
import tqdm

API_BASE = "https://api.chzzk.naver.com/service"

# 채팅 내용 필터 (해당 문자열이 하나라도 포함되면 유지)
FILTER_MESSAGE = ["ㄱ", "ㄷ", "ㅇ", "ㅉ", "ㅋ", "ㅎ", "?"]
# 강조할 유저 (UID) - filtered_chats에서 닉네임에 밑줄 표시
FILTER_USER = "34908dd0d6c0d1495ace4f281b515094"
# 제외할 봇 유저 (UID)
BOT_USER = "bb88ee67c4551e08e953f291d41f1a85"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
})


def fetch_chats(video_id):
    video_data = session.get(f"{API_BASE}/v2/videos/{video_id}").json()
    if video_data["code"] != 200:
        print(f"영상 '{video_id}'에 대한 데이터를 불러오지 못했습니다: {video_data['message']}")
        return None

    live_open_date = video_data["content"]["liveOpenDate"].split()[0].replace("-", ".")

    chats = []
    player_message_time = 0
    pbar = tqdm.tqdm(desc=f"Fetching chats for video ID {video_id}", unit=" chats")
    while True:
        chat_data = session.get(
            f"{API_BASE}/v1/videos/{video_id}/chats"
            f"?playerMessageTime={player_message_time}&previousVideoChatSize=50"
        ).json()
        if chat_data["code"] != 200:
            pbar.write(f"채팅 데이터를 불러오지 못했습니다 (playerMessageTime: {player_message_time}): {chat_data['message']}")
            break

        content = chat_data["content"]
        chats.extend(content["videoChats"])
        pbar.update(len(content["videoChats"]))

        if content["nextPlayerMessageTime"] is None:
            break
        player_message_time = content["nextPlayerMessageTime"]
    pbar.close()
    return chats, live_open_date


def format_timestamp(ms, fps=60):
    hours = ms // 3600000
    minutes = ms // 60000 % 60
    seconds = ms // 1000 % 60
    frames = ms % 1000 * fps // 1000
    return f"{hours:02}:{minutes:02}:{seconds:02}:{frames:02}"


def format_chat(chat, highlight_user):
    if not chat.get("profile") or chat.get("userIdHash") == BOT_USER:
        return None
    nickname = json.loads(chat["profile"])["nickname"]
    if chat["userIdHash"] == highlight_user:
        nickname = f"<u>{nickname}</u>"
    timestamp = format_timestamp(chat["playerMessageTime"])
    return f"[{timestamp}] {nickname} ({chat['userIdHash']}) - {chat['content']}"


def save_chats(path, chats, highlight_user=None):
    with open(path, "w", encoding="utf-8") as f:
        for chat in chats:
            line = format_chat(chat, highlight_user)
            if line:
                f.write(line + "\n")


def get_obsidian_vault_path():
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    if os.path.exists(config_path):
        with open(config_path, encoding="utf-8") as f:
            vault_path = json.load(f).get("obsidian_vault_path")
        if vault_path:
            return os.path.expanduser(vault_path)

    default_path = os.path.expanduser("~/Documents/Obsidian Vault")
    return default_path if os.path.isdir(default_path) else None


def output_dirs(live_open_date):
    dirs = [os.path.join("logs", live_open_date)]
    vault_path = get_obsidian_vault_path()
    if vault_path:
        dirs.append(os.path.join(vault_path, "chzzk-chat-logs", live_open_date))
    return dirs


def process_video(video_id):
    result = fetch_chats(video_id)
    if result is None:
        return
    chats, live_open_date = result

    filtered_chats = [c for c in chats if any(m in c["content"] for m in FILTER_MESSAGE)] if FILTER_MESSAGE else chats
    print(f"채팅 수: {len(chats)} (필터링: {len(filtered_chats)})")

    dirs = output_dirs(live_open_date)
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        save_chats(os.path.join(d, "all_chats.md"), chats)
        save_chats(os.path.join(d, "filtered_chats.md"), filtered_chats, FILTER_USER)
    print("저장 위치: " + ", ".join(dirs))


def parse_video_id(user_input):
    # 'https://chzzk.naver.com/video/9330920' 형태의 URL도 허용
    try:
        return int(user_input.rstrip("/").split("/")[-1])
    except ValueError:
        return None


def main():
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
