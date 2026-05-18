# Copyright (c) 2026-present 마지막남은뚜또. All rights reserved.

# 채팅 내용 필터 (포함 조건: 해당 문자열이 하나라도 포함되면 유지)
FILTER_MESSAGE = [
    "ㄱ",
    "ㄷ",
    "ㅇ",
    "ㅉ",
    "ㅋ",
    "ㅎ",
    "?"
]
# 특정 유저만 필터링 (UID)
FILTER_USER = "34908dd0d6c0d1495ace4f281b515094"
# 제외할 봇 유저 (UID)
BOT_USER = "bb88ee67c4551e08e953f291d41f1a85"

import json, os, requests, tqdm

session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
})

def fetchChats(videoId: int):
    videoData = session.get(f"https://api.chzzk.naver.com/service/v2/videos/{videoId}").json()
    if videoData['code'] != 200:
        print(f"영상 '{videoId}' 에 대한 데이터를 불러오지 못했습니다: {videoData['message']}")
        return None
    
    live_open_date = videoData['content']['liveOpenDate'].split()[0].replace("-", ".")

    chats = []
    playerMessageTime = 0

    _pbar = tqdm.tqdm(desc=f"Fetching chats for video ID {videoId}", unit=" chats")
    while True:
        chatData = session.get(f"https://api.chzzk.naver.com/service/v1/videos/{videoId}/chats?playerMessageTime={playerMessageTime}&previousVideoChatSize=50").json()
        if chatData['code'] != 200:
            print(f"영상 '{videoId}'에 대한 채팅 데이터를 불러오지 못했습니다 (player message time: {playerMessageTime}): {chatData['message']}")
            break
        content = chatData['content']

        chats.extend(content['videoChats'])
        if content['nextPlayerMessageTime'] is None:
            print(f"영상 '{videoId}'에 대한 모든 채팅을 가져왔습니다.")
            break
        
        playerMessageTime = content['nextPlayerMessageTime']
        _pbar.update(len(content['videoChats']))
        _pbar.set_postfix({"last_message_time": playerMessageTime})
    return chats, live_open_date

def formatTimestamp(ms, fps=60):
    hours = ms // 3600000
    minutes = ms // 60000 % 60
    seconds = ms // 1000 % 60
    frames = (ms % 1000) * fps // 1000
    return f"{hours:02}:{minutes:02}:{seconds:02}:{frames:02}"

def formatChat(chat):
    if not chat.get('profile'):
        return None
    if chat.get('userIdHash') == BOT_USER:
        return None
    profile = json.loads(chat['profile'])   
    timestamp = formatTimestamp(chat['playerMessageTime'])
    return f"[{timestamp}] {profile['nickname']} ({chat['userIdHash']}) - {chat['content']}"

def saveChats(path, chats):
    with open(path, "w", encoding="utf-8") as f:
        for chat in chats:
            content = formatChat(chat)
            if content:
                f.write(content + "\n")

def main():
    videoId = input("영상 ID 또는 URL을 입력하세요: ").strip()
    # 사용자가 'https://chzzk.naver.com/video/13246889' 처럼 넣는 경우를 대비하여 파싱
    try:
        videoId = int(videoId) if isinstance(videoId, int) else int(videoId.split('/')[-1])
    except ValueError:
        print("유효한 영상 ID 또는 URL을 입력하세요.")
        return

    chats, live_open_date = fetchChats(videoId)
    if chats is None:
        print("채팅 데이터를 가져오는 데 실패했습니다.")
    else:
        path = f"./logs/{live_open_date}"
        if not os.path.exists(path):
            os.mkdir(path)

        print(f"채팅 수: {len(chats)}")
        saveChats(f"{path}/all_chats.md", chats)

        # 필터링
        filtered_chats = [chat for chat in chats if any(msg in chat['content'] for msg in FILTER_MESSAGE)] if FILTER_MESSAGE else chats

        print(f"필터링된 채팅 수: {len(filtered_chats)}")
        saveChats(f"{path}/filtered_chats.md", filtered_chats)

        if FILTER_USER:
            filtered_chats = [chat for chat in filtered_chats if chat['userIdHash'] == FILTER_USER]
            
            print(f"필터링된 특정 유저의 채팅 수: {len(filtered_chats)}")
            saveChats(f"{path}/filtered_chats_{FILTER_USER}.md", filtered_chats)
    
if __name__ == "__main__":
    main()