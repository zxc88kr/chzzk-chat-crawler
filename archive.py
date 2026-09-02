import fcntl
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
from xml.sax.saxutils import escape

import chat

FPS = chat.FPS
MIN_FREE_GB = 30          # 다운로드 전 최소 여유 공간
EST_GB_PER_HOUR = 8       # 방송 1시간당 요구 공간 (1080p60 약 4GB + 컨테이너 변환 임시 공간)
WINDOW_SEC = 20           # 하이라이트 검출 슬라이딩 윈도우 크기
MARKER_OFFSET_SEC = 0     # 채팅이 몰리기 시작한 지점에 그대로 찍음 (컷 시작점은 편집에서 뒤로 스크럽)
DENSITY_FACTOR = 3        # 방송 평균 밀도의 몇 배부터 하이라이트로 볼지
MIN_CHATS_PER_WINDOW = 4  # 조용한 방송에서도 이보다 적게 몰린 구간은 잡음으로 간주
MIN_GAP_SEC = 80          # 마커 간 최소 간격
MAX_MARKERS = 50

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCK_PATH = os.path.join(BASE_DIR, ".live.lock")
POLL_BASE = "https://api.chzzk.naver.com/polling/v2"

# 라이브 녹화용
POLL_SEC = 30             # 방송 시작 감지 주기
LIVE_GB_PER_HOUR = 4      # 라이브 1시간당 요구 공간 (1080p60 실측 3.81GB + 변환 여유)
DISK_FLOOR_GB = 5         # 녹화 도중 여유 공간이 이 아래로 내려가면 스스로 멈춘다


def fetch_metadata(video_id):
    content = chat.fetch_video_content(video_id)
    if content is None:
        return None
    return {
        "video_id": content["videoNo"],
        "title": normalize_title(content["videoTitle"]) or str(content["videoNo"]),
        "date": chat.broadcast_date(content),
        "duration": content["duration"],
        # 라이브와 다시보기를 이어주는 유일한 열쇠. 영상 번호는 체계가 달라 못 쓴다
        "opened": content.get("liveOpenDate"),
    }


def normalize_title(title):
    parts = [p.strip() for p in title.split("/")]
    title = "_".join(p for p in parts if p)
    return re.sub(r'[\\:*?"<>|]', "", title).strip()


def update_timestamp_note(meta, replaces=None):
    vault_path = chat.get_obsidian_vault_path()
    if not vault_path:
        print("옵시디언 볼트를 찾지 못해 타임스탬프 기록을 건너뜁니다.")
        return
    note_path = os.path.join(vault_path, chat.VAULT_SUBDIR, "타임스탬프.md")
    content = ""
    if os.path.exists(note_path):
        with open(note_path, encoding="utf-8") as f:
            content = f.read()
        if re.search(rf"^\s*{meta['video_id']}\s*$", content, re.M):
            print(f"타임스탬프 노트에 이미 기록된 영상입니다: {meta['video_id']}")
            return
    entry = f"{meta['date']}\n{meta['title']}\n{meta['video_id']}"
    blocks = [b.strip() for b in content.split("\n\n") if b.strip()]

    def entry_id(block):
        return block.splitlines()[-1].strip()

    replaced = False
    if replaces is not None:
        # 라이브로 적어둔 항목을 다시보기 항목으로 갈아끼운다 (한 방송에 한 줄만 남도록)
        for i, block in enumerate(blocks):
            if entry_id(block) == str(replaces):
                blocks[i] = entry
                replaced = True
                break
    if not replaced:
        blocks.append(entry)

    os.makedirs(os.path.dirname(note_path), exist_ok=True)
    with open(note_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(blocks) + "\n")
    action = "갈아끼웠습니다" if replaced else "기록했습니다"
    print(f"타임스탬프 노트에 {action}: {meta['date']} / {meta['title']}")


def output_paths(meta):
    name = f"{meta['date'][5:7]}{meta['date'][8:10]} {meta['title']}"
    video_dir = os.path.join(BASE_DIR, "videos")
    xml_dir = os.path.join(BASE_DIR, "premiere")
    os.makedirs(video_dir, exist_ok=True)
    os.makedirs(xml_dir, exist_ok=True)
    return os.path.join(video_dir, name + ".mp4"), os.path.join(xml_dir, name + ".xml")


