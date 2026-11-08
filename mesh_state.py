"""
mesh_state.py - 메시 네트워크 상태 저장소 (싱글톤)
=================================================
모든 데이터 저장소 클래스와 싱글톤 인스턴스를 정의.
espnow_mesh_pro.py 및 다른 모듈에서 import 하여 사용.

사용법:
  from mesh_state import stats, peers, sensor_store, ...
"""

import time
import ujson as ujson

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio


def now_str():
    """현재 시간 문자열 (YYYY-MM-DD HH:MM:SS)."""
    t = time.localtime()
    return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(*t[:6])


def _current_time_int():
    """현재 시각을 HHMM 정수로 반환 (예: 1430 = 14:30)."""
    t = time.localtime()
    return t[3] * 100 + t[4]


def _current_weekday():
    """현재 요일 (0=월, 1=화, ..., 6=일)."""
    return time.localtime()[6]


# 자동화 로그 표시 여부 (기본: False = 보이지 않음)
auto_log_enabled = False


# ============ 데이터 저장소 클래스들 ============

class Stats:
    """네트워크 통계 (송수신/중계/중복/복구/손실 카운트)."""
    def __init__(self):
        self._data = {"sent": 0, "recv": 0, "relayed": 0, "dup_dropped": 0,
                      "recovered": 0, "lost": 0}

    def inc(self, key, n=1):
        self._data[key] = self._data.get(key, 0) + n

    def get(self, key, default=0):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value

    def items(self):
        return self._data.items()

    def keys(self):
        return self._data.keys()

    def to_dict(self):
        return dict(self._data)

    def reset(self):
        for k in list(self._data.keys()):
            self._data[k] = 0

    # dict 호환 인터페이스 (기존 코드 호환)
    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value

    def __contains__(self, key):
        return key in self._data

    def __len__(self):
        return len(self._data)


class PeerRegistry:
    """발견된 노드 목록 (node_id -> {mac, nick, role, last_seen})."""
    def __init__(self):
        self._peers = {}

    def add(self, node_id, info):
        self._peers[node_id] = info

    def get(self, node_id):
        return self._peers.get(node_id)

    def remove(self, node_id):
        return self._peers.pop(node_id, None)

    def pop(self, node_id, default=None):
        return self._peers.pop(node_id, default)

    def contains(self, node_id):
        return node_id in self._peers

    def items(self):
        return self._peers.items()

    def keys(self):
        return self._peers.keys()

    def values(self):
        return self._peers.values()

    def count(self):
        return len(self._peers)

    def clear(self):
        self._peers.clear()

    # dict 호환 인터페이스 (기존 코드 호환)
    def __getitem__(self, node_id):
        return self._peers[node_id]

    def __setitem__(self, node_id, info):
        self._peers[node_id] = info

    def __contains__(self, node_id):
        return node_id in self._peers

    def __len__(self):
        return len(self._peers)

    def __iter__(self):
        return iter(self._peers)


class MessageCache:
    """msg_id 중복 제거용 캐시 (FIFO, max_size 유지)."""
    def __init__(self):
        self._cache = []

    def contains(self, msg_id):
        return msg_id in self._cache

    def add(self, msg_id, max_size=100):
        self._cache.append(msg_id)
        if len(self._cache) > max_size:
            self._cache.pop(0)

    def clear(self):
        self._cache.clear()

    def count(self):
        return len(self._cache)

    # list 호환 인터페이스 (기존 코드 호환)
    def __contains__(self, msg_id):
        return msg_id in self._cache

    def __len__(self):
        return len(self._cache)


class SensorStore:
    """센서 데이터 시계열 저장소 (집계 노드용)."""
    def __init__(self):
        self.data = {}
        self.max_history = 50

    def store(self, src, nick, name, value, unit):
        if src not in self.data:
            self.data[src] = {"nick": nick}
        if name not in self.data[src]:
            self.data[src][name] = {"unit": unit, "data": []}
        s = self.data[src][name]
        s["unit"] = unit
        s["data"].append((time.time(), value))
        if len(s["data"]) > self.max_history:
            s["data"] = s["data"][-self.max_history:]

    def get_all(self):
        return self.data

    def get_json(self):
        out = {}
        for src, sensors in self.data.items():
            out[src] = {}
            for sname, info in sensors.items():
                if sname == "nick":
                    out[src]["nick"] = info
                    continue
                out[src][sname] = {
                    "unit": info.get("unit", ""),
                    "data": info.get("data", [])[-10:]
                }
        return out

    def get_summary(self):
        summary = {}
        for src, sensors in self.data.items():
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
        return summary

    def is_empty(self):
        return len(self.data) == 0

    def print_status(self):
        if not self.data:
            print("[MESH] 수집된 데이터 없음.")
        else:
            for src, sensors in self.data.items():
                print("  [{}]".format(src), end="")
                for name, info in sensors.items():
                    if name == "nick":
                        continue
                    vals = info["data"]
                    if vals:
                        print(" {}: 최근={} {} ({}개)".format(
                            name, vals[-1][1], info["unit"], len(vals)), end="")
                print()


