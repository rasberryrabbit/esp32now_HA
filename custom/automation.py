"""
automation.py - 자동화 규칙 설정 (게이트웨이에서만 자동 로드됨)
==============================================================
다양한 자동화 예제를 포함.

예제 목록:
  1. 보드LED 1초 색상 순환 (별도 태스크)
  2. 배터리 전압 기반 보드LED 색상 변경 (센서 규칙 + 히스테리시스)
  3. 배터리 저전압 시 거실조명 자동 OFF (센서 규칙 + device 조건)
  4. 거실조명이 켜져 있을 때만 보일러 허용 (device 조건)
  5. 평일 아침 보일러 자동 ON (시간 규칙)

setup() 함수가 있으면 자동으로 호출됨 (일반 함수).
"""

import sys


def setup():
    """자동화 규칙 설정 (게이트웨이만, 일반 함수)."""
    print("[AUTO] setup() 시작")

    try:
        import espnow_mesh_pro as mesh
        import uasyncio as asyncio
        from mesh_config import cfg
        print("[AUTO] 로드됨 (role={})".format(cfg.NODE_ROLE))
    except Exception as ex:
        print("[AUTO] 로드 실패: {}".format(ex))
        sys.print_exception(ex)
        return

    # ================================================================
    # 예제 1: 보드LED 1초 색상 순환 (별도 태스크)
    # ================================================================
    #_neopixel_colors = [
    #    (255, 0, 0),     # 빨강
    #    (255, 64, 0),    # 주황
    #    (255, 255, 0),   # 노랑
    #    (0, 255, 0),     # 초록
    #    (0, 255, 255),   # 청록
    #    (0, 0, 255),     # 파랑
    #    (128, 0, 255),   # 보라
    #]

    #async def neopixel_cycle_loop():
    #    """1초마다 보드LED 색상을 순환."""
    #    import gpio_control
    #    gm = gpio_control.gm
    #    idx = 0
    #    while True:
    #        try:
    #            r, g, b = _neopixel_colors[idx]
    #            gm.neopixel_set_color("보드LED", r, g, b)
    #            idx = (idx + 1) % len(_neopixel_colors)
    #        except Exception:
    #            pass
    #        await asyncio.sleep(1)

    #loop = asyncio.get_event_loop()
    #loop.create_task(neopixel_cycle_loop())
    #print("[AUTO] 예제 1: 보드LED 1초 색상 순환 시작")

    #================================================================
    #예제 2: 배터리 전압 기반 보드LED 색상 (센서 규칙 + 히스테리시스)
    #================================================================
    #주의: 예제 1의 색상 순환과 충돌하므로, 예제 1을 주석 처리 후 사용
    mesh.automation_rules.add_rule(
        name="정상: 보드LED 초록",
        sensor="배터리", operator=">", value=0.03,
        action_device="보드LED", action_value="0x00FF00",
        hysteresis=0.01, cooldown_sec=10,
        priority=10,
        action_off={"device": "보드LED", "value": "0x000000"},
    )
    mesh.automation_rules.add_rule(
        name="고전압: 보드LED 빨강",
        sensor="배터리", operator=">", value=0.05,
        action_device="보드LED", action_value="0xFF0000",
        hysteresis=0.01, cooldown_sec=10,
        priority=1,
        action_off={"device": "보드LED", "value": "0x00FF00"},
    )
    mesh.automation_rules.add_rule(
        name="저전압: 보드LED 파랑",
        sensor="배터리", operator="<", value=0.02,
        action_device="보드LED", action_value="0x0000FF",
        hysteresis=0.005, cooldown_sec=30,
        priority=5,
        action_off={"device": "보드LED", "value": "0x000000"},
    )

    #================================================================
    #예제 3: 배터리 저전압 시 거실조명 자동 OFF (센서 규칙)
    #================================================================
    #배터리가 0.01V 이하로 떨어지면 거실조명을 끔
    mesh.automation_rules.add_rule(
        name="저전압 경고: 조명 OFF",
        sensor="배터리", operator="<", value=0.01,
        action_device="거실조명", action_value="0",
        hysteresis=0.005, cooldown_sec=60,
        priority=1,
        action_off={"device": "거실조명", "value": "1"},
    )

    #================================================================
    #예제 4: 거실조명이 켜져 있을 때만 보일러 허용 (device 조건)
    #================================================================
    #조명이 ON일 때 + 온도 20도 이하 → 보일러 ON
    #조명이 OFF면 보일러도 OFF
    mesh.automation_rules.add_rule(
        name="조명 ON + 저온 시 보일러",
        sensor="거실온도", operator="<", value=20,
        action_device="보일러", action_value="1",
        hysteresis=1.0, cooldown_sec=60,
        priority=5,
        conditions=[
            {"device": "거실조명", "operator": "==", "value": 1},
        ],
        action_off={"device": "보일러", "value": "0"},
    )

    #================================================================
    #예제 5: 평일 아침 보일러 자동 ON (시간 규칙)
    #================================================================
    #월~금 06:00~08:00 에 보일러 ON, 그 외 시간 OFF
    mesh.automation_rules.add_rule(
        name="평일 아침 보일러",
        rule_type="time",
        schedule={"days": [0, 1, 2, 3, 4], "start": 600, "end": 800},
        action_device="보일러", action_value="1",
        cooldown_sec=60, priority=5,
        action_off={"device": "보일러", "value": "0"},
    )

    #================================================================
    #예제 6: 평일 저녁 거실팬 50% (시간 규칙)
    #================================================================
    #월~금 18:00~22:00 에 거실팬 50%
    mesh.automation_rules.add_rule(
        name="평일 저녁 팬 50%",
        rule_type="time",
        schedule={"days": [0, 1, 2, 3, 4], "start": 1800, "end": 2200},
        action_device="거실팬", action_value="50",
        cooldown_sec=60, priority=5,
        action_off={"device": "거실팬", "value": "0"},
    )

    # ================================================================
    # 예제 7: 타이머 스위치 (GPIO ON 후 30초 후 자동 OFF)
    # ================================================================
    # /GPIO 거실조명 1 30  → 30초 후 자동 OFF
    # REPL이나 웹에서 직접 실행: /GPIO 거실조명 1 30
    # (자동화 규칙이 아닌 GPIO 명령의 타이머 기능 사용)

    # ================================================================
    # 예제 8: 우선순위 충돌 테스트
    # ================================================================
    # 같은 장치(거실팬)에 두 규칙이 충돌:
    #   우선순위 1 (높음): 온도 28도 이상 → 팬 100%
    #   우선순위 10 (낮음): 온도 25도 이상 → 팬 50%
    # 28도 이상이면 우선순위 1이 이김 (팬 100%)
    # mesh.automation_rules.add_rule(
    #     name="고온 팬 100%",
    #     sensor="거실온도", operator=">", value=28,
    #     action_device="거실팬", action_value="100",
    #     hysteresis=1.0, cooldown_sec=30,
    #     priority=1,
    #     action_off={"device": "거실팬", "value": "0"},
    # )
    # mesh.automation_rules.add_rule(
    #     name="미온 팬 50%",
    #     sensor="거실온도", operator=">", value=25,
    #     action_device="거실팬", action_value="50",
    #     hysteresis=1.0, cooldown_sec=60,
    #     priority=10,
    #     action_off={"device": "거실팬", "value": "0"},
    # )

    # ================================================================
    # 요약 출력
    # ================================================================
    print("[AUTO] 자동화 규칙: {}개".format(mesh.automation_rules.count()))
    print("[AUTO] 백그라운드 태스크: 보드LED 색상 순환")
    if mesh.automation_rules.count() > 0:
        print("[AUTO] 규칙 목록:")
        for rid, rule in mesh.automation_rules.items():
            print("  [{}] {} (우선순위 {})".format(
                rid, rule["name"], rule.get("priority", 0)))
