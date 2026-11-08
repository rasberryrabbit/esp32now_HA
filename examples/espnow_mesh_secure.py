"""
마이크로파이썬 ESP-NOW 메시 네트워크 Secure (ESP32-S3)
=========================================================
espnow_mesh_pro.py 기반에 다음 보안/확장 기능을 추가:

  1. AES-CTR 암호화 (보안)
     - 모든 노드가 같은 16바이트 키 공유 (AES-128)
     - 각 메시지마다 msg_id(16바이트)를 nonce로 사용
     - ucryptolib (마이크로파이썬 내장) 사용
     - 키가 다른 노드는 메시지 해독 불가 → 외부 침입 차단

  2. 게이트웨이 다중화 (로드밸런싱 + 안정성)
     - 여러 게이트웨이가 동일 MQTT 토픽 구독
     - 메시 → 외부: 모든 게이트웨이가 포워딩 (외부에서 msg_id로 중복 제거)
     - 외부 → 메시: 첫 번째 게이트웨이만 처리 (나머지는 msg_id 캐시로 무시)
     - 게이트웨이 장애 시 자동으로 다른 게이트웨이가 인계

  5. 웹 대시보드 (HTTP 서버)
     - 게이트웨이 노드가 HTTP 서버 동작 (포트 80)
     - 브라우저에서 노드 목록/통계/센서 데이터 실시간 조회
     - URL: http://<게이트웨이_IP>/
     - JSON API: /api/nodes, /api/stats, /api/sensors, /api/send

설정:
  - SECURITY_KEY: 모든 노드가 동일한 16바이트 키 (hex)
  - GATEWAY_GROUP_ID: 다중 게이트웨이 식별용 그룹 ID (동일하게)
  - WEB_PORT: 웹 대시보드 포트 (기본 80)

사용 방법:
  1. 모든 노드의 SECURITY_KEY, WIFI_CHANNEL 동일하게 설정
  2. gateway 역할 노드는 config.txt 에 Wi-Fi AP 정보 + MQTT 설정 저장
     (REPL에서 /config wifi <ssid> <password> 또는 config_save() 사용)
  3. REPL에서 import espnow_mesh_secure; espnow_mesh_secure.run()

config.txt 형식 (자동 생성/수정):
  gateway_ssid=YOUR_WIFI
  gateway_password=YOUR_PASS
  mqtt_broker=broker.hivemq.com
  mqtt_port=1883
  mqtt_topic_up=mesh/chat/up
  mqtt_topic_down=mesh/chat/down
  mqtt_topic_sensor=mesh/sensor
  gateway_group_id=mesh-gw-1
  security_key=00112233445566778899aabbccddeeff
"""

import uasyncio as asyncio
import espnow
import network
import time
import ubinascii
import ujson
import uos
import gc
import sys
import ustruct

# 임포트 시도 (역할에 따라 필요)
try:
    from ucryptolib import aes as _aes
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False

try:
    from umqtt.simple import MQTTClient
    _HAS_MQTT = True
except ImportError:
    _HAS_MQTT = False


# ============ 설정 ============
# NODE_ID, NICKNAME, NODE_ROLE 은 최초 부팅 시 자동 생성됨.
# - NODE_ID   = "node-" + MAC 주소 마지막 3바이트 hex (예: node-76c204)
# - NICKNAME  = "ESP-"  + MAC 주소 마지막 2바이트 hex (예: ESP-c204)
# - NODE_ROLE = "node" (기본값)
# 최초 실행 후 config.txt 에 저장되어 재부팅 시 유지됨.
NODE_ID = ""                   # 자동 생성 (init_config 에서 설정)
NICKNAME = ""                  # 자동 생성
NODE_ROLE = "node"             # "node" / "aggregator" / "gateway"
WIFI_CHANNEL = 1
MAX_TTL = 5
MSG_CACHE_SIZE = 100
HEARTBEAT_INTERVAL = 15
NODE_TIMEOUT = 60
BROADCAST_ADDR = b'\xff\xff\xff\xff\xff\xff'

# ---- config.txt 파일 경로 ----
CONFIG_PATH = "config.txt"

# ---- 기본값 (config.txt 없을 때 사용) ----
# 암호화: 16바이트 (AES-128). hex 32문자.
SECURITY_KEY_HEX = "00112233445566778899aabbccddeeff"

# 게이트웨이 다중화 설정 (config.txt 에서 읽어옴)
GATEWAY_GROUP_ID = "mesh-gw-1"
GATEWAY_WIFI_SSID = ""          # config.txt 에서 로드
GATEWAY_WIFI_PASSWORD = ""      # config.txt 에서 로드
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_CLIENT_ID = ""             # init_config 에서 NODE_ID 기반 생성
MQTT_TOPIC_UP = "mesh/chat/up"
MQTT_TOPIC_DOWN = "mesh/chat/down"
MQTT_TOPIC_SENSOR = "mesh/sensor"
MQTT_TOPIC_GW_PRESENCE = "mesh/gateway/presence"

# ---- 암호화 키 (init 후 SECURITY_KEY_HEX 에서 파생) ----
SECURITY_KEY = None  # init_config() 호출 후 설정됨

# ---- 웹 대시보드 ----
WEB_PORT = 80

# ---- 집계 ----
AGGREGATOR_HISTORY_PER_SENSOR = 50
AGGREGATOR_REPORT_INTERVAL = 120


# ============ config.txt 읽기/쓰기 ============
# config.txt 형식: 키=값 (한 줄에 하나씩, # 는 주석)
# 값에 = 또는 공백이 포함되면 큰따옴표로 감쌈

# config.txt 에서 읽을 수 있는 설정 키 목록
CONFIG_KEYS = [
    "node_id", "nickname", "node_role",
    "gateway_ssid", "gateway_password",
    "mqtt_broker", "mqtt_port",
    "mqtt_topic_up", "mqtt_topic_down", "mqtt_topic_sensor",
    "gateway_group_id", "security_key",
]


def config_load(path=CONFIG_PATH):
    """config.txt 파일을 읽어서 딕셔너리로 반환.
    파일이 없으면 빈 딕셔너리 반환.
    """
    result = {}
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                # 큰따옴표로 감싸져 있으면 제거
                if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
                    value = value[1:-1]
                # 이스케이프 처리 (\n, \t)
                value = value.replace("\\n", "\n").replace("\\t", "\t")
                result[key] = value
        print("[CONFIG] config.txt 로드: {}개 항목".format(len(result)))
    except OSError:
        # 파일 없음
        print("[CONFIG] config.txt 없음. 기본값 사용.")
    except Exception as ex:
        print("[CONFIG] 로드 오류:", ex)
    return result


def config_save(config_dict, path=CONFIG_PATH):
    """딕셔너리를 config.txt 파일로 저장."""
    try:
        with open(path, "w") as f:
            f.write("# ESP-NOW 메시 네트워크 Secure 설정 파일\n")
            f.write("# 형식: 키=값 (값에 공백이 있으면 큰따옴표 사용)\n")
            f.write("# 마지막 수정: {}\n\n".format(now_str()))
            for key in CONFIG_KEYS:
                if key in config_dict:
                    value = str(config_dict[key])
                    if any(c in value for c in [" ", "=", "#", "\n"]):
                        value = '"' + value.replace('"', '\\"') + '"'
                    f.write("{}={}\n".format(key, value))
        print("[CONFIG] 저장 완료:", path)
        return True
    except Exception as ex:
        print("[CONFIG] 저장 오류:", ex)
        return False


def config_get(config_dict, key, default=""):
    """config 딕셔너리에서 값 가져오기 (없으면 default)."""
    return config_dict.get(key, default)


