# Chzzk Chat Crawler

<img src="assets/chzzk_logo.png" width="200">

파이썬을 통해 네이버 치지직 서비스의 채팅을 크롤링 해봅시다.

이 코드는 [마지막남은뚜또](https://github.com/LastDice)님의 코드를 기반으로 작성하였습니다.

## 시작 가이드
1. 프로젝트 클론
```
git clone https://github.com/zxc88kr/chzzk-chat-crawler.git
```
2. 실행

macOS / Linux
```
./run.sh
영상 ID 또는 URL을 입력하세요: 9330920
```

Windows
```
run.bat
영상 ID 또는 URL을 입력하세요: 9330920
```

> 첫 실행 시 가상환경(venv) 생성과 패키지 설치가 자동으로 진행됩니다. 별도로 `pip install`을 실행할 필요가 없습니다.
> 출력 내용은 자동으로 logs 폴더에 저장됩니다.

## 예시 입력
- 영상 ID
  - `9330920`
- 치지직 다시보기 URL
  - `https://chzzk.naver.com/video/9330920`

## 옵시디언(Obsidian) 연동
로그를 `logs` 폴더뿐 아니라 옵시디언 볼트에도 함께 저장할 수 있습니다.

- 옵시디언 기본 볼트 위치(`~/Documents/Obsidian Vault`)가 존재하면 별도 설정 없이 자동으로 그 안의 `chzzk-chat-logs/{날짜}` 폴더에 함께 저장됩니다.
- 볼트 위치를 다른 곳으로 옮겼거나 다르게 지정하고 싶다면, `config.example.json`을 `config.json`으로 복사한 뒤 `obsidian_vault_path`에 원하는 경로를 입력하세요.
```json
{
    "obsidian_vault_path": "/Users/이름/내볼트경로"
}
```
> `config.json`은 기기마다 경로가 다를 수 있어 git에 포함되지 않습니다 (Windows/macOS 각자 설정).
