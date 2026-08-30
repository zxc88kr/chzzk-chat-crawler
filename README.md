# Chzzk VOD Archiver

<img src="assets/chzzk_logo.png" width="200">

네이버 치지직 다시보기 링크 하나로 방송 아카이빙 전 과정을 자동으로 수행하는 macOS용 도구입니다.

1. **타임스탬프 노트 기록** — 방송 날짜·제목·영상 ID를 옵시디언 노트에 추가
2. **채팅 크롤링** — 전체/필터 채팅을 마크다운 로그로 저장
3. **프리미어 마커 XML 생성** — 채팅이 몰린 하이라이트 구간을 분석해 Premiere Pro로 바로 가져올 수 있는 시퀀스 XML 생성
4. **영상 다운로드** — yt-dlp로 최고 화질(1080p60) 다운로드

## 요구 사항
- macOS, Python 3 (기본 설치본으로 충분, 외부 패키지 불필요)
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)와 ffmpeg: `brew install yt-dlp ffmpeg`

## 시작 가이드
1. 프로젝트 클론
```
git clone https://github.com/zxc88kr/chzzk-vod-archiver.git
```
2. 실행
```
./archive.sh
다시보기 링크 또는 영상 ID를 입력하세요 (종료: q 또는 빈 입력): https://chzzk.naver.com/video/9330920
```
링크를 인자로 넘기면 바로 실행됩니다 (여러 개 연속 처리 가능).
```
./archive.sh https://chzzk.naver.com/video/9330920
```

> 외부 파이썬 패키지를 사용하지 않아 별도 설치 과정이 없습니다.
> 이미 다운로드된 영상·기록된 타임스탬프는 자동으로 건너뜁니다.
> 디스크 여유 공간이 30GB 미만이면 영상 다운로드를 중단합니다.

채팅 크롤링만 필요하면 단독으로도 실행할 수 있습니다.
```
python3 chat.py [링크]
```

## 결과물
- `videos/{MMDD 제목}.mp4` — 영상 (1080p60)
- `premiere/{MMDD 제목}.xml` — 프리미어 마커 XML. Premiere Pro에서 File > Import 하면 영상이 올라간 시퀀스와 하이라이트 마커가 생성됩니다. 마커 이름은 `[채팅 수] 대표 채팅`.
- `logs/{YYYY-MM-DD}/all_chats.md`, `filtered_chats.md` — 채팅 로그 (같은 날 다른 방송이 있으면 파일명에 영상 ID가 붙습니다)

## 설정 (선택)
기본 저장 위치를 바꾸고 싶을 때만 프로젝트 루트에 `config.json`을 만드세요. 없으면 영상은 `videos/`, 옵시디언은 기본 볼트 위치를 사용합니다.
```json
{
    "video_dir": "/Users/이름/영상저장폴더",
    "obsidian_vault_path": "/Users/이름/내볼트경로"
}
```
> `config.json`은 기기마다 경로가 달라 git에 포함되지 않습니다.

## 옵시디언(Obsidian) 연동
채팅 로그와 타임스탬프 노트를 옵시디언 볼트에도 함께 저장합니다.

- 옵시디언 기본 볼트 위치(`~/Documents/Obsidian Vault`)가 존재하면 별도 설정 없이 자동으로 그 안의 `치지직/{YYYY-MM-DD}` 폴더에 함께 저장됩니다.
- 타임스탬프 노트는 `치지직/타임스탬프.md`에 기록되며, 수정 전 `.bak` 백업을 남깁니다.

## 하이라이트 검출 방식
필터 채팅(리액션성 채팅)을 15초 단위로 훑어 채팅이 몰린 구간을 찾고, 채팅이 사건보다 늦게 터지는 점을 감안해 마커를 10초 앞당겨 찍습니다. 마커 간 최소 간격 60초, 최대 30개. 값은 `archive.py` 상단 상수로 조절할 수 있습니다.