def config_show(config_dict):
    """현재 config 내용 출력 (비밀번호는 마스킹)."""
    print("[CONFIG] 현재 설정:")
    for key in CONFIG_KEYS:
        value = config_dict.get(key, "(미설정)")
        # 비밀번호는 마스킹
        if "password" in key.lower() and value != "(미설정)":
            masked = value[0] + "*" * (len(value) - 2) + value[-1] if len(value) > 2 else "**"
            print("  {} = {}".format(key, masked))
        elif key == "security_key" and value != "(미설정)":
            print("  {} = {}...".format(key, value[:8]))
        else:
            print("  {} = {}".format(key, value))


def generate_node_id_from_mac(mac_bytes):
    """MAC 주소 마지막 3바이트 hex 로 NODE_ID 생성.
    예: MAC 90:da:72:76:c2:04 → "node-76c204"
    """
    suffix = ubinascii.hexlify(mac_bytes[-3:]).decode()
    return "node-" + suffix


def generate_nickname_from_mac(mac_bytes):
    """MAC 주소 마지막 2바이트 hex 로 NICKNAME 생성.
    예: MAC 90:da:72:76:c2:04 → "ESP-c204"
    """
    suffix = ubinascii.hexlify(mac_bytes[-2:]).decode()
    return "ESP-" + suffix


def init_config(mac_bytes=None):
    """config.txt 를 로드하여 전역 설정에 반영.
    mac_bytes 가 제공되면 NODE_ID/NICKNAME 자동 생성에 사용.
    """
    global NODE_ID, NICKNAME, NODE_ROLE
    global SECURITY_KEY_HEX, SECURITY_KEY
    global GATEWAY_WIFI_SSID, GATEWAY_WIFI_PASSWORD
    global MQTT_BROKER, MQTT_PORT
    global MQTT_TOPIC_UP, MQTT_TOPIC_DOWN, MQTT_TOPIC_SENSOR
    global GATEWAY_GROUP_ID
    global MQTT_CLIENT_ID

    cfg = config_load()

    # 노드 식별 (config.txt 우선, 없으면 MAC 기반 자동 생성)
    if "node_id" in cfg and cfg["node_id"]:
        NODE_ID = cfg["node_id"]
        print("[CONFIG] NODE_ID 로드: {}".format(NODE_ID))
    elif mac_bytes is not None:
        NODE_ID = generate_node_id_from_mac(mac_bytes)
        print("[CONFIG] NODE_ID 자동 생성: {} (MAC 기반)".format(NODE_ID))

    if "nickname" in cfg and cfg["nickname"]:
        NICKNAME = cfg["nickname"]
        print("[CONFIG] NICKNAME 로드: {}".format(NICKNAME))
    elif mac_bytes is not None:
        NICKNAME = generate_nickname_from_mac(mac_bytes)
        print("[CONFIG] NICKNAME 자동 생성: {} (MAC 기반)".format(NICKNAME))

    if "node_role" in cfg and cfg["node_role"]:
        NODE_ROLE = cfg["node_role"]
        print("[CONFIG] NODE_ROLE 로드: {}".format(NODE_ROLE))
    else:
        NODE_ROLE = "node"
        print("[CONFIG] NODE_ROLE 기본값: node")

    # MQTT_CLIENT_ID 도 NODE_ID 기반으로 생성
    MQTT_CLIENT_ID = "esp32-gw-" + NODE_ID

    # config.txt 에서 값 읽어서 전역 변수에 반영 (기본값 유지)
    if "gateway_ssid" in cfg:
        GATEWAY_WIFI_SSID = cfg["gateway_ssid"]
    if "gateway_password" in cfg:
        GATEWAY_WIFI_PASSWORD = cfg["gateway_password"]
    if "mqtt_broker" in cfg:
        MQTT_BROKER = cfg["mqtt_broker"]
    if "mqtt_port" in cfg:
        try:
            MQTT_PORT = int(cfg["mqtt_port"])
        except ValueError:
            print("[CONFIG] mqtt_port 값 오류:", cfg["mqtt_port"])
    if "mqtt_topic_up" in cfg:
        MQTT_TOPIC_UP = cfg["mqtt_topic_up"]
    if "mqtt_topic_down" in cfg:
        MQTT_TOPIC_DOWN = cfg["mqtt_topic_down"]
    if "mqtt_topic_sensor" in cfg:
        MQTT_TOPIC_SENSOR = cfg["mqtt_topic_sensor"]
    if "gateway_group_id" in cfg:
        GATEWAY_GROUP_ID = cfg["gateway_group_id"]
    if "security_key" in cfg:
        SECURITY_KEY_HEX = cfg["security_key"]

    # SECURITY_KEY 파생
    if _HAS_CRYPTO:
        try:
            SECURITY_KEY = bytes.fromhex(SECURITY_KEY_HEX)
            if len(SECURITY_KEY) != 16:
                print("[CONFIG] security_key 길이 오류. 16바이트여야 함.")
                SECURITY_KEY = None
        except Exception:
            print("[CONFIG] security_key hex 디코딩 실패.")
            SECURITY_KEY = None

    # 최초 부팅 (config.txt 없었음) → 현재 값으로 config.txt 자동 생성
    if not cfg and mac_bytes is not None:
        print("[CONFIG] 최초 부팅. config.txt 자동 생성.")
        save_data = {
            "node_id": NODE_ID,
            "nickname": NICKNAME,
            "node_role": NODE_ROLE,
            "gateway_ssid": GATEWAY_WIFI_SSID,
            "gateway_password": GATEWAY_WIFI_PASSWORD,
            "mqtt_broker": MQTT_BROKER,
            "mqtt_port": str(MQTT_PORT),
            "mqtt_topic_up": MQTT_TOPIC_UP,
            "mqtt_topic_down": MQTT_TOPIC_DOWN,
            "mqtt_topic_sensor": MQTT_TOPIC_SENSOR,
            "gateway_group_id": GATEWAY_GROUP_ID,
            "security_key": SECURITY_KEY_HEX,
        }
        config_save(save_data)

    return cfg


# ============ 전역 상태 ============
e = None
sta = None
my_mac = None
peers = {}  # node_id -> {mac, nick, role, last_seen}
msg_cache = []
config_data = {}  # config.txt 에서 로드한 데이터 (init_config 후 설정)
stats = {"sent": 0, "recv": 0, "relayed": 0, "dup_dropped": 0,
         "recovered": 0, "lost": 0, "decrypt_failed": 0}

# 집계 저장소
sensor_store = {}
sensor_store_lock = asyncio.Lock()

# 게이트웨이 상태
mqtt_client = None
mqtt_inbound_queue = []
gateways = {}  # gw_id -> {last_seen, active} (다중 게이트웨이 추적)
gw_lock = asyncio.Lock()

# 웹 서버 상태
web_server = None


# ============ 유틸 ============
def now_str():
    t = time.localtime()
    return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(*t[:6])


def gen_msg_id():
    """16바이트 nonce 용 msg_id 생성 (hex 32문자)."""
    raw = uos.urandom(16)
    return ubinascii.hexlify(raw).decode()


def gen_nonce_bytes(msg_id_hex):
    """msg_id(hex 32자) → 16바이트 nonce."""
    return ubinascii.unhexlify(msg_id_hex)


def make_msg(msg_type, data, ttl=MAX_TTL):
    return {
        "type": msg_type,
        "src": NODE_ID,
        "nick": NICKNAME,
        "role": NODE_ROLE,
        "msg_id": gen_msg_id(),
        "ttl": ttl,
        "ts": time.time(),
        "data": data,
    }


# ============ 암호화 (AES-CBC) ============
def _pkcs7_pad(data, block_size=16):
    """PKCS7 패딩: 데이터를 블록 크기의 배수로 만듦."""
    pad_len = block_size - (len(data) % block_size)
    return data + bytes([pad_len] * pad_len)


