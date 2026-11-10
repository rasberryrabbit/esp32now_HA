"""
devices.py - GPIO/PWM 초기화 및 메시 핸들러 등록 (자동 로드됨)
=============================================================
"""

import sys


def setup():
    """GPIO/PWM 초기화 및 메시 핸들러 등록 (일반 함수)."""
    print("[DEVICES] setup() 시작")

    try:
        import node_config
        print("[DEVICES] node_config 로드됨 (GPIO {}개, PWM {}개)".format(
            len(getattr(node_config, "GPIO_CONFIG", {})),
            len(getattr(node_config, "PWM_CONFIG", {})),
        ))
    except Exception as ex:
        print("[DEVICES] node_config 로드 실패: {}".format(ex))
        sys.print_exception(ex)
        return

    try:
        import gpio_control
        print("[DEVICES] gpio_control 로드됨")
    except Exception as ex:
        print("[DEVICES] gpio_control 로드 실패: {}".format(ex))
        sys.print_exception(ex)
        return

    gm = gpio_control.gm

    gpio_config = getattr(node_config, "GPIO_CONFIG", {})
    if gpio_config:
        try:
            gm.init_gpio(gpio_config)
            print("[DEVICES] GPIO {} 개 초기화 완료".format(len(gpio_config)))
        except Exception as ex:
            print("[DEVICES] GPIO 초기화 오류: {}".format(ex))
            sys.print_exception(ex)

    pwm_config = getattr(node_config, "PWM_CONFIG", {})
    if pwm_config:
        try:
            pwm_freq = getattr(node_config, "PWM_FREQ", 2000)
            gm.init_pwm(pwm_config, freq=pwm_freq)
            print("[DEVICES] PWM {} 개 초기화 완료 (freq={}Hz)".format(len(pwm_config), pwm_freq))
        except Exception as ex:
            print("[DEVICES] PWM 초기화 오류: {}".format(ex))
            sys.print_exception(ex)

    if gpio_config or pwm_config:
        try:
            gm.register_mesh_handler()
            print("[DEVICES] 메시 네트워크 /GPIO 핸들러 등록 완료")
            print("[DEVICES] 원격 명령: /GPIO <이름> <0|1|PWM값>")
        except Exception as ex:
            print("[DEVICES] 핸들러 등록 오류: {}".format(ex))
            sys.print_exception(ex)