def find_filtered_log(meta):
    """이 방송의 필터 채팅 로그를 찾는다.

    같은 날 다른 방송의 로그로 마커를 만들지 않도록 방송 시작 시각을 대조한다.
    시각이 없는 예전 로그는 종전대로 영상 번호로 확인한다.
    """
    log_dir = os.path.join(BASE_DIR, "logs", meta["date"])
    opened = meta.get("opened")

    candidates = [os.path.join(log_dir, "filtered_chats.md")]
    if opened:
        candidates.append(os.path.join(log_dir,
                                       f"filtered_chats_{opened[11:13]}{opened[14:16]}.md"))
    candidates.append(os.path.join(log_dir, f"filtered_chats_{meta['video_id']}.md"))

    for path in candidates:
        if not os.path.exists(path):
            continue
        info = chat.read_log_meta(path)
        if opened and info.get("opened"):
            if info["opened"] == opened:
                return path
            continue
        logged = info.get("video")
        if logged is None or logged == str(meta["video_id"]):
            return path
    return None


def find_live_leftovers(meta):
    """이 방송을 라이브로 먼저 받아둔 흔적이 있으면 그 결과물 경로를 돌려준다."""
    opened = meta.get("opened")
    if not opened:
        return None
    log_dir = os.path.join(BASE_DIR, "logs", meta["date"])
    for path in sorted(glob.glob(os.path.join(log_dir, "all_chats*.md"))):
        info = chat.read_log_meta(path)
        if info.get("opened") != opened or info.get("source") != "live":
            continue
        title = info.get("title")
        if not title:
            return None
        video_path, xml_path = output_paths({"date": meta["date"], "title": title})
        return {"video": video_path, "xml": xml_path,
                "video_id": info.get("video"), "title": title}
    return None


def remove_live_leftovers(leftovers):
    """다시보기로 갈아끼우면서 라이브가 만든 영상과 XML을 치운다.

    채팅 로그는 같은 이름에 덮어써지므로 따로 지울 것이 없다.
    """
    removed = False
    for path in (leftovers["video"], leftovers["xml"]):
        if os.path.exists(path):
            size = os.path.getsize(path)
            os.remove(path)
            removed = True
            print(f"  라이브 결과물 삭제: {os.path.basename(path)} ({size / 1e9:.1f}GB)"
                  if size > 1e8 else f"  라이브 결과물 삭제: {os.path.basename(path)}")
    if not removed:
        print("  삭제할 라이브 결과물이 없습니다 (이미 지웠거나 이름이 바뀐 듯합니다).")


def parse_chat_log(path):
    chats = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = chat.CHAT_LINE.match(line)
            if m:
                h, mi, s, fr, msg = m.groups()
                sec = int(h) * 3600 + int(mi) * 60 + int(s) + int(fr) / FPS
                chats.append((sec, msg))
    return chats


def sample_score(msg):
    # ㅋㅋㅋ 같은 리액션 문자를 걷어낸 뒤 남는 정보량이 많은 채팅을 대표로 뽑는다
    semantic = re.sub(r"[ㄱ-ㅎㅏ-ㅣ?!.,~…\s]", "", msg)
    return (bool(semantic), len(semantic), len(msg))