class DeviceRegistry:
    """게이트웨이가 수집한 다른 노드의 장치 정보 저장소."""
    def __init__(self):
        self._devices = {}  # {node_id: {nick, role, last_seen, devices}}

    def add(self, node_id, info):
        self._devices[node_id] = info

    def get(self, node_id):
        return self._devices.get(node_id)

    def remove(self, node_id):
        return self._devices.pop(node_id, None)

    def pop(self, node_id, default=None):
        return self._devices.pop(node_id, default)

    def items(self):
        return self._devices.items()

    def keys(self):
        return self._devices.keys()

    def values(self):
        return self._devices.values()

    def count(self):
        return len(self._devices)

    def clear(self):
        self._devices.clear()

    # dict 호환 인터페이스
    def __getitem__(self, node_id):
        return self._devices[node_id]

    def __setitem__(self, node_id, info):
        self._devices[node_id] = info

    def __contains__(self, node_id):
        return node_id in self._devices

    def __len__(self):
        return len(self._devices)


class AutomationRules:
    """자동화 규칙 저장소 (rule_id -> rule dict)."""
    def __init__(self):
        self._rules = {}

    def add(self, rule_id, rule):
        self._rules[rule_id] = rule

    def get(self, rule_id, default=None):
        return self._rules.get(rule_id, default)

    def contains(self, rule_id):
        return rule_id in self._rules

    def remove(self, rule_id):
        return self._rules.pop(rule_id, None)

    def pop(self, rule_id, default=None):
        return self._rules.pop(rule_id, default)

    def items(self):
        return self._rules.items()

    def values(self):
        return self._rules.values()

    def keys(self):
        return self._rules.keys()

    def count(self):
        return len(self._rules)

    def is_empty(self):
        return len(self._rules) == 0

    def clear(self):
        self._rules.clear()

    def update(self, rules_dict):
        self._rules.update(rules_dict)

    def to_dict(self):
        return dict(self._rules)

    def next_id(self):
        return "rule_{}".format(len(self._rules) + 1)

    # ============ 고수준 규칙 관리 ============
    def add_rule(self, name, sensor="", operator="", value=0, action_device="",
                 action_value="", hysteresis=0.0, cooldown_sec=60,
                 rule_type="sensor", schedule=None, sun_event=None,
                 group=None, enabled=True, priority=0,
                 conditions=None, action_off=None):
        """자동화 규칙 추가.

        인자:
          name: 규칙 이름 (예: "거실온도 25도 이상 시 팬 켜기")
          rule_type: 규칙 타입 ("sensor", "time", "sun")
          sensor: 센서 이름 (sensor 타입일 때)
          operator: 비교 연산자 (">", "<", ">=", "<=", "==", "!=")
          value: 임계값 (sensor) 또는 시각 (time, HHMM 형식 정수)
          action_device: 제어할 장치 이름 (예: "거실팬")
          action_value: 제어값 (예: 75 → PWM 75%, 또는 1 → ON)
          hysteresis: 히스테리시스
          cooldown_sec: 같은 규칙 재실행 최소 간격 (초)
          schedule: time 타입일 때 {"days": [0..6], "time": HHMM} 또는
                    {"days": [0..6], "start": HHMM, "end": HHMM} (구간)
          sun_event: sun 타입일 때 {"event": "sunrise"|"sunset",
                                    "offset_min": int, "days": [0..6]}
          group: 그룹 이름
          enabled: 규칙 활성화 여부
          priority: 우선순위 (낮을수록 먼저 평가).
          conditions: 추가 조건 리스트 (모두 만족해야 트리거).
          action_off: 상태가 False 로 전환될 때 실행할 액션.

        반환:
          str: 규칙 ID
        """
        rule_id = self.next_id()
        self.add(rule_id, {
            "name": name,
            "type": rule_type,
            "sensor": sensor,
            "operator": operator,
            "value": float(value) if rule_type == "sensor" else value,
            "action_device": action_device,
            "action_value": str(action_value),
            "hysteresis": float(hysteresis),
            "cooldown_sec": int(cooldown_sec),
            "schedule": schedule,
            "sun_event": sun_event,
            "group": group,
            "enabled": enabled,
            "priority": int(priority),
            "conditions": conditions or [],
            "action_off": action_off,
            "last_state": False,
            "last_triggered": 0,
        })
        print("[AUTO] 규칙 추가: {} [{}] (우선순위 {}) → {} {}".format(
            name, rule_type, priority, action_device, action_value))
        if rule_type == "sensor":
            print("[AUTO]   센서: {} {} {} (히스테리시스 ±{})".format(
                sensor, operator, value, hysteresis))
        elif rule_type == "time":
            print("[AUTO]   시간: {}".format(schedule))
        elif rule_type == "sun":
            print("[AUTO]   일출/일몰: {}".format(sun_event))
        if group:
            print("[AUTO]   그룹: {}".format(group))
        if conditions:
            print("[AUTO]   추가 조건: {} 개".format(len(conditions)))
        if action_off:
            print("[AUTO]   OFF 액션: {} {}".format(
                action_off.get("device"), action_off.get("value")))
        self.save()
        return rule_id

    def remove_rule(self, rule_id):
        """자동화 규칙 제거 (그룹에서도 제거)."""
        if self.contains(rule_id):
            rule = self.remove(rule_id)
            # 그룹에서도 제거
            for g in rule_groups.values():
                if rule_id in g.get("rules", []):
                    g["rules"].remove(rule_id)
            print("[AUTO] 규칙 제거: {}".format(rule.get("name", rule_id)))
            self.save()
            return True
        return False

    def list_rules(self):
        """모든 자동화 규칙 반환 (dict 호환 뷰)."""
        return self

    # ============ 영속화 ============
    def save(self):
        """자동화 규칙을 automation.txt 에 저장 (영속화)."""
        if self.is_empty():
            return
        try:
            with open("automation.txt", "w") as f:
                data = {}
                for rid, rule in self.items():
                    data[rid] = {
                        "name": rule["name"],
                        "type": rule.get("type", "sensor"),
                        "sensor": rule.get("sensor", ""),
                        "operator": rule.get("operator", ""),
                        "value": rule.get("value", 0),
                        "action_device": rule.get("action_device", ""),
                        "action_value": rule.get("action_value", ""),
                        "hysteresis": rule.get("hysteresis", 0),
                        "cooldown_sec": rule.get("cooldown_sec", 60),
                        "schedule": rule.get("schedule"),
                        "sun_event": rule.get("sun_event"),
                        "group": rule.get("group"),
                        "enabled": rule.get("enabled", True),
                        "priority": rule.get("priority", 0),
                        "conditions": rule.get("conditions", []),
                        "action_off": rule.get("action_off"),
                    }
                output = {
                    "rules": data,
                    "groups": rule_groups.to_dict(),
                }
                f.write(ujson.dumps(output))
        except Exception as ex:
            print("[AUTO] 저장 오류:", ex)

    def load(self):
        """automation.txt 에서 자동화 규칙 로드."""
        try:
            with open("automation.txt", "r") as f:
                data = ujson.loads(f.read())
            # 새 형식 (rules + groups)
            if "rules" in data:
                rules_data = data["rules"]
                groups_data = data.get("groups", {})
            else:
                # 구 형식 호환 (rules 만)
                rules_data = data
                groups_data = {}
            # 싱글톤 인스턴스 초기화 후 로드
            self.clear()
            rule_groups.clear()
            for rid, rule in rules_data.items():
                rule["last_state"] = False
                rule["last_triggered"] = 0
                self.add(rid, rule)
            rule_groups.update(groups_data)
            # 그룹 내 rules 리스트 갱신
            for gname, g in rule_groups.items():
                g["rules"] = [rid for rid, r in self.items()
                             if r.get("group") == gname]
            print("[AUTO] {} 개 규칙, {} 개 그룹 로드됨".format(
                self.count(), rule_groups.count()))
        except OSError:
            pass
        except Exception as ex:
            print("[AUTO] 로드 오류:", ex)

    # ============ 조건 평가 헬퍼 ============
    def _evaluate_condition(self, value, operator, threshold, hysteresis, last_state):
        """히스테리시스를 적용한 조건 평가.

        임계값 + 히스테리시스 구조:
          - 값이 threshold + hysteresis 이상이면 ON
          - 값이 threshold - hysteresis 이하이면 OFF
          - 그 사이는 last_state 유지 (첨핑 방지)
        """
        try:
            value = float(value)
        except (TypeError, ValueError):
            return last_state

        if hysteresis > 0:
            upper = threshold + hysteresis
            lower = threshold - hysteresis
            # 부동소수점 정밀도 문제 방지를 위한 작은 오차
            eps = 1e-9
            if operator in (">", ">="):
                if value >= upper - eps:
                    return True
                elif value <= lower + eps:
                    return False
                else:
                    return last_state  # 히스테리시스 구간 → 상태 유지
            elif operator in ("<", "<="):
                if value <= lower + eps:
                    return True
                elif value >= upper - eps:
                    return False
                else:
                    return last_state
            else:
                # ==, != 는 히스테리시스 미적용
                pass

        # 히스테리시스 없는 단순 비교
        if operator == ">":
            return value > threshold
        elif operator == ">=":
            return value >= threshold
        elif operator == "<":
            return value < threshold
        elif operator == "<=":
            return value <= threshold
        elif operator == "==":
            return abs(value - threshold) < 0.01
        elif operator == "!=":
            return abs(value - threshold) >= 0.01
        return False

    def _check_conditions(self, conditions, sensor_data, cached_values):
        """추가 조건들이 모두 만족하는지 평가.

        인자:
          conditions: [{"sensor": 이름, "operator": 연산자, "value": 임계값},
                       {"device": 장치이름, "operator": "==", "value": 1}, ...]
          sensor_data: 이번 수신한 센서 데이터
          cached_values: 이전에 캐싱된 센서 값들

        반환:
          bool: 모든 조건 만족 시 True
        """
        if not conditions:
            return True

        for cond in conditions:
            # GPIO 장치 상태 조건 ({"device": "거실조명", "operator": "==", "value": 1})
            device_name = cond.get("device", "")
            if device_name:
                try:
                    import gpio_control
                    dev_state = gpio_control.gm.gpio_state(device_name)
                    if dev_state < 0:
                        # 장치를 찾을 수 없음
                        return False
                    cond_value = cond.get("value", 1)
                    if cond.get("operator", "==") == "==":
                        if dev_state != cond_value:
                            return False
                    elif cond.get("operator", "==") == "!=":
                        if dev_state == cond_value:
                            return False
                except Exception:
                    return False
                continue

            # 센서 조건
            sensor_name = cond.get("sensor", "")
            # 이번 수신 데이터 또는 캐시에서 값 조회
            value = sensor_data.get(sensor_name)
            if value is None:
                value = cached_values.get(sensor_name)
            if value is None:
                return False  # 값 없음 → 조건 불만족

            # 히스테리시스 없는 단순 비교
            if not self._evaluate_condition(value, cond.get("operator", "=="),
                                              cond.get("value", 0), 0, False):
                return False

        return True

    def _check_time_schedule(self, schedule):
        """시간 규칙 평가.

        schedule 형식:
          {"days": [0,1,2,3,4], "time": 700}  → 특정 시각에 ON (그 외 OFF)
          {"days": [0,1,2,3,4], "start": 700, "end": 900}  → 시간 구간 동안 ON

        반환: True (조건 만족) / False
        """
        if not schedule:
            return False

        # 요일 체크
        days = schedule.get("days", [0, 1, 2, 3, 4, 5, 6])
        if _current_weekday() not in days:
            return False

        now_hhmm = _current_time_int()

        # 시간 구간 (start~end)
        if "start" in schedule and "end" in schedule:
            start = int(schedule["start"])
            end = int(schedule["end"])
            # 자정 넘김 (예: 2200~200 = 밤 10시~새벽 2시)
            if start <= end:
                return start <= now_hhmm <= end
            else:
                return now_hhmm >= start or now_hhmm <= end

        # 단일 시각 (정확히 그 시각에만 True, 1분 안에 매칭)
        elif "time" in schedule:
            target = int(schedule["time"])
            # 같은 분(minute) 내에서 매칭 (마이크로파이썬 시간 정확도 한계)
            return now_hhmm == target

        return False

    # ============ 메인 평가 로직 ============
    async def check(self, sensor_data):
        """자동화 규칙 평가 및 실행.

        센서 기반 규칙은 sensor_data 수신 시 즉시 평가.
        시간/일출일몰 규칙은 periodic_check_loop 에서 주기적으로 평가.

        인자:
          sensor_data: {센서이름: 값} (수신한 센서 데이터, 없으면 빈 dict)
        """
        if self.is_empty():
            return

        # 센서 값 캐싱
        for name, value in sensor_data.items():
            last_sensor_values.set(name, value)

        now = time.time()

        # 1단계: 모든 규칙의 새 상태 계산 (아직 트리거하지 않음)
        new_states = {}
        for rule_id, rule in self.items():
            if not rule.get("enabled", True):
                new_states[rule_id] = False
                continue

            rule_type = rule.get("type", "sensor")
            new_state = False

            if rule_type == "sensor":
                sensor_name = rule["sensor"]
                # 이번 수신 데이터 또는 캐시에서 값 조회
                current_value = sensor_data.get(sensor_name)
                if current_value is None:
                    current_value = last_sensor_values.get(sensor_name)
                if current_value is not None:
                    new_state = self._evaluate_condition(
                        current_value, rule["operator"], rule["value"],
                        rule["hysteresis"], rule["last_state"])

            elif rule_type == "time":
                new_state = self._check_time_schedule(rule.get("schedule"))

            elif rule_type == "sun":
                new_state = sun_times.check_event(rule.get("sun_event"))

            # 추가 조건 (conditions) 체크: 기본 조건이 True 일 때만 평가
            if new_state:
                conditions = rule.get("conditions", [])
                if not self._check_conditions(conditions, sensor_data, last_sensor_values):
                    new_state = False

            new_states[rule_id] = new_state

        # 2단계: 그룹 "all" 모드 처리 (그룹 내 모든 규칙이 True 여야 트리거)
        for gname, g in rule_groups.items():
            if g.get("mode") != "all":
                continue
            group_rule_ids = g.get("rules", [])
            if not all(new_states.get(rid, False) for rid in group_rule_ids):
                for rid in group_rule_ids:
                    new_states[rid] = False

        # 3단계: 우선순위에 따라 규칙 정렬 (낮은 priority 가 먼저)
        # 같은 장치에 여러 규칙이 충돌할 때 우선순위 높은 규칙이 이김
        sorted_rules = sorted(
            self.items(),
            key=lambda x: x[1].get("priority", 0)
        )

        # 4단계: 그룹 "any" 모드 - 이미 트리거된 그룹의 나머지 규칙은 무시
        triggered_groups = set()
        # 같은 장치에 대해 이미 액션한 경우 추적 (우선순위 높은 규칙이 먼저)
        # 이번 check() 호출에서 트리거된 {장치이름: 설정값} 추적
        triggered_devices = {}

        # 5단계: 상태 변화 감지 및 트리거 실행
        import espnow_mesh_pro as _mesh
        for rule_id, rule in sorted_rules:
            new_state = new_states.get(rule_id, False)
            group_name = rule.get("group")
            rule_type = rule.get("type", "sensor")
            action_device = rule.get("action_device", "")

            # any 모드에서 이미 트리거된 그룹은 건너뜀
            if group_name and group_name in triggered_groups:
                g_info = rule_groups.get(group_name) or {}
                if g_info.get("mode") == "any":
                    rule["last_state"] = new_state
                    continue

            # 상태 변화 감지 (False → True 일 때만 실행)
            if new_state and not rule["last_state"]:
                # 쿨다운 체크
                if now - rule["last_triggered"] < rule["cooldown_sec"]:
                    rule["last_state"] = new_state
                    continue

                # 우선순위 충돌 체크: 같은 장치에 이미 액션했으면 건너뜀
                # 단, 같은 값으로 설정하는 규칙은 충돌 아님
                if action_device in triggered_devices:
                    current_value = triggered_devices[action_device]
                    if current_value != rule.get("action_value"):
                        if auto_log_enabled:
                            print("[AUTO] 우선순위 충돌, 건너뜀: {} (장치 {} 이미 제어됨: {})".format(
                                rule["name"], action_device, current_value))
                        rule_log.log_execution(rule, rule_type, "on", "skipped")
                        rule["last_state"] = new_state
                        continue

                if auto_log_enabled:
                    print("[AUTO] 규칙 트리거: {} [{}] (우선순위 {}) → {} {}".format(
                        rule["name"], rule_type, rule.get("priority", 0),
                        rule["action_device"], rule["action_value"]))

                # 메시 네트워크로 /GPIO 명령 전송
                cmd = "/GPIO {} {}".format(rule["action_device"], rule["action_value"])
                msg = _mesh.make_msg("chat", {"text": "[자동화] " + cmd})
                await _mesh.send_mesh(msg)
                # 게이트웨이 자신도 로컬에서 직접 실행
                # (게이트웨이는 자기가 보낸 ESP-NOW 메시지를 수신하지 못하므로)
                try:
                    import gpio_control
                    await gpio_control.gm.handle_command(cmd)
                except Exception:
                    pass

                rule["last_triggered"] = now
                triggered_devices[action_device] = rule.get("action_value")

                # 로그 기록
                rule_log.log_execution(rule, rule_type, "on", "ok")

                # 그룹 any 모드: 트리거된 그룹 기록
                if group_name:
                    triggered_groups.add(group_name)

            # 상태 True → False 전환 시 action_off 실행
            elif not new_state and rule["last_state"]:
                action_off = rule.get("action_off")
                if action_off:
                    off_device = action_off.get("device", action_device)
                    off_value = action_off.get("value", "0")
                    if auto_log_enabled:
                        print("[AUTO] 규칙 해제: {} → {} {} (OFF 액션)".format(
                            rule["name"], off_device, off_value))
                    cmd = "/GPIO {} {}".format(off_device, off_value)
                    msg = _mesh.make_msg("chat", {"text": "[자동화] " + cmd})
                    await _mesh.send_mesh(msg)
                    # 게이트웨이 자신도 로컬에서 직접 실행
                    try:
                        import gpio_control
                        await gpio_control.gm.handle_command(cmd)
                    except Exception:
                        pass
                    rule_log.log_execution(rule, rule_type, "off", "ok")

            # 상태 갱신
            rule["last_state"] = new_state

    async def periodic_check_loop(self):
        """시간/일출일몰 규칙을 주기적으로 평가 (60초마다).

        센서 규칙은 check() 에서 처리하므로 여기서는 시간 기반만.
        """
        while True:
            try:
                # 시간/일출일몰 규칙이 있는지 확인
                has_time_rules = any(
                    r.get("type") in ("time", "sun")
                    for r in self.values()
                )
                if has_time_rules:
                    # 빈 sensor_data 로 호출 (센서 규칙은 건너뜀)
                    await self.check({})
            except Exception as ex:
                print("[AUTO] 주기 평가 오류:", ex)
            await asyncio.sleep(60)

    # dict 호환 인터페이스
    def __getitem__(self, rule_id):
        return self._rules[rule_id]

    def __setitem__(self, rule_id, rule):
        self._rules[rule_id] = rule

    def __delitem__(self, rule_id):
        del self._rules[rule_id]

    def __contains__(self, rule_id):
        return rule_id in self._rules

    def __len__(self):
        return len(self._rules)

    def __iter__(self):
        return iter(self._rules)

    def __bool__(self):
        return len(self._rules) > 0


