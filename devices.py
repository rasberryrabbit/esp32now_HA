"""
devices.py - GPIO/PWM/NeoPixel 초기화 및 메시 핸들러 등록 (자동 로드됨)
=====================================================================
"""

import sys


def setup():
    """GPIO/PWM/NeoPixel 초기화 및 메시 핸들러 등록 (일반 함수)."""
    print("[DEVICES] setup() 시작")

    try:
        import node_config
        print("[DEVICES] node_config 로드됨 (GPIO {}개, PWM {}개, NeoPixel {}개, MCP23017 {}개, PCF8574 {}개)".format(
            len(getattr(node_config, "GPIO_CONFIG", {})),
            len(getattr(node_config, "PWM_CONFIG", {})),
            len(getattr(node_config, "NEOPIXEL_CONFIG", {})),
            len(getattr(node_config, "MCP23017_CONFIG", {})),
            len(getattr(node_config, "PCF8574_CONFIG", {})),
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

    neopixel_config = getattr(node_config, "NEOPIXEL_CONFIG", {})
    if neopixel_config:
        try:
            neopixel_count = getattr(node_config, "NEOPIXEL_COUNT", 1)
            gm.init_neopixel(neopixel_config, count=neopixel_count)
            print("[DEVICES] NeoPixel {} 개 초기화 완료 (count={})".format(
                len(neopixel_config), neopixel_count))
        except Exception as ex:
            print("[DEVICES] NeoPixel 초기화 오류: {}".format(ex))
            sys.print_exception(ex)

    # I2C 버스 설정 (MCP23017/PCF8574 공용)
    i2c_sda = getattr(node_config, "I2C_SDA_PIN", 8)
    i2c_scl = getattr(node_config, "I2C_SCL_PIN", 9)
    i2c_freq = getattr(node_config, "I2C_FREQ", 400000)

    # MCP23017 (I2C 16채널 GPIO 확장)
    mcp23017_config = getattr(node_config, "MCP23017_CONFIG", {})
    if mcp23017_config:
        try:
            gm.init_mcp23017(mcp23017_config, sda=i2c_sda, scl=i2c_scl, freq=i2c_freq)
            print("[DEVICES] MCP23017 {} 개 초기화 완료".format(len(mcp23017_config)))
        except Exception as ex:
            print("[DEVICES] MCP23017 초기화 오류: {}".format(ex))
            sys.print_exception(ex)

    # PCF8574 (I2C 8채널 GPIO 확장)
    pcf8574_config = getattr(node_config, "PCF8574_CONFIG", {})
    if pcf8574_config:
        try:
            gm.init_pcf8574(pcf8574_config, sda=i2c_sda, scl=i2c_scl, freq=i2c_freq)
            print("[DEVICES] PCF8574 {} 개 초기화 완료".format(len(pcf8574_config)))
        except Exception as ex:
            print("[DEVICES] PCF8574 초기화 오류: {}".format(ex))
            sys.print_exception(ex)

    if gpio_config or pwm_config or neopixel_config or mcp23017_config or pcf8574_config:
        try:
            gm.register_mesh_handler()
            print("[DEVICES] 메시 네트워크 /GPIO 핸들러 등록 완료")
            print("[DEVICES] 원격 명령: /GPIO <이름> <값> [타이머초]")
            print("[DEVICES]   GPIO: 0|1, PWM: 0-100, NeoPixel: 0xRRGGBB|r,g,b|0|1")
        except Exception as ex:
            print("[DEVICES] 핸들러 등록 오류: {}".format(ex))
            sys.print_exception(ex)
