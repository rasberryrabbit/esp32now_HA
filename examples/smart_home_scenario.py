"""
스마트홈 자동화 시나리오 예제 (게이트웨이 노드에서 실행)
========================================================
espnow_mesh_pro.py 가 게이트웨이로 실행 중인 상태에서 이 스크립트를 import 하면
실제 스마트홈 자동화 시나리오를 한 번에 설정할 수 있습니다.

시나리오 구성:
  1. 거실 온도 관리 (히스테리시스 + 우선순위)
     - 25도 이상: 거실팬 50% (낮은 우선순위)
     - 28도 이상: 거실팬 100% (높은 우선순위, 팬 50% 무시)
     - 23도 이하: 팬 끄기 (action_off)

  2. 재실 감지 기반 조명 제어 (조건부 액션)
     - 조도 50 이하 AND 재실여부=1 → 조명 ON
     - 재실여부=0 → 조명 OFF (action_off)

  3. 일몰 자동 외부 조명 (일출/일몰)
     - 일몰 30분 전 → 외부조명 ON
     - 일출 시 → 외부조명 OFF (action_off)

  4. 평일 근무시간 보일러 (시간 기반)
     - 평일 06:00-08:00 → 보일러 ON
     - 평일 18:00-22:00 → 보일러 ON
     - 그 외 시간 → 보일러 OFF (action_off)

  5. CO2 고농도 환기 (그룹 any 모드)
     - CO2 1000ppm OR 습도 75% → 환기팬 100%

  6. 야간 보안 모드 (시간 + 조건부)
     - 22:00-06:00 AND 움직임 감지 → 경광등 ON
     - 시간 외 → 경광등 OFF (action_off)

사용 방법:
  # 게이트웨이 노드 REPL에서
  import espnow_mesh_pro as mesh
  mesh.run()  # 메시 네트워크 시작

  # 다른 REPL 세션에서 (또는 mesh.run() 후)
  import smart_home_scenario
  smart_home_scenario.setup_all_rules()
  # → 모든 자동화 규칙이 등록됨

  # 상태 확인
  smart_home_scenario.print_status()

  # 로그 확인
  smart_home_scenario.print_log()

  # 규칙 초기화 (전체 삭제)
  smart_home_scenario.clear_all_rules()
"""

import sys


