"""
ESP-NOW 메시 네트워크 Pro 클라이언트 (PC/스마트폰용)
=====================================================
게이트웨이 노드가 제공하는 웹 API 또는 MQTT 를 통해 메시 네트워크에 접속합니다.

지원 모드:
  1. HTTP 모드 (기본): 게이트웨이의 웹 API 로 채팅/센서/노드 조회
     - 게이트웨이가 같은 LAN 에 있어야 함
     - URL: http://<gateway_ip>/

  2. MQTT 모드: 외부 MQTT 브로커를 통해 메시 네트워크와 통신
     - 게이트웨이가 인터넷 연결된 경우 사용
     - 어디서든 접속 가능

사용 방법:
  python3 mesh_client.py --gateway 192.168.1.50
  python3 mesh_client.py --gateway 192.168.1.50 --port 80
  python3 mesh_client.py --mqtt --broker broker.hivemq.com --port 1883 \
      --topic-up mesh/chat/up --topic-down mesh/chat/down

명령어 (채팅 모드):
  /nodes       노드 목록 조회
  /stats       서버 통계
  /sensors     센서 데이터
  /config      게이트웨이 설정 보기
  /ssid <ssid> <password>  Wi-Fi 설정 (config.txt 저장)
  /role <node|aggregator|gateway>  노드 역할 변경
  /help        도움말
  /quit        종료
  그 외: 채팅 메시지로 전송
"""

import argparse
import json
import sys
import threading
import time
try:
    import urllib.request
    import urllib.parse
except ImportError:
    print("오류: urllib 모듈이 필요합니다. (CPython 3.x)")
    sys.exit(1)

try:
    import paho.mqtt.client as mqtt
    _HAS_MQTT = True
except ImportError:
    _HAS_MQTT = False


# ============ 색상 코드 ============
class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"


def color(text, c):
    return "{}{}{}".format(c, text, Color.RESET)


# ============ HTTP 클라이언트 ============
class HTTPMeshClient:
    """게이트웨이 웹 API 를 사용하는 클라이언트."""

    def __init__(self, gateway_ip, port=80):
        self.base_url = "http://{}:{}".format(gateway_ip, port)
        self.nickname = "PC-{}".format(int(time.time()) % 10000)
        self.running = False

    def _get(self, path):
        try:
            url = self.base_url + path
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as ex:
            return {"error": str(ex)}

    def _get_text(self, path):
        try:
            url = self.base_url + path
            with urllib.request.urlopen(url, timeout=5) as resp:
                return resp.read().decode("utf-8")
        except Exception as ex:
            return "[오류] {}".format(ex)

    def get_nodes(self):
        return self._get("/api/nodes")

    def get_stats(self):
        return self._get("/api/stats")

    def get_sensors(self):
        return self._get("/api/sensors")

    def get_config(self):
        return self._get("/api/config")

    def send_message(self, text):
        encoded = urllib.parse.quote(text)
        return self._get("/api/send?text=" + encoded)

    def save_wifi_config(self, ssid, password):
        params = urllib.parse.urlencode({
            "gateway_ssid": ssid,
            "gateway_password": password
        })
        return self._get("/api/config_save?" + params)

    def change_role(self, role):
        params = urllib.parse.urlencode({"node_role": role})
        return self._get("/api/config_save?" + params)


