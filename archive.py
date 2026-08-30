# 치지직 다시보기 링크 하나로 아카이빙 전 과정을 수행한다:
# 타임스탬프 노트 기록 -> 채팅 크롤링 -> 프리미어 마커 XML 생성 -> 영상 다운로드

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from xml.sax.saxutils import escape

import chat

FPS = 60
MIN_FREE_GB = 30          # 다운로드 전 최소 여유 공간
WINDOW_SEC = 15           # 하이라이트 검출 슬라이딩 윈도우 크기
MARKER_OFFSET_SEC = 10    # 채팅은 사건보다 늦게 터지므로 마커를 앞으로 당기는 정도
MIN_CHATS_PER_WINDOW = 10 # 이보다 적게 몰린 구간은 하이라이트로 안 봄
MIN_GAP_SEC = 60          # 마커 간 최소 간격
MAX_MARKERS = 30

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHAT_LINE = re.compile(r"^\[(\d+):(\d+):(\d+):(\d+)\] .+? \([0-9a-f]+\) - (.*)$")


def get_video_dir():
    config_path = os.path.join(BASE_DIR, "config.json")
    if os.path.exists(config_path):
        with open(config_path, encoding="utf-8") as f:
            video_dir = json.load(f).get("video_dir")
        if video_dir:
            return os.path.expanduser(video_dir)
    return os.path.join(BASE_DIR, "videos")


def fetch_metadata(video_id):
    data = chat.session.get(f"{chat.API_BASE}/v2/videos/{video_id}").json()
    if data["code"] != 200:
        print(f"영상 '{video_id}'의 정보를 불러오지 못했습니다: {data['message']}")
        return None
    content = data["content"]
    date = (content["liveOpenDate"] or content["publishDate"]).split()[0]
    return {
        "video_id": content["videoNo"],
        "title": normalize_title(content["videoTitle"]),
        "date": date,
        "duration": content["duration"],
    }


def normalize_title(title):
    parts = [p.strip() for p in title.split("/")]
    title = "_".join(p for p in parts if p)
    return re.sub(r'[\\:*?"<>|]', "", title).strip()


def update_timestamp_note(meta):
    vault_path = chat.get_obsidian_vault_path()
    if not vault_path:
        print("옵시디언 볼트를 찾지 못해 타임스탬프 기록을 건너뜁니다.")
        return
    note_path = os.path.join(vault_path, "chzzk-chat-logs", "타임스탬프.md")
    content = ""
    if os.path.exists(note_path):
        with open(note_path, encoding="utf-8") as f:
            content = f.read()
        if re.search(rf"^\s*{meta['video_id']}\s*$", content, re.M):
            print(f"타임스탬프 노트에 이미 기록된 영상입니다: {meta['video_id']}")
            return
        shutil.copy2(note_path, note_path + ".bak")
    entry = f"{meta['date']}\n{meta['title']}\n{meta['video_id']}"
    with open(note_path, "w", encoding="utf-8") as f:
        f.write(content.rstrip() + "\n\n" + entry + "\n")
    print(f"타임스탬프 노트에 기록했습니다: {meta['date']} / {meta['title']}")


def video_paths(meta, video_dir):
    mmdd = meta["date"][5:7] + meta["date"][8:10]
    base = os.path.join(video_dir, f"{mmdd} {meta['title']}")
    return base + ".mp4", base + ".xml"


def find_filtered_log(meta):
    log_dir = os.path.join(BASE_DIR, "logs", meta["date"])
    suffixed = os.path.join(log_dir, f"filtered_chats_{meta['video_id']}.md")
    if os.path.exists(suffixed):
        return suffixed
    default = os.path.join(log_dir, "filtered_chats.md")
    return default if os.path.exists(default) else None


def parse_chat_log(path):
    chats = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = CHAT_LINE.match(line)
            if m:
                h, mi, s, fr, msg = m.groups()
                sec = int(h) * 3600 + int(mi) * 60 + int(s) + int(fr) / FPS
                chats.append((sec, msg))
    return chats


def find_highlights(chats, duration):
    if not chats:
        return []
    end = int(max(duration, chats[-1][0])) + WINDOW_SEC + 1
    counts = [0] * end
    for sec, _ in chats:
        counts[int(sec)] += 1

    window_sum = sum(counts[:WINDOW_SEC])
    windows = []
    for t in range(end - WINDOW_SEC):
        windows.append((window_sum, t))
        window_sum += counts[t + WINDOW_SEC] - counts[t]

    picked = []
    for count, t in sorted(windows, reverse=True):
        if count < MIN_CHATS_PER_WINDOW or len(picked) >= MAX_MARKERS:
            break
        if all(abs(t - pt) >= MIN_GAP_SEC for _, pt in picked):
            picked.append((count, t))

    highlights = []
    for count, t in sorted(picked, key=lambda p: p[1]):
        in_window = [msg for sec, msg in chats if t <= sec < t + WINDOW_SEC]
        sample = max(in_window, key=len) if in_window else ""
        highlights.append({
            "sec": max(0, t - MARKER_OFFSET_SEC),
            "count": count,
            "sample": sample[:40],
        })
    return highlights