def setup_all_rules():
    """모든 스마트홈 자동화 규칙을 한 번에 설정."""
    try:
        import espnow_mesh_pro as mesh
    except ImportError:
        print("오류: espnow_mesh_pro 가 import 되어야 합니다.")
        return False

    print("=" * 60)
    print("  스마트홈 자동화 시나리오 설정")
    print("=" * 60)

    # === 시나리오 1: 거실 온도 관리 (히스테리시스 + 우선순위) ===
    print("\n[시나리오 1] 거실 온도 관리")
    print("  - 25도 이상: 거실팬 50% (우선순위 10)")
    print("  - 28도 이상: 거실팬 100% (우선순위 1, 높음)")
    print("  - 23도 이하: 팬 끄기 (action_off)")

    mesh.automation_rules.add_rule(
        name="거실 고온 팬 50%",
        sensor="거실온도", operator=">", value=25,
        action_device="거실팬", action_value="50",
        hysteresis=1.0,        # 24~26도 구간에서 상태 유지
        cooldown_sec=60,
        priority=10,           # 낮은 우선순위
        action_off={"device": "거실팬", "value": "0"},  # OFF 시 팬 끄기
    )
    mesh.automation_rules.add_rule(
        name="거실 초고온 팬 100%",
        sensor="거실온도", operator=">", value=28,
        action_device="거실팬", action_value="100",
        hysteresis=1.0,        # 27~29도 구간에서 상태 유지
        cooldown_sec=30,
        priority=1,            # 높은 우선순위 (팬 50% 무시)
        action_off={"device": "거실팬", "value": "0"},
    )

    # === 시나리오 2: 재실 감지 기반 조명 제어 (조건부 액션) ===
    print("\n[시나리오 2] 재실 감지 기반 조명")
    print("  - 조도 50 이하 AND 재실여부=1 → 조명 ON")
    print("  - 재실여부=0 → 조명 OFF (action_off)")

    mesh.automation_rules.add_rule(
        name="재실 시 저조도 조명 켜기",
        sensor="조도", operator="<", value=50,
        action_device="거실조명", action_value="1",
        hysteresis=10,
        cooldown_sec=10,
        priority=5,
        # 추가 조건: 재실여부 센서가 1일 때만
        conditions=[
            {"sensor": "재실여부", "operator": "==", "value": 1},
        ],
        action_off={"device": "거실조명", "value": "0"},
    )

    # === 시나리오 3: 일몰 자동 외부 조명 (일출/일몰) ===
    print("\n[시나리오 3] 일몰 자동 외부 조명")
    print("  - 일몰 30분 전 → 외부조명 ON")
    print("  - 일출 시 → 외부조명 OFF (action_off)")

    mesh.automation_rules.add_rule(
        name="일몰 30분 전 외부 조명 켜기",
        rule_type="sun",
        sun_event={"event": "sunset", "offset_min": -30, "days": [0,1,2,3,4,5,6]},
        action_device="외부조명", action_value="1",
        cooldown_sec=60,
        priority=5,
        action_off={"device": "외부조명", "value": "0"},
    )

    # === 시나리오 4: 평일 근무시간 보일러 (시간 기반) ===
    print("\n[시나리오 4] 평일 근무시간 보일러")
    print("  - 평일 06:00-08:00 → 보일러 ON (아침)")
    print("  - 평일 18:00-22:00 → 보일러 ON (저녁)")
    print("  - 그 외 → 보일러 OFF (action_off)")

    mesh.automation_rules.add_rule(
        name="평일 아침 보일러",
        rule_type="time",
        schedule={"days": [0, 1, 2, 3, 4], "start": 600, "end": 800},
        action_device="보일러", action_value="1",
        cooldown_sec=60,
        priority=5,
        action_off={"device": "보일러", "value": "0"},
    )
    mesh.automation_rules.add_rule(
        name="평일 저녁 보일러",
        rule_type="time",
        schedule={"days": [0, 1, 2, 3, 4], "start": 1800, "end": 2200},
        action_device="보일러", action_value="1",
        cooldown_sec=60,
        priority=5,
        action_off={"device": "보일러", "value": "0"},
    )

    # === 시나리오 5: CO2 고농도 환기 (그룹 any 모드) ===
    print("\n[시나리오 5] CO2/습도 환기 (그룹 any)")
    print("  - CO2 1000ppm OR 습도 75% → 환기팬 100%")

    mesh.rule_groups.add_group("환기제어", mode="any")

    mesh.automation_rules.add_rule(
        name="고농도 CO2 환기",
        sensor="CO2", operator=">", value=1000,
        action_device="환기팬", action_value="100",
        hysteresis=50,
        cooldown_sec=60,
        priority=5,
        group="환기제어",
    )
    mesh.automation_rules.add_rule(
        name="고습 환기",
        sensor="거실습도", operator=">", value=75,
        action_device="환기팬", action_value="100",
        hysteresis=3,
        cooldown_sec=60,
        priority=5,
        group="환기제어",
    )

    # === 시나리오 6: 야간 보안 모드 (시간 + 조건부) ===
    print("\n[시나리오 6] 야간 보안 모드")
    print("  - 22:00-06:00 AND 움직임 감지 → 경광등 ON")
    print("  - 시간 외 → 경광등 OFF (action_off)")

    mesh.automation_rules.add_rule(
        name="야간 움직임 감지 시 경광등",
        rule_type="time",
        schedule={"days": [0,1,2,3,4,5,6], "start": 2200, "end": 600},
        action_device="경광등", action_value="1",
        cooldown_sec=30,
        priority=1,           # 높은 우선순위
        # 추가 조건: 움직임 센서가 1일 때만
        conditions=[
            {"sensor": "움직임", "operator": "==", "value": 1},
        ],
        action_off={"device": "경광등", "value": "0"},
    )

    print("\n" + "=" * 60)
    print("  총 {} 개 규칙, {} 개 그룹 설정 완료".format(
        mesh.automation_rules.count(), mesh.rule_groups.count()))
    print("=" * 60)
    return True


def setup_temperature_rules():
    """온도 관리 규칙만 설정 (시나리오 1만)."""
    try:
        import espnow_mesh_pro as mesh
    except ImportError:
        print("오류: espnow_mesh_pro 가 import 되어야 합니다.")
        return False

    print("\n[온도 관리 규칙 설정]")
    mesh.automation_rules.add_rule(
        name="거실 고온 팬 50%",
        sensor="거실온도", operator=">", value=25,
        action_device="거실팬", action_value="50",
        hysteresis=1.0, cooldown_sec=60,
        priority=10,
        action_off={"device": "거실팬", "value": "0"},
    )
    mesh.automation_rules.add_rule(
        name="거실 초고온 팬 100%",
        sensor="거실온도", operator=">", value=28,
        action_device="거실팬", action_value="100",
        hysteresis=1.0, cooldown_sec=30,
        priority=1,
        action_off={"device": "거실팬", "value": "0"},
    )
    return True