# ============ MQTT 클라이언트 ============
class MQTTMeshClient:
    """MQTT 브로커를 통해 메시 네트워크와 통신하는 클라이언트."""

    def __init__(self, broker, port=1883,
                 topic_up="mesh/chat/up", topic_down="mesh/chat/down",
                 topic_sensor="mesh/sensor"):
        if not _HAS_MQTT:
            print("오류: paho-mqtt 라이브러리가 필요합니다.")
            print("설치: pip install paho-mqtt")
            sys.exit(1)

        self.broker = broker
        self.port = port
        self.topic_up = topic_up
        self.topic_down = topic_down
        self.topic_sensor = topic_sensor
        self.nickname = "PC-{}".format(int(time.time()) % 10000)
        self.client = mqtt.Client(client_id="mesh-pc-{}".format(int(time.time())))
        self.running = False

        # 콜백 등록
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print(color("[MQTT] 브로커 연결 성공: {}".format(self.broker), Color.GREEN))
            client.subscribe(self.topic_up)
            client.subscribe(self.topic_sensor)
            print(color("[MQTT] 구독: {}, {}".format(self.topic_up, self.topic_sensor), Color.CYAN))
        else:
            print(color("[MQTT] 연결 실패 (코드: {})".format(rc), Color.RED))

    def _on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode("utf-8"))
            ts = data.get("ts", "?")
            src = data.get("nick", data.get("src", "?"))

            if msg.topic == self.topic_up:
                text = data.get("text", "")
                print(color("[{}] ".format(ts), Color.GRAY) +
                      color("<{}> ".format(src), Color.MAGENTA) +
                      text)
            elif msg.topic == self.topic_sensor:
                name = data.get("name", "?")
                value = data.get("value", "?")
                unit = data.get("unit", "")
                print(color("[{}] ".format(ts), Color.GRAY) +
                      color("[센서/{}] ".format(src), Color.GREEN) +
                      "{} {} {}".format(name, value, unit))
        except Exception as ex:
            print(color("[MQTT] 메시지 파싱 오류: {}".format(ex), Color.RED))

    def connect(self):
        try:
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()
            self.running = True
            return True
        except Exception as ex:
            print(color("[MQTT] 연결 오류: {}".format(ex), Color.RED))
            return False

    def send_message(self, text):
        if not self.running:
            print(color("[MQTT] 연결되지 않음", Color.RED))
            return False
        payload = json.dumps({
            "nick": self.nickname,
            "text": text,
            "ts": time.strftime("%H:%M:%S"),
        })
        self.client.publish(self.topic_down, payload)
        return True

    def set_nickname(self, nick):
        self.nickname = nick
        print(color("[CLIENT] 닉네임 변경: {}".format(nick), Color.YELLOW))

    def disconnect(self):
        self.running = False
        self.client.loop_stop()
        self.client.disconnect()


# ============ 인터랙티브 채팅 루프 ============
def http_chat_loop(client):
    """HTTP 모드 인터랙티브 루프."""
    print("\n" + "=" * 60)
    print(color("  ESP-NOW 메시 네트워크 클라이언트 (HTTP)", Color.CYAN))
    print("  게이트웨이: " + color(client.base_url, Color.YELLOW))
    print("=" * 60)
    print("명령어: /nodes /stats /sensors /config /ssid /role /help /quit")
    print("그 외 입력: 채팅 메시지로 전송\n")

    # 최초 노드 목록 표시
    nodes = client.get_nodes()
    if isinstance(nodes, list) and nodes:
        print(color("[현재 접속 노드 {}개]".format(len(nodes)), Color.GREEN))
        for n in nodes:
            role_color = Color.CYAN if n.get("role") == "gateway" else Color.RESET
            print("  - {} ({}) {}".format(
                n.get("id", "?"), n.get("nick", "?"),
                color("[" + n.get("role", "?") + "]", role_color)))
        print()

    while True:
        try:
            line = input(color("mesh> ", Color.CYAN)).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n종료합니다.")
            break

        if not line:
            continue

        if line.startswith("/"):
            cmd = line.lower()
            if cmd == "/quit":
                print("종료합니다.")
                break
            elif cmd == "/help":
                print_help()
            elif cmd == "/nodes":
                show_nodes(client)
            elif cmd == "/stats":
                show_stats(client)
            elif cmd == "/sensors":
                show_sensors(client)
            elif cmd == "/config":
                show_config(client)
            elif cmd.startswith("/ssid "):
                parts = line[6:].strip().split(None, 1)
                if len(parts) < 2:
                    print("사용법: /ssid <ssid> <password>")
                else:
                    result = client.save_wifi_config(parts[0], parts[1])
                    if result.get("status") == "saved":
                        print(color("✓ config.txt 저장 완료", Color.GREEN))
                    else:
                        print(color("저장 실패: {}".format(result), Color.RED))
            elif cmd.startswith("/role "):
                role = line[6:].strip().lower()
                if role not in ("node", "aggregator", "gateway"):
                    print("역할: node, aggregator, gateway 중 하나")
                else:
                    result = client.change_role(role)
                    if result.get("status") == "saved":
                        print(color("✓ 역할 변경: {} (재시작 후 적용)".format(role), Color.GREEN))
                    else:
                        print(color("변경 실패: {}".format(result), Color.RED))
            else:
                print("알 수 없는 명령. /help")
        else:
            # 채팅 메시지 전송
            result = client.send_message(line)
            if result.get("status") == "sent":
                print(color("<{}(나)> {}".format(client.nickname, line), Color.GRAY))
            else:
                print(color("전송 실패: {}".format(result), Color.RED))