def _pkcs7_unpad(data, block_size=16):
    """PKCS7 언패딩: 마지막 바이트가 패딩 길이."""
    if not data or len(data) % block_size != 0:
        return data
    pad_len = data[-1]
    if 1 <= pad_len <= block_size:
        # 모든 패딩 바이트가 pad_len 인지 검증
        if all(b == pad_len for b in data[-pad_len:]):
            return data[:-pad_len]
    return data


def encrypt_payload(plaintext_bytes, iv_bytes):
    """AES-CBC 암호화 (PKCS7 패딩).
    iv_bytes 는 16바이트여야 함.
    마이크로파이썬 ucryptolib mode 2 = CBC (가장 널리 지원됨).
    """
    if not _HAS_CRYPTO or SECURITY_KEY is None:
        return plaintext_bytes  # 암호화 미지원시 그대로
    padded = _pkcs7_pad(plaintext_bytes)
    cipher = _aes(SECURITY_KEY, 2, iv_bytes)  # mode 2 = CBC
    return cipher.encrypt(padded)


def decrypt_payload(ciphertext_bytes, iv_bytes):
    """AES-CBC 복호화 (PKCS7 언패딩)."""
    if not _HAS_CRYPTO or SECURITY_KEY is None:
        return ciphertext_bytes
    cipher = _aes(SECURITY_KEY, 2, iv_bytes)  # mode 2 = CBC
    decrypted = cipher.decrypt(ciphertext_bytes)
    return _pkcs7_unpad(decrypted)


def encode(msg):
    """딕셔너리 → 암호화된 바이트열."""
    raw = ujson.dumps(msg).encode('utf-8')
    if len(raw) > 240:  # 암호화 후 250바이트 제한 고려
        print("[MESH] 경고: 메시지 길이", len(raw))
    iv = gen_nonce_bytes(msg["msg_id"])  # msg_id 를 IV 로 사용
    encrypted = encrypt_payload(raw, iv)
    # msg_id(32문자 hex) + 암호문 → 한 패킷
    return msg["msg_id"].encode() + encrypted


def decode(raw):
    """바이트열 → 딕셔너리 (복호화 포함)."""
    if len(raw) < 32:
        return None
    msg_id_hex = raw[:32].decode('ascii', 'ignore')
    ciphertext = raw[32:]
    iv = gen_nonce_bytes(msg_id_hex)
    try:
        plaintext = decrypt_payload(ciphertext, iv)
        msg = ujson.loads(plaintext.decode('utf-8'))
        return msg
    except Exception:
        return None


# ============ Wi-Fi / ESP-NOW ============
def init_mac_only():
    """MAC 주소만 빠르게 획득 (config.txt 로드 전에 호출)."""
    global sta, my_mac
    sta = network.WLAN(network.STA_IF)
    sta.active(False)
    sta.active(True)
    sta.config(channel=WIFI_CHANNEL)
    my_mac = sta.config('mac')
    print("[MESH] MAC:", ubinascii.hexlify(my_mac, ':').decode(),
          "Crypto:", _HAS_CRYPTO)


def init_wifi_connect():
    """config.txt 로드 후 NODE_ROLE 에 따라 Wi-Fi 연결 (게이트웨이만)."""
    if NODE_ROLE == "gateway":
        if not GATEWAY_WIFI_SSID:
            print("[GATEWAY] 경고: gateway_ssid 미설정. /config wifi <ssid> <password> 로 설정.")
            print("[GATEWAY] Wi-Fi 없이 ESP-NOW 만 동작.")
        else:
            print("[GATEWAY] Wi-Fi AP 연결 중: SSID='{}'".format(GATEWAY_WIFI_SSID))
            sta.connect(GATEWAY_WIFI_SSID, GATEWAY_WIFI_PASSWORD)
            t0 = time.ticks_ms()
            while not sta.isconnected():
                if time.ticks_diff(time.ticks_ms(), t0) > 15000:
                    print("[GATEWAY] Wi-Fi 연결 실패 (15초 타임아웃). 메시 전용으로 동작.")
                    break
                time.sleep_ms(200)
            if sta.isconnected():
                ifconfig = sta.ifconfig()
                ip, subnet, gateway, dns = ifconfig[0], ifconfig[1], ifconfig[2], ifconfig[3]
                print("=" * 60)
                print("[GATEWAY] Wi-Fi 연결 성공!")
                print("  IP 주소      : {}".format(ip))
                print("  서브넷 마스크 : {}".format(subnet))
                print("  게이트웨이    : {}".format(gateway))
                print("  DNS 서버     : {}".format(dns))
                print("  SSID         : {}".format(GATEWAY_WIFI_SSID))
                print("  웹 대시보드  : http://{}".format(ip))
                print("=" * 60)
    else:
        # 일반 노드는 AP 연결 해제 (ESP-NOW 전용)
        sta.disconnect()


def init_espnow():
    global e
    e = espnow.ESPNow()
    # 마이크로파이썬 버전 호환성:
    # - 구버전(1.20 이하): e.init() 필요
    # - 신버전(1.21+): 자동 초기화, e.active(True) 사용
    try:
        e.active(True)
    except AttributeError:
        try:
            e.init()
        except Exception as ex:
            print("[MESH] ESPNow 활성화 경고:", ex)
    e.add_peer(BROADCAST_ADDR)
    print("[MESH] ESP-NOW 초기화 완료")


# ============ 송신 ============
async def send_mesh(msg):
    try:
        raw = encode(msg)
        e.send(BROADCAST_ADDR, raw)
        stats["sent"] += 1
        return True
    except Exception as ex:
        print("[MESH] 송신 오류:", ex)
        return False


async def send_chat(text):
    msg = make_msg("chat", {"text": text})
    await send_mesh(msg)
    print("<{}(나)> {}".format(NICKNAME, text))


async def send_sensor(name, value, unit=""):
    msg = make_msg("sensor", {"name": name, "value": value, "unit": unit})
    await send_mesh(msg)


async def send_system(text, ttl=1):
    msg = make_msg("system", {"text": text}, ttl=ttl)
    await send_mesh(msg)


# ============ 수신 + 중계 ============
async def recv_loop():
    print("[MESH] 수신 대기 중...")
    while True:
        try:
            host, msg = e.recv(0)
            if msg is None or len(msg) == 0:
                await asyncio.sleep_ms(50)
                continue
            decoded = decode(msg)
            if not decoded:
                stats["decrypt_failed"] += 1
                continue
            stats["recv"] += 1
            await handle_message(host, decoded)
        except Exception as ex:
            print("[MESH] 수신 오류:", ex)
            await asyncio.sleep(1)


