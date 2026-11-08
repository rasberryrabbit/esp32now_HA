"""
GPIO 제어 모듈 (ESP32-S3) - 클래스 기반
=========================================
GPIO 핀에 이름을 부여하여 "/GPIO 이름 값" 형식으로 원격 제어.

지원 장치:
  - 디지털 출력 (GPIO ON/OFF)
  - PWM 출력 (0-1023 또는 0-100%)
  - NeoPixel (RGB LED, 색상 지정)
  - MCP23017 (I2C 16채널 GPIO 확장)
  - PCF8574 (I2C 8채널 GPIO 확장)
  - 타이머 스위치 (지정 시간 후 자동 OFF)

사용법:
  import gpio_control
  gm = gpio_control.gm  # 싱글톤 인스턴스

  gm.init_gpio({"거실조명": 2, "보일러": 3})
  gm.init_pwm({"거실팬": 5}, freq=2000)
  gm.init_neopixel({"거실LED": 8}, count=16)
  gm.init_mcp23017({"extension0": (0x20, 0)}, sda=8, scl=9)  # I2C 0x20, 핀 0
  gm.init_pcf8574({"extension1": (0x21, 0)}, sda=8, scl=9)   # I2C 0x21, 핀 0
  gm.gpio_on("거실조명")
  gm.gpio_on_timer("거실조명", 30)  # 30초 후 자동 OFF
  gm.neopixel_set_color("거실LED", 255, 0, 0)  # 빨강
  gm.gpio_on("extension0")  # MCP23017 핀 0 ON
  gm.get_device_list()
  gm.register_mesh_handler()
  gm.status()
"""

import time

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

try:
    from machine import Pin, PWM, I2C
    _HAS_MACHINE = True
except ImportError:
    _HAS_MACHINE = False

# NeoPixel (마이크로파이썬 firmware 에 포함된 neopixel 모듈)
try:
    import neopixel as _neopixel
    _HAS_NEOPIXEL = True
except ImportError:
    _HAS_NEOPIXEL = False


# ============ I2C GPIO 확장 칩 추상 클래스 ============
class I2CGPIOExpander:
    """I2C GPIO 확장 칩의 공통 인터페이스."""

    def __init__(self, i2c, addr):
        self.i2c = i2c
        self.addr = addr
        self._pin_states = {}  # {핀번호: 0|1}
        self._input_pins = set()  # 입력 모드로 설정된 핀 번호 집합

    def pin_on(self, pin):
        """지정 핀을 HIGH 로 설정 (출력 모드)."""
        raise NotImplementedError

    def pin_off(self, pin):
        """지정 핀을 LOW 로 설정 (출력 모드)."""
        raise NotImplementedError

    def pin_state(self, pin):
        """지정 핀의 현재 상태 반환 (0|1)."""
        return self._pin_states.get(pin, 0)

    def pin_read(self, pin):
        """지정 핀의 입력 값을 읽기 (0|1). 입력 모드 핀에서 사용."""
        raise NotImplementedError

    def set_pin_input(self, pin, pullup=True):
        """핀을 입력 모드로 설정 (풀업 옵션)."""
        raise NotImplementedError

    def count(self):
        """지원하는 핀 개수 반환."""
        raise NotImplementedError


# MCP23017 레지스터 (BANK=0 모드)
_MCP23017_IODIRA = 0x00   # 포트 A 방향 (0=출력, 1=입력)
_MCP23017_IODIRB = 0x01   # 포트 B 방향
_MCP23017_IPOLA = 0x02    # 입력 극성 (0=정상)
_MCP23017_IPOLB = 0x03
_MCP23017_GPPUA = 0x0C    # 포트 A 풀업 저항 (1=활성)
_MCP23017_GPPUB = 0x0D    # 포트 B 풀업 저항
_MCP23017_GPIOA = 0x12     # 포트 A 핀 상태 (읽기)
_MCP23017_GPIOB = 0x13     # 포트 B 핀 상태 (읽기)
_MCP23017_OLATA = 0x14     # 포트 A 출력 래치
_MCP23017_OLATB = 0x15     # 포트 B 출력 래치