def mqtt_chat_loop(client):
    """MQTT 모드 인터랙티브 루프."""
    print("\n" + "=" * 60)
    print(color("  ESP-NOW 메시 네트워크 클라이언트 (MQTT)", Color.CYAN))
    print("  브로커: " + color("{}:{}".format(client.broker, client.port), Color.YELLOW))
    print("  닉네임: " + color(client.nickname, Color.MAGENTA))
    print("=" * 60)
    print("명령어: /nick /help /quit")
    print("그 외 입력: 메시 네트워크로 브로드캐스트\n")

    while True:
        try:
            line = input(color("mesh> ", Color.CYAN)).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n종료합니다.")
            break

        if not line:
            continue

        if line.startswith("/"):
            cmd = line.lower()
            if cmd == "/quit":
                print("종료합니다.")
                break
            elif cmd == "/help":
                print("MQTT 모드 명령어:")
                print("  /nick <이름>  닉네임 변경")
                print("  /help         도움말")
                print("  /quit         종료")
                print("그 외: 메시 네트워크로 브로드캐스트")
            elif cmd.startswith("/nick "):
                new_nick = line[6:].strip()[:16]
                if new_nick:
                    client.set_nickname(new_nick)
                else:
                    print("닉네임을 입력하세요.")
            else:
                print("알 수 없는 명령. /help")
        else:
            # 메시 네트워크로 전송
            if client.send_message(line):
                print(color("<{}(나)> {}".format(client.nickname, line), Color.GRAY))


def print_help():
    print("명령어:")
    print("  /nodes       노드 목록 조회")
    print("  /stats       서버 통계")
    print("  /sensors     센서 데이터")
    print("  /config      게이트웨이 설정 보기")
    print("  /ssid <ssid> <password>  Wi-Fi 설정 (config.txt 저장)")
    print("  /role <node|aggregator|gateway>  노드 역할 변경")
    print("  /help        도움말")
    print("  /quit        종료")
    print("그 외 입력: 채팅 메시지로 전송")


def show_nodes(client):
    nodes = client.get_nodes()
    if isinstance(nodes, list):
        print(color("\n[접속 노드 {}개]".format(len(nodes)), Color.GREEN))
        for n in nodes:
            role = n.get("role", "?")
            role_color = Color.CYAN if role == "gateway" else (
                Color.YELLOW if role == "aggregator" else Color.RESET)
            age = n.get("last_seen", 0)
            print("  - {} ({}) {}".format(
                n.get("id", "?"), n.get("nick", "?"),
                color("[" + role + "]", role_color)))
        print()
    else:
        print(color("조회 실패: {}".format(nodes), Color.RED))


def show_stats(client):
    stats = client.get_stats()
    if isinstance(stats, dict) and "error" not in stats:
        print(color("\n[서버 통계]", Color.GREEN))
        for k, v in stats.items():
            print("  {}: {}".format(k, v))
        print()
    else:
        print(color("조회 실패: {}".format(stats), Color.RED))