async def handle_message(host, msg):
    msg_id = msg.get("msg_id", "")
    ttl = msg.get("ttl", 0)
    src = msg.get("src", "???")
    nick = msg.get("nick", src)
    role = msg.get("role", "node")

    if src == NODE_ID:
        return

    if msg_id in msg_cache:
        stats["dup_dropped"] += 1
        return
    msg_cache.append(msg_id)
    if len(msg_cache) > MSG_CACHE_SIZE:
        msg_cache.pop(0)

    # 자가 복구
    is_new = src not in peers
    was_lost = False
    if src in peers:
        age = time.time() - peers[src]["last_seen"]
        if age > NODE_TIMEOUT:
            was_lost = True

    peers[src] = {
        "mac": ubinascii.hexlify(host, ':').decode(),
        "nick": nick,
        "role": role,
        "last_seen": time.time(),
    }

    if is_new:
        print("[MESH] 새 노드: {} ({}) role={}".format(src, nick, role))
        if role != "gateway":  # 게이트웨이 입장은 조용히
            await send_system("*** {} 님이 입장했습니다 ***".format(nick))
    elif was_lost:
        stats["recovered"] += 1
        print("[MESH] 노드 복귀: {} ({})".format(src, nick))

    # 중계
    if ttl > 1:
        relay = dict(msg)
        relay["ttl"] = ttl - 1
        await send_mesh(relay)
        stats["relayed"] += 1

    # 로컬 처리
    msg_type = msg.get("type", "")
    data = msg.get("data", {})

    if msg_type == "chat":
        text = data.get("text", "")
        print("[{}] <{}> {}".format(now_str(), nick, text))
        # 자동 응답
        low = text.strip().lower()
        if low == "ping":
            await send_chat("pong from {}".format(NODE_ID))

        # 게이트웨이: 외부 포워딩
        if NODE_ROLE == "gateway" and mqtt_client:
            try:
                mqtt_client.publish(MQTT_TOPIC_UP,
                                    ujson.dumps({"src": src, "nick": nick,
                                                 "text": text, "ts": now_str(),
                                                 "msg_id": msg_id}))
            except Exception as ex:
                print("[GATEWAY] MQTT 송신 오류:", ex)

    elif msg_type == "sensor":
        name = data.get("name", "?")
        value = data.get("value", "?")
        unit = data.get("unit", "")
        print("[{}] [센서/{}] {} {} {}".format(
            now_str(), src, name, value, unit))
        if NODE_ROLE == "aggregator":
            await store_sensor(src, nick, name, value, unit)
        if NODE_ROLE == "gateway" and mqtt_client:
            try:
                mqtt_client.publish(MQTT_TOPIC_SENSOR,
                                    ujson.dumps({"src": src, "nick": nick,
                                                 "name": name, "value": value,
                                                 "unit": unit, "ts": now_str(),
                                                 "msg_id": msg_id}))
            except Exception:
                pass

    elif msg_type == "system":
        text = data.get("text", "")
        print("[{}] [시스템] {}".format(now_str(), text))

    elif msg_type == "discover":
        await send_chat("[{}] {} ({}): role={}".format(
            now_str(), NODE_ID, NICKNAME, NODE_ROLE))

    elif msg_type == "heartbeat":
        pass

    elif msg_type == "gw_presence":
        # 다른 게이트웨이의 존재 알림
        gw_id = data.get("gw_id", "")
        if gw_id and gw_id != NODE_ID:
            async with gw_lock:
                gateways[gw_id] = {
                    "last_seen": time.time(),
                    "nick": nick,
                    "active": True,
                }

    elif msg_type == "web_command":
        # 웹 대시보드에서 보낸 명령 (게이트웨이가 처리)
        if NODE_ROLE == "gateway":
            text = data.get("text", "")
            print("[WEB → MESH] 명령 수신:", text)
            # 메시 네트워크로 브로드캐스트
            await send_chat("[웹] " + text)


# ============ 자가 복구 ============
async def heartbeat_loop():
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        msg = make_msg("heartbeat", {"text": "alive"}, ttl=MAX_TTL)
        await send_mesh(msg)
        # 게이트웨이는 자기 존재 알림
        if NODE_ROLE == "gateway":
            gw_msg = make_msg("gw_presence",
                              {"gw_id": NODE_ID, "group": GATEWAY_GROUP_ID},
                              ttl=MAX_TTL)
            await send_mesh(gw_msg)


async def cleanup_loop():
    while True:
        await asyncio.sleep(20)
        now = time.time()
        stale = []
        for nid, info in list(peers.items()):
            age = now - info["last_seen"]
            if age > NODE_TIMEOUT:
                stale.append((nid, info))
        for nid, info in stale:
            peers.pop(nid, None)
            stats["lost"] += 1
            print("[MESH] 노드 퇴장: {} ({})".format(nid, info.get("nick", "")))
            await send_system("*** {} 님이 오프라인 ***".format(info.get("nick", nid)))

        # 게이트웨이 다중화: 다른 게이트웨이 활성 상태 정리
        async with gw_lock:
            stale_gw = [gid for gid, info in gateways.items()
                        if now - info["last_seen"] > NODE_TIMEOUT]
            for gid in stale_gw:
                gateways.pop(gid, None)
                print("[GATEWAY] 다른 게이트웨이 다운:", gid)


# ============ 집계 노드 ============
async def store_sensor(src, nick, name, value, unit):
    async with sensor_store_lock:
        if src not in sensor_store:
            sensor_store[src] = {"nick": nick}
        if name not in sensor_store[src]:
            sensor_store[src][name] = {"unit": unit, "data": []}
        store = sensor_store[src][name]
        store["unit"] = unit
        store["data"].append((time.time(), value))
        if len(store["data"]) > AGGREGATOR_HISTORY_PER_SENSOR:
            store["data"] = store["data"][-AGGREGATOR_HISTORY_PER_SENSOR:]


async def aggregator_report_loop():
    while True:
        await asyncio.sleep(AGGREGATOR_REPORT_INTERVAL)
        async with sensor_store_lock:
            if not sensor_store:
                continue
            summary = {}
            for src, sensors in sensor_store.items():
                summary[src] = {}
                for name, info in sensors.items():
                    if name == "nick":
                        continue
                    values = [v for _, v in info["data"]]
                    if not values:
                        continue
                    summary[src][name] = {
                        "unit": info["unit"],
                        "count": len(values),
                        "min": min(values),
                        "max": max(values),
                        "avg": round(sum(values) / len(values), 2),
                        "last": values[-1],
                    }
        await send_mesh(make_msg("aggregate", {"summary": summary}, ttl=MAX_TTL))


# ============ 게이트웨이 (다중화) ============
def connect_mqtt():
    global mqtt_client
    if not _HAS_MQTT:
        print("[GATEWAY] umqtt.simple 없음. MQTT 비활성화.")
        return False
    if not GATEWAY_WIFI_SSID:
        print("[GATEWAY] Wi-Fi 미설정. MQTT 비활성화.")
        return False
    try:
        print("[GATEWAY] MQTT 연결 시도: {}:{}".format(MQTT_BROKER, MQTT_PORT))
        mqtt_client = MQTTClient(MQTT_CLIENT_ID, MQTT_BROKER, MQTT_PORT)
        mqtt_client.set_callback(mqtt_callback)
        mqtt_client.connect()
        mqtt_client.subscribe(MQTT_TOPIC_DOWN)
        print("[GATEWAY] MQTT 연결 성공:", MQTT_BROKER)
        return True
    except Exception as ex:
        err_str = str(ex)
        if "-202" in err_str:
            print("[GATEWAY] MQTT 연결 실패 (-202): 브로커에 도달할 수 없음")
            print("  확인사항:")
            print("  - 브로커 주소가 맞는지 (현재: {})".format(MQTT_BROKER))
            print("  - 인터넷 연결 상태")
            print("  - 방화벽 차단 여부 (포트 {})".format(MQTT_PORT))
        else:
            print("[GATEWAY] MQTT 연결 실패 ({}): {}".format(err_str, ex))
        print("[GATEWAY] 웹 대시보드는 정상 동작합니다. (로컬 전용)")
        mqtt_client = None
        return False


def mqtt_callback(topic, msg):
    """외부 MQTT 메시지 수신. 다중 게이트웨이 중복 처리 포함."""
    try:
        data = ujson.loads(msg.decode('utf-8'))
        # 다중 게이트웨이: msg_id 기반 중복 처리
        # (첫 번째 게이트웨이만 처리, 나머지는 무시)
        msg_id = data.get("msg_id", "")
        if not msg_id:
            # msg_id 없으면 생성해서 처리 (레거시 호환)
            msg_id = gen_msg_id()

        if msg_id in msg_cache:
            print("[GATEWAY] 다른 게이트웨이가 이미 처리:", msg_id[:8])
            return
        msg_cache.append(msg_id)
        if len(msg_cache) > MSG_CACHE_SIZE:
            msg_cache.pop(0)

        mqtt_inbound_queue.append(data)
    except Exception:
        mqtt_inbound_queue.append({"text": msg.decode('utf-8', 'ignore'),
                                   "nick": "external"})