class LastSensorValues:
    """센서 마지막 값 캐시 (히스테리시스 계산용)."""
    def __init__(self):
        self._values = {}

    def set(self, name, value):
        self._values[name] = value

    def get(self, name, default=None):
        return self._values.get(name, default)

    def update(self, data):
        for k, v in data.items():
            self._values[k] = v

    def items(self):
        return self._values.items()

    def clear(self):
        self._values.clear()

    # dict 호환 인터페이스
    def __getitem__(self, name):
        return self._values[name]

    def __setitem__(self, name, value):
        self._values[name] = value

    def __contains__(self, name):
        return name in self._values

    def __len__(self):
        return len(self._values)


class RuleLog:
    """규칙 실행 로그 (최대 max_size 개 유지)."""
    def __init__(self, max_size=100):
        self._log = []
        self._max_size = max_size

    def append(self, entry):
        self._log.append(entry)
        if len(self._log) > self._max_size:
            self._log = self._log[-self._max_size:]

    def get(self, limit=20):
        return list(reversed(self._log[-limit:]))

    def clear(self):
        self._log.clear()

    def count(self):
        return len(self._log)

    def to_list(self):
        return list(self._log)

    # ============ 고수준 로깅 ============
    def log_execution(self, rule, rule_type, action, result="ok"):
        """규칙 실행 로그를 기록.

        인자:
          rule: 규칙 dict
          rule_type: "sensor" / "time" / "sun"
          action: "on" (트리거) / "off" (상태 해제)
          result: "ok" / "skipped" / "error"
        """
        entry = {
            "timestamp": time.time(),
            "ts_str": now_str(),
            "rule_id": None,  # rule_id 는 호출 시점에 모름, name 으로 식별
            "rule_name": rule.get("name", "?"),
            "rule_type": rule_type,
            "action": action,
            "device": rule.get("action_device", ""),
            "value": rule.get("action_value", "") if action == "on" else
                     (rule.get("action_off") or {}).get("value", ""),
            "result": result,
        }
        self.append(entry)  # 클래스 내부에서 max_size 자동 유지

    def get_recent(self, limit=20):
        """최근 로그 엔트리 반환 (최근순).

        인자:
          limit: 반환할 최대 로그 개수

        반환:
          list: 로그 엔트리 리스트 (최근순)
        """
        return self.get(limit)