def find_highlights(chats, duration):
    if not chats:
        return []
    end = int(max(duration, chats[-1][0])) + WINDOW_SEC + 1
    counts = [0] * end
    for sec, _ in chats:
        counts[int(sec)] += 1

    # 방송 평균 밀도의 배수와 절대 최소값 중 높은 쪽을 기준으로 사용
    mean_density = len(chats) * WINDOW_SEC / end
    threshold = max(MIN_CHATS_PER_WINDOW, round(mean_density * DENSITY_FACTOR))

    window_sum = sum(counts[:WINDOW_SEC])
    windows = []
    for t in range(end - WINDOW_SEC):
        windows.append((window_sum, t))
        window_sum += counts[t + WINDOW_SEC] - counts[t]

    # 동점 구간은 이른 시각부터 처리해 방송 후반 편향을 막는다
    picked = []
    for count, t in sorted(windows, key=lambda w: (-w[0], w[1])):
        if count < threshold:
            break
        if all(abs(t - pt) >= MIN_GAP_SEC for _, pt in picked):
            picked.append((count, t))

    # 상한을 넘으면 경계 동점 후보를 방송 시간 전체에서 균등하게 뽑아 채운다
    if len(picked) > MAX_MARKERS:
        cutoff = sorted((c for c, _ in picked), reverse=True)[MAX_MARKERS - 1]
        keep = [p for p in picked if p[0] > cutoff]
        tied = sorted((p for p in picked if p[0] == cutoff), key=lambda p: p[1])
        slots = MAX_MARKERS - len(keep)
        step = len(tied) / slots
        picked = keep + [tied[int(i * step)] for i in range(slots)]

    highlights = []
    for count, t in sorted(picked, key=lambda p: p[1]):
        in_window = [msg for sec, msg in chats if t <= sec < t + WINDOW_SEC]
        sample = max(in_window, key=sample_score) if in_window else ""
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
        return
    free_gb = shutil.disk_usage(os.path.dirname(video_path)).free / 1e9
    need_gb = max(MIN_FREE_GB, meta["duration"] / 3600 * EST_GB_PER_HOUR)
    if free_gb < need_gb:
        print(f"디스크 여유 공간이 {free_gb:.0f}GB뿐이라 다운로드를 중단합니다 (이 방송 기준 {need_gb:.0f}GB 필요).")
        return
    template = os.path.splitext(video_path)[0].replace("%", "%%") + ".%(ext)s"
    try:
        result = subprocess.run([
            "yt-dlp", "-N", "8", "--merge-output-format", "mp4", "-o", template,
            f"https://chzzk.naver.com/video/{meta['video_id']}",
        ])
    except FileNotFoundError:
        print("yt-dlp가 설치되어 있지 않습니다. 설치: brew install yt-dlp")
        return
    if result.returncode != 0 or not os.path.exists(video_path):
        print("영상 다운로드에 실패했습니다.")
        return
    print(f"영상 다운로드 완료: {video_path}")


def archive(user_input):
    video_id = chat.parse_video_id(user_input)
    if video_id is None:
        print(f"유효한 영상 ID 또는 URL이 아닙니다: {user_input}")
        return
    meta = fetch_metadata(video_id)
    if meta is None:
        return
    video_path, xml_path = output_paths(meta)
    # 같은 방송을 라이브로 먼저 받아뒀는지 확인한다 (방송 시작 시각으로 대조)
    leftovers = find_live_leftovers(meta)

    print(f"\n=== {meta['date']} {meta['title']} ({meta['video_id']}) ===")
    if leftovers:
        print(f"이 방송의 라이브 녹화본을 다시보기로 갈아끼웁니다: {leftovers['title']}")
    print("[1/5] 타임스탬프 노트 기록")
    update_timestamp_note(meta, replaces=leftovers["video_id"] if leftovers else None)
    print("[2/5] 채팅 크롤링")
    crawled = chat.process_video(video_id, meta["date"], meta.get("opened"), "vod")
    print("[3/5] 프리미어 마커 XML 생성")
    if crawled:
        generate_premiere_xml(meta, video_path, xml_path)
    else:
        # 오래된 로그가 남아 있어도 다른 방송의 채팅으로 마커를 만들지 않도록 건너뜀
        print("채팅 크롤링이 실패해 마커 XML 생성을 건너뜁니다.")
    print("[4/5] 라이브 녹화본 정리")
    if leftovers and crawled:
        # 채팅 크롤링이 됐다는 건 이 다시보기가 실제로 살아있다는 뜻이다. 그때만 지운다.
        # 크롤링이 실패했는데 지워버리면 대체물 없이 원본만 사라진다
        remove_live_leftovers(leftovers)
    elif leftovers:
        print("  채팅 크롤링이 실패해 라이브 녹화본을 그대로 둡니다.")
    else:
        print("  정리할 라이브 녹화본이 없습니다.")
    print("[5/5] 영상 다운로드")
    download_video(meta, video_path)


# ================================================================ 라이브 녹화
#
# 다시보기가 올라오지 않는 방송을 대비한 보험. 방송이 켜지면 영상과 실시간 채팅을 함께
# 받아두고, 끝나면 위의 다시보기 경로와 똑같이 마커 XML까지 만든다. 영상과 채팅은 항상
# 같은 소스에서 온 것끼리만 짝지어 쓴다 (라이브 영상에 다시보기 채팅을 섞으면 어긋난다).