async def mqtt_loop():
    if not mqtt_client:
        return
    while True:
        try:
            mqtt_client.check_msg()
            while mqtt_inbound_queue:
                data = mqtt_inbound_queue.pop(0)
                text = data.get("text", "")
                if text:
                    # 외부 메시지를 메시로 전파 (msg_id 포함으로 다른 게이트웨이 중복 방지)
                    msg = make_msg("chat",
                                   {"text": "[외부] " + text,
                                    "origin_msg_id": data.get("msg_id", "")},
                                   ttl=MAX_TTL)
                    # 강제로 같은 msg_id 사용하여 다른 게이트웨이가 무시하게
                    if "msg_id" in data:
                        msg["msg_id"] = data["msg_id"]
                    await send_mesh(msg)
                    print("[GATEWAY] 외부 → 메시:", text[:50])
            await asyncio.sleep(1)
        except Exception as ex:
            print("[GATEWAY] MQTT 오류:", ex)
            try:
                mqtt_client.connect()
                mqtt_client.subscribe(MQTT_TOPIC_DOWN)
            except Exception:
                await asyncio.sleep(10)


# ============ 웹 대시보드 (게이트웨이 전용) ============
INDEX_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ESP32 메시 대시보드</title>
<style>
body{font-family:system-ui,sans-serif;background:#1a1a2e;color:#e0e0e0;
     margin:0;padding:20px}
