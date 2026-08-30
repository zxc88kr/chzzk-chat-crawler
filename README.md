# Chzzk VOD Archiver

<img src="assets/chzzk_logo.png" width="200">

네이버 치지직 다시보기 링크 하나로 방송 아카이빙 전 과정을 자동으로 수행하는 macOS용 도구입니다.

1. **타임스탬프 노트 기록** — 방송 날짜·제목·영상 ID를 옵시디언 노트에 추가
2. **채팅 크롤링** — 전체/필터 채팅을 마크다운 로그로 저장
3. **프리미어 마커 XML 생성** — 채팅이 몰린 하이라이트 구간을 Premiere Pro용 시퀀스 XML로 저장
4. **영상 다운로드** — yt-dlp로 최고 화질(1080p60) 다운로드

이미 처리된 단계는 자동으로 건너뛰므로 같은 링크를 다시 실행해도 안전합니다.

## 요구 사항

- macOS, Python 3 (외부 패키지 불필요)
- yt-dlp와 ffmpeg: `brew install yt-dlp ffmpeg`

## 사용법

```
./archive.sh
다시보기 링크 또는 영상 ID를 입력하세요 (종료: q 또는 빈 입력): https://chzzk.naver.com/video/9330920
```

링크를 인자로 넘기면 바로 실행되고, 여러 개를 넘기면 연속 처리합니다.

```
./archive.sh https://chzzk.naver.com/video/9330920
```

채팅 크롤링만 필요하면 `python3 chat.py [링크]`로 단독 실행할 수 있습니다.

## 결과물

| 위치 | 내용 |
|---|---|
| `videos/{MMDD 제목}.mp4` | 영상 (1080p60) |
| `premiere/{MMDD 제목}.xml` | 프리미어 마커 XML — Premiere에서 File > Import 하면 시퀀스와 마커가 생성됨 |
| `logs/{YYYY-MM-DD}/` | 채팅 로그 (`all_chats.md`, `filtered_chats.md`) |

옵시디언 기본 볼트(`~/Documents/Obsidian Vault`)가 있으면 채팅 로그는 `치지직/로그/{YYYY-MM-DD}/`, 타임스탬프 노트는 `치지직/타임스탬프.md`에도 함께 저장됩니다.

## 설정 (config.json)

| 키 | 역할 |
|---|---|
| `highlight_users` | 닉네임에 밑줄을 표시할 유저 ID 목록 |
| `bot_users` | 로그에서 제외할 봇 계정 ID 목록 |
| `filter_messages` | 필터본에 남길 기준 문자 목록 |

유저 ID는 `all_chats.md`의 닉네임 뒤 괄호 안 해시를 복사하면 됩니다. 처음 사용한다면 `highlight_users`를 본인 계정 ID로 바꿔주세요.

## 하이라이트 검출

필터 채팅을 20초 창으로 훑어 리액션이 몰린 구간을 마커로 만듭니다. 기준은 방송 평균 밀도의 3배(최소 4건)로 방송마다 자동 조정되며, 마커는 10초 앞당겨 최대 50개까지 찍힙니다. 값은 `archive.py` 상단 상수로 조절합니다.