class MCP23017(I2CGPIOExpander):
    """MCP23017: I2C 16채널 GPIO 확장 (포트 A: 0-7, 포트 B: 8-15)."""

    def __init__(self, i2c, addr=0x20):
        super().__init__(i2c, addr)
        try:
            # 모든 핀을 출력으로 설정 (0=출력)
            self.i2c.writeto(self.addr, bytes([_MCP23017_IODIRA, 0x00]))
            self.i2c.writeto(self.addr, bytes([_MCP23017_IODIRB, 0x00]))
            # 모든 출력을 LOW 로 초기화
            self.i2c.writeto(self.addr, bytes([_MCP23017_OLATA, 0x00]))
            self.i2c.writeto(self.addr, bytes([_MCP23017_OLATB, 0x00]))
            # 풀업 저항 비활성화
            self.i2c.writeto(self.addr, bytes([_MCP23017_GPPUA, 0x00]))
            self.i2c.writeto(self.addr, bytes([_MCP23017_GPPUB, 0x00]))
            # 핀 상태 초기화
            for i in range(16):
                self._pin_states[i] = 0
        except Exception as ex:
            print("[GPIO] MCP23017 0x{:02x} 초기화 오류: {}".format(addr, ex))
            raise

    def _port_pin(self, pin):
        """핀 번호(0-15)를 (출력 래치 레지스터, 비트)로 변환."""
        if pin < 8:
            return _MCP23017_OLATA, pin
        else:
            return _MCP23017_OLATB, pin - 8

    def _gpio_reg(self, pin):
        """핀 번호를 GPIO 읽기 레지스터로 변환."""
        if pin < 8:
            return _MCP23017_GPIOA
        else:
            return _MCP23017_GPIOB

    def _iodir_reg(self, pin):
        """핀 번호를 방향 레지스터로 변환."""
        if pin < 8:
            return _MCP23017_IODIRA
        else:
            return _MCP23017_IODIRB

    def _gppu_reg(self, pin):
        """핀 번호를 풀업 레지스터로 변환."""
        if pin < 8:
            return _MCP23017_GPPUA
        else:
            return _MCP23017_GPPUB

    def set_pin_input(self, pin, pullup=True):
        """핀을 입력 모드로 설정 (풀업 옵션)."""
        if pin < 0 or pin > 15:
            return False
        try:
            bit = pin if pin < 8 else pin - 8
            # 방향 레지스터: 1=입력
            iodir_reg = self._iodir_reg(pin)
            self.i2c.writeto(self.addr, bytes([iodir_reg]))
            current = self.i2c.readfrom(self.addr, 1)[0]
            self.i2c.writeto(self.addr, bytes([iodir_reg, current | (1 << bit)]))
            # 풀업 저항 설정
            if pullup:
                gppu_reg = self._gppu_reg(pin)
                self.i2c.writeto(self.addr, bytes([gppu_reg]))
                current = self.i2c.readfrom(self.addr, 1)[0]
                self.i2c.writeto(self.addr, bytes([gppu_reg, current | (1 << bit)]))
            self._input_pins.add(pin)
            return True
        except Exception as ex:
            print("[GPIO] MCP23017 핀 {} 입력 설정 오류: {}".format(pin, ex))
            return False

    def pin_read(self, pin):
        """입력 핀의 값을 읽기 (0|1)."""
        if pin < 0 or pin > 15:
            return -1
        try:
            bit = pin if pin < 8 else pin - 8
            gpio_reg = self._gpio_reg(pin)
            self.i2c.writeto(self.addr, bytes([gpio_reg]))
            val = self.i2c.readfrom(self.addr, 1)[0]
            state = (val >> bit) & 1
            self._pin_states[pin] = state
            return state
        except Exception as ex:
            print("[GPIO] MCP23017 핀 {} 읽기 오류: {}".format(pin, ex))
            return -1

    def pin_on(self, pin):
        if pin < 0 or pin > 15:
            return False
        if pin in self._input_pins:
            return False  # 입력 모드 핀은 출력 불가
        try:
            reg, bit = self._port_pin(pin)
            # 현재 래치 값 읽기
            self.i2c.writeto(self.addr, bytes([reg]))
            current = self.i2c.readfrom(self.addr, 1)[0]
            new_val = current | (1 << bit)
            self.i2c.writeto(self.addr, bytes([reg, new_val]))
            self._pin_states[pin] = 1
            return True
        except Exception as ex:
            print("[GPIO] MCP23017 핀 {} ON 오류: {}".format(pin, ex))
            return False

    def pin_off(self, pin):
        if pin < 0 or pin > 15:
            return False
        if pin in self._input_pins:
            return False  # 입력 모드 핀은 출력 불가
        try:
            reg, bit = self._port_pin(pin)
            self.i2c.writeto(self.addr, bytes([reg]))
            current = self.i2c.readfrom(self.addr, 1)[0]
            new_val = current & ~(1 << bit)
            self.i2c.writeto(self.addr, bytes([reg, new_val]))
            self._pin_states[pin] = 0
            return True
        except Exception as ex:
            print("[GPIO] MCP23017 핀 {} OFF 오류: {}".format(pin, ex))
            return False

    def count(self):
        return 16


class PCF8574(I2CGPIOExpander):
    """PCF8574: I2C 8채널 GPIO 확장 (핀 0-7).

    PCF8574는 quasi-bidirectional 포트: 핀을 HIGH 로 쓰면 입력 모드로 동작.
    입력 핀을 읽으려면 먼저 해당 비트를 HIGH 로 설정 후 읽기.
    """

    def __init__(self, i2c, addr=0x20):
        super().__init__(i2c, addr)
        self._output = 0xFF  # 초기값: 모든 핀 HIGH (입력 모드)
        try:
            self.i2c.writeto(self.addr, bytes([self._output]))
            for i in range(8):
                self._pin_states[i] = 1  # HIGH 상태
        except Exception as ex:
            print("[GPIO] PCF8574 0x{:02x} 초기화 오류: {}".format(addr, ex))
            raise

    def set_pin_input(self, pin, pullup=True):
        """핀을 입력 모드로 설정. PCF8574는 HIGH 출력 = 입력 모드."""
        if pin < 0 or pin > 7:
            return False
        try:
            self._output |= (1 << pin)  # HIGH = 입력 모드
            self.i2c.writeto(self.addr, bytes([self._output]))
            self._input_pins.add(pin)
            # PCF8574는 내장 풀업이 없으므로 pullup 파라미터는 무시됨
            # 외부 풀업 저항 필요
            return True
        except Exception as ex:
            print("[GPIO] PCF8574 핀 {} 입력 설정 오류: {}".format(pin, ex))
            return False

    def pin_read(self, pin):
        """입력 핀의 값을 읽기 (0|1)."""
        if pin < 0 or pin > 7:
            return -1
        try:
            # 입력 핀을 HIGH 로 유지하면서 읽기
            self._output |= (1 << pin)
            self.i2c.writeto(self.addr, bytes([self._output]))
            val = self.i2c.readfrom(self.addr, 1)[0]
            state = (val >> pin) & 1
            self._pin_states[pin] = state
            return state
        except Exception as ex:
            print("[GPIO] PCF8574 핀 {} 읽기 오류: {}".format(pin, ex))
            return -1

    def pin_on(self, pin):
        if pin < 0 or pin > 7:
            return False
        if pin in self._input_pins:
            return False  # 입력 모드 핀은 출력 불가
        try:
            self._output |= (1 << pin)
            self.i2c.writeto(self.addr, bytes([self._output]))
            self._pin_states[pin] = 1
            return True
        except Exception as ex:
            print("[GPIO] PCF8574 핀 {} ON 오류: {}".format(pin, ex))
            return False

    def pin_off(self, pin):
        if pin < 0 or pin > 7:
            return False
        try:
            self._output &= ~(1 << pin)
            self.i2c.writeto(self.addr, bytes([self._output]))
            self._pin_states[pin] = 0
            return True
        except Exception as ex:
            print("[GPIO] PCF8574 핀 {} OFF 오류: {}".format(pin, ex))
            return False

    def count(self):
        return 8