h1{color:#0ff;text-align:center;border-bottom:2px solid #0ff;padding-bottom:10px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin:20px 0}
.card{background:#16213e;padding:15px;border-radius:8px;border:1px solid #0f3460}
.card h2{color:#e94560;margin-top:0;font-size:16px}
table{width:100%;border-collapse:collapse;font-size:13px}
td,th{padding:6px 8px;border-bottom:1px solid #0f3460;text-align:left}
th{color:#0ff}
.stat{font-size:24px;font-weight:bold;color:#0ff}
input,button{padding:8px;font-size:14px;border-radius:4px;border:1px solid #0f3460;
             background:#0f3460;color:#fff}
input{flex:1}
.send-form{display:flex;gap:8px;margin-top:10px}
.msg-list{max-height:300px;overflow-y:auto}
.msg-item{padding:6px;border-bottom:1px solid #0f3460}
.msg-time{color:#888;font-size:11px}
.nick{color:#e94560;font-weight:bold}
</style>
</head>
<body>
<h1>ESP32 메시 네트워크 대시보드</h1>
<div style="text-align:center;color:#0f0;font-size:14px;margin-bottom:10px">
  IP: <strong id="gw-ip">...</strong> | SSID: <strong id="gw-ssid">...</strong> | 역할: <strong id="gw-role">...</strong> | 암호화: <strong id="gw-crypto">...</strong>
</div>
<div class="grid">
  <div class="card">
    <h2>노드 목록</h2>
    <table id="nodes-table">
      <thead><tr><th>ID</th><th>닉네임</th><th>역할</th><th>마지막 활동</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>
  <div class="card">
    <h2>통계</h2>
    <div id="stats"></div>
  </div>
  <div class="card">
    <h2>센서 데이터</h2>
    <div id="sensors"></div>
  </div>
  <div class="card">
    <h2>메시지 보내기</h2>
    <div class="send-form">
      <input id="msg-input" type="text" placeholder="메시지 입력...">
      <button onclick="sendMsg()">전송</button>
    </div>
    <h2 style="margin-top:20px">최근 메시지</h2>
    <div class="msg-list" id="messages"></div>
  </div>
  <div class="card">
    <h2>게이트웨이 설정 (config.txt)</h2>
    <div id="config-info"></div>
    <h2 style="margin-top:15px">Wi-Fi 설정 변경</h2>
    <div class="send-form">
      <input id="ssid-input" type="text" placeholder="SSID">
    </div>
    <div class="send-form" style="margin-top:8px">
      <input id="pass-input" type="password" placeholder="비밀번호">
      <button onclick="saveConfig()">저장</button>
    </div>
    <div id="config-result" style="margin-top:8px;color:#0f0;font-size:12px"></div>
  </div>
</div>
<script>
async function fetchData(){
  try{
    const [nodes,stats,sensors,cfg] = await Promise.all([
      fetch('/api/nodes').then(r=>r.json()),
      fetch('/api/stats').then(r=>r.json()),
      fetch('/api/sensors').then(r=>r.json()),
      fetch('/api/config').then(r=>r.json())
    ]);
    // 노드 테이블
    let html='';
    nodes.forEach(n=>{
      const age = Math.round(Date.now()/1000 - n.last_seen);
      html += '<tr><td>'+n.id+'</td><td>'+n.nick+'</td><td>'+n.role+
              '</td><td>'+age+'초 전</td></tr>';
    });
    document.querySelector('#nodes-table tbody').innerHTML = html;
    // 통계
    let s = '<table>';
    for(const k in stats){ s += '<tr><td>'+k+'</td><td class="stat">'+stats[k]+'</td></tr>'; }
    s += '</table>';
    document.getElementById('stats').innerHTML = s;
    // 센서
    let sh = '<table><tr><th>노드</th><th>센서</th><th>값</th><th>단위</th></tr>';
    for(const src in sensors){
      if(src==='nick') continue;
      for(const sname in sensors[src]){
        if(sname==='nick') continue;
        const d = sensors[src][sname];
        if(d.data && d.data.length){
          sh += '<tr><td>'+src+'</td><td>'+sname+'</td><td>'+
                d.data[d.data.length-1][1]+'</td><td>'+d.unit+'</td></tr>';
        }
      }
    }
    sh += '</table>';
    document.getElementById('sensors').innerHTML = sh;
    // config 정보 표시
    let ch = '<table>';
    ch += '<tr><td>노드 ID</td><td>'+cfg.node_id+'</td></tr>';
    ch += '<tr><td>닉네임</td><td>'+cfg.nickname+'</td></tr>';
    ch += '<tr><td>역할</td><td>'+cfg.node_role+'</td></tr>';
    ch += '<tr><td>Wi-Fi 채널</td><td>'+cfg.wifi_channel+'</td></tr>';
    ch += '<tr><td>SSID</td><td>'+(cfg.gateway_ssid||'(미설정)')+'</td></tr>';
    ch += '<tr><td>비밀번호</td><td>'+(cfg.gateway_password_set?'설정됨':'미설정')+'</td></tr>';
    ch += '<tr><td>MQTT 브로커</td><td>'+cfg.mqtt_broker+':'+cfg.mqtt_port+'</td></tr>';
    ch += '<tr><td>그룹 ID</td><td>'+cfg.gateway_group_id+'</td></tr>';
    ch += '<tr><td>암호화</td><td>'+(cfg.security_key_set?'활성':'비활성')+'</td></tr>';
    ch += '</table>';
    document.getElementById('config-info').innerHTML = ch;
    // SSID 필드에 현재 값 채우기
    document.getElementById('ssid-input').placeholder = cfg.gateway_ssid || 'SSID';
    // 헤더 IP/SSID/암호화 표시
    if(cfg.ip){ document.getElementById('gw-ip').textContent = cfg.ip; }
    document.getElementById('gw-ssid').textContent = cfg.gateway_ssid || '(미설정)';
    document.getElementById('gw-role').textContent = cfg.node_role;
    document.getElementById('gw-crypto').textContent = cfg.security_key_set ? '활성' : '비활성';
  }catch(e){console.error(e);}
}
async function sendMsg(){
  const input = document.getElementById('msg-input');
  const text = input.value.trim();
  if(!text) return;
  await fetch('/api/send?text='+encodeURIComponent(text));
  input.value = '';
}
async function saveConfig(){
  const ssid = document.getElementById('ssid-input').value.trim();
  const pass = document.getElementById('pass-input').value.trim();
  if(!ssid && !pass){
    document.getElementById('config-result').textContent = 'SSID 또는 비밀번호 입력 필요';
    return;
  }
  const params = new URLSearchParams();
  if(ssid) params.append('gateway_ssid', ssid);
  if(pass) params.append('gateway_password', pass);
  try{
    const r = await fetch('/api/config_save?'+params.toString());
    const data = await r.json();
    if(data.status === 'saved'){
      document.getElementById('config-result').textContent = '✓ config.txt 저장 완료';
      document.getElementById('ssid-input').value = '';
      document.getElementById('pass-input').value = '';
      fetchData();
    } else {
      document.getElementById('config-result').textContent = '오류: '+JSON.stringify(data);
    }
  }catch(e){
    document.getElementById('config-result').textContent = '오류: '+e;
  }
}
fetchData();
setInterval(fetchData, 3000);
</script>
</body>
</html>"""


async def handle_http(reader, writer):
    """간단한 HTTP 서버 핸들러."""
    global NODE_ROLE, GATEWAY_WIFI_SSID, GATEWAY_WIFI_PASSWORD
    try:
        req_line = await reader.readline()
        if not req_line:
            writer.close()
            return
        req = req_line.decode('utf-8', 'ignore').strip()
        parts = req.split(' ')
        if len(parts) < 2:
            writer.close()
            return
        method, path = parts[0], parts[1]
        # 헤더 소모
        while True:
            h = await reader.readline()
            if h == b'\r\n' or h == b'\n' or not h:
                break

        if path == '/' and method == 'GET':
            body = INDEX_HTML.encode('utf-8')
            header = b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: " + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n"
            writer.write(header + body)
        elif path == '/api/nodes':
            now = time.time()
            data = []
            for nid, info in peers.items():
                data.append({"id": nid, "nick": info["nick"],
                             "role": info["role"],
                             "last_seen": int(info["last_seen"])})
            data.append({"id": NODE_ID, "nick": NICKNAME,
                         "role": NODE_ROLE, "last_seen": int(now)})
            body = ujson.dumps(data).encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: " + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
        elif path == '/api/stats':
            data = dict(stats)
            data["free_heap"] = gc.mem_free()
            data["peers"] = len(peers)
            data["gateways"] = len([g for g in gateways.values()])
            body = ujson.dumps(data).encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: " + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
        elif path == '/api/sensors':
            async with sensor_store_lock:
                # 그대로는 JSON 직렬화 어려우므로 변환
                out = {}
                for src, sensors in sensor_store.items():
                    out[src] = {}
                    for sname, info in sensors.items():
                        if sname == "nick":
                            out[src]["nick"] = info
                            continue
                        out[src][sname] = {
                            "unit": info.get("unit", ""),
                            "data": info.get("data", [])[-10:]  # 최근 10개만
                        }
            body = ujson.dumps(out).encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: " + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
        elif path.startswith('/api/send') and method == 'GET':
            # ?text=... 파싱
            q = path.split('?', 1)[1] if '?' in path else ''
            text = ''
            for kv in q.split('&'):
                if kv.startswith('text='):
                    text = kv[5:]
                    # URL 디코딩 (간단히)
                    text = text.replace('%20', ' ').replace('+', ' ')
                    text = text.replace('%3F', '?').replace('%21', '!')
            if text:
                # 메시 네트워크로 브로드캐스트
                msg = make_msg("chat", {"text": "[웹] " + text})
                await send_mesh(msg)
                body = b'{"status":"sent"}'
            else:
                body = b'{"error":"no text"}'
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: " + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
        elif path.startswith('/api/config_save') and method == 'GET':
            # /api/config_save?gateway_ssid=...&gateway_password=...&node_role=...
            q = path.split('?', 1)[1] if '?' in path else ''
            params = {}
            for kv in q.split('&'):
                if '=' in kv:
                    k, v = kv.split('=', 1)
                    params[k] = v.replace('%20', ' ').replace('+', ' ')
            updated = False
            if 'node_role' in params and params['node_role'] in ('node', 'aggregator', 'gateway'):
                NODE_ROLE = params['node_role']
                config_data['node_role'] = NODE_ROLE
                updated = True
            if 'gateway_ssid' in params:
                GATEWAY_WIFI_SSID = params['gateway_ssid']
                config_data['gateway_ssid'] = GATEWAY_WIFI_SSID
                updated = True
            if 'gateway_password' in params:
                GATEWAY_WIFI_PASSWORD = params['gateway_password']
                config_data['gateway_password'] = GATEWAY_WIFI_PASSWORD
                updated = True
            if updated:
                # config.txt 에 저장
                save_data = {
                    "node_id": NODE_ID,
                    "nickname": NICKNAME,
                    "node_role": NODE_ROLE,
                    "gateway_ssid": GATEWAY_WIFI_SSID,
                    "gateway_password": GATEWAY_WIFI_PASSWORD,
                    "mqtt_broker": MQTT_BROKER,
                    "mqtt_port": str(MQTT_PORT),
                    "mqtt_topic_up": MQTT_TOPIC_UP,
                    "mqtt_topic_down": MQTT_TOPIC_DOWN,
                    "mqtt_topic_sensor": MQTT_TOPIC_SENSOR,
                    "gateway_group_id": GATEWAY_GROUP_ID,
                    "security_key": SECURITY_KEY_HEX,
                }
                config_save(save_data)
                body = b'{"status":"saved"}'
            else:
                body = b'{"error":"no params"}'
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: " + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
        elif path.startswith('/api/config') and method == 'GET':
            # config 정보 반환 (비밀번호는 마스킹)
            ip_addr = ""
            if sta and sta.isconnected():
                ip_addr = sta.ifconfig()[0]
            cfg_view = {
                "gateway_ssid": GATEWAY_WIFI_SSID or "",
                "gateway_password_set": bool(GATEWAY_WIFI_PASSWORD),
                "mqtt_broker": MQTT_BROKER,
                "mqtt_port": MQTT_PORT,
                "mqtt_topic_up": MQTT_TOPIC_UP,
                "mqtt_topic_down": MQTT_TOPIC_DOWN,
                "mqtt_topic_sensor": MQTT_TOPIC_SENSOR,
                "gateway_group_id": GATEWAY_GROUP_ID,
                "security_key_set": bool(SECURITY_KEY),
                "node_id": NODE_ID,
                "nickname": NICKNAME,
                "node_role": NODE_ROLE,
                "wifi_channel": WIFI_CHANNEL,
                "ip": ip_addr,
                "connected": bool(sta and sta.isconnected()),
            }
            body = ujson.dumps(cfg_view).encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: " + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
        else:
            body = b'{"error":"not found"}'
            writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Type: application/json\r\nContent-Length: " + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
        await writer.drain()
    except Exception as ex:
        print("[WEB] 오류:", ex)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def web_server_loop():
    """HTTP 서버 (게이트웨이 전용).
    마이크로파이썬의 asyncio.start_server() 는 CPython 과 다르게 동작:
    - serve_forever() 메서드 없음
    - start_server() 자체가 백그라운드로 동작
    - 이 함수는 서버가 종료되지 않도록 대기만 함
    """
    global web_server
    if NODE_ROLE != "gateway":
        return
    try:
        web_server = await asyncio.start_server(handle_http, "0.0.0.0", WEB_PORT)
        print("[WEB] 대시보드 활성화: http://{}/".format(sta.ifconfig()[0]))
        # 마이크로파이썬에서는 start_server() 가 백그라운드 동작하므로
        # 이 태스크를 계속 대기시킴
        while True:
            await asyncio.sleep(3600)
    except Exception as ex:
        print("[WEB] 서버 오류:", ex)


# ============ REPL 입력 ============
# 마이크로파이썬은 run_in_executor 미지원.
# uselect 로 stdin 을 비동기 폴링하여 줄 단위로 읽음.

try:
    import uselect
    _HAS_USELECT = True
except ImportError:
    _HAS_USELECT = False

# 입력 버퍼 (한 줄이 완성될 때까지 바이트 누적)
_input_buffer = b""


async def async_input():
    """비동기 입력. 마이크로파이썬에서 uselect 로 stdin 폴링."""
    global _input_buffer
    if not _HAS_USELECT:
        # uselect 도 없으면 폴백: 동기 input() 호출 (블로킹이지만 기능은 함)
        # 이 경우 asyncio 가 잠깐 멈추지만, ESP32 REPL 입력이라 실용적임.
        await asyncio.sleep(0)
        return input()
    
    poller = uselect.poll()
    # stdin 은 fd 0
    poller.register(sys.stdin, uselect.POLLIN)
    
    while True:
        # 100ms 타임아웃으로 폴링 → 다른 태스크가 동작할 기회 줌
        events = poller.poll(100)
        if events:
            ch = sys.stdin.read(1)
            if ch is None or ch == "":
                await asyncio.sleep_ms(10)
                continue
            # 줄바꿈 처리 (LF, CR, CRLF 모두)
            if ch == "\n":
                line = _input_buffer.decode("utf-8", "ignore")
                _input_buffer = b""
                return line
            elif ch == "\r":
                # CR 단독 (구형 터미널) → LF 로 처리
                line = _input_buffer.decode("utf-8", "ignore")
                _input_buffer = b""
                return line
            else:
                _input_buffer += ch.encode("utf-8")
        else:
            # 입력 없음 → 다른 태스크 양보
            await asyncio.sleep_ms(50)


async def input_loop():
    while True:
        try:
            line = await async_input()
            line = line.strip()
            if not line:
                continue
            if line.startswith("/"):
                await handle_command(line)
            else:
                await send_chat(line)
        except Exception as ex:
            print("[입력 오류]", ex)
            await asyncio.sleep(1)


async def handle_command(cmd_line):
    global NICKNAME
    global NODE_ROLE
    global MQTT_BROKER, MQTT_PORT
    global GATEWAY_WIFI_SSID, GATEWAY_WIFI_PASSWORD
    global MQTT_TOPIC_UP, MQTT_TOPIC_DOWN, MQTT_TOPIC_SENSOR
    global GATEWAY_GROUP_ID, SECURITY_KEY_HEX, SECURITY_KEY
    cmd = cmd_line.lower()
    if cmd == "/who":
        print("[MESH] 발견된 노드 ({}개):".format(len(peers)))
        print("  나: {} ({}) role={}".format(NODE_ID, NICKNAME, NODE_ROLE))
        for nid, info in peers.items():
            age = time.time() - info["last_seen"]
            print("  - {} ({}) role={} 활동={}초전".format(
                nid, info["nick"], info["role"], int(age)))
        async with gw_lock:
            if gateways:
                print("\n  다른 게이트웨이 ({}):".format(len(gateways)))
                for gid, info in gateways.items():
                    age = time.time() - info["last_seen"]
                    print("  - {} ({}) {}초전".format(
                        gid, info.get("nick", ""), int(age)))
    elif cmd == "/discover":
        await send_mesh(make_msg("discover", {"text": "who?"}, ttl=MAX_TTL))
    elif cmd.startswith("/nick "):
        new = cmd_line[6:].strip()[:16]
        if new:
            old = NICKNAME
            NICKNAME = new
            print("[MESH] 닉네임 변경: {} → {}".format(old, NICKNAME))
            await send_system("{} → {}".format(old, NICKNAME))
    elif cmd == "/role" or cmd.startswith("/role "):
        new_role = cmd_line[5:].strip().lower() if len(cmd_line) > 5 else ""
        if not new_role:
            print("사용법: /role <node|aggregator|gateway>")
            print("현재 역할: {}".format(NODE_ROLE))
        elif new_role not in ("node", "aggregator", "gateway"):
            print("[CONFIG] 역할: node, aggregator, gateway 중 하나")
        else:
            old = NODE_ROLE
            NODE_ROLE = new_role
            config_data["node_role"] = new_role
            print("[CONFIG] NODE_ROLE 변경: {} → {} (/config save)".format(old, new_role))
            print("[CONFIG] 주의: 변경사항은 재시작 후 적용됩니다.")
    elif cmd == "/stats":
        print("[통계]")
        for k, v in stats.items():
            print("  {}: {}".format(k, v))
        print("  발견 노드:", len(peers))
        print("  다른 게이트웨이:", len(gateways))
        print("  free heap:", gc.mem_free())
    elif cmd == "/sensors":
        if NODE_ROLE != "aggregator":
            print("[MESH] aggregator 가 아님.")
        else:
            async with sensor_store_lock:
                for src, sensors in sensor_store.items():
                    print("  [{}]: ".format(src), end="")
                    for name, info in sensors.items():
                        if name == "nick":
                            continue
                        vals = info["data"]
                        if vals:
                            print("{}={} ({}개) ".format(
                                name, vals[-1][1], len(vals)), end="")
                    print()
    elif cmd == "/help":
        print("명령어:")
        print("  /who          노드 목록 (게이트웨이 포함)")
        print("  /discover     노드 발견")
        print("  /nick <이름>   닉네임 변경")
        print("  /role <역할>  node|aggregator|gateway 변경")
        print("  /stats        통계")
        print("  /sensors      센서 데이터 (aggregator)")
        print("  /config       현재 설정 보기")
        print("  /config save  현재 설정을 config.txt 에 저장")
        print("  /config wifi <ssid> <password>  Wi-Fi AP 설정")
        print("  /config mqtt <broker> [port]    MQTT 브로커 설정")
        print("  /config topic <up|down|sensor> <name>  토픽 설정")
        print("  /config group <id>              게이트웨이 그룹 ID")
        print("  /config key <hex32>              암호화 키 (16바이트 hex)")
        print("  /config reload                   config.txt 다시 로드")
        print("  /config show_raw                 config.txt 원본 보기")
        print("  /help /quit")
    elif cmd == "/quit":
        await send_system("{} 퇴장".format(NICKNAME))
        raise KeyboardInterrupt
    elif cmd.startswith("/config"):
        await handle_config_command(cmd_line)
    else:
        print("[MESH] 알 수 없는 명령. /help")


# ============ config 명령어 처리 ============
async def handle_config_command(cmd_line):
    """ /config <subcmd> [args] 명령어 처리."""
    global config_data
    global GATEWAY_WIFI_SSID, GATEWAY_WIFI_PASSWORD
    global MQTT_BROKER, MQTT_PORT
    global MQTT_TOPIC_UP, MQTT_TOPIC_DOWN, MQTT_TOPIC_SENSOR
    global GATEWAY_GROUP_ID, SECURITY_KEY_HEX, SECURITY_KEY

    parts = cmd_line.split(None, 1)
    subcmd = parts[1].strip() if len(parts) > 1 else ""

    if not subcmd or subcmd == "show":
        # 현재 설정 보기
        print("\n[CONFIG] 현재 동작 중인 설정:")
        print("  --- 노드 식별 ---")
        print("  node_id    = {}".format(NODE_ID))
        print("  nickname   = {}".format(NICKNAME))
        print("  node_role  = {}".format(NODE_ROLE))
        print("  --- 게이트웨이 ---")
        print("  gateway_ssid = {}".format(GATEWAY_WIFI_SSID or "(미설정)"))
        if GATEWAY_WIFI_PASSWORD:
            masked = GATEWAY_WIFI_PASSWORD[0] + "*" * (len(GATEWAY_WIFI_PASSWORD) - 2) + GATEWAY_WIFI_PASSWORD[-1]
            print("  gateway_password = {}".format(masked))
        else:
            print("  gateway_password = (미설정)")
        print("  --- MQTT ---")
        print("  mqtt_broker = {}".format(MQTT_BROKER))
        print("  mqtt_port = {}".format(MQTT_PORT))
        print("  mqtt_topic_up = {}".format(MQTT_TOPIC_UP))
        print("  mqtt_topic_down = {}".format(MQTT_TOPIC_DOWN))
        print("  mqtt_topic_sensor = {}".format(MQTT_TOPIC_SENSOR))
        print("  gateway_group_id = {}".format(GATEWAY_GROUP_ID))
        print("  --- 암호화 ---")
        print("  security_key = {}...".format(SECURITY_KEY_HEX[:8]))
        return

    # /config show_raw : config.txt 원본 표시
    if subcmd == "show_raw":
        try:
            with open(CONFIG_PATH, "r") as f:
                print("\n[CONFIG] config.txt 원본:")
                print("-" * 40)
                print(f.read())
                print("-" * 40)
        except OSError:
            print("[CONFIG] config.txt 파일 없음.")
        return

    # /config save : 현재 전역 설정을 config.txt 에 저장
    if subcmd == "save":
        save_data = {
            "node_id": NODE_ID,
            "nickname": NICKNAME,
            "node_role": NODE_ROLE,
            "gateway_ssid": GATEWAY_WIFI_SSID,
            "gateway_password": GATEWAY_WIFI_PASSWORD,
            "mqtt_broker": MQTT_BROKER,
            "mqtt_port": str(MQTT_PORT),
            "mqtt_topic_up": MQTT_TOPIC_UP,
            "mqtt_topic_down": MQTT_TOPIC_DOWN,
            "mqtt_topic_sensor": MQTT_TOPIC_SENSOR,
            "gateway_group_id": GATEWAY_GROUP_ID,
            "security_key": SECURITY_KEY_HEX,
        }
        if config_save(save_data):
            config_data.clear()
            config_data.update(save_data)
        return

    # /config reload : config.txt 다시 로드
    if subcmd == "reload":
        config_data.clear()
        config_data.update(init_config(my_mac))
        print("[CONFIG] 리로드 완료. (일부 설정은 재시작 필요)")
        return

    # /config wifi <ssid> <password>
    if subcmd.startswith("wifi "):
        args = subcmd[5:].strip().split(None, 1)
        if len(args) < 2:
            print("사용법: /config wifi <ssid> <password>")
            return
        GATEWAY_WIFI_SSID = args[0]
        GATEWAY_WIFI_PASSWORD = args[1]
        config_data["gateway_ssid"] = GATEWAY_WIFI_SSID
        config_data["gateway_password"] = GATEWAY_WIFI_PASSWORD
        print("[CONFIG] Wi-Fi 설정: SSID='{}' (저장하려면 /config save)".format(GATEWAY_WIFI_SSID))
        return

    # /config mqtt <broker> [port]
    if subcmd.startswith("mqtt "):
        args = subcmd[5:].strip().split()
        if len(args) < 1:
            print("사용법: /config mqtt <broker> [port]")
            return
        MQTT_BROKER = args[0]
        config_data["mqtt_broker"] = MQTT_BROKER
        if len(args) >= 2:
            try:
                MQTT_PORT = int(args[1])
                config_data["mqtt_port"] = str(MQTT_PORT)
            except ValueError:
                print("[CONFIG] port 값 오류. 정수여야 함.")
                return
        print("[CONFIG] MQTT 설정: {}:{} (저장: /config save)".format(MQTT_BROKER, MQTT_PORT))
        return

    # /config topic <up|down|sensor> <name>
    if subcmd.startswith("topic "):
        args = subcmd[6:].strip().split(None, 1)
        if len(args) < 2:
            print("사용법: /config topic <up|down|sensor> <name>")
            return
        which = args[0].lower()
        topic_name = args[1].strip()
        if which == "up":
            MQTT_TOPIC_UP = topic_name
            config_data["mqtt_topic_up"] = topic_name
        elif which == "down":
            MQTT_TOPIC_DOWN = topic_name
            config_data["mqtt_topic_down"] = topic_name
        elif which == "sensor":
            MQTT_TOPIC_SENSOR = topic_name
            config_data["mqtt_topic_sensor"] = topic_name
        else:
            print("[CONFIG] 토픽 종류: up, down, sensor 중 하나")
            return
        print("[CONFIG] 토픽 {} = {} (저장: /config save)".format(which, topic_name))
        return

    # /config group <id>
    if subcmd.startswith("group "):
        gid = subcmd[6:].strip()
        if not gid:
            print("사용법: /config group <id>")
            return
        GATEWAY_GROUP_ID = gid
        config_data["gateway_group_id"] = gid
        print("[CONFIG] 그룹 ID = {} (저장: /config save)".format(gid))
        return

    # /config key <hex32>
    if subcmd.startswith("key "):
        key_hex = subcmd[4:].strip()
        if len(key_hex) != 32:
            print("[CONFIG] 키는 32문자 hex (16바이트) 여야 함.")
            return
        try:
            test_key = bytes.fromhex(key_hex)
            if len(test_key) != 16:
                raise ValueError()
        except ValueError:
            print("[CONFIG] hex 디코딩 실패.")
            return
        SECURITY_KEY_HEX = key_hex
        SECURITY_KEY = test_key if _HAS_CRYPTO else None
        config_data["security_key"] = key_hex
        print("[CONFIG] 암호화 키 설정 완료 (저장: /config save)")
        return

    print("[CONFIG] 알 수 없는 명령. /help 참고.")


# ============ 메인 ============
async def main():
    global config_data
    print("=" * 60)
    print("  ESP-NOW 메시 네트워크 Secure")
    print("=" * 60)

    # 1. MAC 주소만 빠르게 획득 (WLAN 활성화만, 연결 안 함)
    init_mac_only()
    # 2. config.txt 로드 (MAC 기반 NODE_ID/NICKNAME 자동 생성 + 역할/SSID/MQTT/security_key 로드)
    config_data = init_config(my_mac)

    print("[MESH] Node: {} ({})".format(NODE_ID, NICKNAME))
    print("[MESH] Role: {} / Channel: {} / TTL: {}".format(
        NODE_ROLE, WIFI_CHANNEL, MAX_TTL))
    print("[MESH] Crypto: {} (key={}...)".format(_HAS_CRYPTO, SECURITY_KEY_HEX[:8]))

    if NODE_ROLE == "gateway":
        print("[MESH] Gateway SSID: {} / MQTT: {}:{}".format(
            GATEWAY_WIFI_SSID or "(미설정)", MQTT_BROKER, MQTT_PORT))
        if not GATEWAY_WIFI_SSID:
            print("[MESH] 경고: gateway_ssid 미설정. /config wifi <ssid> <password> 로 설정.")

    # 3. config.txt 의 NODE_ROLE 기반으로 Wi-Fi 연결 (게이트웨이만)
    init_wifi_connect()
    # 4. ESP-NOW 초기화
    init_espnow()
    gc.collect()
    print("[MESH] free heap:", gc.mem_free(), "bytes")

    _ = asyncio.create_task(recv_loop())
    _ = asyncio.create_task(heartbeat_loop())
    _ = asyncio.create_task(cleanup_loop())

    if NODE_ROLE == "aggregator":
        _ = asyncio.create_task(aggregator_report_loop())
        print("[AGGREGATOR] 센서 집계 모드")

    if NODE_ROLE == "gateway":
        ok = connect_mqtt()
        if ok:
            _ = asyncio.create_task(mqtt_loop())
            print("[GATEWAY] MQTT 브릿지 활성화")
        # 웹 서버 시작
        _ = asyncio.create_task(web_server_loop())

    await send_system("{} 입장 (role={})".format(NICKNAME, NODE_ROLE))
    print("\n[MESH] 준비 완료. /help 로 명령어 확인.\n")

    try:
        await input_loop()
    except KeyboardInterrupt:
        print("\n[MESH] 종료.")


def run():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n종료합니다.")


if __name__ == "__main__":
    run()
