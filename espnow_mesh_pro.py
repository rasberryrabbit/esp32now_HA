"""
마이크로파이썬 ESP-NOW 메시 네트워크 Pro (ESP32-S3)
====================================================
기본 espnow_mesh.py 에 다음 기능을 추가한 버전:

  2. 게이트웨이 노드 (Gateway) - 다중화 지원
     - Wi-Fi AP(인터넷)와 ESP-NOW 메시 동시 연결
     - 수신한 메시지를 MQTT 브로커로 포워딩
     - 외부에서 들어온 명령을 메시 네트워크로 전파
     - 여러 게이트웨이가 동일 MQTT 토픽 구독 → msg_id 로 중복 제거
     - 게이트웨이 장애 시 다른 게이트웨이가 자동 인계

  3. 센서 데이터 집계 (Aggregator)
     - 모든 노드의 센서 데이터 수집
     - 시계열 저장 (PSRAM 활용, 최근 N개)
     - 주기적 요약 통계 (평균/최소/최대) 브로드캐스트

  5. 네트워크 자가 복구 (Self-healing)
     - 주기적 heartbeat (15초) 로 노드 활동 감시
     - 60초 이상 응답 없는 노드는 자동 퇴장 처리
     - 노드 재등장 시 자동 복구 및 알림

  config.txt 설정 파일 (모든 변경사항 영속화)
     - gateway_ssid / gateway_password
     - mqtt_broker / mqtt_port / mqtt_topic_*
     - gateway_group_id
     - REPL: /config wifi <ssid> <pass>, /config save, /config reload
     - 웹: /api/config, /api/config_save

  웹 대시보드 (HTTP 서버, 게이트웨이 전용)
     - 브라우저에서 노드 목록/통계/센서/config 실시간 조회
     - URL: http://<게이트웨이_IP>/
     - JSON API: /api/nodes, /api/stats, /api/sensors, /api/config, /api/send

노드 역할 (cfg.NODE_ROLE):
  - "node"       일반 노드 (채팅 + 센서 송수신)
  - "gateway"    외부 인터넷과 브릿지 (Wi-Fi AP 연결 필요 + 웹 대시보드)

사용 방법:
  1. 각 보드마다 cfg.NODE_ID, cfg.NICKNAME, cfg.NODE_ROLE 설정
  2. gateway 역할 보드는 config.txt 에 Wi-Fi AP 정보 + MQTT 설정 저장
     (REPL: /config wifi <ssid> <password> → /config save)
  3. 모든 보드의 cfg.WIFI_CHANNEL 동일 (기본 1)
  4. REPL에서 import espnow_mesh_pro; espnow_mesh_pro.run()

config.txt 형식 (자동 생성/수정):
  gateway_ssid=YOUR_WIFI
  gateway_password=YOUR_PASS
  mqtt_broker=broker.hivemq.com
  mqtt_port=1883
  mqtt_topic_up=mesh/chat/up
  mqtt_topic_down=mesh/chat/down
  mqtt_topic_sensor=mesh/sensor
  gateway_group_id=mesh-gw-1
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
import mesh_config
from mesh_config import cfg

# 임포트 시도 (역할에 따라 필요)
try:
    from umqtt.simple import MQTTClient
    _HAS_MQTT = True
except ImportError:
    _HAS_MQTT = False


# ============ 설정 (클래스 기반) ============
# 마이크로파이썬에서 모듈 간 전역 변수 참조가 불안정하므로
# 클래스 인스턴스의 속성으로 관리 (객체는 참조로 전달됨)


# ============ 전역 상태 ============
e = None
sta = None
my_mac = None
mqtt_client = None
web_server = None
gw_lock = asyncio.Lock()


# ============ 데이터 저장소 (mesh_state.py 에서 import) ============
from mesh_state import (
    Stats, PeerRegistry, MessageCache, SensorStore, DeviceRegistry,
    AutomationRules, LastSensorValues, RuleLog, RuleGroups, SunTimes,
    GatewayRegistry, MqttInboundQueue, ConfigData,
    stats, peers, msg_cache, sensor_store, device_registry,
    automation_rules, last_sensor_values, rule_log, rule_groups,
    sun_times, gateways, mqtt_inbound_queue, config_data,
    _automation_rules, _rule_groups, _device_registry,
    _rule_log, _last_sensor_values, _sun_times, _RULE_LOG_MAX,
    now_str, _current_time_int, _current_weekday,
)


# ============ 유틸 ============
def get_node_id():
    return cfg.NODE_ID

def get_nickname():
    return cfg.NICKNAME

def get_node_role():
    return cfg.NODE_ROLE

def get_node_info():
    return cfg.NODE_ID, cfg.NICKNAME, cfg.NODE_ROLE

def set_node_id(nid):
    cfg.NODE_ID = nid

def set_nickname(nick):
    cfg.NICKNAME = nick


def url_decode(s):
    """URL 디코딩 (마이크로파이썬 호환, 한글 UTF-8 퍼센트 인코딩 지원).

    %XX 형식의 퍼센트 인코딩을 원래 바이트로 변환 후 UTF-8 디코딩.
    + 는 공백으로 변환.
    """
    if not s:
        return ""
    # + → 공백
    s = s.replace('+', ' ')
    # %XX → 바이트
    result = bytearray()
    i = 0
    while i < len(s):
        if s[i] == '%' and i + 2 < len(s) + 1 and i + 2 < len(s):
            try:
                result.append(int(s[i+1:i+3], 16))
                i += 3
                continue
            except ValueError:
                pass
        result.append(ord(s[i]))
        i += 1
    try:
        return bytes(result).decode('utf-8')
    except Exception:
        return bytes(result).decode('utf-8', 'ignore')


def gen_msg_id():
    return "{:x}{:04x}".format(time.ticks_ms() & 0xFFFFFFFF,
                                uos.urandom(2)[0] << 8 | uos.urandom(2)[1])


def make_msg(msg_type, data, ttl=cfg.MAX_TTL):
    return {
        "type": msg_type,
        "src": cfg.NODE_ID,
        "nick": cfg.NICKNAME,
        "role": cfg.NODE_ROLE,
        "msg_id": gen_msg_id(),
        "ttl": ttl,
        "ts": time.time(),
        "data": data,
    }


def encode(msg):
    return ujson.dumps(msg).encode('utf-8')


def decode(raw):
    try:
        return ujson.loads(raw.decode('utf-8'))
    except Exception:
        return None


# ============ Wi-Fi / ESP-NOW 초기화 ============
# AP 모드 설정 (인터넷 연결 실패 시 웹 대시보드 접근용)
AP_FALLBACK_SSID_PREFIX = "ESP32-Mesh-"
AP_FALLBACK_PASSWORD = "mesh1234"  # 최소 8자리 필요
AP_FALLBACK_TIMEOUT_SEC = 15


def init_mac_only():
    """MAC 주소만 빠르게 획득 (config.txt 로드 전에 호출).
    WLAN 인터페이스만 활성화하고 채널만 설정. 연결은 나중에."""
    global sta, my_mac
    sta = network.WLAN(network.STA_IF)
    sta.active(False)
    sta.active(True)
    sta.config(channel=cfg.WIFI_CHANNEL)
    my_mac = sta.config('mac')
    print("[MESH] MAC:", ubinascii.hexlify(my_mac, ':').decode())


def _start_ap_fallback():
    """Wi-Fi 연결 실패 시 AP 모드로 전환하여 웹 대시보드 제공.

    ESP32 가 자체 Wi-Fi AP 를 생성:
      SSID: ESP32-Mesh-XXXX (MAC 마지막 4자리)
      Password: mesh1234
    사용자가 이 AP 에 연결 후 http://192.168.4.1/ 로 대시보드 접속 가능.
    /config 페이지에서 올바른 Wi-Fi 설정 후 재부팅하면 인터넷 연결 가능.
    """
    global sta
    # MAC 주소 마지막 2바이트로 SSID 생성 (예: ESP32-Mesh-c204)
    mac_suffix = ubinascii.hexlify(my_mac[-2:]).decode()
    ap_ssid = AP_FALLBACK_SSID_PREFIX + mac_suffix

    print("[GATEWAY] AP 모드로 전환 (인터넷 연결 실패 폴백)")
    print("[GATEWAY]   SSID: {}".format(ap_ssid))
    print("[GATEWAY]   Password: {}".format(AP_FALLBACK_PASSWORD))

    # STA 인터페이스 비활성화 후 AP 인터페이스 활성화
    try:
        sta.active(False)
    except Exception:
        pass

    try:
        ap = network.WLAN(network.AP_IF)
        ap.active(True)
        # AP 설정: SSID, password, channel, auth mode
        ap.config(essid=ap_ssid, password=AP_FALLBACK_PASSWORD,
                  channel=cfg.WIFI_CHANNEL, authmode=network.AUTH_WPA2_PSK)
        # AP 가 활성화될 때까지 대기
        t0 = time.ticks_ms()
        while not ap.active():
            if time.ticks_diff(time.ticks_ms(), t0) > 5000:
                print("[GATEWAY] AP 활성화 실패 (5초 타임아웃)")
                return False
            time.sleep_ms(100)
        # AP 의 IP 주소 확인 (기본 192.168.4.1)
        ifconfig = ap.ifconfig()
        ip = ifconfig[0]
        print("=" * 60)
        print("[GATEWAY] AP 모드 활성화 완료!")
        print("  AP SSID     : {}".format(ap_ssid))
        print("  AP Password : {}".format(AP_FALLBACK_PASSWORD))
        print("  IP 주소     : {}".format(ip))
        print("  웹 대시보드 : http://{}".format(ip))
        print("  /config 에서 Wi-Fi 설정 후 /config save → 재부팅")
        print("=" * 60)
        # cfg 에 AP 모드 정보 저장 (웹에서 표시용)
        cfg.IP_ADDR = ip
        cfg.AP_MODE = True
        cfg.AP_SSID = ap_ssid
        return True
    except Exception as ex:
        print("[GATEWAY] AP 모드 전환 오류:", ex)
        return False


def init_wifi_connect():
    """config.txt 로드 후 cfg.NODE_ROLE 에 따라 Wi-Fi 연결 (게이트웨이만).

    게이트웨이:
      1. 설정된 Wi-Fi AP 에 연결 시도 (15초 타임아웃)
      2. 연결 실패 시 AP 모드로 전환 (웹 대시보드 접근용)
    """
    # AP 모드 플래그 초기화
    cfg.AP_MODE = False
    cfg.AP_SSID = ""

    if cfg.NODE_ROLE == "gateway":
        if not cfg.GATEWAY_WIFI_SSID:
            print("[GATEWAY] 경고: gateway_ssid 미설정. AP 모드로 전환.")
            print("[GATEWAY] /config 페이지에서 Wi-Fi 설정 후 저장하세요.")
            _start_ap_fallback()
        else:
            print("[GATEWAY] Wi-Fi AP 연결 중: SSID='{}'".format(cfg.GATEWAY_WIFI_SSID))
            sta.connect(cfg.GATEWAY_WIFI_SSID, cfg.GATEWAY_WIFI_PASSWORD)
            t0 = time.ticks_ms()
            connected = False
            while not sta.isconnected():
                if time.ticks_diff(time.ticks_ms(), t0) > 15000:
                    print("[GATEWAY] Wi-Fi 연결 실패 (15초 타임아웃).")
                    break
                time.sleep_ms(200)
            if sta.isconnected():
                connected = True
                ifconfig = sta.ifconfig()
                ip, subnet, gateway, dns = ifconfig[0], ifconfig[1], ifconfig[2], ifconfig[3]
                print("=" * 60)
                print("[GATEWAY] Wi-Fi 연결 성공!")
                print("  IP 주소      : {}".format(ip))
                print("  서브넷 마스크 : {}".format(subnet))
                print("  게이트웨이    : {}".format(gateway))
                print("  DNS 서버     : {}".format(dns))
                print("  SSID         : {}".format(cfg.GATEWAY_WIFI_SSID))
                print("  웹 대시보드  : http://{}".format(ip))
                print("=" * 60)
                cfg.IP_ADDR = ip
                # NTP 동기화 (Wi-Fi 연결 직후 1회)
                sync_ntp()

            if not connected:
                # Wi-Fi 연결 실패 → AP 모드로 전환
                print("[GATEWAY] 인터넷 연결 실패. AP 모드로 전환합니다.")
                _start_ap_fallback()
    else:
        # 일반 노드는 AP 연결 해제 (ESP-NOW 전용)
        sta.disconnect()


def init_espnow():
    """ESP-NOW 초기화."""
    global e
    e = espnow.ESPNow()
    # 마이크로파이썬 버전 호환성
    try:
        e.active(True)
    except AttributeError:
        try:
            e.init()
        except Exception as ex:
            print("[MESH] ESPNow 활성화 경고:", ex)
    e.add_peer(cfg.BROADCAST_ADDR)
    print("[MESH] ESP-NOW 초기화 완료")


# ============ 송신 ============
async def send_mesh(msg):
    if e is None:
        return False
    try:
        raw = encode(msg)
        if len(raw) > 250:
            print("[MESH] 경고: 메시지 길이", len(raw), "바이트")
        e.send(cfg.BROADCAST_ADDR, raw)
        stats.inc("sent")
        return True
    except Exception as ex:
        print("[MESH] 송신 오류:", ex)
        return False


async def send_chat(text):
    msg = make_msg("chat", {"text": text})
    await send_mesh(msg)
    print("<{}(나)> {}".format(cfg.NICKNAME, text))


async def send_sensor(name, value, unit=""):
    msg = make_msg("sensor", {"name": name, "value": value, "unit": unit})
    await send_mesh(msg)
    # 자기 자신의 센서 데이터도 sensor_store 에 저장
    # (게이트웨이는 자기가 보낸 ESP-NOW 메시지를 수신하지 못하므로)
    sensor_store.store(cfg.NODE_ID, cfg.NICKNAME, name, value, unit)
    # 게이트웨이: 자동화 규칙 평가 (자기 센서 데이터로)
    if cfg.NODE_ROLE == "gateway":
        try:
            await automation_rules.check({name: value})
        except Exception as ex:
            print("[AUTO] 평가 오류:", ex)


def store_sensor(node_id, nick, name, value, unit=""):
    """센서 데이터를 sensor_store 에 직접 저장 (비동기 X).

    sensor_runner.send_to_mesh() 에서 호출.
    """
    sensor_store.store(node_id, nick, name, value, unit)


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
                await asyncio.sleep_ms(100)
                continue
            decoded = decode(msg)
            if not decoded:
                continue
            stats.inc("recv")
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

    if src == cfg.NODE_ID:
        return

    # 중복 필터링
    if msg_cache.contains(msg_id):
        stats.inc("dup_dropped")
        return
    msg_cache.add(msg_id, cfg.MSG_CACHE_SIZE)

    # 자가 복구: 노드 재등장 감지
    is_new = not peers.contains(src)
    was_lost = False
    if peers.contains(src):
        age = time.time() - peers.get(src)["last_seen"]
        if age > cfg.NODE_TIMEOUT:
            was_lost = True

    peers.add(src, {
        "mac": ubinascii.hexlify(host, ':').decode(),
        "nick": nick,
        "role": role,
        "last_seen": time.time(),
    })

    # 자가 복구 알림
    if is_new:
        print("[MESH] 새 노드 발견: {} ({}) role={}".format(src, nick, role))
        if role != "gateway":
            await send_system("*** {} 님이 입장했습니다 ***".format(nick))
    elif was_lost:
        stats.inc("recovered")
        print("[MESH] 노드 복구: {} ({})".format(src, nick))

    # 중계
    if ttl > 1:
        relay = dict(msg)
        relay["ttl"] = ttl - 1
        await send_mesh(relay)
        stats.inc("relayed")

    # 로컬 처리
    msg_type = msg.get("type", "")
    data = msg.get("data", {})

    if msg_type == "chat":
        text = data.get("text", "")
        print("[{}] <{}> {}".format(now_str(), nick, text))
        # 자동 응답
        low = text.strip().lower()
        if low == "ping":
            await send_chat("pong from {}".format(cfg.NODE_ID))
        elif low in ("hello", "hi", "안녕"):
            await send_chat("안녕하세요! {}".format(cfg.NICKNAME))

        # 게이트웨이: 외부로 포워딩
        if cfg.NODE_ROLE == "gateway" and mqtt_client:
            try:
                mqtt_client.publish(cfg.MQTT_TOPIC_UP,
                                    ujson.dumps({"src": src, "nick": nick,
                                                 "text": text, "ts": now_str(),
                                                 "msg_id": msg_id}))
            except Exception as ex:
                print("[GATEWAY] MQTT 송신 오류:", ex)

    elif msg_type == "sensor":
        name = data.get("name", "?")
        value = data.get("value", "?")
        unit = data.get("unit", "")

        # 집계 노드 + 게이트웨이 모두 sensor_store 에 저장
        if cfg.NODE_ROLE == "gateway":
            sensor_store.store(src, nick, name, value, unit)

        # 게이트웨이: 자동화 규칙 평가 + 외부 포워딩
        if cfg.NODE_ROLE == "gateway":
            # 자동화 규칙 평가 (센서 이름을 키로 사용)
            try:
                sensor_data = {name: value}
                await automation_rules.check(sensor_data)
            except Exception as ex:
                print("[AUTO] 평가 오류:", ex)

            if mqtt_client:
                try:
                    mqtt_client.publish(cfg.MQTT_TOPIC_SENSOR,
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
            now_str(), cfg.NODE_ID, cfg.NICKNAME, cfg.NODE_ROLE))

    elif msg_type == "heartbeat":
        pass  # 조용히 처리 (peers 이미 갱신됨)

    elif msg_type == "gw_presence":
        # 다른 게이트웨이의 존재 알림
        gw_id = data.get("gw_id", "")
        if gw_id and gw_id != cfg.NODE_ID:
            async with gw_lock:
                gateways.add(gw_id, {
                    "last_seen": time.time(),
                    "nick": nick,
                    "active": True,
                })

    elif msg_type == "web_command":
        # 웹 대시보드에서 보낸 명령 (게이트웨이가 처리)
        if cfg.NODE_ROLE == "gateway":
            text = data.get("text", "")
            print("[WEB → MESH] 명령 수신:", text)
            await send_chat("[웹] " + text)

    elif msg_type == "device_info":
        # 다른 노드의 장치 정보 (센서/GPIO 목록)
        # 게이트웨이가 수집하여 /api/devices 응답에 사용
        if cfg.NODE_ROLE == "gateway":
            devices = data.get("devices", [])
            device_registry.add(src, {
                "nick": nick,
                "role": role,
                "last_seen": time.time(),
                "devices": devices,
            })
            print("[{}] [장치정보] {} ({}): {} 개 장치".format(
                now_str(), src, nick, len(devices)))

    elif msg_type == "device_info_req":
        # 게이트웨이가 원격 노드의 장치 상태를 즉시 갱신하기 위해 보낸 요청
        # 대상 노드는 자신의 장치 상태를 다시 브로드캐스트
        target = data.get("target", "")
        # target 이 명시된 경우 해당 노드만 응답, 빈 문자열이면 모든 노드 응답
        if not target or target == cfg.NODE_ID:
            print("[{}] [장치정보요청] {} → 장치 상태 브로드캐스트".format(
                now_str(), src))
            # gpio_control 모듈이 있으면 즉시 브로드캐스트
            try:
                import gpio_control
                await gpio_control.gm.broadcast_device_info()
            except Exception as ex:
                print("[MESH] 장치 정보 브로드캐스트 오류:", ex)


# ============ 자가 복구 ============
# NTP 동기화 설정
NTP_SERVER = "pool.ntp.org"
NTP_TIMEZONE_OFFSET = 9 * 3600  # KST (UTC+9)
NTP_SYNC_INTERVAL = 7 * 24 * 3600  # 1주일마다 재동기화
_ntp_last_sync = 0  # 마지막 동기화 시각 (time.time())


def sync_ntp():
    """NTP 서버에서 시간 동기화 (동기식, 인터넷 연결 필요).

    Wi-Fi 연결 성공 후 호출. 실패해도 계속 동작 (내부 RTC 사용).
    """
    global _ntp_last_sync
    if not sta or not sta.isconnected():
        return False
    try:
        import ntptime
        ntptime.host = NTP_SERVER
        ntptime.settime()  # UTC 시간으로 RTC 설정
        # 타임존 적용 (KST = UTC+9)
        try:
            import time as _time
            _time.settimezone(NTP_TIMEZONE_OFFSET)
        except Exception:
            # settimezone 미지원 시 수동 offset 은 nodes age 계산에서 문제 없음
            pass
        _ntp_last_sync = time.time()
        t = time.localtime()
        print("[NTP] 동기화 성공: {:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(*t[:6]))
        return True
    except OSError as ex:
        print("[NTP] 동기화 실패 (네트워크):", ex)
        return False
    except Exception as ex:
        print("[NTP] 동기화 실패:", ex)
        return False


async def ntp_sync_loop():
    """NTP 재동기화 루프.

    1. 초기 동기화 실패 시 1분 간격으로 재시도 (성공할 때까지)
    2. 성공 후에는 1주일마다 재동기화
    MicroPython asyncio.sleep() 의 ticks_ms 오버플로우 방지를 위해
    1시간 단위로 대기하면서 카운트 (168시간 = 1주일).
    """
    # 1단계: 초기 동기화 (1분 간격 재시도)
    while True:
        if sta and sta.isconnected():
            if sync_ntp():
                break  # 성공 → 주기 모드로 전환
        await asyncio.sleep(60)  # 1분 후 재시도

    # 2단계: 주기적 재동기화 (1주일마다)
    HOUR_SEC = 3600  # 1시간 (안전한 대기 단위)
    hours_left = NTP_SYNC_INTERVAL // HOUR_SEC  # 1주일 = 168시간
    while True:
        await asyncio.sleep(HOUR_SEC)
        hours_left -= 1
        if hours_left <= 0:
            hours_left = NTP_SYNC_INTERVAL // HOUR_SEC
            # 인터넷 연결된 경우에만 시도
            if sta and sta.isconnected():
                sync_ntp()


async def heartbeat_loop():
    """주기적으로 heartbeat 전송 + 게이트웨이 존재 알림."""
    while True:
        await asyncio.sleep(cfg.HEARTBEAT_INTERVAL)
        await send_mesh(make_msg("heartbeat", {"text": "alive"}, ttl=cfg.MAX_TTL))
        if cfg.NODE_ROLE == "gateway":
            gw_msg = make_msg("gw_presence",
                              {"gw_id": cfg.NODE_ID, "group": cfg.GATEWAY_GROUP_ID},
                              ttl=cfg.MAX_TTL)
            await send_mesh(gw_msg)


async def cleanup_loop():
    """응답 없는 노드 자동 퇴장 처리 + 다른 게이트웨이 감시."""
    while True:
        await asyncio.sleep(60)
        now = time.time()
        # 일반 노드 정리
        stale = []
        for nid, info in list(peers.items()):
            age = now - info["last_seen"]
            if age > cfg.NODE_TIMEOUT:
                stale.append((nid, info))
        for nid, info in stale:
            peers.pop(nid, None)
            stats.inc("lost")
            print("[MESH] 노드 퇴장: {} ({})".format(nid, info.get("nick", "")))
            await send_system("*** {} 님이 오프라인 ***".format(info.get("nick", nid)))

        # 게이트웨이 다중화: 다른 게이트웨이 활성 상태 정리
        async with gw_lock:
            stale_gw = [gid for gid, info in gateways.items()
                        if now - info["last_seen"] > cfg.NODE_TIMEOUT]
            for gid in stale_gw:
                gateways.pop(gid)
                print("[GATEWAY] 다른 게이트웨이 다운:", gid)


# ============ 게이트웨이 (다중화) ============
def connect_mqtt():
    """MQTT 브로커 연결 (config.txt 의 mqtt_enabled 가 true 일 때만)."""
    global mqtt_client
    if not cfg.MQTT_ENABLED:
        print("[GATEWAY] MQTT 비활성화 (config.txt: mqtt_enabled=false)")
        return False
    if not _HAS_MQTT:
        print("[GATEWAY] umqtt.simple 모듈 없음. MQTT 비활성화.")
        return False
    if not cfg.GATEWAY_WIFI_SSID:
        print("[GATEWAY] Wi-Fi 미설정. MQTT 비활성화.")
        return False
    try:
        print("[GATEWAY] MQTT 연결 시도: {}:{}".format(cfg.MQTT_BROKER, cfg.MQTT_PORT))
        mqtt_client = MQTTClient(cfg.MQTT_CLIENT_ID, cfg.MQTT_BROKER, cfg.MQTT_PORT)
        mqtt_client.set_callback(mqtt_callback)
        mqtt_client.connect()
        mqtt_client.subscribe(cfg.MQTT_TOPIC_DOWN)
        print("[GATEWAY] MQTT 연결 성공:", cfg.MQTT_BROKER)
        return True
    except Exception as ex:
        # MQTT 오류 코드:
        # -202: 네트워크 타임아웃 (브로커 접근 불가, DNS 실패 등)
        # -1: 연결 거부
        err_str = str(ex)
        if "-202" in err_str:
            print("[GATEWAY] MQTT 연결 실패 (-202): 브로커에 도달할 수 없음")
            print("  확인사항:")
            print("  - 브로커 주소가 맞는지 (현재: {})".format(cfg.MQTT_BROKER))
            print("  - 인터넷 연결 상태")
            print("  - 방화벽 차단 여부 (포트 {})".format(cfg.MQTT_PORT))
        else:
            print("[GATEWAY] MQTT 연결 실패 ({}): {}".format(err_str, ex))
        print("[GATEWAY] 웹 대시보드는 정상 동작합니다. (로컬 전용)")
        mqtt_client = None
        return False


def mqtt_callback(topic, msg):
    """외부 MQTT 메시지 수신. 다중 게이트웨이 중복 처리 포함."""
    try:
        data = ujson.loads(msg.decode('utf-8'))
        msg_id = data.get("msg_id", "")
        if not msg_id:
            msg_id = gen_msg_id()

        # 다중 게이트웨이: msg_id 로 중복 처리
        if msg_cache.contains(msg_id):
            print("[GATEWAY] 다른 게이트웨이가 이미 처리:", msg_id[:8])
            return
        msg_cache.add(msg_id, cfg.MSG_CACHE_SIZE)

        mqtt_inbound_queue.append(data)
    except Exception:
        mqtt_inbound_queue.append({"text": msg.decode('utf-8', 'ignore'),
                                   "nick": "external"})


async def mqtt_loop():
    """MQTT keepalive 및 인바운드 메시지 처리."""
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
                    msg = make_msg("chat", {"text": "[외부] " + text}, ttl=cfg.MAX_TTL)
                    if "msg_id" in data:
                        msg["msg_id"] = data["msg_id"]
                    await send_mesh(msg)
                    print("[GATEWAY] 외부 → 메시:", text[:50])
            await asyncio.sleep(1)
        except Exception as ex:
            print("[GATEWAY] MQTT 오류:", ex)
            try:
                mqtt_client.connect()
                mqtt_client.subscribe(cfg.MQTT_TOPIC_DOWN)
            except Exception:
                await asyncio.sleep(10)


# ============ 웹 대시보드 (게이트웨이 전용) ============
# HTML 페이지는 web_pages.py 모듈에서 import (경량화 + .mpy 컴파일 지원)
try:
    import web_pages
    INDEX_HTML = web_pages.INDEX_HTML
    STATS_HTML = web_pages.STATS_HTML
    CONFIG_HTML = web_pages.CONFIG_HTML
except ImportError:
    # web_pages.py 가 없으면 최소 페이지 사용
    INDEX_HTML = "<html><body><h1>Mesh Dashboard</h1><p>web_pages.py 가 없습니다.</p></body></html>"
    STATS_HTML = "<html><body><h1>Stats</h1><p>web_pages.py 가 없습니다.</p></body></html>"
    CONFIG_HTML = "<html><body><h1>Config</h1><p>web_pages.py 가 없습니다.</p></body></html>"


# ============ Stats 페이지 ============



# ============ Config 페이지 ============



async def handle_http(reader, writer):
    """간단한 HTTP 서버 핸들러 (각 연결별로 독립 실행)."""
    try:
        # 요청 처리를 별도 코루틴으로 분리하여 다중 연결 동시 처리 지원
        await _handle_http_impl(reader, writer)
    except Exception as ex:
        print("[WEB] 오류:", ex)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def _handle_http_impl(reader, writer):
    """HTTP 요청 처리 구현 (handle_http 에서 호출)."""
    # cfg.GATEWAY_WIFI_SSID/PASSWORD 은 cfg 객체 사용
    try:
        req_line = await reader.readline()
        if not req_line:
            return
        req = req_line.decode('utf-8', 'ignore').strip()
        parts = req.split(' ')
        if len(parts) < 2:
            return
        method, path = parts[0], parts[1]
        # 헤더 소모
        while True:
            h = await reader.readline()
            if h == b'\r\n' or h == b'\n' or not h:
                break

        # 응답 헤더 빌더 (항상 close - MicroPython asyncio는 keep-alive 미지원)
        def build_header(content_type, length):
            return (b"HTTP/1.1 200 OK\r\nContent-Type: " + content_type.encode() +
                    b"\r\nCache-Control: no-cache\r\nContent-Length: " + str(length).encode() +
                    b"\r\nConnection: close\r\n\r\n")

        # 간단한 핑 엔드포인트 (연결 테스트용)
        if path == '/api/ping':
            body = b'{"ok":true}'
            writer.write(build_header("application/json", len(body)) + body)
            await writer.drain()
            return

        elif path == '/' and method == 'GET':
            body = INDEX_HTML.encode('utf-8')
            writer.write(build_header("text/html; charset=utf-8", len(body)))
            await writer.drain()
            # 분할 전송 (ESP32 socket 버퍼 한계 대응)
            chunk_size = 2048
            for i in range(0, len(body), chunk_size):
                writer.write(body[i:i + chunk_size])
                await writer.drain()
            return

        elif path.startswith('/stats') and not path.startswith('/api/'):
            body = STATS_HTML.encode('utf-8')
            writer.write(build_header("text/html; charset=utf-8", len(body)))
            await writer.drain()
            chunk_size = 2048
            for i in range(0, len(body), chunk_size):
                writer.write(body[i:i + chunk_size])
                await writer.drain()
            return

        elif path.startswith('/config') and not path.startswith('/api/'):
            body = CONFIG_HTML.encode('utf-8')
            writer.write(build_header("text/html; charset=utf-8", len(body)))
            await writer.drain()
            chunk_size = 2048
            for i in range(0, len(body), chunk_size):
                writer.write(body[i:i + chunk_size])
                await writer.drain()
            return

        elif path.startswith('/api/nodes'):
            now = time.time()
            data = []
            for nid, info in peers.items():
                data.append({"id": nid, "nick": info["nick"],
                             "role": info["role"],
                             "age_sec": max(0, int(now - info["last_seen"]))})
            data.append({"id": cfg.NODE_ID, "nick": cfg.NICKNAME,
                         "role": cfg.NODE_ROLE, "age_sec": 0})
            body = ujson.dumps(data).encode()
            writer.write(build_header("application/json", len(body)) + body)
            await writer.drain()
            return

        elif path.startswith('/api/stats'):
            data = stats.to_dict()
            data["free_heap"] = gc.mem_free()
            data["peers"] = peers.count()
            data["gateways"] = gateways.count()
            data["chip_temp"] = _last_chip_temp
            data["cpu_freq_mhz"] = _current_cpu_freq // 1000000
            body = ujson.dumps(data).encode()
            writer.write(build_header("application/json", len(body)) + body)
            await writer.drain()
            return

        elif path.startswith('/api/sensors'):
            # sensor_store 에서 읽기 + sensor_runner.sm._buffer 에서 최신값 보완
            sensor_out = sensor_store.get_json()
            # sensor_runner.sm 에서 최신 버퍼값 추가/갱신
            try:
                import sensor_runner
                import mesh_config; _cfg = mesh_config.cfg
                _snid = _cfg.NODE_ID
                _snick = _cfg.NICKNAME
                if _snid not in sensor_out:
                    sensor_out[_snid] = {"nick": _snick}
                _sm = sensor_runner.sm
                for _sname, _hist in _sm._buffer.items():
                    if _hist:
                        _sunit = _sm.devices.get(_sname, {}).get("unit", "")
                        # _buffer 의 최신값으로 갱신 (sensor_store 보다 최신일 수 있음)
                        sensor_out[_snid][_sname] = {
                            "unit": _sunit,
                            "data": [(t, v) for t, v in _hist[-10:]]
                        }
            except Exception:
                pass
            body = ujson.dumps(sensor_out).encode()
            writer.write(build_header("application/json", len(body)) + body)
            await writer.drain()
            return
        elif path.startswith('/api/config_save') and method == 'GET':
            q = path.split('?', 1)[1] if '?' in path else ''
            params = {}
            for kv in q.split('&'):
                if '=' in kv:
                    k, v = kv.split('=', 1)
                    params[k] = url_decode(v)
            updated = False
            if 'gateway_ssid' in params:
                cfg.GATEWAY_WIFI_SSID = params['gateway_ssid']
                config_data['gateway_ssid'] = cfg.GATEWAY_WIFI_SSID
                updated = True
            if 'gateway_password' in params:
                cfg.GATEWAY_WIFI_PASSWORD = params['gateway_password']
                config_data['gateway_password'] = cfg.GATEWAY_WIFI_PASSWORD
                updated = True
            if updated:
                save_data = {
                    "gateway_ssid": cfg.GATEWAY_WIFI_SSID,
                    "gateway_password": cfg.GATEWAY_WIFI_PASSWORD,
                    "mqtt_broker": cfg.MQTT_BROKER,
                    "mqtt_port": str(cfg.MQTT_PORT),
                    "mqtt_topic_up": cfg.MQTT_TOPIC_UP,
                    "mqtt_topic_down": cfg.MQTT_TOPIC_DOWN,
                    "mqtt_topic_sensor": cfg.MQTT_TOPIC_SENSOR,
                    "gateway_group_id": cfg.GATEWAY_GROUP_ID,
                }
                config_save(save_data)
                body = b'{"status":"saved"}'
            else:
                body = b'{"error":"no params"}'
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nCache-Control: no-cache\r\nContent-Length: " + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
            await writer.drain()
            return
        elif path.startswith('/api/settime') and method == 'GET':
            # /api/settime?time=2026-11-08T14:30:00
            q = path.split('?', 1)[1] if '?' in path else ''
            params = {}
            for kv in q.split('&'):
                if '=' in kv:
                    k, v = kv.split('=', 1)
                    params[k] = url_decode(v)
            time_str = params.get('time', '')
            if time_str:
                try:
                    # 형식: YYYY-MM-DDTHH:MM:SS 또는 YYYY-MM-DD HH:MM:SS
                    time_str = time_str.replace('T', ' ')
                    parts = time_str.replace('-', ' ').replace(':', ' ').split()
                    if len(parts) >= 6:
                        year = int(parts[0])
                        month = int(parts[1])
                        day = int(parts[2])
                        hour = int(parts[3])
                        minute = int(parts[4])
                        second = int(parts[5])
                        # RTC 설정 (마이크로파이썬 machine.RTC)
                        try:
                            import machine
                            rtc = machine.RTC()
                            rtc.datetime((year, month, day, 0, hour, minute, second, 0))
                        except Exception:
                            pass
                        # NTP 동기화 상태 업데이트
                        global _ntp_last_sync
                        _ntp_last_sync = time.time()
                        t = time.localtime()
                        body = ujson.dumps({
                            "status": "ok",
                            "set_time": "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(*t[:6]),
                        }).encode()
                        print("[TIME] 수동 설정: {:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(*t[:6]))
                    else:
                        body = b'{"error":"invalid time format"}'
                except Exception as ex:
                    body = ujson.dumps({"status": "error", "error": str(ex)}).encode()
            else:
                # 현재 시간 반환
                t = time.localtime()
                body = ujson.dumps({
                    "current_time": "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(*t[:6]),
                    "ntp_synced": _ntp_last_sync > 0,
                }).encode()
            writer.write(build_header("application/json", len(body)) + body)
            await writer.drain()
            return
        elif path.startswith('/api/config') and method == 'GET':
            # IP 주소 조회 (연결된 경우 또는 AP 모드)
            ip_addr = ""
            connected = False
            if sta and sta.isconnected():
                ip_addr = sta.ifconfig()[0]
                connected = True
            elif getattr(cfg, "AP_MODE", False):
                ip_addr = getattr(cfg, "IP_ADDR", "")
            cfg_view = {
                "gateway_ssid": cfg.GATEWAY_WIFI_SSID or "",
                "gateway_password_set": bool(cfg.GATEWAY_WIFI_PASSWORD),
                "mqtt_broker": cfg.MQTT_BROKER,
                "mqtt_port": cfg.MQTT_PORT,
                "mqtt_topic_up": cfg.MQTT_TOPIC_UP,
                "mqtt_topic_down": cfg.MQTT_TOPIC_DOWN,
                "mqtt_topic_sensor": cfg.MQTT_TOPIC_SENSOR,
                "gateway_group_id": cfg.GATEWAY_GROUP_ID,
                "node_id": cfg.NODE_ID,
                "nickname": cfg.NICKNAME,
                "node_role": cfg.NODE_ROLE,
                "wifi_channel": cfg.WIFI_CHANNEL,
                "ip": ip_addr,
                "connected": connected,
                "ap_mode": getattr(cfg, "AP_MODE", False),
                "ap_ssid": getattr(cfg, "AP_SSID", ""),
            }
            body = ujson.dumps(cfg_view).encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nCache-Control: no-cache\r\nContent-Length: " + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
            await writer.drain()
            return
        elif path.startswith('/api/send') and method == 'GET':
            q = path.split('?', 1)[1] if '?' in path else ''
            text = ''
            for kv in q.split('&'):
                if kv.startswith('text='):
                    text = kv[5:]
                    text = text.replace('%20', ' ').replace('+', ' ')
                    text = text.replace('%3F', '?').replace('%21', '!')
            if text:
                msg = make_msg("chat", {"text": "[웹] " + text})
                await send_mesh(msg)
                body = b'{"status":"sent"}'
            else:
                body = b'{"error":"no text"}'
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nCache-Control: no-cache\r\nContent-Length: " + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
            await writer.drain()
            return
        elif path.startswith('/api/devices') and method == 'GET':
            # 등록된 모든 노드의 제어 가능 장치(GPIO/PWM) 리스트 반환
            # 센서(type=sensor)는 제어 대상이 아니므로 제외
            now = time.time()
            nodes_with_devices = []
            # 게이트웨이 자신의 장치 (로컬 gpio_control만 - 제어 가능 장치)
            local_devices = []
            try:
                import gpio_control
                local_devices.extend(gpio_control.gm.get_device_list())
            except Exception:
                pass
            if local_devices:
                nodes_with_devices.append({
                    "node_id": cfg.NODE_ID,
                    "nick": cfg.NICKNAME,
                    "role": cfg.NODE_ROLE,
                    "is_self": True,
                    "devices": local_devices,
                })
            # 다른 노드들이 브로드캐스트한 장치 정보 (센서 제외)
            for nid, info in device_registry.items():
                age = now - info.get("last_seen", 0)
                if age > 300:  # 5분 이상 지난 정보는 제외
                    continue
                # 센서가 아닌 장치(GPIO/PWM)만 필터링
                controllable_devices = [
                    d for d in info.get("devices", [])
                    if d.get("type") != "sensor"
                ]
                if not controllable_devices:
                    continue
                nodes_with_devices.append({
                    "node_id": nid,
                    "nick": info.get("nick", nid),
                    "role": info.get("role", "node"),
                    "is_self": False,
                    "devices": controllable_devices,
                })
            body = ujson.dumps({"nodes": nodes_with_devices}).encode()
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nCache-Control: no-cache\r\nContent-Length: " + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
            await writer.drain()
            return
        elif path.startswith('/api/control') and method == 'GET':
            # /api/control?name=거실조명&value=1
            # 선택적으로 &node=<node_id> 로 대상 노드 명시
            q = path.split('?', 1)[1] if '?' in path else ''
            params = {}
            for kv in q.split('&'):
                if '=' in kv:
                    k, v = kv.split('=', 1)
                    params[k] = url_decode(v)
            dev_name = params.get('name', '')
            dev_value = params.get('value', '')
            target_node = params.get('node', '')  # 명시적 대상 노드 (없으면 자동 판별)
            if dev_name and dev_value:
                cmd = "/GPIO {} {}".format(dev_name, dev_value)

                # 1) 장치가 속한 노드 식별
                #    - 명시적 node 파라미터 최우선
                #    - 로컬(gm)에 해당 이름이 있으면 self
                #    - device_registry 에서 해당 장치를 가진 노드 검색
                is_local = False
                if not target_node:
                    try:
                        import gpio_control
                        for dev in gpio_control.gm.get_device_list():
                            if dev.get("name") == dev_name:
                                is_local = True
                                break
                    except Exception:
                        pass
                    if not is_local:
                        # device_registry 에서 해당 장치를 가진 노드 검색
                        for nid, info in device_registry.items():
                            for d in info.get("devices", []):
                                if d.get("name") == dev_name:
                                    target_node = nid
                                    break
                            if target_node:
                                break
                else:
                    is_local = (target_node == cfg.NODE_ID)

                # 2) 메시 네트워크로 브로드캐스트 (모든 노드가 수신)
                msg = make_msg("chat", {"text": "[웹] " + cmd})
                await send_mesh(msg)

                # 3) 로컬 장치면 즉시 실행 후 상태 읽어 응답
                if is_local:
                    try:
                        import gpio_control
                        result = await gpio_control.gm.handle_command(cmd)
                        # 실행 직후 장치에서 현재 상태를 다시 읽어 응답에 포함
                        current_state = None
                        current_duty = None
                        current_freq = None
                        dev_type = None
                        for dev in gpio_control.gm.get_device_list():
                            if dev.get("name") == dev_name:
                                current_state = dev.get("current_state")
                                current_duty = dev.get("current_duty")
                                current_freq = dev.get("current_freq")
                                dev_type = dev.get("type")
                                break
                        # 시리얼 로그: GPIO 스위칭 결과
                        if dev_type == "pwm":
                            state_str = "{}%".format(round((current_duty or 0) / 10.23))
                            print("[GPIO] {} -> {} (local {}, duty={})".format(
                                dev_name, state_str, cfg.NICKNAME, current_duty))
                        else:
                            state_str = "ON" if current_state == 1 else "OFF"
                            print("[GPIO] {} -> {} (local {}, state={})".format(
                                dev_name, state_str, cfg.NICKNAME, current_state))
                        body = ujson.dumps({
                            "status": "ok",
                            "command": cmd,
                            "result": result.get("msg", ""),
                            "node_id": cfg.NODE_ID,
                            "nick": cfg.NICKNAME,
                            "is_self": True,
                            "device": {
                                "name": dev_name,
                                "state": current_state,
                                "duty": current_duty,
                                "freq": current_freq,
                            },
                        }).encode()
                    except Exception as ex:
                        print("[GPIO] {} error: {}".format(dev_name, ex))
                        body = ujson.dumps({"status": "error", "command": cmd,
                                            "error": str(ex)}).encode()
                else:
                    # 4) 원격 노드 장치: 상태 갱신 요청 (device_info_req) 전송
                    #    해당 노드가 즉시 자신의 장치 상태를 브로드캐스트하게 함
                    req_data = {"requested_by": cfg.NODE_ID}
                    if target_node:
                        req_data["target"] = target_node
                    req_msg = make_msg("device_info_req", req_data, ttl=cfg.MAX_TTL)
                    await send_mesh(req_msg)
                    # 시리얼 로그: 원격 노드로 GPIO 명령 전송
                    print("[GPIO] {} -> {} (remote {}, cmd sent)".format(
                        dev_name, dev_value, target_node or "unknown"))
                    body = ujson.dumps({
                        "status": "sent",
                        "command": cmd,
                        "is_self": False,
                        "target_node": target_node or "",
                        "message": "명령 전송됨, 원격 노드에서 상태 갱신 중",
                    }).encode()
            else:
                body = b'{"error":"name and value required"}'
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nCache-Control: no-cache\r\nContent-Length: " + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
            await writer.drain()
            return
        elif path.startswith('/api/automation') and method == 'GET':
            # /api/automation - 자동화 규칙 목록 반환
            # /api/automation?action=add&name=...&sensor=...&operator=>&value=25&...
            q = path.split('?', 1)[1] if '?' in path else ''
            params = {}
            for kv in q.split('&'):
                if '=' in kv:
                    k, v = kv.split('=', 1)
                    params[k] = url_decode(v)

            action = params.get('action', 'list')

            if action == 'list':
                # 규칙 목록 반환
                rules = {}
                for rid, rule in automation_rules.items():
                    rules[rid] = {
                        "name": rule["name"],
                        "sensor": rule["sensor"],
                        "operator": rule["operator"],
                        "value": rule["value"],
                        "hysteresis": rule["hysteresis"],
                        "cooldown_sec": rule["cooldown_sec"],
                        "action_device": rule["action_device"],
                        "action_value": rule["action_value"],
                        "last_state": rule["last_state"],
                    }
                body = ujson.dumps({"rules": rules}).encode()

            elif action == 'add':
                # 규칙 추가
                rid = automation_rules.add_rule(
                    name=params.get('name', ''),
                    sensor=params.get('sensor', ''),
                    operator=params.get('operator', '>'),
                    value=float(params.get('value', 0)),
                    action_device=params.get('action_device', ''),
                    action_value=params.get('action_value', ''),
                    hysteresis=float(params.get('hysteresis', 0)),
                    cooldown_sec=int(params.get('cooldown_sec', 60)),
                )
                body = ujson.dumps({"status": "added", "rule_id": rid}).encode()

            elif action == 'remove':
                # 규칙 제거
                rid = params.get('rule_id', '')
                if automation_rules.remove_rule(rid):
                    body = ujson.dumps({"status": "removed"}).encode()
                else:
                    body = b'{"error":"rule not found"}'

            elif action == 'log':
                # 규칙 실행 로그 반환
                limit = int(params.get('limit', '20'))
                log = rule_log.get_recent(limit)
                body = ujson.dumps({"log": log}).encode()

            elif action == 'clear_log':
                # 로그 삭제
                rule_log.clear()
                body = ujson.dumps({"status": "cleared"}).encode()

            else:
                body = b'{"error":"unknown action"}'

            writer.write(build_header("application/json", len(body)) + body)
            await writer.drain()
            return
        else:
            body = b'{"error":"not found"}'
            writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Type: application/json\r\nCache-Control: no-cache\r\nContent-Length: " + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
            await writer.drain()
            return
    except Exception as ex:
        print("[WEB] 오류:", ex)


async def web_server_loop():
    """HTTP 서버 (게이트웨이 전용).
    마이크로파이썬의 asyncio.start_server() 는 CPython 과 다르게 동작:
    - serve_forever() 메서드 없음
    - start_server() 자체가 백그라운드로 동작
    - 이 함수는 서버가 종료되지 않도록 대기만 함

    다중 연결 지원:
    - asyncio.start_server() 는 각 연결마다 새 코루틴을 생성
    - backlog=8 로 동시 대기 연결 수 확대
    - handle_http() 는 각 연결을 독립적으로 처리 (await 지점에서 다른 연결 양보)
    """
    global web_server
    if cfg.NODE_ROLE != "gateway":
        return
    try:
        # backlog=8: 동시 대기 연결 수 (기본값 2 → 8로 확대)
        try:
            web_server = await asyncio.start_server(handle_http, "0.0.0.0", cfg.WEB_PORT, backlog=8)
        except TypeError:
            # 구버전 MicroPython 은 backlog 미지원
            web_server = await asyncio.start_server(handle_http, "0.0.0.0", cfg.WEB_PORT)
        if sta and sta.isconnected():
            print("[WEB] 대시보드 활성화: http://{}/".format(sta.ifconfig()[0]))
        # 마이크로파이썬에서는 start_server() 가 백그라운드 동작하므로
        # 이 태스크를 계속 대기시킴
        while True:
            await asyncio.sleep(3600)
    except Exception as ex:
        print("[WEB] 서버 오류:", ex)


# ============ 고정 파일 자동 로드 ============
# espnow_mesh_pro.py 시작 시 사용자 모듈을 자동으로 import 하여 실행:
#
#   [사용자 설정 파일 - custom/ 폴더]
#   1. custom/node_config.py  - 노드별 설정 (센서/GPIO 이름, 핀 번호 등)
#   2. custom/automation.py   - 자동화 규칙 설정 (게이트웨이만)
#
#   [표준 로직 파일 - 루트]
#   3. sensors.py             - 센서 초기화 및 주기적 전송 (custom/node_config.py 참조)
#   4. devices.py             - GPIO/PWM 초기화 및 메시 핸들러 등록 (custom/node_config.py 참조)
#
# 각 파일은 선택 사항이며, 없으면 건너뜀.
# 파일이 있으면 import 하고, 모듈에 setup() 함수가 있으면 호출.

CUSTOM_DIR = "custom"

# custom/ 폴더의 사용자 설정 파일
CUSTOM_MODULE_FILES = [
    "node_config",   # 노드별 설정 (사용자 수정)
    "automation",    # 자동화 규칙 (사용자 수정, 게이트웨이만)
]

# 루트의 표준 로직 파일 (사용자 수정 불필요)
STANDARD_MODULE_FILES = [
    "sensors",       # 센서 초기화 표준 로직
    "devices",       # GPIO/PWM 초기화 표준 로직
]


def _ensure_custom_path():
    """custom/ 폴더를 sys.path 에 추가하여 하위 모듈 import 가능하게 함."""
    import os as _os
    # 절대 경로로 변환 (MicroPython 호환)
    custom_path = CUSTOM_DIR
    try:
        # 현재 작업 디렉토리 확인
        cwd = _os.getcwd()
        custom_abs = cwd + "/" + CUSTOM_DIR
    except Exception:
        custom_abs = CUSTOM_DIR

    # sys.path 에 없으면 추가
    if custom_abs not in sys.path:
        try:
            _os.listdir(custom_abs)
            sys.path.insert(0, custom_abs)
            print("[BOOT] custom/ 폴더를 sys.path 에 추가: {}".format(custom_abs))
        except OSError:
            pass

    # 상대 경로도 추가 (폴백)
    if custom_path not in sys.path:
        try:
            _os.listdir(custom_path)
            sys.path.insert(0, custom_path)
        except OSError:
            print("[BOOT] custom/ 폴더 없음")


async def _load_user_modules():
    """고정 파일명의 사용자 모듈을 자동으로 import 하여 실행.

    1. custom/ 폴더의 사용자 설정 파일 (node_config, automation) 로드
    2. 루트의 표준 로직 파일 (sensors, devices) 로드
    각 모듈에 setup() 함수가 있으면 호출.
    파일이 없으면 조용히 건너뜀.
    setup() 은 일반 함수 (비동기 아님).
    """
    # custom/ 폴더를 sys.path 에 추가 (node_config 등 import 가능하게)
    _ensure_custom_path()

    # 1. custom/ 폴더의 사용자 설정 파일 로드
    for mod_name in CUSTOM_MODULE_FILES:
        # automation.py는 게이트웨이에서만 로드
        if mod_name == "automation" and cfg.NODE_ROLE != "gateway":
            continue

        mod = None
        # 방법 1: __import__ 로 시도
        try:
            mod = __import__(mod_name)
            print("[BOOT] 모듈 로드: custom/{}.py".format(mod_name))
        except ImportError:
            # 방법 2: 파일에서 직접 읽어서 exec (MicroPython 호환 폴백)
            try:
                filepath = CUSTOM_DIR + "/" + mod_name + ".py"
                with open(filepath, "r") as f:
                    code = f.read()
                # 빈 모듈 네임스페이스 생성
                mod = type(sys)(mod_name)
                # __name__ 설정
                mod.__name__ = mod_name
                exec(code, mod.__dict__)
                # sys.modules 에 등록 (이후 import node_config 등이 가능)
                sys.modules[mod_name] = mod
                print("[BOOT] 모듈 로드 (exec): custom/{}.py".format(mod_name))
            except OSError:
                # 파일 없음 - 정상
                pass
            except Exception as ex2:
                print("[BOOT] {} exec 오류: {}".format(mod_name, ex2))

        if mod is not None:
            try:
                # setup() 함수 존재 확인
                if hasattr(mod, "setup"):
                    print("[BOOT] {}.setup() 호출 중...".format(mod_name))
                    mod.setup()
                    print("[BOOT] {}.setup() 완료".format(mod_name))
                else:
                    print("[BOOT] {} 에 setup() 함수 없음".format(mod_name))
            except Exception as ex:
                print("[BOOT] {} 로드 오류: {}".format(mod_name, ex))
                import sys as _sys
                _sys.print_exception(ex)

    # 2. 루트의 표준 로직 파일 로드
    for mod_name in STANDARD_MODULE_FILES:
        try:
            mod = __import__(mod_name)
            print("[BOOT] 모듈 로드: {}.py".format(mod_name))

            # setup() 함수 존재 확인
            if hasattr(mod, "setup"):
                print("[BOOT] {}.setup() 호출 중...".format(mod_name))
                mod.setup()
                print("[BOOT] {}.setup() 완료".format(mod_name))
            else:
                print("[BOOT] {} 에 setup() 함수 없음".format(mod_name))

        except ImportError:
            # 파일 없음 - 정상
            pass
        except Exception as ex:
            print("[BOOT] {} 로드 오류: {}".format(mod_name, ex))
            import sys as _sys
            _sys.print_exception(ex)


# ============ REPL 입력 ============
# 마이크로파이썬은 run_in_executor 미지원.
# uselect 로 stdin 을 비동기 폴링하여 줄 단위로 읽음.
try:
    import uselect
    _HAS_USELECT = True
except ImportError:
    _HAS_USELECT = False

_input_buffer = b""


async def async_input():
    """비동기 입력. 마이크로파이썬에서 uselect 로 stdin 폴링."""
    global _input_buffer
    if not _HAS_USELECT:
        await asyncio.sleep(0)
        return input()

    poller = uselect.poll()
    poller.register(sys.stdin, uselect.POLLIN)

    while True:
        events = poller.poll(200)
        if events:
            ch = sys.stdin.read(1)
            if ch is None or ch == "":
                await asyncio.sleep_ms(50)
                continue
            if ch == "\n" or ch == "\r":
                line = _input_buffer.decode("utf-8", "ignore")
                _input_buffer = b""
                return line
            else:
                _input_buffer += ch.encode("utf-8")
        else:
            await asyncio.sleep_ms(100)


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


# ============ 명령어 처리 ============
async def handle_command(cmd_line):
    # cfg.GATEWAY_WIFI_SSID/PASSWORD 은 cfg 객체 사용
    # cfg.MQTT_BROKER/PORT 은 cfg 객체 사용
    # MQTT_TOPIC_* 은 cfg 객체 사용
    # cfg.GATEWAY_GROUP_ID 는 cfg 객체 사용
    cmd = cmd_line.lower()

    if cmd == "/who":
        print("[MESH] 발견된 노드 ({}개):".format(peers.count()))
        print("  나: {} ({}) role={}".format(cfg.NODE_ID, cfg.NICKNAME, cfg.NODE_ROLE))
        for nid, info in peers.items():
            age = time.time() - info["last_seen"]
            print("  - {} ({}) role={} 활동={}초전".format(
                nid, info["nick"], info["role"], int(age)))
        async with gw_lock:
            if gateways.count() > 0:
                print("\n  다른 게이트웨이 ({}):".format(gateways.count()))
                for gid, info in gateways.items():
                    age = time.time() - info["last_seen"]
                    print("  - {} ({}) {}초전".format(
                        gid, info.get("nick", ""), int(age)))

    elif cmd == "/discover":
        print("[MESH] discover 전송...")
        await send_mesh(make_msg("discover", {"text": "who?"}, ttl=cfg.MAX_TTL))

    elif cmd.startswith("/nick "):
        new = cmd_line[6:].strip()[:16]
        if new:
            old = cfg.NICKNAME
            cfg.NICKNAME = new
            print("[MESH] 닉네임 변경: {} → {}".format(old, cfg.NICKNAME))
            await send_system("{} → {}".format(old, cfg.NICKNAME))

    elif cmd == "/stats":
        print("[통계]")
        for k, v in stats.items():
            print("  {}: {}".format(k, v))
        print("  발견 노드:", peers.count())
        print("  다른 게이트웨이:", gateways.count())
        print("  free heap:", gc.mem_free(), "bytes")
        if _last_chip_temp > 0:
            print("  칩 온도: {:.1f}°C".format(_last_chip_temp))
            print("  CPU 클럭: {}MHz".format(_current_cpu_freq // 1000000))

    elif cmd == "/sensors":
        sensor_store.print_status()

    elif cmd == "/config" or cmd == "/config show":
        print("\n[CONFIG] 현재 동작 중인 설정:")
        print("  --- 노드 식별 ---")
        print("  node_id    = {}".format(cfg.NODE_ID))
        print("  nickname   = {}".format(cfg.NICKNAME))
        print("  node_role  = {}".format(cfg.NODE_ROLE))
        print("  --- 게이트웨이 ---")
        print("  gateway_ssid = {}".format(cfg.GATEWAY_WIFI_SSID or "(미설정)"))
        if cfg.GATEWAY_WIFI_PASSWORD:
            masked = cfg.GATEWAY_WIFI_PASSWORD[0] + "*" * (len(cfg.GATEWAY_WIFI_PASSWORD) - 2) + cfg.GATEWAY_WIFI_PASSWORD[-1]
            print("  gateway_password = {}".format(masked))
        else:
            print("  gateway_password = (미설정)")
        print("  --- MQTT ---")
        print("  mqtt_broker = {}".format(cfg.MQTT_BROKER))
        print("  mqtt_port = {}".format(cfg.MQTT_PORT))
        print("  mqtt_topic_up = {}".format(cfg.MQTT_TOPIC_UP))
        print("  mqtt_topic_down = {}".format(cfg.MQTT_TOPIC_DOWN))
        print("  mqtt_topic_sensor = {}".format(cfg.MQTT_TOPIC_SENSOR))
        print("  gateway_group_id = {}".format(cfg.GATEWAY_GROUP_ID))

    elif cmd.startswith("/config save"):
        save_data = {
            "node_id": cfg.NODE_ID,
            "nickname": cfg.NICKNAME,
            "node_role": cfg.NODE_ROLE,
            "gateway_ssid": cfg.GATEWAY_WIFI_SSID,
            "gateway_password": cfg.GATEWAY_WIFI_PASSWORD,
            "mqtt_broker": cfg.MQTT_BROKER,
            "mqtt_port": str(cfg.MQTT_PORT),
            "mqtt_topic_up": cfg.MQTT_TOPIC_UP,
            "mqtt_topic_down": cfg.MQTT_TOPIC_DOWN,
            "mqtt_topic_sensor": cfg.MQTT_TOPIC_SENSOR,
            "gateway_group_id": cfg.GATEWAY_GROUP_ID,
        }
        if cfg.save_current():
            config_data.clear()
            config_data.update(save_data)

    elif cmd.startswith("/config reload"):
        config_data.clear()
        config_data.update(cfg.init(my_mac))
        print("[CONFIG] 리로드 완료. (일부 설정은 재시작 필요)")

    elif cmd.startswith("/config show_raw"):
        try:
            with open(cfg.CONFIG_PATH, "r") as f:
                print("\n[CONFIG] config.txt 원본:")
                print("-" * 40)
                print(f.read())
                print("-" * 40)
        except OSError:
            print("[CONFIG] config.txt 파일 없음.")

    elif cmd.startswith("/config wifi "):
        args = cmd_line[len("/config wifi "):].strip().split(None, 1)
        if len(args) < 2:
            print("사용법: /config wifi <ssid> <password>")
        else:
            cfg.GATEWAY_WIFI_SSID = args[0]
            cfg.GATEWAY_WIFI_PASSWORD = args[1]
            config_data["gateway_ssid"] = cfg.GATEWAY_WIFI_SSID
            config_data["gateway_password"] = cfg.GATEWAY_WIFI_PASSWORD
            print("[CONFIG] Wi-Fi 설정: SSID='{}' (/config save 로 저장)".format(cfg.GATEWAY_WIFI_SSID))

    elif cmd.startswith("/config mqtt "):
        args = cmd_line[len("/config mqtt "):].strip().split()
        if len(args) < 1:
            print("사용법: /config mqtt <broker> [port]")
        else:
            cfg.MQTT_BROKER = args[0]
            config_data["mqtt_broker"] = cfg.MQTT_BROKER
            if len(args) >= 2:
                try:
                    cfg.MQTT_PORT = int(args[1])
                    config_data["mqtt_port"] = str(cfg.MQTT_PORT)
                except ValueError:
                    print("[CONFIG] port 값 오류. 정수여야 함.")
            print("[CONFIG] MQTT 설정: {}:{} (/config save)".format(cfg.MQTT_BROKER, cfg.MQTT_PORT))

    elif cmd.startswith("/config mqtt_enable"):
        args = cmd_line[len("/config mqtt_enable"):].strip().split()
        if not args:
            print("[CONFIG] MQTT 활성화: {} (/config mqtt_enable on|off)".format(cfg.MQTT_ENABLED))
        else:
            val = args[0].lower()
            if val in ("on", "true", "1", "yes"):
                cfg.MQTT_ENABLED = True
                config_data["mqtt_enabled"] = "true"
                print("[CONFIG] MQTT 활성화됨 (/config save)")
            elif val in ("off", "false", "0", "no"):
                cfg.MQTT_ENABLED = False
                config_data["mqtt_enabled"] = "false"
                print("[CONFIG] MQTT 비활성화됨 (/config save)")
            else:
                print("사용법: /config mqtt_enable on|off")

    elif cmd.startswith("/config topic "):
        args = cmd_line[len("/config topic "):].strip().split(None, 1)
        if len(args) < 2:
            print("사용법: /config topic <up|down|sensor> <name>")
        else:
            which = args[0].lower()
            topic_name = args[1].strip()
            if which == "up":
                cfg.MQTT_TOPIC_UP = topic_name
                config_data["mqtt_topic_up"] = topic_name
            elif which == "down":
                cfg.MQTT_TOPIC_DOWN = topic_name
                config_data["mqtt_topic_down"] = topic_name
            elif which == "sensor":
                cfg.MQTT_TOPIC_SENSOR = topic_name
                config_data["mqtt_topic_sensor"] = topic_name
            else:
                print("[CONFIG] 토픽 종류: up, down, sensor 중 하나")
                return
            print("[CONFIG] 토픽 {} = {} (/config save)".format(which, topic_name))

    elif cmd.startswith("/config group "):
        gid = cmd_line[len("/config group "):].strip()
        if not gid:
            print("사용법: /config group <id>")
        else:
            cfg.GATEWAY_GROUP_ID = gid
            config_data["gateway_group_id"] = gid
            print("[CONFIG] 그룹 ID = {} (/config save)".format(gid))

    elif cmd == "/role" or cmd.startswith("/role "):
        new_role = cmd_line[5:].strip().lower() if len(cmd_line) > 5 else ""
        if not new_role:
            print("사용법: /role <node|gateway>")
            print("현재 역할: {}".format(cfg.NODE_ROLE))
        elif new_role not in ("node", "gateway"):
            print("[CONFIG] 역할: node, gateway 중 하나")
        else:
            old = cfg.NODE_ROLE
            cfg.NODE_ROLE = new_role
            config_data["node_role"] = new_role
            print("[CONFIG] cfg.NODE_ROLE 변경: {} → {} (/config save)".format(old, new_role))
            print("[CONFIG] 주의: 변경사항은 재시작 후 적용됩니다.")

    elif cmd.startswith("/wifipower"):
        # /wifipower [dBm] - Wi-Fi 출력 전력 설정 (8~20dBm, 기본 20)
        args = cmd_line[len("/wifipower"):].strip().split()
        try:
            if not args:
                # 현재 값 표시
                try:
                    current = sta.config("txpower")
                except Exception:
                    current = "?"
                print("[WIFI] 현재 출력: {} dBm (범위: 8-20)".format(current))
            else:
                dbm = int(args[0])
                dbm = max(8, min(20, dbm))  # 최소 8dBm, 최대 20dBm
                sta.config(txpower=dbm)
                print("[WIFI] 출력 설정: {} dBm".format(dbm))
                if dbm <= 10:
                    print("[WIFI] 저출력 모드 (발열 저감)")
        except Exception as ex:
            print("[WIFI] 출력 설정 오류:", ex)

    elif cmd.startswith("/autolog"):
        # /autolog on|off - 자동화 규칙 트리거 로그 표시 토글
        args = cmd_line[len("/autolog"):].strip().split()
        import mesh_state
        if not args:
            print("[AUTO] 로그: {} (/autolog on|off)".format(
                "표시" if mesh_state.auto_log_enabled else "숨김"))
        else:
            val = args[0].lower()
            if val in ("on", "true", "1", "yes"):
                mesh_state.auto_log_enabled = True
                print("[AUTO] 규칙 트리거 로그 표시")
            elif val in ("off", "false", "0", "no"):
                mesh_state.auto_log_enabled = False
                print("[AUTO] 규칙 트리거 로그 숨김")
            else:
                print("사용법: /autolog on|off")

    elif cmd == "/help":
        print("명령어:")
        print("  /who          노드 목록 (게이트웨이 포함)")
        print("  /discover     노드 발견")
        print("  /nick <이름>   닉네임 변경")
        print("  /role <역할>  node|gateway 변경")
        print("  /stats        통계")
        print("  /sensors      센서 데이터")
        print("  /config       현재 설정 보기")
        print("  /config save  현재 설정을 config.txt 에 저장")
        print("  /config wifi <ssid> <password>   Wi-Fi AP 설정")
        print("  /config mqtt <broker> [port]     MQTT 브로커 설정")
        print("  /config mqtt_enable on|off       MQTT 활성화/비활성화")
        print("  /config topic <up|down|sensor> <name>  토픽 설정")
        print("  /config group <id>               게이트웨이 그룹 ID")
        print("  /config reload  config.txt 다시 로드")
        print("  /config show_raw  config.txt 원본 보기")
        print("  /wifipower [dBm]  Wi-Fi 출력 전력 (8-20, 기본 20)")
        print("  /autolog on|off  자동화 규칙 트리거 로그 표시/숨김")
        print("  /GPIO <이름> <값> [타이머초]  장치 제어 (대소문자 무관)")
        print("  /help /quit")

    elif cmd.startswith("/gpio"):
        # /GPIO 명령을 로컬에서 직접 실행 (대소문자 무관)
        try:
            import gpio_control
            result = await gpio_control.gm.handle_command(cmd_line)
            if result.get("ok"):
                print("[GPIO] {}".format(result.get("msg", "")))
            else:
                print("[GPIO] {}".format(result.get("msg", "실패")))
        except Exception as ex:
            print("[GPIO] 명령 오류:", ex)

    elif cmd == "/quit":
        await send_system("{} 퇴장".format(cfg.NICKNAME))
        raise KeyboardInterrupt

    else:
        print("[MESH] 알 수 없는 명령. /help")


# ============ 메인 ============
# ============ 온도 모니터링 + 클럭 자동 조정 ============
# ESP32-S3 내장 온도 센서로 칩 온도 측정 후 클럭 조정
_TEMP_THRESHOLDS = [
    (55, 80000000),   # 55°C 이상 → 80MHz (과열 방지)
    (45, 160000000),  # 45°C 이상 → 160MHz (발열 저감)
    (0,  240000000),  # 45°C 미만 → 240MHz (최대 성능)
]
_TEMP_CHECK_INTERVAL = 3  # 3초마다 온도 확인
_current_cpu_freq = 240000000
_last_chip_temp = 0


def read_chip_temp():
    """ESP32 내장 온도 센서에서 칩 온도 읽기 (°C)."""
    try:
        import machine
        # ESP32: 내장 센서는 ADC 채널이나 esp32 모듈로 접근
        try:
            import esp32
            t = esp32.mcu_temperature()
            return round(t, 1)
        except (ImportError, AttributeError):
            pass
        # 대안: 내장 ADC로 대략적 온도 추정 (정확하지 않음)
        try:
            from machine import ADC
            # ESP32-S3: 온도 센서는 ADC 채널이 아님
            # esp32.mcu_temperature() 미지원 시 None 반환
            pass
        except Exception:
            pass
    except Exception:
        pass
    return None


def adjust_cpu_freq(temp=None):
    """칩 온도에 따라 CPU 클럭 자동 조정.

    인자:
      temp: 칩 온도 (°C). None 이면 내장 센서에서 읽기.
    반환:
      조정된 클럭 (Hz) 또는 None (실패 시)
    """
    global _current_cpu_freq, _last_chip_temp
    if temp is None:
        temp = read_chip_temp()
    if temp is None:
        return None

    _last_chip_temp = temp

    # 온도에 따른 목표 클럭 결정
    target_freq = 240000000  # 기본값
    for threshold, freq in _TEMP_THRESHOLDS:
        if temp >= threshold:
            target_freq = freq
            break

    # 현재 클럭과 다르면 변경
    if target_freq != _current_cpu_freq:
        try:
            import machine
            machine.freq(target_freq)
            old_freq = _current_cpu_freq
            _current_cpu_freq = target_freq
            print("[TEMP] 칩 온도: {:.1f}°C → 클럭 변경: {}MHz → {}MHz".format(
                temp, old_freq // 1000000, target_freq // 1000000))
        except Exception as ex:
            print("[TEMP] 클럭 변경 오류:", ex)

    return _current_cpu_freq


async def temp_monitor_loop():
    """주기적으로 칩 온도를 모니터링하여 클럭 자동 조정.

    3초마다 온도 확인:
      55°C 이상 → 80MHz (과열 방지)
      45°C 이상 → 160MHz (발열 저감)
      45°C 미만 → 240MHz (최대 성능)
    시리얼 로그는 클럭 변경 시에만 출력. 상태는 /api/stats 로 확인.
    """
    while True:
        await asyncio.sleep(_TEMP_CHECK_INTERVAL)
        try:
            adjust_cpu_freq()
            # 주기적 로그 출력 안 함 (웹 대시보드 /api/stats 에서 확인)
        except Exception:
            pass


async def main():
    global web_server
    print("=" * 60)
    print("  ESP-NOW 메시 네트워크 Pro")
    print("=" * 60)

    # CPU 클럭 초기 설정 (발열 저감: 부팅 시 80MHz로 시작)
    try:
        import machine
        machine.freq(80000000)
        _current_cpu_freq = 80000000
        # 초기 온도 확인
        temp = read_chip_temp()
        if temp is not None:
            print("[TEMP] 칩 온도: {:.1f}°C".format(temp))
            adjust_cpu_freq(temp)
        else:
            print("[TEMP] 내장 온도 센서 미지원 (수동 160MHz)")
        print("[MESH] CPU 클럭: {}MHz".format(_current_cpu_freq // 1000000))
    except Exception:
        pass

    # 1. MAC 주소만 빠르게 획득 (WLAN 활성화만, 연결 안 함)
    init_mac_only()
    # 2. config.txt 로드 (MAC 기반 cfg.NODE_ID/cfg.NICKNAME 자동 생성 + 역할/SSID/MQTT 로드)
    config_data.clear()
    config_data.update(cfg.init(my_mac))

    # 3. 자동화 규칙 로드 (게이트웨이만)
    if cfg.NODE_ROLE == "gateway":
        automation_rules.load()

    print("[MESH] Node: {} ({})".format(cfg.NODE_ID, cfg.NICKNAME))
    print("[MESH] Role: {} / Channel: {} / TTL: {}".format(
        cfg.NODE_ROLE, cfg.WIFI_CHANNEL, cfg.MAX_TTL))

    if cfg.NODE_ROLE == "gateway":
        print("[MESH] Gateway SSID: {} / MQTT: {}:{}".format(
            cfg.GATEWAY_WIFI_SSID or "(미설정)", cfg.MQTT_BROKER, cfg.MQTT_PORT))
        if not cfg.GATEWAY_WIFI_SSID:
            print("[MESH] 경고: gateway_ssid 미설정. /config wifi <ssid> <password> 로 설정.")

    # 3. config.txt 의 cfg.NODE_ROLE 기반으로 Wi-Fi 연결 (게이트웨이만)
    init_wifi_connect()
    # 4. ESP-NOW 초기화
    init_espnow()
    gc.collect()
    print("[MESH] free heap:", gc.mem_free(), "bytes")

    # 백그라운드 태스크
    _ = asyncio.create_task(recv_loop())
    _ = asyncio.create_task(heartbeat_loop())
    _ = asyncio.create_task(cleanup_loop())
    # NTP 주기 동기화 (인터넷 연결 시에만 동작)
    _ = asyncio.create_task(ntp_sync_loop())
    # 칩 온도 모니터링 + 클럭 자동 조정
    _ = asyncio.create_task(temp_monitor_loop())

    # 역할별 추가 태스크
    if cfg.NODE_ROLE == "gateway":
        ok = connect_mqtt()
        if ok:
            _ = asyncio.create_task(mqtt_loop())
            print("[GATEWAY] MQTT 브릿지 활성화")
        # 자동화 규칙 주기 평가 (시간/일출일몰 규칙용)
        _ = asyncio.create_task(automation_rules.periodic_check_loop())
        print("[AUTO] 자동화 규칙 평가 루프 시작")

    # 고정 파일 자동 로드 (센서/GPIO/자동화 설정)
    await _load_user_modules()

    # 입장 알림
    await send_system("{} 입장 (role={})".format(cfg.NICKNAME, cfg.NODE_ROLE))

    print("\n[MESH] 준비 완료. /help 로 명령어 확인.\n")

    # 게이트웨이: 웹 서버를 메인 루프에서 직접 실행
    # (create_task 로 하면 가비지 컬렉션으로 서버가 멈출 수 있음)
    if cfg.NODE_ROLE == "gateway":
        try:
            print("[WEB] 웹 서버 시작 중...")
            # backlog=8: 동시 대기 연결 수 확대 (다중 클라이언트 지원)
            try:
                web_server = await asyncio.start_server(handle_http, "0.0.0.0", cfg.WEB_PORT, backlog=8)
            except TypeError:
                web_server = await asyncio.start_server(handle_http, "0.0.0.0", cfg.WEB_PORT)
            if sta and sta.isconnected():
                print("[WEB] 대시보드 활성화: http://{}/".format(sta.ifconfig()[0]))
            else:
                print("[WEB] 대시보드 활성화 (IP 미확인)")
            # 서버가 종료되지 않도록 대기
            # input_loop 와 함께 실행하기 위해 input_loop 를 태스크로
            input_task = asyncio.create_task(input_loop())
            while True:
                await asyncio.sleep(3600)
        except Exception as ex:
            print("[WEB] 서버 오류:", ex)
            import sys as _sys
            _sys.print_exception(ex)
            # 웹 서버 실패 시 input_loop 만 실행
            try:
                await input_loop()
            except KeyboardInterrupt:
                print("\n[MESH] 종료.")
    else:
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