def show_sensors(client):
    sensors = client.get_sensors()
    if isinstance(sensors, dict) and "error" not in sensors:
        print(color("\n[센서 데이터]", Color.GREEN))
        for src, data in sensors.items():
            nick = data.get("nick", src)
            print("  [{}]:".format(src))
            for sname, info in data.items():
                if sname == "nick":
                    continue
                unit = info.get("unit", "")
                history = info.get("data", [])
                if history:
                    last_val = history[-1][1]
                    print("    {}: 최근={} {} ({}개)".format(
                        sname, last_val, unit, len(history)))
        print()
    else:
        print(color("조회 실패: {}".format(sensors), Color.RED))


def show_config(client):
    cfg = client.get_config()
    if isinstance(cfg, dict) and "error" not in cfg:
        print(color("\n[게이트웨이 설정]", Color.GREEN))
        print("  노드 ID    : {}".format(cfg.get("node_id", "?")))
        print("  닉네임     : {}".format(cfg.get("nickname", "?")))
        print("  역할       : {}".format(cfg.get("node_role", "?")))
        print("  IP 주소    : {}".format(cfg.get("ip", "(미연결)")))
        print("  SSID       : {}".format(cfg.get("gateway_ssid", "(미설정)")))
        print("  비밀번호   : {}".format(
            "설정됨" if cfg.get("gateway_password_set") else "미설정"))
        print("  Wi-Fi 채널 : {}".format(cfg.get("wifi_channel", "?")))
        print("  MQTT       : {}:{}".format(
            cfg.get("mqtt_broker", "?"), cfg.get("mqtt_port", "?")))
        print("  그룹 ID    : {}".format(cfg.get("gateway_group_id", "?")))
        print()
    else:
        print(color("조회 실패: {}".format(cfg), Color.RED))


# ============ 메인 ============
def main():
    parser = argparse.ArgumentParser(
        description="ESP-NOW 메시 네트워크 클라이언트",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예제:
  HTTP 모드 (게이트웨이 웹 API):
    python3 mesh_client.py --gateway 192.168.1.50

  HTTP 모드 (포트 지정):
    python3 mesh_client.py --gateway 192.168.1.50 --port 8080

  MQTT 모드 (외부 브로커):
    python3 mesh_client.py --mqtt --broker broker.hivemq.com

  MQTT 모드 (토픽 지정):
    python3 mesh_client.py --mqtt --broker broker.hivemq.com \\
        --topic-up mesh/chat/up --topic-down mesh/chat/down
""")
    parser.add_argument("--gateway", help="게이트웨이 IP 주소 (HTTP 모드)")
    parser.add_argument("--port", type=int, default=80, help="HTTP 포트 (기본 80)")
    parser.add_argument("--mqtt", action="store_true", help="MQTT 모드 사용")
    parser.add_argument("--broker", help="MQTT 브로커 주소")
    parser.add_argument("--mqtt-port", dest="mqtt_port", type=int, default=1883,
                        help="MQTT 포트 (기본 1883)")
    parser.add_argument("--topic-up", default="mesh/chat/up",
                        help="메시→외부 토픽 (기본 mesh/chat/up)")
    parser.add_argument("--topic-down", default="mesh/chat/down",
                        help="외부→메시 토픽 (기본 mesh/chat/down)")
    parser.add_argument("--topic-sensor", default="mesh/sensor",
                        help="센서 데이터 토픽 (기본 mesh/sensor)")

    args = parser.parse_args()

    # 모드 결정
    if args.mqtt:
        if not args.broker:
            print("오류: --broker 를 지정하세요 (MQTT 모드)")
            parser.print_help()
            sys.exit(1)
        client = MQTTMeshClient(
            broker=args.broker,
            port=args.mqtt_port,
            topic_up=args.topic_up,
            topic_down=args.topic_down,
            topic_sensor=args.topic_sensor,
        )
        if not client.connect():
            sys.exit(1)
        try:
            mqtt_chat_loop(client)
        finally:
            client.disconnect()
    else:
        if not args.gateway:
            print("오류: --gateway 또는 --mqtt 를 지정하세요")
            parser.print_help()
            sys.exit(1)
        client = HTTPMeshClient(args.gateway, args.port)
        http_chat_loop(client)


if __name__ == "__main__":
    main()