def setup_occupancy_rules():
    """재실 감지 조명 규칙만 설정 (시나리오 2만)."""
    try:
        import espnow_mesh_pro as mesh
    except ImportError:
        print("오류: espnow_mesh_pro 가 import 되어야 합니다.")
        return False

    print("\n[재실 감지 조명 규칙 설정]")
    mesh.automation_rules.add_rule(
        name="재실 시 저조도 조명 켜기",
        sensor="조도", operator="<", value=50,
        action_device="거실조명", action_value="1",
        hysteresis=10, cooldown_sec=10, priority=5,
        conditions=[
            {"sensor": "재실여부", "operator": "==", "value": 1},
        ],
        action_off={"device": "거실조명", "value": "0"},
    )
    return True


def setup_sun_rules():
    """일출/일몰 규칙만 설정 (시나리오 3만)."""
    try:
        import espnow_mesh_pro as mesh
    except ImportError:
        print("오류: espnow_mesh_pro 가 import 되어야 합니다.")
        return False

    print("\n[일출/일몰 규칙 설정]")
    mesh.automation_rules.add_rule(
        name="일몰 30분 전 외부 조명 켜기",
        rule_type="sun",
        sun_event={"event": "sunset", "offset_min": -30, "days": [0,1,2,3,4,5,6]},
        action_device="외부조명", action_value="1",
        cooldown_sec=60, priority=5,
        action_off={"device": "외부조명", "value": "0"},
    )
    return True


def setup_time_rules():
    """시간 기반 규칙만 설정 (시나리오 4만)."""
    try:
        import espnow_mesh_pro as mesh
    except ImportError:
        print("오류: espnow_mesh_pro 가 import 되어야 합니다.")
        return False

    print("\n[시간 기반 규칙 설정]")
    mesh.automation_rules.add_rule(
        name="평일 아침 보일러",
        rule_type="time",
        schedule={"days": [0, 1, 2, 3, 4], "start": 600, "end": 800},
        action_device="보일러", action_value="1",
        cooldown_sec=60, priority=5,
        action_off={"device": "보일러", "value": "0"},
    )
    mesh.automation_rules.add_rule(
        name="평일 저녁 보일러",
        rule_type="time",
        schedule={"days": [0, 1, 2, 3, 4], "start": 1800, "end": 2200},
        action_device="보일러", action_value="1",
        cooldown_sec=60, priority=5,
        action_off={"device": "보일러", "value": "0"},
    )
    return True


def setup_ventilation_rules():
    """환기 규칙만 설정 (시나리오 5만)."""
    try:
        import espnow_mesh_pro as mesh
    except ImportError:
        print("오류: espnow_mesh_pro 가 import 되어야 합니다.")
        return False

    print("\n[환기 규칙 설정 (그룹 any)]")
    mesh.rule_groups.add_group("환기제어", mode="any")

    mesh.automation_rules.add_rule(
        name="고농도 CO2 환기",
        sensor="CO2", operator=">", value=1000,
        action_device="환기팬", action_value="100",
        hysteresis=50, cooldown_sec=60, priority=5,
        group="환기제어",
    )
    mesh.automation_rules.add_rule(
        name="고습 환기",
        sensor="거실습도", operator=">", value=75,
        action_device="환기팬", action_value="100",
        hysteresis=3, cooldown_sec=60, priority=5,
        group="환기제어",
    )
    return True


def setup_security_rules():
    """야간 보안 규칙만 설정 (시나리오 6만)."""
    try:
        import espnow_mesh_pro as mesh
    except ImportError:
        print("오류: espnow_mesh_pro 가 import 되어야 합니다.")
        return False

    print("\n[야간 보안 규칙 설정]")
    mesh.automation_rules.add_rule(
        name="야간 움직임 감지 시 경광등",
        rule_type="time",
        schedule={"days": [0,1,2,3,4,5,6], "start": 2200, "end": 600},
        action_device="경광등", action_value="1",
        cooldown_sec=30, priority=1,
        conditions=[
            {"sensor": "움직임", "operator": "==", "value": 1},
        ],
        action_off={"device": "경광등", "value": "0"},
    )
    return True


