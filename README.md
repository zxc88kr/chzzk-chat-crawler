# Chzzk Chat Crawler

파이썬을 통해 네이버 치지직 서비스의 채팅을 크롤링 해봅시다.

이 코드는 [마지막남은뚜또](https://github.com/LastDice)님의 코드를 기반으로 작성하였습니다.

## 시작 가이드
1. 프로젝트 클론
```
git clone https://github.com/zxc88kr/chzzk-chat-crawler.git
```
2. 패키지 설치
```
pip install requests tqdm
```
3. 실행
```
python chzzk_chat.py
영상 ID 또는 URL을 입력하세요: 9330920
```
> 출력 내용은 자동으로 logs 폴더에 저장됩니다.

## 예시 입력
- 영상 ID
  - `9330920`
- 치지직 다시보기 URL
  - `https://chzzk.naver.com/video/9330920`