def fetch_live_detail(channel_id):
    data = chat.get_json(f"{chat.API_BASE}/v3/channels/{channel_id}/live-detail")
    if data.get("code") != 200:
        print(f"채널 정보를 불러오지 못했습니다: {data.get('message')}")
        return None
    return data["content"]


def fetch_live_status(channel_id):
    # live-detail보다 가벼운 폴링 전용 엔드포인트 (응답 약 1.7KB)
    data = chat.get_json(f"{POLL_BASE}/channels/{channel_id}/live-status")
    return data["content"] if data.get("code") == 200 else None


def parse_channel_id(user_input):
    text = user_input.strip().split("?")[0].rstrip("/")
    if "/" in text:
        text = text.split("/")[-1]
    return text if re.fullmatch(r"[0-9a-f]{32}", text) else None


def best_hls_url(detail):
    """가장 화질이 높은 트랙의 m3u8 주소. 성인/구독 전용이면 재생 정보 자체가 없다."""
    raw = detail.get("livePlaybackJson")
    if not raw:
        return None
    media = [m for m in json.loads(raw).get("media", []) if m.get("mediaId") == "HLS"]
    if not media:
        return None
    master = media[0]["path"]
    lines = chat.get_text(master).splitlines()

    variants = []
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF") and i + 1 < len(lines):
            bandwidth = re.search(r"BANDWIDTH=(\d+)", line)
            if bandwidth:
                variants.append((int(bandwidth.group(1)),
                                 urllib.parse.urljoin(master, lines[i + 1].strip())))
    if not variants:
        return None
    return max(variants)[1]


def enough_disk(target_dir):
    free_gb = shutil.disk_usage(target_dir).free / 1e9
    if free_gb < MIN_FREE_GB:
        print(f"디스크 여유 공간이 {free_gb:.0f}GB뿐이라 녹화를 시작하지 않습니다 "
              f"(최소 {MIN_FREE_GB}GB 필요).")
        return False
    print(f"디스크 여유 {free_gb:.0f}GB - 약 {free_gb / LIVE_GB_PER_HOUR:.1f}시간 녹화 가능")
    return True


def start_recording(url, ts_path):
    """mpegts로 받는다. 정전이나 강제 종료로 중단돼도 그 시점까지는 재생된다."""
    process = subprocess.Popen([
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        # ffmpeg 8의 extension_picky 기본값이 치지직 세그먼트(.m4v)를 거부한다
        "-extension_picky", "0",
        # 플레이리스트에 남아있는 앞부분까지 받는다. 기본값(-3)은 라이브 최전방에서
        # 6초 뒤부터 시작하는데, 0으로 두면 약 28초를 더 확보해 감지 지연을 메운다
        "-live_start_index", "0",
        "-user_agent", chat.USER_AGENT,
        "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "30",
        "-i", url, "-c", "copy", "-f", "mpegts", ts_path,
    ])
    return process


def stop_recording(process):
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def media_duration(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def remux(ts_path, mp4_path):
    """재인코딩 없이 컨테이너만 바꾼다 - 화질 손실이 없고 CPU도 거의 쓰지 않는다."""
    result = subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", ts_path, "-c", "copy", "-movflags", "+faststart", mp4_path,
    ])
    if result.returncode != 0 or not os.path.exists(mp4_path):
        print(f"mp4 변환에 실패했습니다. 원본은 그대로 두었습니다: {ts_path}")
        return False
    os.remove(ts_path)
    return True


def to_player_times(messages, anchor_epoch):
    """절대 시각으로 모아둔 채팅을 '영상 기준 몇 밀리초'로 바꾼다.

    기준점은 (녹화 종료 시각 - 실제 녹화 길이)로 잡는다. 재생 버퍼 때문에 녹화 시작
    시각을 그대로 쓰면 몇 초씩 어긋나는데, 끝에서 되짚으면 그 오차가 사라진다.
    """
    converted = []
    for message in messages:
        if message["msgTime"] is None:
            continue
        offset = int(message["msgTime"] - anchor_epoch * 1000)
        if offset < 0:
            continue                      # 녹화 시작 전에 올라온 채팅
        converted.append({
            "profile": message["profile"],
            "userIdHash": message["userIdHash"],
            "playerMessageTime": offset,
            "content": message["content"],
        })
    converted.sort(key=lambda m: m["playerMessageTime"])
    return converted