def build_premiere_xml(meta, video_path, highlights):
    frames = int(meta["duration"] * FPS)
    name = escape(os.path.splitext(os.path.basename(video_path))[0])
    pathurl = "file://localhost" + urllib.parse.quote(os.path.abspath(video_path))
    rate = f"<rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate>"

    markers = "\n".join(
        f"  <marker>"
        f"<name>[{h['count']}] {escape(h['sample'])}</name>"
        f"<comment>{WINDOW_SEC}초 동안 채팅 {h['count']}건</comment>"
        f"<in>{int(h['sec'] * FPS)}</in><out>-1</out>"
        f"</marker>"
        for h in highlights
    )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE xmeml>
<xmeml version="4">
 <sequence id="sequence-1">
  <name>{name}</name>
  <duration>{frames}</duration>
  {rate}
  <media>
   <video>
    <format>
     <samplecharacteristics>
      {rate}
      <width>1920</width>
      <height>1080</height>
      <pixelaspectratio>square</pixelaspectratio>
     </samplecharacteristics>
    </format>
    <track>
     <clipitem id="clipitem-1">
      <name>{name}</name>
      <enabled>TRUE</enabled>
      <duration>{frames}</duration>
      {rate}
      <start>0</start><end>{frames}</end><in>0</in><out>{frames}</out>
      <file id="file-1">
       <name>{escape(os.path.basename(video_path))}</name>
       <pathurl>{pathurl}</pathurl>
       {rate}
       <duration>{frames}</duration>
       <media>
        <video>
         <samplecharacteristics>
          {rate}
          <width>1920</width>
          <height>1080</height>
         </samplecharacteristics>
        </video>
        <audio>
         <samplecharacteristics><depth>16</depth><samplerate>48000</samplerate></samplecharacteristics>
         <channelcount>2</channelcount>
        </audio>
       </media>
      </file>
      <link><linkclipref>clipitem-1</linkclipref><mediatype>video</mediatype><trackindex>1</trackindex><clipindex>1</clipindex></link>
      <link><linkclipref>clipitem-2</linkclipref><mediatype>audio</mediatype><trackindex>1</trackindex><clipindex>1</clipindex></link>
     </clipitem>
    </track>
   </video>
   <audio>
    <track>
     <clipitem id="clipitem-2">
      <name>{name}</name>
      <enabled>TRUE</enabled>
      <duration>{frames}</duration>
      {rate}
      <start>0</start><end>{frames}</end><in>0</in><out>{frames}</out>
      <file id="file-1"/>
      <sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack>
      <link><linkclipref>clipitem-1</linkclipref><mediatype>video</mediatype><trackindex>1</trackindex><clipindex>1</clipindex></link>
      <link><linkclipref>clipitem-2</linkclipref><mediatype>audio</mediatype><trackindex>1</trackindex><clipindex>1</clipindex></link>
     </clipitem>
    </track>
   </audio>
  </media>
  <timecode>{rate}<string>00:00:00:00</string><frame>0</frame><displayformat>NDF</displayformat></timecode>
{markers}
 </sequence>
</xmeml>
"""


def generate_premiere_xml(meta, video_path, xml_path):
    log_path = find_filtered_log(meta)
    if not log_path:
        print("필터 채팅 로그를 찾지 못해 마커 XML 생성을 건너뜁니다.")
        return
    highlights = find_highlights(parse_chat_log(log_path), meta["duration"])
    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(build_premiere_xml(meta, video_path, highlights))
    print(f"프리미어 마커 XML 생성 (하이라이트 {len(highlights)}개): {xml_path}")


def download_video(meta, video_path):
    if os.path.exists(video_path):
        print(f"이미 다운로드된 영상입니다: {video_path}")
        return True
    free_gb = shutil.disk_usage(os.path.dirname(video_path)).free / 1e9
    if free_gb < MIN_FREE_GB:
        print(f"디스크 여유 공간이 {free_gb:.0f}GB뿐이라 다운로드를 중단합니다 (최소 {MIN_FREE_GB}GB 필요).")
        return False
    result = subprocess.run([
        "yt-dlp", "-N", "8", "--merge-output-format", "mp4",
        "-o", os.path.splitext(video_path)[0] + ".%(ext)s",
        f"https://chzzk.naver.com/video/{meta['video_id']}",
    ])
    if result.returncode != 0 or not os.path.exists(video_path):
        print("영상 다운로드에 실패했습니다.")
        return False
    print(f"영상 다운로드 완료: {video_path}")
    return True


def archive(user_input):
    video_id = chat.parse_video_id(user_input)
    if video_id is None:
        print(f"유효한 영상 ID 또는 URL이 아닙니다: {user_input}")
        return
    meta = fetch_metadata(video_id)
    if meta is None:
        return
    video_dir = get_video_dir()
    os.makedirs(video_dir, exist_ok=True)
    video_path, xml_path = video_paths(meta, video_dir)

    print(f"\n=== {meta['date']} {meta['title']} ({meta['video_id']}) ===")
    print("[1/4] 타임스탬프 노트 기록")
    update_timestamp_note(meta)
    print("[2/4] 채팅 크롤링")
    chat.process_video(video_id)
    print("[3/4] 프리미어 마커 XML 생성")
    generate_premiere_xml(meta, video_path, xml_path)
    print("[4/4] 영상 다운로드")
    download_video(meta, video_path)


def main():
    if sys.argv[1:]:
        for arg in sys.argv[1:]:
            archive(arg)
        return

    while True:
        try:
            user_input = input("다시보기 링크 또는 영상 ID를 입력하세요 (종료: q 또는 빈 입력): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input or user_input.lower() in ("q", "quit", "exit", "종료"):
            break
        archive(user_input)
        print()


if __name__ == "__main__":
    main()