class RuleGroups:
    """규칙 그룹 저장소 (group_name -> {mode, rules})."""
    def __init__(self):
        self._groups = {}

    def add(self, name, mode="any"):
        self._groups[name] = {"mode": mode, "rules": []}

    def get(self, name):
        return self._groups.get(name)

    def contains(self, name):
        return name in self._groups

    def remove(self, name):
        return self._groups.pop(name, None)

    def pop(self, name, default=None):
        return self._groups.pop(name, default)

    def items(self):
        return self._groups.items()

    def values(self):
        return self._groups.values()

    def keys(self):
        return self._groups.keys()

    def count(self):
        return len(self._groups)

    def clear(self):
        self._groups.clear()

    def update(self, groups_dict):
        self._groups.update(groups_dict)

    def to_dict(self):
        return dict(self._groups)

    # ============ 고수준 그룹 관리 ============
    def add_group(self, name, mode="any"):
        """규칙 그룹 추가.

        인자:
          name: 그룹 이름
          mode: "any" (하나라도 만족하면 트리거, 나머지는 무시)
                "all" (모두 만족해야 트리거)

        같은 그룹의 규칙들은 add_rule 시 group=name 으로 지정.
        """
        self.add(name, mode)
        # 기존 규칙 중 이 그룹에 속하는 규칙들 추가
        for rid, rule in automation_rules.items():
            if rule.get("group") == name:
                self[name]["rules"].append(rid)
        print("[AUTO] 그룹 추가: {} (mode={})".format(name, mode))

    def remove_group(self, name):
        """규칙 그룹 제거 (규칙 자체는 유지, 그룹만 제거)."""
        if self.contains(name):
            # 그룹에서 규칙들의 group 필드 제거
            for rid in self[name]["rules"]:
                if automation_rules.contains(rid):
                    automation_rules[rid]["group"] = None
            self.remove(name)
            print("[AUTO] 그룹 제거: {}".format(name))
            return True
        return False

    def list_groups(self):
        """모든 규칙 그룹 반환."""
        return self

    # dict 호환 인터페이스
    def __getitem__(self, name):
        return self._groups[name]

    def __setitem__(self, name, value):
        self._groups[name] = value

    def __delitem__(self, name):
        del self._groups[name]

    def __contains__(self, name):
        return name in self._groups

    def __len__(self):
        return len(self._groups)

    def __iter__(self):
        return iter(self._groups)

    def __bool__(self):
        return len(self._groups) > 0


