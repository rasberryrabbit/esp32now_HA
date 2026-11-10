"""
sensors.py - 센서 초기화 및 주기적 전송 (자동 로드됨)
====================================================
espnow_mesh_pro.py 시작 시 자동으로 import 됨.
node_config.py 의 SENSOR_CONFIG 를 읽어 센서를 초기화하고
주기적으로 메시 네트워크로 센서 데이터를 전송.
"""

import sys


def setup():
    """센서 초기화 및 주기적 전송 시작 (일반 함수)."""
    print("[SENSORS] setup() 시작")

    try:
        import node_config
        print("[SENSORS] node_config 로드됨 (센서 {}개)".format(
            len(node_config.SENSOR_CONFIG)))
    except Exception as ex:
        print("[SENSORS] node_config 로드 실패: {}".format(ex))
        sys.print_exception(ex)
        return

    try:
        import sensor_runner
        print("[SENSORS] sensor_runner 로드됨")
    except Exception as ex:
        print("[SENSORS] sensor_runner 로드 실패: {}".format(ex))
        sys.print_exception(ex)
        return

    # mesh_config 에서 NODE_ID/NICKNAME 가져와서 sensor_runner.sm 에 설정
    try:
        from mesh_config import cfg
        sensor_runner.sm.node_id = cfg.NODE_ID
        sensor_runner.sm.nickname = cfg.NICKNAME
        print("[SENSORS] 노드 ID 설정: {} ({})".format(cfg.NODE_ID, cfg.NICKNAME))
    except Exception as ex:
        print("[SENSORS] 노드 ID 설정 실패: {}".format(ex))

    if not hasattr(node_config, "SENSOR_CONFIG") or not node_config.SENSOR_CONFIG:
        print("[SENSORS] SENSOR_CONFIG 없음 또는 빈 값")
        return

    try:
        count = sensor_runner.sm.init_sensors(node_config.SENSOR_CONFIG)
        print("[SENSORS] 센서 초기화: {} 개 활성".format(count))
        if count == 0:
            print("[SENSORS] 활성 센서 없음 (하드웨어 연결 확인)")
            return
    except Exception as ex:
        print("[SENSORS] 센서 초기화 오류: {}".format(ex))
        sys.print_exception(ex)
        return

    try:
        read_interval = getattr(node_config, "SENSOR_READ_INTERVAL", 10)
        send_interval = getattr(node_config, "SENSOR_SEND_INTERVAL", 30)
        sensor_runner.sm.start_periodic(
            read_interval=read_interval,
            send_interval=send_interval,
        )
        print("[SENSORS] 센서 주기적 전송 시작 (읽기 {}초, 전송 {}초)".format(
            read_interval, send_interval))
    except Exception as ex:
        print("[SENSORS] 주기적 전송 시작 오류: {}".format(ex))
        sys.print_exception(ex)
