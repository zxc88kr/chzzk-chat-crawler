import base64
import hashlib
import json
import os
import re
import socket
import ssl
import struct
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://api.chzzk.naver.com/service"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
FPS = 60
VAULT_SUBDIR = "치지직"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# format_chat이 만드는 한 줄 포맷의 역파싱 정규식 - 포맷 변경 시 함께 수정
CHAT_LINE = re.compile(r"^\[(\d+):(\d+):(\d+):(\d+)\] .+? \([0-9a-f]+\) - (.*)$")

COMM_BASE = "https://comm-api.game.naver.com/nng_main/v1"
CHAT_IDLE_LIMIT = 180     # 이 시간 동안 채팅 서버가 조용하면 끊긴 것으로 보고 재접속
RECONNECT_WAIT = 5


def load_config():
    try:
        with open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8") as f:
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
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        # 치지직 API는 오류도 JSON 본문(code/message)으로 주므로 살려서 반환
        try:
            return json.load(error)
        except ValueError:
            return {"code": error.code, "message": str(error)}


def get_text(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read().decode("utf-8", "replace")


def fetch_video_content(video_id):
    data = get_json(f"{API_BASE}/v2/videos/{video_id}")
    if data["code"] != 200:
        print(f"영상 '{video_id}'의 정보를 불러오지 못했습니다: {data['message']}")
        return None
    return data["content"]


def broadcast_date(content):
    # 업로드 영상은 liveOpenDate가 없으므로 publishDate로 대체
    return (content["liveOpenDate"] or content["publishDate"]).split()[0]


def fetch_chats(video_id):
    chats = []
    player_message_time = 0
    while True:
        chat_data = get_json(
            f"{API_BASE}/v1/videos/{video_id}/chats"
            f"?playerMessageTime={player_message_time}&previousVideoChatSize=50"
        )
        if chat_data["code"] != 200:
            # 부분 수집본으로 기존 로그를 덮어쓰지 않도록 실패로 처리
            print(f"채팅 데이터를 불러오지 못했습니다 (playerMessageTime: {player_message_time}): {chat_data['message']}")
            return None

        content = chat_data["content"]
        chats.extend(content["videoChats"])

        if content["nextPlayerMessageTime"] is None:
            return chats
        player_message_time = content["nextPlayerMessageTime"]


def format_timestamp(ms):
    hours = ms // 3600000
    minutes = ms // 60000 % 60
    seconds = ms // 1000 % 60
    frames = ms % 1000 * FPS // 1000
    return f"{hours:02}:{minutes:02}:{seconds:02}:{frames:02}"


def format_chat(chat, highlight_users):
    nickname = json.loads(chat["profile"])["nickname"]
    if highlight_users and chat["userIdHash"] in highlight_users:
        nickname = f"<u>{nickname}</u>"
    timestamp = format_timestamp(chat["playerMessageTime"])
    return f"[{timestamp}] {nickname} ({chat['userIdHash']}) - {chat.get('content') or ''}"


def save_chats(path, chats, video_id, highlight_users=None,
               opened=None, source=None, title=None):
    """채팅 로그를 저장한다.

    앞머리의 opened(방송 시작 시각)가 이 방송의 신원이다. 영상 번호는 라이브(liveId)와
    다시보기(videoNo)가 서로 다른 체계라 같은 방송인지 판단하는 데 쓸 수 없다.
    source와 title은 나중에 다시보기가 올라왔을 때 라이브가 만든 결과물을 찾아
    치우기 위해 남긴다.
    """
    with open(path, "w", encoding="utf-8") as f:
        f.write("---\n")
        f.write(f"video: {video_id}\n")
        for key, value in (("opened", opened), ("source", source), ("title", title)):
            if value:
                f.write(f"{key}: {value}\n")
        f.write("---\n")
        for chat in chats:
            f.write(format_chat(chat, highlight_users) + "\n")


def write_chat_logs(chats, video_id, live_open_date,
                    opened=None, source=None, title=None):
    """전체본과 필터본을 로컬 logs/와 옵시디언 볼트에 저장한다.

    다시보기 크롤링과 라이브 수집이 같은 형식을 쓰므로 저장 경로도 공유한다.
    """
    filtered = ([c for c in chats
                 if any(m in (c.get("content") or "") for m in FILTER_MESSAGES)]
                if FILTER_MESSAGES else chats)
    print(f"채팅 수: {len(chats)} (필터링: {len(filtered)})")

    dirs = output_dirs(live_open_date)
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        suffix = log_suffix(d, video_id, opened)
        save_chats(os.path.join(d, f"all_chats{suffix}.md"), chats, video_id,
                   None, opened, source, title)
        save_chats(os.path.join(d, f"filtered_chats{suffix}.md"),
                   filtered, video_id, HIGHLIGHT_USERS, opened, source, title)
    print("저장 위치: " + ", ".join(dirs))


def read_log_meta(path):
    """로그 앞머리를 딕셔너리로 읽는다. 앞머리가 없는 예전 로그면 빈 딕셔너리."""
    if not os.path.exists(path):
        return {}
    meta = {}
    with open(path, encoding="utf-8") as f:
        if f.readline().strip() != "---":
            return {}
        for line in f:
            if line.strip() == "---":
                break
            if ":" in line:
                key, value = line.split(":", 1)   # 시각의 콜론은 값에 남는다
                meta[key.strip()] = value.strip()
    return meta


def read_logged_video_id(path):
    return read_log_meta(path).get("video")


def log_suffix(directory, video_id, opened):
    """같은 날 다른 방송의 로그를 덮어쓰지 않도록 붙일 접미사.

    시작 시각이 같으면 같은 방송이므로 접미사 없이 덮어쓴다. 라이브로 먼저 받아둔
    로그를 다시보기 로그가 그대로 대체하게 하려는 것이다.
    """
    existing = read_log_meta(os.path.join(directory, "all_chats.md"))
    if not existing:
        return ""
    if opened and existing.get("opened"):
        if existing["opened"] == opened:
            return ""
        return "_" + opened[11:13] + opened[14:16]      # 다른 방송 - 시작 시각으로 구분
    # 시작 시각이 없는 예전 로그는 종전대로 영상 번호로 판단한다
    logged = existing.get("video")
    return f"_{video_id}" if logged is not None and logged != str(video_id) else ""


def get_obsidian_vault_path():
    default_path = os.path.expanduser("~/Documents/Obsidian Vault")
    return default_path if os.path.isdir(default_path) else None


def output_dirs(live_open_date):
    dirs = [os.path.join(BASE_DIR, "logs", live_open_date)]
    vault_path = get_obsidian_vault_path()
    if vault_path:
        dirs.append(os.path.join(vault_path, VAULT_SUBDIR, "로그", live_open_date))
    return dirs


def process_video(video_id, live_open_date=None, opened=None, source="vod"):
    if live_open_date is None or opened is None:
        content = fetch_video_content(video_id)
        if content is None:
            return
        live_open_date = live_open_date or broadcast_date(content)
        opened = opened or content.get("liveOpenDate")

    chats = fetch_chats(video_id)
    if chats is None:
        return
    # 봇과 프로필 없는(후원·시스템성) 레코드는 로그 대상이 아님
    chats = [c for c in chats if c.get("profile") and c.get("userIdHash") not in BOT_USERS]
    write_chat_logs(chats, video_id, live_open_date, opened, source)
    return True


# ---------------------------------------------------------------- 라이브 채팅

# 라이브 채팅은 WebSocket으로만 받을 수 있는데 표준 라이브러리에는 클라이언트가 없다.
# RFC 6455 중 이 용도에 필요한 부분(텍스트 프레임 송수신, ping 응답, 종료)만 구현한다.
# 확장(permessage-deflate)은 협상하지 않으므로 압축 프레임은 오지 않는다.

OP_CONT, OP_TEXT, OP_BINARY = 0x0, 0x1, 0x2
OP_CLOSE, OP_PING, OP_PONG = 0x8, 0x9, 0xA


class WebSocketError(Exception):
    pass


class WebSocket:
    def __init__(self, url, timeout=60):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "wss":
            raise WebSocketError(f"wss만 지원합니다: {url}")
        host = parts.hostname
        port = parts.port or 443
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query

        raw = socket.create_connection((host, port), timeout=timeout)
        self._sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        self._sock.settimeout(timeout)
        self._buf = b""
        self._handshake(host, path)

    def _handshake(self, host, path):
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "Origin: https://chzzk.naver.com\r\n"
            "\r\n"
        )
        self._sock.sendall(request.encode())
        while b"\r\n\r\n" not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise WebSocketError("핸드셰이크 도중 연결이 끊겼습니다.")
            self._buf += chunk
        head, _, rest = self._buf.partition(b"\r\n\r\n")
        self._buf = rest
        status = head.split(b"\r\n", 1)[0].decode("latin-1")
        if "101" not in status:
            raise WebSocketError(f"업그레이드 실패: {status}")

    def _read(self, n):
        while len(self._buf) < n:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise WebSocketError("연결이 끊겼습니다.")
            self._buf += chunk
        data, self._buf = self._buf[:n], self._buf[n:]
        return data

    def _send_frame(self, opcode, payload=b""):
        # 클라이언트가 보내는 프레임은 반드시 마스킹해야 한다 (RFC 6455 5.3)
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", length)
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(bytes(header) + mask + masked)

    def send_text(self, text):
        self._send_frame(OP_TEXT, text.encode())

    def recv_text(self):
        """텍스트 메시지 하나를 돌려준다. ping은 내부에서 pong으로 응답하고 넘어간다."""
        fragments = bytearray()
        frag_opcode = None
        while True:
            b0, b1 = self._read(2)
            fin, opcode = b0 & 0x80, b0 & 0x0F
            length = b1 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(length) if length else b""

            if opcode == OP_PING:
                self._send_frame(OP_PONG, payload)
                continue
            if opcode == OP_PONG:
                continue
            if opcode == OP_CLOSE:
                raise WebSocketError("서버가 연결을 종료했습니다.")
            if opcode in (OP_TEXT, OP_BINARY):
                frag_opcode = opcode
                fragments = bytearray(payload)
            elif opcode == OP_CONT:
                fragments += payload
            if fin:
                if frag_opcode == OP_TEXT:
                    return fragments.decode("utf-8", "replace")
                fragments = bytearray()
                frag_opcode = None

    def send_json(self, obj):
        self.send_text(json.dumps(obj, ensure_ascii=False))

    def recv_json(self):
        return json.loads(self.recv_text())

    def close(self):
        try:
            self._send_frame(OP_CLOSE, struct.pack(">H", 1000))
        except OSError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass


class ChatCollector(threading.Thread):
    """라이브 채팅을 절대 시각(epoch ms)으로 모아둔다.

    영상 기준 몇 초 지점인지는 녹화가 끝난 뒤 실제 길이를 알아야 정확해지므로,
    여기서는 변환하지 않고 원본 시각 그대로 쌓는다.
    """

    def __init__(self, chat_channel_id):
        super().__init__(daemon=True)
        self.chat_channel_id = chat_channel_id
        self.messages = []
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def stop(self):
        self._stop.set()

    def collected(self):
        with self._lock:
            return list(self.messages)

    def _access_token(self):
        data = get_json(
            f"{COMM_BASE}/chats/access-token"
            f"?channelId={self.chat_channel_id}&chatType=STREAMING"
        )
        return (data.get("content") or {}).get("accessToken")

    def _server_url(self):
        index = (int(hashlib.md5(self.chat_channel_id.encode()).hexdigest(), 16) % 9) + 1
        return f"wss://kr-ss{index}.chat.naver.com/chat"

    def run(self):
        while not self._stop.is_set():
            try:
                self._session()
            except Exception as error:
                if not self._stop.is_set():
                    print(f"  채팅 연결이 끊겼습니다 ({error}). {RECONNECT_WAIT}초 후 재접속합니다.")
            if not self._stop.is_set():
                time.sleep(RECONNECT_WAIT)

    def _session(self):
        token = self._access_token()
        if not token:
            raise RuntimeError("채팅 토큰 발급 실패")
        ws = WebSocket(self._server_url(), timeout=CHAT_IDLE_LIMIT)
        try:
            ws.send_json({
                "ver": "3", "svcid": "game", "cid": self.chat_channel_id,
                "cmd": 100, "tid": 1,
                "bdy": {"uid": None, "devType": 2001, "accTkn": token, "auth": "READ"},
            })
            while not self._stop.is_set():
                message = ws.recv_json()
                command = message.get("cmd")
                if command == 0:                      # 서버 ping - 응답하지 않으면 끊긴다
                    ws.send_json({"ver": "3", "svcid": "game", "cmd": 10000})
                elif command == 93101:                # 일반 채팅
                    self._store(message.get("bdy") or [])
        finally:
            ws.close()

    def _store(self, records):
        fresh = []
        for record in records:
            if not record.get("profile") or record.get("uid") in BOT_USERS:
                continue
            fresh.append({
                "profile": record["profile"],
                "userIdHash": record.get("uid"),
                "msgTime": record.get("msgTime"),
                "content": record.get("msg") or "",
            })
        if fresh:
            with self._lock:
                self.messages.extend(fresh)


def parse_video_id(user_input):
    try:
        return int(user_input.split("?")[0].split("#")[0].rstrip("/").split("/")[-1])
    except ValueError:
        return None


def run_cli(handler, prompt):
    def run(user_input):
        try:
            handler(user_input)
        except (urllib.error.URLError, TimeoutError) as error:
            print(f"네트워크 오류: {getattr(error, 'reason', error)}")

    if sys.argv[1:]:
        for arg in sys.argv[1:]:
            run(arg)
        return

    while True:
        try:
            user_input = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input or user_input.lower() in ("q", "quit", "exit", "종료"):
            break
        run(user_input)
        print()


def crawl(user_input):
    video_id = parse_video_id(user_input)
    if video_id is None:
        print(f"유효한 영상 ID 또는 URL이 아닙니다: {user_input}")
        return
    process_video(video_id)


if __name__ == "__main__":
    run_cli(crawl, "영상 ID 또는 URL을 입력하세요 (종료: q 또는 빈 입력): ")