class GPIOManager:

    def __init__(self):
        self.gpio_devices = {}   # {이름: Pin 객체}
        self.pwm_devices = {}    # {이름: PWM 객체}
        self.neopixel_devices = {}  # {이름: NeoPixel 객체}
        self.i2c_gpio_devices = {}  # {이름: (I2CGPIOExpander, 핀번호)} 출력용
        self.i2c_input_devices = {} # {이름: (I2CGPIOExpander, 핀번호, chip_type)} 입력용(센서)
        self._i2c_buses = {}    # {bus_id: I2C 객체} (공유 I2C 버스)
        self._pin_to_name = {}   # {핀번호: 이름}
        self._last_gpio_state = {}  # {이름: 0|1} 마지막으로 설정한 GPIO 상태
        self._last_pwm_duty = {}    # {이름: duty} 마지막으로 설정한 PWM duty
        self._last_neopixel = {}   # {이름: (r, g, b)} 마지막으로 설정한 NeoPixel 색상
        self._timers = {}          # {장치이름: (task, expire_time)} 활성 타이머

    # ============ 초기화 ============
    def init_gpio(self, devices, default_state=0):
        if not _HAS_MACHINE:
            print("[GPIO] machine 모듈 미지원")
            return []
        initialized = []
        for name, pin in devices.items():
            if pin in self._pin_to_name:
                print("[GPIO] 핀 {} 이미 사용 중 ({})".format(pin, self._pin_to_name[pin]))
                continue
            try:
                p = Pin(pin, Pin.OUT, value=default_state)
                self.gpio_devices[name] = p
                self._pin_to_name[pin] = name
                self._last_gpio_state[name] = default_state  # 초기 상태 저장
                initialized.append(name)
                print("[GPIO] {} 초기화 (GPIO {}, 출력, 초기값={})".format(
                    name, pin, "HIGH" if default_state else "LOW"))
            except Exception as ex:
                print("[GPIO] {} (GPIO {}) 초기화 실패: {}".format(name, pin, ex))
        return initialized

    def init_pwm(self, devices, freq=1000):
        if not _HAS_MACHINE:
            return []
        initialized = []
        for name, pin in devices.items():
            if pin in self._pin_to_name:
                continue
            try:
                p = Pin(pin, Pin.OUT)
                pwm = PWM(p, freq=freq, duty=0)
                self.pwm_devices[name] = pwm
                self._pin_to_name[pin] = name
                self._last_pwm_duty[name] = 0  # 초기 duty 저장
                initialized.append(name)
                print("[GPIO] {} 초기화 (PWM GPIO {}, freq={}Hz, duty=0)".format(
                    name, pin, freq))
            except Exception as ex:
                print("[GPIO] {} (GPIO {}) PWM 초기화 실패: {}".format(name, pin, ex))
        return initialized

    def init_neopixel(self, devices, count=1):
        """NeoPixel LED 초기화.

        인자:
          devices: {이름: 핀번호} 딕셔너리
          count: NeoPixel 개수 (LED 체인 길이)
        """
        if not _HAS_MACHINE:
            return []
        if not _HAS_NEOPIXEL:
            print("[GPIO] NeoPixel 모듈 미지원 (펌웨어에 neopixel 모듈 필요)")
            return []
        initialized = []
        for name, pin in devices.items():
            if pin in self._pin_to_name:
                print("[GPIO] 핀 {} 이미 사용 중 ({})".format(pin, self._pin_to_name[pin]))
                continue
            try:
                p = Pin(pin, Pin.OUT)
                np = _neopixel.NeoPixel(p, count)
                self.neopixel_devices[name] = np
                self._pin_to_name[pin] = name
                self._last_neopixel[name] = (0, 0, 0)  # 초기 OFF
                initialized.append(name)
                print("[GPIO] {} 초기화 (NeoPixel GPIO {}, {}개)".format(
                    name, pin, count))
            except Exception as ex:
                print("[GPIO] {} (GPIO {}) NeoPixel 초기화 실패: {}".format(name, pin, ex))
        return initialized

    # ============ I2C GPIO 확장 칩 ============
    def _get_i2c(self, sda, scl, freq=400000):
        """공유 I2C 버스 반환 (같은 SDA/SCL 이면 재사용)."""
        bus_id = (sda, scl)
        if bus_id in self._i2c_buses:
            return self._i2c_buses[bus_id]
        i2c = I2C(sda=Pin(sda), scl=Pin(scl), freq=freq)
        self._i2c_buses[bus_id] = i2c
        print("[GPIO] I2C 버스 생성 (SDA={}, SCL={}, freq={}Hz)".format(sda, scl, freq))
        return i2c

    def init_mcp23017(self, devices, sda=8, scl=9, freq=400000):
        """MCP23017 (I2C 16채널 GPIO 확장) 초기화.

        인자:
          devices: {이름: (i2c_addr, pin)} 딕셔너리
                   pin: 0-15 (포트 A: 0-7, 포트 B: 8-15)
          sda, scl: I2C SDA/SCL 핀 번호
          freq: I2C 클럭 주파수 (기본 400kHz)
        """
        if not _HAS_MACHINE:
            return []
        initialized = []
        try:
            i2c = self._get_i2c(sda, scl, freq)
        except Exception as ex:
            print("[GPIO] MCP23017 I2C 초기화 실패: {}".format(ex))
            return []
        for name, (addr, pin) in devices.items():
            device_key = "mcp23017_{:02x}_{}".format(addr, pin)
            if device_key in self._pin_to_name:
                print("[GPIO] MCP23017 0x{:02x} 핀 {} 이미 사용 중 ({})".format(
                    addr, pin, self._pin_to_name[device_key]))
                continue
            try:
                # 같은 주소의 칩은 캐시하여 재사용
                expander_key = "mcp23017_{:02x}".format(addr)
                if not hasattr(self, "_mcp_cache"):
                    self._mcp_cache = {}
                if expander_key not in self._mcp_cache:
                    self._mcp_cache[expander_key] = MCP23017(i2c, addr)
                expander = self._mcp_cache[expander_key]
                self.i2c_gpio_devices[name] = (expander, pin)
                self._pin_to_name[device_key] = name
                self._last_gpio_state[name] = expander.pin_state(pin)
                initialized.append(name)
                print("[GPIO] {} 초기화 (MCP23017 0x{:02x} 핀 {})".format(name, addr, pin))
            except Exception as ex:
                print("[GPIO] {} (MCP23017 0x{:02x} 핀 {}) 초기화 실패: {}".format(
                    name, addr, pin, ex))
        return initialized

    def init_pcf8574(self, devices, sda=8, scl=9, freq=400000):
        """PCF8574 (I2C 8채널 GPIO 확장) 초기화.

        인자:
          devices: {이름: (i2c_addr, pin)} 딕셔너리
                   pin: 0-7
          sda, scl: I2C SDA/SCL 핀 번호
          freq: I2C 클럭 주파수 (기본 400kHz)
        """
        if not _HAS_MACHINE:
            return []
        initialized = []
        try:
            i2c = self._get_i2c(sda, scl, freq)
        except Exception as ex:
            print("[GPIO] PCF8574 I2C 초기화 실패: {}".format(ex))
            return []
        for name, (addr, pin) in devices.items():
            device_key = "pcf8574_{:02x}_{}".format(addr, pin)
            if device_key in self._pin_to_name:
                print("[GPIO] PCF8574 0x{:02x} 핀 {} 이미 사용 중 ({})".format(
                    addr, pin, self._pin_to_name[device_key]))
                continue
            try:
                # 같은 주소의 칩은 캐시하여 재사용
                expander_key = "pcf8574_{:02x}".format(addr)
                if not hasattr(self, "_pcf_cache"):
                    self._pcf_cache = {}
                if expander_key not in self._pcf_cache:
                    self._pcf_cache[expander_key] = PCF8574(i2c, addr)
                expander = self._pcf_cache[expander_key]
                self.i2c_gpio_devices[name] = (expander, pin)
                self._pin_to_name[device_key] = name
                self._last_gpio_state[name] = expander.pin_state(pin)
                initialized.append(name)
                print("[GPIO] {} 초기화 (PCF8574 0x{:02x} 핀 {})".format(name, addr, pin))
            except Exception as ex:
                print("[GPIO] {} (PCF8574 0x{:02x} 핀 {}) 초기화 실패: {}".format(
                    name, addr, pin, ex))
        return initialized

    # ============ I2C GPIO 확장 핀 제어 ============
    def i2c_gpio_on(self, name):
        """I2C GPIO 확장 핀을 HIGH 로 설정."""
        if name not in self.i2c_gpio_devices:
            return False
        expander, pin = self.i2c_gpio_devices[name]
        ok = expander.pin_on(pin)
        if ok:
            self._last_gpio_state[name] = 1
        return ok

    def i2c_gpio_off(self, name):
        """I2C GPIO 확장 핀을 LOW 로 설정."""
        if name not in self.i2c_gpio_devices:
            return False
        expander, pin = self.i2c_gpio_devices[name]
        ok = expander.pin_off(pin)
        if ok:
            self._last_gpio_state[name] = 0
        return ok

    def i2c_gpio_state(self, name):
        """I2C GPIO 확장 핀의 상태 반환 (0|1)."""
        if name not in self.i2c_gpio_devices:
            return -1
        if name in self._last_gpio_state:
            return self._last_gpio_state[name]
        expander, pin = self.i2c_gpio_devices[name]
        return expander.pin_state(pin)

    # ============ I2C GPIO 입력 핀 (센서용) ============
    def init_i2c_input(self, chip_type, devices, sda=8, scl=9, freq=400000, pullup=True):
        """I2C GPIO 확장 칩의 핀을 입력 모드로 설정 (센서용).

        인자:
          chip_type: "mcp23017" 또는 "pcf8574"
          devices: {이름: (i2c_addr, pin)} 딕셔너리
          sda, scl: I2C SDA/SCL 핀 번호
          freq: I2C 클럭 주파수
          pullup: 풀업 저항 활성화 (MCP23017만 지원, PCF8574는 외부 풀업 필요)

        반환:
          list: 초기화된 입력 핀 이름 목록
        """
        if not _HAS_MACHINE:
            return []
        initialized = []
        try:
            i2c = self._get_i2c(sda, scl, freq)
        except Exception as ex:
            print("[GPIO] I2C 입력 초기화 실패: {}".format(ex))
            return []

        for name, (addr, pin) in devices.items():
            try:
                chip_key = "{}_{:02x}".format(chip_type, addr)
                # 칩 객체 가져오기 (캐시에서 재사용)
                if chip_type == "mcp23017":
                    if not hasattr(self, "_mcp_cache"):
                        self._mcp_cache = {}
                    if chip_key not in self._mcp_cache:
                        self._mcp_cache[chip_key] = MCP23017(i2c, addr)
                    expander = self._mcp_cache[chip_key]
                elif chip_type == "pcf8574":
                    if not hasattr(self, "_pcf_cache"):
                        self._pcf_cache = {}
                    if chip_key not in self._pcf_cache:
                        self._pcf_cache[chip_key] = PCF8574(i2c, addr)
                    expander = self._pcf_cache[chip_key]
                else:
                    print("[GPIO] 알 수 없는 칩 타입: {}".format(chip_type))
                    continue

                # 핀을 입력 모드로 설정
                expander.set_pin_input(pin, pullup=pullup)
                self.i2c_input_devices[name] = (expander, pin, chip_type)
                initialized.append(name)
                print("[GPIO] {} 입력 핀 초기化 ({} 0x{:02x} 핀 {}, pullup={})".format(
                    name, chip_type, addr, pin, pullup))
            except Exception as ex:
                print("[GPIO] {} ({} 0x{:02x} 핀 {}) 입력 설정 실패: {}".format(
                    name, chip_type, addr, pin, ex))
        return initialized

    def read_i2c_input(self, name):
        """I2C 입력 핀의 값을 읽기 (0|1). 센서용."""
        if name not in self.i2c_input_devices:
            return None
        expander, pin, _ = self.i2c_input_devices[name]
        return expander.pin_read(pin)

    def get_i2c_input_device_list(self):
        """I2C 입력 핀 목록 반환 (센서용)."""
        devices = []
        for name in self.i2c_input_devices:
            expander, pin, chip_type = self.i2c_input_devices[name]
            value = expander.pin_read(pin)
            devices.append({
                "name": name,
                "type": "i2c_input",
                "chip": chip_type,
                "addr": expander.addr,
                "pin": pin,
                "value": value,
                "unit": "",
            })
        return devices

    # ============ NeoPixel 제어 ============
    def neopixel_set_color(self, name, r, g, b):
        """NeoPixel 색상 설정 (RGB 0-255)."""
        if name not in self.neopixel_devices:
            return False
        try:
            np = self.neopixel_devices[name]
            r = max(0, min(255, int(r)))
            g = max(0, min(255, int(g)))
            b = max(0, min(255, int(b)))
            for i in range(len(np)):
                np[i] = (r, g, b)
            np.write()
            self._last_neopixel[name] = (r, g, b)
            return True
        except Exception as ex:
            print("[GPIO] {} NeoPixel 색상 오류: {}".format(name, ex))
            return False

    def neopixel_off(self, name):
        """NeoPixel 끄기 (검정색)."""
        return self.neopixel_set_color(name, 0, 0, 0)

    def neopixel_state(self, name):
        """NeoPixel 마지막 색상 반환 (r, g, b)."""
        return self._last_neopixel.get(name, (0, 0, 0))

    def _parse_color(self, value):
        """값을 (r, g, b) 튜플로 변환.

        지원 형식:
          - 정수: 0xRRGGBB (예: 0xFF0000 = 빨강)
          - "r,g,b" 문자열: "255,0,0"
          - 0: OFF (검정)
          - 1: 흰색 (255,255,255)
        """
        if isinstance(value, str):
            if "," in value:
                parts = value.split(",")
                if len(parts) == 3:
                    try:
                        return (int(parts[0]), int(parts[1]), int(parts[2]))
                    except ValueError:
                        return None
            try:
                value = int(value, 0)  # 0x 접두사 허용
            except ValueError:
                return None
        if isinstance(value, int):
            if value == 0:
                return (0, 0, 0)
            if value == 1:
                return (255, 255, 255)
            # 0xRRGGBB 해석
            return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)
        return None

    # ============ 타이머 스위치 ============
    def gpio_on_timer(self, name, seconds):
        """GPIO/PWM/NeoPixel 을 켠 후 지정 시간(초) 후 자동으로 끔.

        인자:
          name: 장치 이름
          seconds: 타이머 시간 (초). 0 이하면 타이머 없음.
        """
        # 기존 타이머 취소
        self.cancel_timer(name)

        if seconds <= 0:
            return False

        expire = time.time() + seconds
        gm = self

        async def _timer_task():
            try:
                await asyncio.sleep(seconds)
                # 시간 경과 후 자동 OFF
                if name in gm.gpio_devices:
                    gm.gpio_off(name)
                elif name in gm.pwm_devices:
                    gm.pwm_off(name)
                elif name in gm.neopixel_devices:
                    gm.neopixel_off(name)
                gm._timers.pop(name, None)
                print("[GPIO] {} 타이머 만료 → 자동 OFF".format(name))
            except Exception as ex:
                print("[GPIO] {} 타이머 오류: {}".format(name, ex))
                gm._timers.pop(name, None)

        try:
            task = asyncio.create_task(_timer_task())
            self._timers[name] = (task, expire)
            return True
        except Exception as ex:
            print("[GPIO] 타이머 생성 오류: {}".format(ex))
            return False

    def cancel_timer(self, name):
        """장치의 활성 타이머 취소."""
        if name in self._timers:
            task, _ = self._timers.pop(name)
            try:
                task.cancel()
            except Exception:
                pass
            return True
        return False

    def get_timer_remaining(self, name):
        """장치의 타이머 남은 시간(초) 반환. 없으면 0."""
        if name not in self._timers:
            return 0
        _, expire = self._timers[name]
        remaining = expire - time.time()
        return max(0, int(remaining))

    # ============ 디지털 출력 제어 ============
    def gpio_on(self, name):
        # I2C GPIO 확장 핀
        if name in self.i2c_gpio_devices:
            return self.i2c_gpio_on(name)
        if name not in self.gpio_devices:
            return False
        try:
            self.gpio_devices[name].value(1)
            self._last_gpio_state[name] = 1  # 상태 추적
            return True
        except Exception as ex:
            print("[GPIO] {} ON 오류: {}".format(name, ex))
            return False

    def gpio_off(self, name):
        # I2C GPIO 확장 핀
        if name in self.i2c_gpio_devices:
            return self.i2c_gpio_off(name)
        if name not in self.gpio_devices:
            return False
        try:
            self.gpio_devices[name].value(0)
            self._last_gpio_state[name] = 0  # 상태 추적
            return True
        except Exception as ex:
            print("[GPIO] {} OFF 오류: {}".format(name, ex))
            return False

    def gpio_toggle(self, name):
        # I2C GPIO 확장 핀
        if name in self.i2c_gpio_devices:
            current = self._last_gpio_state.get(name, 0)
            if current == 1:
                return self.i2c_gpio_off(name)
            else:
                return self.i2c_gpio_on(name)
        if name not in self.gpio_devices:
            return False
        try:
            current = self._last_gpio_state.get(name, 0)
            new_state = 1 - current
            self.gpio_devices[name].value(new_state)
            self._last_gpio_state[name] = new_state
            return True
        except Exception as ex:
            print("[GPIO] {} 토글 오류: {}".format(name, ex))
            return False

    def gpio_state(self, name):
        # I2C GPIO 확장 핀
        if name in self.i2c_gpio_devices:
            return self.i2c_gpio_state(name)
        if name not in self.gpio_devices:
            return -1
        # 마지막으로 설정한 상태를 우선 반환 (핀 읽기 타이밍 문제 방지)
        if name in self._last_gpio_state:
            return self._last_gpio_state[name]
        try:
            return self.gpio_devices[name].value()
        except Exception:
            return -1

    # ============ PWM 제어 ============
    def pwm_set(self, name, duty):
        if name not in self.pwm_devices:
            return False
        try:
            duty = max(0, min(1023, int(duty)))
            self.pwm_devices[name].duty(duty)
            self._last_pwm_duty[name] = duty  # 상태 추적
            return True
        except Exception as ex:
            print("[GPIO] {} duty 오류: {}".format(name, ex))
            return False

    def pwm_set_percent(self, name, percent):
        duty = int(max(0, min(100, percent)) * 1023 / 100)
        return self.pwm_set(name, duty)

    def pwm_off(self, name):
        return self.pwm_set(name, 0)

    # ============ 장치 정보 ============
    def _get_pin_for_name(self, name):
        for pin, n in self._pin_to_name.items():
            if n == name:
                return pin
        return None

    def get_device_list(self):
        devices = []
        for name in self.gpio_devices:
            devices.append({
                "name": name, "type": "gpio",
                "pin": self._get_pin_for_name(name),
                "current_state": self.gpio_state(name),
                "timer_remaining": self.get_timer_remaining(name),
            })
        # I2C GPIO 확장 핀 (MCP23017/PCF8574)
        for name in self.i2c_gpio_devices:
            expander, pin = self.i2c_gpio_devices[name]
            chip_type = "mcp23017" if isinstance(expander, MCP23017) else "pcf8574"
            devices.append({
                "name": name, "type": "gpio",
                "chip": chip_type,
                "pin": pin,
                "current_state": self.gpio_state(name),
                "timer_remaining": self.get_timer_remaining(name),
            })
        for name in self.pwm_devices:
            # 마지막으로 설정한 duty를 우선 사용 (핀 읽기 타이밍 문제 방지)
            d = self._last_pwm_duty.get(name, 0)
            try:
                f = self.pwm_devices[name].freq()
            except Exception:
                f = 0
            devices.append({
                "name": name, "type": "pwm",
                "pin": self._get_pin_for_name(name),
                "current_duty": d, "current_freq": f,
                "timer_remaining": self.get_timer_remaining(name),
            })
        for name in self.neopixel_devices:
            r, g, b = self._last_neopixel.get(name, (0, 0, 0))
            devices.append({
                "name": name, "type": "neopixel",
                "pin": self._get_pin_for_name(name),
                "current_color": (r << 16) | (g << 8) | b,
                "current_r": r, "current_g": g, "current_b": b,
                "timer_remaining": self.get_timer_remaining(name),
            })
        return devices

    # ============ 브로드캐스트 ============
    async def broadcast_device_info(self):
        try:
            import espnow_mesh_pro as mesh
        except ImportError:
            try:
                import espnow_mesh_secure as mesh
            except ImportError:
                return False
        if not hasattr(mesh, "e") or mesh.e is None:
            return False
        devices = self.get_device_list()
        if not devices:
            return False
        try:
            msg = mesh.make_msg("device_info", {"devices": devices}, ttl=5)
            await mesh.send_mesh(msg)
            print("[GPIO] 장치 정보 브로드캐스트: {} 개".format(len(devices)))
        except Exception as ex:
            print("[GPIO] 브로드캐스트 오류: {}".format(ex))
        return True

    # ============ /GPIO 명령어 처리 ============
    async def handle_command(self, text, src_node_id=None):
        cmd = text.strip()
        if cmd.lower().startswith("/gpio "):
            cmd = cmd[6:].strip()
        elif cmd.lower() == "/gpio":
            cmd = ""

        if not cmd:
            return {"ok": True, "msg": "사용법: /GPIO <이름> <값> [타이머초] 또는 /GPIO list"}

        if cmd.lower() == "list":
            devices = self.get_device_list()
            return {"ok": True, "msg": "{} 개 장치 등록됨".format(len(devices)),
                    "data": {"devices": devices}}

        parts = cmd.split()
        if len(parts) < 2:
            return {"ok": False, "msg": "사용법: /GPIO <이름> <값> [타이머초]"}

        name = parts[0]
        value_str = parts[1]
        # 세 번째 인자는 타이머 (초, 선택사항)
        timer_sec = 0
        if len(parts) >= 3:
            try:
                timer_sec = int(parts[2])
            except ValueError:
                return {"ok": False, "msg": "타이머 값이 정수가 아님: {}".format(parts[2])}

        # NeoPixel 장치 처리 (값이 색상: 0xRRGGBB, "r,g,b", 0, 1)
        if name in self.neopixel_devices:
            color = self._parse_color(value_str)
            if color is None:
                return {"ok": False, "msg": "NeoPixel 색상 형식 오류: {} (예: 0xFF0000, 255,0,0, 0, 1)".format(value_str)}
            r, g, b = color
            self.neopixel_set_color(name, r, g, b)
            # 색상이 검정(0,0,0)이면 항상 타이머 취소 (OFF)
            if r == 0 and g == 0 and b == 0:
                self.cancel_timer(name)
            elif timer_sec > 0:
                # 색상이 설정되고 타이머가 지정된 경우 타이머 시작
                self.gpio_on_timer(name, timer_sec)
            else:
                # 색상이 변경되었지만 타이머 없음 - 기존 타이머 유지하지 않고 취소
                # (새 색상 설정 시 이전 타이머는 무의미하므로)
                self.cancel_timer(name)
            color_hex = (r << 16) | (g << 8) | b
            return {"ok": True, "msg": "{} NeoPixel #{:06X}".format(name, color_hex),
                    "data": {"name": name, "color": color_hex, "r": r, "g": g, "b": b,
                             "timer": timer_sec if (timer_sec > 0 and (r or g or b)) else None}}

        # GPIO 디지털 출력 (로컬 GPIO + I2C 확장 핀 MCP23017/PCF8574)
        if name in self.gpio_devices or name in self.i2c_gpio_devices:
            try:
                value = int(value_str)
            except ValueError:
                return {"ok": False, "msg": "GPIO 값은 0 또는 1: {}".format(value_str)}
            if value in (0, 1):
                if value == 1:
                    self.gpio_on(name)
                    # ON 일 때 타이머가 지정되면 시작, 없으면 기존 타이머 취소
                    if timer_sec > 0:
                        self.gpio_on_timer(name, timer_sec)
                    else:
                        self.cancel_timer(name)
                else:
                    self.gpio_off(name)
                    # OFF 시 항상 타이머 취소
                    self.cancel_timer(name)
                return {"ok": True, "msg": "{} {}".format(name, "ON" if value else "OFF"),
                        "data": {"name": name, "state": value,
                                 "timer": timer_sec if (timer_sec > 0 and value == 1) else None}}
            else:
                return {"ok": False, "msg": "{} 는 디지털 출력 (0 또는 1만 가능)".format(name)}

        # PWM 출력
        elif name in self.pwm_devices:
            try:
                value = int(value_str)
            except ValueError:
                try:
                    value = float(value_str)
                except ValueError:
                    return {"ok": False, "msg": "PWM 값이 숫자가 아님: {}".format(value_str)}
            if value > 100:
                self.pwm_set(name, value)
            else:
                self.pwm_set_percent(name, value)
            # duty가 0이면 항상 타이머 취소 (OFF)
            if value <= 0:
                self.cancel_timer(name)
            elif timer_sec > 0:
                # duty > 0 이고 타이머가 지정된 경우 타이머 시작
                self.gpio_on_timer(name, timer_sec)
            else:
                # duty 변경되었지만 타이머 없음 - 기존 타이머 취소
                self.cancel_timer(name)
            return {"ok": True, "msg": "{} PWM {}%".format(
                        name, value if value <= 100 else int(value / 1023 * 100)),
                    "data": {"name": name, "duty": value,
                             "timer": timer_sec if (timer_sec > 0 and value > 0) else None}}
        else:
            return {"ok": False, "msg": "알 수 없는 장치: {}".format(name)}

    # ============ 상태 조회 ============
    def status(self):
        print("\n[GPIO 상태]")
        if self.gpio_devices:
            print("  디지털 출력:")
            for name in self.gpio_devices:
                state = self.gpio_state(name)
                timer = self.get_timer_remaining(name)
                timer_str = " (타이머 {}초 남음)".format(timer) if timer > 0 else ""
                print("    {}: {} (GPIO {}){}".format(
                    name, "HIGH" if state == 1 else "LOW",
                    self._get_pin_for_name(name), timer_str))
        if self.i2c_gpio_devices:
            print("  I2C GPIO 확장:")
            for name in self.i2c_gpio_devices:
                expander, pin = self.i2c_gpio_devices[name]
                chip_type = "MCP23017" if isinstance(expander, MCP23017) else "PCF8574"
                state = self.gpio_state(name)
                timer = self.get_timer_remaining(name)
                timer_str = " (타이머 {}초 남음)".format(timer) if timer > 0 else ""
                print("    {}: {} ({} 0x{:02x} 핀 {}){}".format(
                    name, "HIGH" if state == 1 else "LOW",
                    chip_type, expander.addr, pin, timer_str))
        if self.pwm_devices:
            print("  PWM:")
            for name in self.pwm_devices:
                d = self._last_pwm_duty.get(name, 0)
                try:
                    f = self.pwm_devices[name].freq()
                except Exception:
                    f = 0
                timer = self.get_timer_remaining(name)
                timer_str = " (타이머 {}초 남음)".format(timer) if timer > 0 else ""
                print("    {}: freq={}Hz, duty={}/1023 ({:.1f}%) (GPIO {}){}".format(
                    name, f, d, d / 1023 * 100, self._get_pin_for_name(name), timer_str))
        if self.neopixel_devices:
            print("  NeoPixel:")
            for name in self.neopixel_devices:
                r, g, b = self._last_neopixel.get(name, (0, 0, 0))
                timer = self.get_timer_remaining(name)
                timer_str = " (타이머 {}초 남음)".format(timer) if timer > 0 else ""
                print("    {}: RGB({},{},{}) #{:06X} (GPIO {}){}".format(
                    name, r, g, b, (r << 16) | (g << 8) | b,
                    self._get_pin_for_name(name), timer_str))
        if not self.gpio_devices and not self.i2c_gpio_devices and not self.pwm_devices and not self.neopixel_devices:
            print("  초기화된 장치 없음")

    # ============ 메시 네트워크 핸들러 등록 ============
    def register_mesh_handler(self):
        try:
            import espnow_mesh_pro as mesh
        except ImportError:
            try:
                import espnow_mesh_secure as mesh
            except ImportError:
                print("[GPIO] espnow_mesh_pro/secure 가 import 되어야 함")
                return False

        if hasattr(mesh, "_original_handle_message_gpio"):
            print("[GPIO] 이미 핸들러 등록됨")
            return True

        original_handler = mesh.handle_message
        mesh._original_handle_message_gpio = original_handler

        gm = self  # 클로저로 self 참조

        async def wrapped_handler(host, msg):
            msg_type = msg.get("type", "")
            data = msg.get("data", {})
            text = data.get("text", "") if msg_type == "chat" else ""
            text_stripped = text.strip()
            is_gpio_cmd = text_stripped.lower().startswith("/gpio")

            if msg_type == "device_info":
                await gm._handle_device_info(mesh, msg)
                return

            await original_handler(host, msg)

            if is_gpio_cmd and msg.get("src") != mesh.cfg.NODE_ID:
                try:
                    cmd_text = text.strip()
                    for prefix in ["[웹] ", "[외부] "]:
                        if cmd_text.startswith(prefix):
                            cmd_text = cmd_text[len(prefix):]
                            break
                    print("\n[GPIO] 원격 명령 수신: '{}'".format(cmd_text))
                    result = await gm.handle_command(cmd_text, msg.get("src"))
                    response = "[GPIO] {}".format(result["msg"])
                    await mesh.send_chat(response)
                    if result.get("ok") and result.get("data"):
                        await gm.broadcast_device_info()
                except Exception as ex:
                    print("[GPIO] 명령 처리 오류:", ex)
                    await mesh.send_chat("[GPIO] 오류: {}".format(ex))

        mesh.handle_message = wrapped_handler

        loop = asyncio.get_event_loop()
        loop.create_task(self._periodic_broadcast())
        print("[GPIO] 메시 네트워크 핸들러 등록 완료")
        print("[GPIO] 명령어: /GPIO <이름> <0|1|PWM값>, /GPIO list")
        return True

    async def _handle_device_info(self, mesh, msg):
        from mesh_config import cfg
        if cfg.NODE_ROLE != "gateway":
            return
        src = msg.get("src", "???")
        data = msg.get("data", {})
        devices = data.get("devices", [])
        # mesh.device_registry 싱글톤 인스턴스 사용
        if not hasattr(mesh, "device_registry"):
            return
        mesh.device_registry.add(src, {
            "nick": msg.get("nick", src),
            "last_seen": time.time(),
            "devices": devices,
        })
        print("[GPIO] 장치 정보 수신: {} ({}개 장치)".format(src, len(devices)))

    async def _periodic_broadcast(self):
        while True:
            await asyncio.sleep(120)
            try:
                await self.broadcast_device_info()
            except Exception as ex:
                print("[GPIO] 주기 브로드캐스트 오류:", ex)

    def unregister_mesh_handler(self):
        try:
            import espnow_mesh_pro as mesh
        except ImportError:
            try:
                import espnow_mesh_secure as mesh
            except ImportError:
                return False
        if hasattr(mesh, "_original_handle_message_gpio"):
            mesh.handle_message = mesh._original_handle_message_gpio
            del mesh._original_handle_message_gpio
            print("[GPIO] 메시 네트워크 핸들러 해제")
            return True
        return False


# 싱글톤 인스턴스
gm = GPIOManager()
