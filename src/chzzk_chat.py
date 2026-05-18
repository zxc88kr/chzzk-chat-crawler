# Copyright (c) 2026-present 마지막남은뚜또. All rights reserved.

# 어떤 채팅을 가져올지 입력. (조금이라도 들어있으면 가져옴, 예: "ㅋㅋㅋ" 등)
FILTER_MESSAGE = [
    "ㄱ",
    "ㄷ",
    "ㅇ",
    "ㅉ",
    "ㅋ",
    "ㅎ",
    "?"
]
# 누구의 채팅을 가져올지 입력. (UID)
FILTER_USERS = "34908dd0d6c0d1495ace4f281b515094"

import datetime, json, os, requests, tqdm

session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
})

def crawlChats(videoId: int):
    videoData = session.get(f"https://api.chzzk.naver.com/service/v2/videos/{videoId}").json()
    if videoData['code'] != 200:
        print(f"영상 '{videoId}' 에 대한 데이터를 불러오지 못했습니다: {videoData['message']}")
        return None
    
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
    return chats

def main():
    videoId = input("영상 ID 또는 URL을 입력하세요: ").strip()
    # 사용자가 'https://chzzk.naver.com/video/13246889' 처럼 넣는 경우를 대비하여 파싱
    try:
        videoId = int(videoId) if isinstance(videoId, int) else int(videoId.split('/')[-1])
    except ValueError:
        print("유효한 영상 ID 또는 URL을 입력하세요.")
        return

    chats = crawlChats(videoId)
    if chats is None:
        print("채팅 데이터를 가져오는 데 실패했습니다.")
    else:
        path = f"./logs/{videoId}"
        if not os.path.exists(path):
            os.mkdir(path)

        print(f"채팅 수: {len(chats)}")
        with open(f"{path}/all_chats.md", "w", encoding="utf-8") as f:
            # 저장 형식: [{timestamp}] {profile.nickname} ({profile.userIdHash}) - {content}
            for chat in chats:
                if chat['profile']:
                    profile = json.loads(chat['profile'])
                    timestamp = datetime.datetime.fromtimestamp(chat['messageTime'] / 1000).strftime("%Y-%m-%d %H:%M:%S")
                    content = f"[{timestamp}] {profile['nickname']} ({chat['userIdHash']}) - {chat['content']}"
                    f.write(content + "\n")

        # 필터링
        filtered_chats = [chat for chat in chats if any(msg in chat['content'] for msg in FILTER_MESSAGE)] if FILTER_MESSAGE else chats

        print(f"필터링된 채팅 수: {len(filtered_chats)}")
        with open(f"{path}/filtered_chats.md", "w", encoding="utf-8") as f:
            # 저장 형식: [{timestamp}] {profile.nickname} ({profile.userIdHash}) - {content}
            for chat in filtered_chats:
                profile = json.loads(chat['profile'])
                timestamp = datetime.datetime.fromtimestamp(chat['messageTime'] / 1000).strftime("%Y-%m-%d %H:%M:%S")
                content = f"[{timestamp}] {profile['nickname']} ({chat['userIdHash']}) - {chat['content']}"
                f.write(content + "\n")

        if FILTER_USERS:
            filtered_chats = [chat for chat in chats if chat['userIdHash'] == FILTER_USERS]

            print(f"필터링된 특정 유저의 채팅 수: {len(filtered_chats)}")
            with open(f"{path}/filtered_chats_{filtered_chats[0]['userIdHash']}.md", "w", encoding="utf-8") as f:
                # 저장 형식: [{timestamp}] {profile.nickname} ({profile.userIdHash}) - {content}
                for chat in filtered_chats:
                    profile = json.loads(chat['profile'])
                    timestamp = datetime.datetime.fromtimestamp(chat['messageTime'] / 1000).strftime("%Y-%m-%d %H:%M:%S")
                    content = f"[{timestamp}] {profile['nickname']} ({chat['userIdHash']}) - {chat['content']}"
                    f.write(content + "\n")
    
if __name__ == "__main__":
    main()