def finalize(detail, ts_path, messages, ended_at):
    duration = media_duration(ts_path)
    if not duration:
        print(f"녹화 파일을 읽을 수 없습니다. 원본을 남겨둡니다: {ts_path}")
        return
    print(f"\n녹화 길이: {duration / 3600:.2f}시간 "
          f"({os.path.getsize(ts_path) / 1e9:.1f}GB)")

    meta = {
        "video_id": detail["liveId"],
        "title": normalize_title(detail["liveTitle"]) or str(detail["liveId"]),
        "date": detail["openDate"].split()[0],
        "duration": duration,
    }
    video_path, xml_path = output_paths(meta)

    print(f"\n=== {meta['date']} {meta['title']} ({meta['video_id']}) ===")
    print("[1/4] 타임스탬프 노트 기록")
    update_timestamp_note(meta)

    print("[2/4] 채팅 로그 저장")
    # 기준점은 끝에서 되짚어 잡는다 (to_player_times 설명 참고)
    converted = to_player_times(messages, ended_at - duration)
    if converted:
        # 다시보기가 올라오면 archive()가 이 정보로 여기서 만든 결과물을 찾아 치운다
        chat.write_chat_logs(converted, meta["video_id"], meta["date"],
                             opened=detail["openDate"], source="live",
                             title=meta["title"])
    else:
        print("수집된 채팅이 없어 로그 저장을 건너뜁니다.")

    print("[3/4] mp4 변환")
    if not remux(ts_path, video_path):
        return
    print(f"영상 저장 완료: {video_path}")

    print("[4/4] 프리미어 마커 XML 생성")
    if converted:
        generate_premiere_xml(meta, video_path, xml_path)
    else:
        print("채팅이 없어 마커 XML 생성을 건너뜁니다.")


def record_broadcast(channel_id):
    """반환값: "done" 녹화 완료 / "skip" 받을 수 없음 / "stop" 사용자가 중단."""
    detail = fetch_live_detail(channel_id)
    if detail is None or detail.get("status") != "OPEN":
        return "skip"

    url = best_hls_url(detail)
    if url is None:
        if detail.get("adult"):
            print("성인 설정 방송이라 로그인 없이는 받을 수 없습니다. 이 방송은 건너뜁니다.")
        else:
            print("재생 정보를 받지 못했습니다 (구독자 전용이거나 일시적 오류). 건너뜁니다.")
        return "skip"

    video_dir = os.path.join(BASE_DIR, "videos")
    os.makedirs(video_dir, exist_ok=True)
    if not enough_disk(video_dir):
        return "skip"

    ts_path = os.path.join(video_dir, f".live_{detail['liveId']}.ts")
    print(f"\n▶ 녹화 시작: {detail['liveTitle']} (liveId {detail['liveId']})")
    print(f"  방송 시작 {detail['openDate']} / 시청자 {detail.get('concurrentUserCount')}명")

    collector = chat.ChatCollector(detail["chatChannelId"])
    collector.start()
    process = start_recording(url, ts_path)

    interrupted = False
    try:
        while process.poll() is None:
            time.sleep(POLL_SEC)
            # 공간이 바닥나면 ffmpeg가 깨지기 전에 우리가 먼저 멈춘다.
            # 여기까지 받아둔 분량은 살리는 편이 낫다.
            if shutil.disk_usage(video_dir).free / 1e9 < DISK_FLOOR_GB:
                print(f"  디스크 여유가 {DISK_FLOOR_GB}GB 아래로 내려가 녹화를 마칩니다.")
                break
            try:
                status = fetch_live_status(channel_id)
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                continue     # 상태 조회가 잠깐 실패해도 녹화는 계속한다
            if status and status.get("status") == "CLOSE":
                print("  방송이 종료되어 녹화를 마칩니다.")
                break
    except KeyboardInterrupt:
        interrupted = True
        print("\n  중단 요청을 받아 녹화를 마칩니다.")
    finally:
        # ffmpeg가 완전히 멈춘 뒤에 시각을 잰다. 먼저 재면 그 사이에 기록된 만큼
        # 기준점이 앞당겨져 채팅 시각이 통째로 밀린다
        stop_recording(process)
        ended_at = time.time()
        collector.stop()

    if not os.path.exists(ts_path):
        print("녹화된 파일이 없습니다.")
        return "skip"
    # 제목은 방송을 켤 때 붙인 것을 쓴다. 도중에 바뀌는 일이 잦은데, 특히 끝날 무렵
    # "방종" 같은 말로 바꾸는 경우가 많아 종료 시점 제목을 쓰면 이름이 쓸모없어진다
    finalize(detail, ts_path, collector.collected(), ended_at)
    return "stop" if interrupted else "done"