class SunTimes:
    """일출/일몰 시간 캐시 (하루 1회 갱신)."""
    def __init__(self):
        self._times = {"sunrise": 0, "sunset": 0, "date": ""}

    def get(self, key, default=None):
        return self._times.get(key, default)

    def set(self, sunrise, sunset, date_str):
        self._times = {"sunrise": sunrise, "sunset": sunset, "date": date_str}

    @property
    def date(self):
        return self._times.get("date", "")

    @property
    def sunrise(self):
        return self._times.get("sunrise", 0)

    @property
    def sunset(self):
        return self._times.get("sunset", 0)

    def to_dict(self):
        return dict(self._times)

    # ============ 일출/일몰 계산 ============
    def _compute(self, lat, lon, year, month, day):
        """일출/일몰 시각 계산 (간단한 알고리즘).

        NOAA 알고리즘 기반 단순화 버전.
        lat: 위도 (예: 37.5665 for 서울)
        lon: 경도 (예: 126.9780 for 서울)
        반환: {"sunrise": HHMM, "sunset": HHMM}
        """
        import math

        # 1년 중 날짜 번호 (1~365)
        days_in_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0):
            days_in_month[1] = 29
        day_of_year = sum(days_in_month[:month - 1]) + day

        # 태양 기울기 (approximate)
        n = day_of_year
        decl = 23.45 * math.sin(math.radians(360 * (284 + n) / 365))

        # 시차 (equation of time, 간소화)
        b = math.radians(360 * (n - 81) / 365)
        eot = 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)

        # 일출/일몰 시각 (UTC)
        lat_rad = math.radians(lat)
        decl_rad = math.radians(decl)
        cos_h = -math.tan(lat_rad) * math.tan(decl_rad)

        # 극지방 (하루 24시간 낮 또는 밤)
        if cos_h > 1:
            return {"sunrise": 0, "sunset": 2359}  # 백야
        elif cos_h < -1:
            return {"sunrise": 0, "sunset": 0}  # 극야

        h = math.degrees(math.acos(cos_h))
        sunrise_utc = 12 - h / 15 - (lon / 15) + (eot / 60)
        sunset_utc = 12 + h / 15 - (lon / 15) + (eot / 60)

        # UTC → 로컬 시간 (한국: UTC+9)
        tz_offset = 9  # Asia/Seoul
        sunrise_local = sunrise_utc + tz_offset
        sunset_local = sunset_utc + tz_offset

        # 시각을 HHMM 형식으로 변환
        def to_hhmm(decimal_hour):
            decimal_hour = max(0, min(24, decimal_hour))
            h = int(decimal_hour)
            m = int((decimal_hour - h) * 60)
            return h * 100 + m

        return {
            "sunrise": to_hhmm(sunrise_local),
            "sunset": to_hhmm(sunset_local),
        }

    def update(self, lat=37.5665, lon=126.9780):
        """일출/일몰 시간 갱신 (하루 1회)."""
        _t = time.localtime()
        today = "{:04d}-{:02d}-{:02d}".format(_t[0], _t[1], _t[2])
        if self.date == today:
            return self

        times = self._compute(lat, lon, _t[0], _t[1], _t[2])
        self.set(times["sunrise"], times["sunset"], today)
        print("[AUTO] 일출/일몰 갱신: 일출={:04d}, 일몰={:04d}".format(
            times["sunrise"], times["sunset"]))
        return self

    def check_event(self, sun_event):
        """일출/일몰 이벤트 규칙 평가.

        sun_event 형식:
          {"event": "sunrise", "offset_min": -30, "days": [0..6]}
          → 일출 30분 전에 트리거

        반환: True (조건 만족) / False
        """
        if not sun_event:
            return False

        self.update()
        event_name = sun_event.get("event", "sunrise")
        offset_min = int(sun_event.get("offset_min", 0))
        days = sun_event.get("days", [0, 1, 2, 3, 4, 5, 6])

        if _current_weekday() not in days:
            return False

        target = self.get(event_name, 0)
        # 오프셋 분을 HHMM 으로 변환
        target_hour = target // 100
        target_minute = target % 100
        total_min = target_hour * 60 + target_minute + offset_min
        if total_min < 0:
            total_min += 24 * 60
        target_hhmm = (total_min // 60) * 100 + (total_min % 60)

        now_hhmm = _current_time_int()
        return now_hhmm == target_hhmm

    # dict 호환 인터페이스
    def __getitem__(self, key):
        return self._times[key]

    def __setitem__(self, key, value):
        self._times[key] = value

    def __contains__(self, key):
        return key in self._times


class GatewayRegistry:
    """다른 게이트웨이 추적 저장소 (gw_id -> {nick, last_seen, active})."""
    def __init__(self):
        self._gateways = {}

    def add(self, gw_id, info):
        self._gateways[gw_id] = info

    def get(self, gw_id):
        return self._gateways.get(gw_id)

    def items(self):
        return self._gateways.items()

    def pop(self, gw_id):
        return self._gateways.pop(gw_id, None)

    def count(self):
        return len(self._gateways)

    def clear(self):
        self._gateways.clear()

    # dict 호환 인터페이스
    def __getitem__(self, gw_id):
        return self._gateways[gw_id]

    def __setitem__(self, gw_id, info):
        self._gateways[gw_id] = info

    def __contains__(self, gw_id):
        return gw_id in self._gateways

    def __len__(self):
        return len(self._gateways)

    def __iter__(self):
        return iter(self._gateways)

    def __bool__(self):
        return len(self._gateways) > 0


class MqttInboundQueue:
    """MQTT 인바운드 메시지 큐."""
    def __init__(self):
        self._queue = []

    def append(self, item):
        self._queue.append(item)

    def pop(self, index=0):
        if 0 <= index < len(self._queue):
            return self._queue.pop(index)
        return None

    def is_empty(self):
        return len(self._queue) == 0

    def clear(self):
        self._queue.clear()

    def count(self):
        return len(self._queue)

    # list 호환 인터페이스
    def __len__(self):
        return len(self._queue)

    def __bool__(self):
        return len(self._queue) > 0


class ConfigData:
    """config.txt 에서 로드한 in-memory 설정 데이터 저장소."""
    def __init__(self):
        self._data = {}

    def set(self, key, value):
        self._data[key] = value

    def get(self, key, default=None):
        return self._data.get(key, default)

    def update(self, data):
        for k, v in data.items():
            self._data[k] = v

    def clear(self):
        self._data.clear()

    def items(self):
        return self._data.items()

    def to_dict(self):
        return dict(self._data)

    # dict 호환 인터페이스 (기존 코드 호환)
    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value

    def __contains__(self, key):
        return key in self._data

    def __len__(self):
        return len(self._data)


# ============ 싱글톤 인스턴스 ============
stats = Stats()
peers = PeerRegistry()
msg_cache = MessageCache()
sensor_store = SensorStore()
device_registry = DeviceRegistry()
automation_rules = AutomationRules()
last_sensor_values = LastSensorValues()
rule_log = RuleLog(max_size=100)
rule_groups = RuleGroups()
sun_times = SunTimes()
gateways = GatewayRegistry()
mqtt_inbound_queue = MqttInboundQueue()
config_data = ConfigData()

# 하위 호환성 별칭 (외부 모듈에서 _automation_rules 등으로 접근하는 경우)
_automation_rules = automation_rules
_rule_groups = rule_groups
_device_registry = device_registry
_rule_log = rule_log
_last_sensor_values = last_sensor_values
_sun_times = sun_times
_RULE_LOG_MAX = 100