def print_status():
    """현재 규칙 및 그룹 상태 출력."""
    try:
        import espnow_mesh_pro as mesh
    except ImportError:
        print("오류: espnow_mesh_pro 가 import 되어야 합니다.")
        return

    print("\n" + "=" * 60)
    print("  자동화 규칙 상태")
    print("=" * 60)

    if mesh.automation_rules.is_empty():
        print("  등록된 규칙 없음")
        return

    for rid, rule in mesh.automation_rules.items():
        print("\n  [{}] {} (우선순위 {})".format(rid, rule["name"], rule.get("priority", 0)))
        print("    타입: {}".format(rule.get("type", "sensor")))
        print("    활성: {}".format("ON" if rule.get("enabled", True) else "OFF"))
        print("    상태: {}".format("트리거됨" if rule.get("last_state") else "대기"))
        if rule.get("type") == "sensor":
            print("    센서: {} {} {} (히스테리시스 ±{})".format(
                rule["sensor"], rule["operator"], rule["value"],
                rule.get("hysteresis", 0)))
        elif rule.get("type") == "time":
            print("    시간: {}".format(rule.get("schedule")))
        elif rule.get("type") == "sun":
            print("    일출/일몰: {}".format(rule.get("sun_event")))
        if rule.get("conditions"):
            print("    추가 조건: {} 개".format(len(rule["conditions"])))
            for cond in rule["conditions"]:
                print("      - {} {} {}".format(
                    cond["sensor"], cond["operator"], cond["value"]))
        print("    액션: {} = {}".format(rule["action_device"], rule["action_value"]))
        if rule.get("action_off"):
            print("    OFF 액션: {} = {}".format(
                rule["action_off"].get("device"),
                rule["action_off"].get("value")))
        if rule.get("group"):
            print("    그룹: {}".format(rule["group"]))

    if mesh.rule_groups.count() > 0:
        print("\n  규칙 그룹:")
        for gname, g in mesh.rule_groups.items():
            print("    - {} (mode={}, {}개 규칙)".format(
                gname, g.get("mode"), len(g.get("rules", []))))


def print_log(limit=20):
    """규칙 실행 로그 출력."""
    try:
        import espnow_mesh_pro as mesh
    except ImportError:
        print("오류: espnow_mesh_pro 가 import 되어야 합니다.")
        return

    print("\n" + "=" * 60)
    print("  규칙 실행 로그 (최근 {}개)".format(limit))
    print("=" * 60)

    log = mesh.rule_log.get_recent(limit)
    if not log:
        print("  로그 없음")
        return

    for entry in log:
        action_str = "트리거" if entry["action"] == "on" else "해제"
        result_str = "✓" if entry["result"] == "ok" else "건너뜀"
        print("  [{}] {} {} [{}] → {} {} ({})".format(
            entry.get("ts_str", "?"),
            action_str,
            entry.get("rule_name", "?"),
            entry.get("rule_type", "?"),
            entry.get("device", "?"),
            entry.get("value", "?"),
            result_str,
        ))


def clear_all_rules():
    """모든 규칙과 그룹 삭제."""
    try:
        import espnow_mesh_pro as mesh
    except ImportError:
        print("오류: espnow_mesh_pro 가 import 되어야 합니다.")
        return

    count = mesh.automation_rules.count()
    for rid in list(mesh.automation_rules.keys()):
        mesh.automation_rules.remove_rule(rid)
    for gname in list(mesh.rule_groups.keys()):
        mesh.rule_groups.remove_group(gname)
    mesh.rule_log.clear()
    print("\n{} 개 규칙, 모든 그룹, 로그 삭제됨".format(count))


def enable_rule(rule_id):
    """특정 규칙 활성화."""
    try:
        import espnow_mesh_pro as mesh
    except ImportError:
        return False
    if mesh.automation_rules.contains(rule_id):
        mesh.automation_rules[rule_id]["enabled"] = True
        mesh.automation_rules.save()
        print("[AUTO] {} 활성화".format(rule_id))
        return True
    return False


def disable_rule(rule_id):
    """특정 규칙 비활성화."""
    try:
        import espnow_mesh_pro as mesh
    except ImportError:
        return False
    if mesh.automation_rules.contains(rule_id):
        mesh.automation_rules[rule_id]["enabled"] = False
        mesh.automation_rules.save()
        print("[AUTO] {} 비활성화".format(rule_id))
        return True
    return False


if __name__ == "__main__":
    print("이 스크립트는 espnow_mesh_pro 가 실행 중일 때 import 하여 사용하세요.")
    print("예: import smart_home_scenario; smart_home_scenario.setup_all_rules()")