def watch(channel_id, once=False):
    print(f"채널 {channel_id} 감시를 시작합니다 ({POLL_SEC}초 간격, 종료는 Ctrl+C)")
    skipped = set()          # 받을 수 없다고 판단한 방송 - 매 주기마다 다시 시도하지 않는다
    while True:
        try:
            status = fetch_live_status(channel_id)
            if status is None:
                print("상태 조회에 실패했습니다. 다음 주기에 다시 시도합니다.")
            elif status.get("status") == "OPEN" and status.get("liveId") not in skipped:
                result = record_broadcast(channel_id)
                if result == "stop" or once:
                    return
                if result == "skip":
                    skipped.add(status.get("liveId"))
                else:
                    print(f"\n다시 감시 상태로 돌아갑니다 ({POLL_SEC}초 간격)")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            # 몇 시간씩 도는 프로그램이라 잠깐의 회선 장애로 죽으면 안 된다
            print(f"네트워크 오류: {getattr(error, 'reason', error)}. 다음 주기에 다시 시도합니다.")
        time.sleep(POLL_SEC)


def hold_awake():
    """이 프로그램이 도는 동안 시스템 잠자기를 막는다.

    방송을 기다리는 감시 구간에도 걸어야 한다. 유휴로 판단되어 맥이 잠들면 폴링이
    멈춰서 방송이 켜져도 알아채지 못한다. -d는 넣지 않아 화면은 평소대로 꺼진다.
    프로그램이 끝나면 -w가 걸린 PID가 사라지므로 자동으로 풀린다.
    """
    try:
        return subprocess.Popen(
            ["caffeinate", "-i", "-m", "-s", "-w", str(os.getpid())])
    except FileNotFoundError:
        print("caffeinate를 찾지 못했습니다. 자리를 비우면 맥이 잠들어 방송을 놓칠 수 있습니다.")
        return None


def acquire_lock():
    """중복 실행을 막는다.

    같은 방송을 두 번 받는 정도가 아니라, 두 ffmpeg가 같은 파일에 동시에 쓰면
    녹화본 자체가 깨진다. 파일 잠금은 프로세스가 죽으면 OS가 알아서 풀어주므로
    비정상 종료 뒤에 남는 찌꺼기 걱정이 없다.
    """
    handle = open(LOCK_PATH, "a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.seek(0)
        running = handle.read().strip() or "?"
        handle.close()
        return None, running
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    return handle, None


def live_main(args):
    once = "--once" in args
    positional = [a for a in args if not a.startswith("-")]

    source = positional[0] if positional else chat.CONFIG.get("live_channel_id", "")
    channel_id = parse_channel_id(source) if source else None
    if channel_id is None:
        sys.exit("채널 ID가 필요합니다. 라이브 주소를 인자로 넘기거나 "
                 "config.json의 live_channel_id에 넣어주세요.\n"
                 "  예: ./live.sh https://chzzk.naver.com/live/<채널ID>")

    lock, running_pid = acquire_lock()
    if lock is None:
        sys.exit(f"이미 실행 중입니다 (PID {running_pid}). 중복 실행하면 녹화본이 깨집니다.\n"
                 f"  진행 상황 확인: ps -p {running_pid} -o pid,etime,command\n"
                 f"  종료하려면    : kill {running_pid}")
    awake = hold_awake()
    try:
        watch(channel_id, once=once)
    except KeyboardInterrupt:
        print("\n감시를 종료합니다.")
    finally:
        if awake is not None and awake.poll() is None:
            awake.terminate()
        lock.close()


if __name__ == "__main__":
    if sys.argv[1:2] == ["live"]:
        live_main(sys.argv[2:])
    else:
        chat.run_cli(archive, "다시보기 링크 또는 영상 ID를 입력하세요 (종료: q 또는 빈 입력): ")
