"""
mesh_config.py - 설정 관리 클래스 (모든 모듈에서 공유)
=====================================================
마이크로파이썬에서 모듈 간 전역 변수 참조가 불안정하므로
별도 모듈의 객체를 import 하여 참조.

사용법:
  from mesh_config import cfg
  print(cfg.NODE_ID)
  cfg.init(my_mac)
  cfg.save_current()
"""

import ubinascii
import time


def _now_str():
    t = time.localtime()
    return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(*t[:6])


class Config:
    NODE_ID = ""
    NICKNAME = ""
    NODE_ROLE = "node"
    WIFI_CHANNEL = 1
    MAX_TTL = 5
    MSG_CACHE_SIZE = 100
    HEARTBEAT_INTERVAL = 30
    NODE_TIMEOUT = 90
    BROADCAST_ADDR = b'\xff\xff\xff\xff\xff\xff'
    CONFIG_PATH = "config.txt"
    GATEWAY_GROUP_ID = "mesh-gw-1"
    GATEWAY_WIFI_SSID = ""
    GATEWAY_WIFI_PASSWORD = ""
    MQTT_ENABLED = False  # 기본: MQTT 비활성화
    MQTT_BROKER = "broker.hivemq.com"
    MQTT_PORT = 1883
    MQTT_CLIENT_ID = ""
    MQTT_TOPIC_UP = "mesh/chat/up"
    MQTT_TOPIC_DOWN = "mesh/chat/down"
    MQTT_TOPIC_SENSOR = "mesh/sensor"
    MQTT_TOPIC_GW_PRESENCE = "mesh/gateway/presence"
    WEB_PORT = 80
    # 런타임 상태 (config.txt 에 저장 안 함)
    IP_ADDR = ""
    AP_MODE = False
    AP_SSID = ""

    CONFIG_KEYS = [
        "node_id", "nickname", "node_role",
        "gateway_ssid", "gateway_password",
        "mqtt_enabled", "mqtt_broker", "mqtt_port",
        "mqtt_topic_up", "mqtt_topic_down", "mqtt_topic_sensor",
        "gateway_group_id",
    ]

    def load(self):
        result = {}
        try:
            with open(self.CONFIG_PATH, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip()
                    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
                        value = value[1:-1]
                    result[key] = value
            print("[CONFIG] config.txt 로드: {}개 항목".format(len(result)))
        except OSError:
            print("[CONFIG] config.txt 없음. 기본값 사용.")
        except Exception as ex:
            print("[CONFIG] 로드 오류:", ex)
        return result

    def save(self, data):
        try:
            with open(self.CONFIG_PATH, "w") as f:
                f.write("# ESP-NOW 메시 네트워크 Pro 설정 파일\n")
                f.write("# 마지막 수정: {}\n\n".format(_now_str()))
                for key in self.CONFIG_KEYS:
                    if key in data:
                        value = str(data[key])
                        if any(c in value for c in [" ", "=", "#", "\n"]):
                            value = '"' + value.replace('"', '\\"') + '"'
                        f.write("{}={}\n".format(key, value))
            print("[CONFIG] 저장 완료:", self.CONFIG_PATH)
            return True
        except Exception as ex:
            print("[CONFIG] 저장 오류:", ex)
            return False

    def _gen_node_id(self, mac_bytes):
        suffix = ubinascii.hexlify(mac_bytes[-3:]).decode()
        return "node-" + suffix

    def _gen_nickname(self, mac_bytes):
        suffix = ubinascii.hexlify(mac_bytes[-2:]).decode()
        return "ESP-" + suffix

    def init(self, mac_bytes=None):
        print("[CONFIG] init() 시작")
        loaded = self.load()
        print("[CONFIG] load 완료: {}개 항목".format(len(loaded)))

        if "node_id" in loaded and loaded["node_id"]:
            self.NODE_ID = loaded["node_id"]
            print("[CONFIG] NODE_ID 로드: {}".format(self.NODE_ID))
        elif mac_bytes is not None:
            self.NODE_ID = self._gen_node_id(mac_bytes)
            print("[CONFIG] NODE_ID 자동 생성: {} (MAC 기반)".format(self.NODE_ID))

        if "nickname" in loaded and loaded["nickname"]:
            self.NICKNAME = loaded["nickname"]
            print("[CONFIG] NICKNAME 로드: {}".format(self.NICKNAME))
        elif mac_bytes is not None:
            self.NICKNAME = self._gen_nickname(mac_bytes)
            print("[CONFIG] NICKNAME 자동 생성: {} (MAC 기반)".format(self.NICKNAME))

        if "node_role" in loaded and loaded["node_role"]:
            self.NODE_ROLE = loaded["node_role"]
            print("[CONFIG] NODE_ROLE 로드: {}".format(self.NODE_ROLE))
        else:
            self.NODE_ROLE = "node"
            print("[CONFIG] NODE_ROLE 기본값: node")

        self.MQTT_CLIENT_ID = "esp32-gw-" + self.NODE_ID

        if "gateway_ssid" in loaded:
            self.GATEWAY_WIFI_SSID = loaded["gateway_ssid"]
        if "gateway_password" in loaded:
            self.GATEWAY_WIFI_PASSWORD = loaded["gateway_password"]
        if "mqtt_enabled" in loaded:
            self.MQTT_ENABLED = loaded["mqtt_enabled"].lower() in ("true", "1", "yes", "on")
        if "mqtt_broker" in loaded:
            self.MQTT_BROKER = loaded["mqtt_broker"]
        if "mqtt_port" in loaded:
            try:
                self.MQTT_PORT = int(loaded["mqtt_port"])
            except ValueError:
                print("[CONFIG] mqtt_port 값 오류:", loaded["mqtt_port"])
        if "mqtt_topic_up" in loaded:
            self.MQTT_TOPIC_UP = loaded["mqtt_topic_up"]
        if "mqtt_topic_down" in loaded:
            self.MQTT_TOPIC_DOWN = loaded["mqtt_topic_down"]
        if "mqtt_topic_sensor" in loaded:
            self.MQTT_TOPIC_SENSOR = loaded["mqtt_topic_sensor"]
        if "gateway_group_id" in loaded:
            self.GATEWAY_GROUP_ID = loaded["gateway_group_id"]

        if not loaded and mac_bytes is not None:
            print("[CONFIG] 최초 부팅. config.txt 자동 생성.")
            self.save_current()

        print("[CONFIG] init() 완료: NODE_ID=[{}] NICKNAME=[{}]".format(
            self.NODE_ID, self.NICKNAME))
        return loaded

    def save_current(self):
        data = {
            "node_id": self.NODE_ID,
            "nickname": self.NICKNAME,
            "node_role": self.NODE_ROLE,
            "gateway_ssid": self.GATEWAY_WIFI_SSID,
            "gateway_password": self.GATEWAY_WIFI_PASSWORD,
            "mqtt_enabled": "true" if self.MQTT_ENABLED else "false",
            "mqtt_broker": self.MQTT_BROKER,
            "mqtt_port": str(self.MQTT_PORT),
            "mqtt_topic_up": self.MQTT_TOPIC_UP,
            "mqtt_topic_down": self.MQTT_TOPIC_DOWN,
            "mqtt_topic_sensor": self.MQTT_TOPIC_SENSOR,
            "gateway_group_id": self.GATEWAY_GROUP_ID,
        }
        return self.save(data)


cfg = Config()
