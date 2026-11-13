"""
sensor_runner.py - 센서 관리 클래스 (ESP32-S3)
=============================================
모든 센서 기능과 변수를 SensorManager 클래스로 통합.

사용법:
  import sensor_runner
  sm = sensor_runner.sm  # 싱글톤 인스턴스

  sm.init_sensors({"거실온도": ("dht", 4, "temp")})
  data = sm.read_all()
  sm.start_periodic(10, 30)
  sm.stop_periodic()
  sm.status()
  devices = sm.get_device_list()
"""

import time

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

try:
    import dht
    _HAS_DHT = True
except ImportError:
    _HAS_DHT = False

try:
    from machine import Pin, I2C, ADC, SPI
    _HAS_MACHINE = True
except ImportError:
    _HAS_MACHINE = False

try:
    import bh1750
    _HAS_BH1750 = True
except ImportError:
    _HAS_BH1750 = False

try:
    import bme280
    _HAS_BME280 = True
except ImportError:
    _HAS_BME280 = False

try:
    import onewire, ds18x20
    _HAS_ONEWIRE = True
except ImportError:
    _HAS_ONEWIRE = False

try:
    import sgp30
    _HAS_SGP30 = True
except ImportError:
    _HAS_SGP30 = False

try:
    from neopixel import NeoPixel
    _HAS_NEOPIXEL = True
except ImportError:
    _HAS_NEOPIXEL = False

# math (roll/pitch/amag 계산용)
try:
    import math
    _HAS_MATH = True
except ImportError:
    _HAS_MATH = False

# ADS1115 (외부 라이브러리 사용 시, 없으면 직접 I2C 제어)
try:
    import ads1115 as _ads1115
    _HAS_ADS1115 = True
except ImportError:
    _HAS_ADS1115 = False


# ============ ADS1115 I2C ADC 직접 제어 (외부 라이브러리 없이) ============
# ADS1115 레지스터
_ADS1115_CONV = 0x00    # 변환 레지스터 (읽기)
_ADS1115_CONFIG = 0x01  # 설정 레지스터
_ADS1115_MUX = {        # 채널 선택 (MUX 비트 [14:12])
    0: 0x4000,  # AIN0 vs GND
    1: 0x5000,  # AIN1 vs GND
    2: 0x6000,  # AIN2 vs GND
    3: 0x7000,  # AIN3 vs GND
}
_ADS1115_PGA = {        # 게인 설정 (PGA 비트 [11:9])
    2/3: 0x0000,  # ±6.144V
    1: 0x0200,    # ±4.096V
    2: 0x0400,    # ±2.048V
    4: 0x0600,    # ±1.024V
    8: 0x0800,    # ±0.512V
    16: 0x0A00,   # ±0.256V
}


class ADS1115:
    """ADS1115 4채널 16비트 I2C ADC (직접 I2C 레지스터 제어).

    외부 라이브러리 없이 동작.
    사용법:
      adc = ADS1115(i2c, 0x48)
      raw = adc.read_raw(0)       # 채널 0 raw 값 (0-32767)
      volt = adc.read_voltage(0)  # 채널 0 전압 (V)
    """

    def __init__(self, i2c, addr=0x48, gain=1):
        self.i2c = i2c
        self.addr = addr
        self.gain = gain
        self.pga = _ADS1115_PGA.get(gain, 0x0200)  # 기본 ±4.096V
        # 게인별 풀스케일 전압
        self.fs_voltage = {2/3: 6.144, 1: 4.096, 2: 2.048, 4: 1.024, 8: 0.512, 16: 0.256}
        self.vref = self.fs_voltage.get(gain, 4.096)

    def read_raw(self, channel):
        """지정 채널의 raw 값을 읽기 (0-32767, 16비트 부호있음).

        인자:
          channel: 0-3
        """
        if channel not in _ADS1115_MUX:
            return None
        try:
            # 설정 레지스터 작성
            # OS[15]=1 (단일 변환 시작)
            # MUX[14:12] = 채널
            # PGA[11:9] = 게인
            # MODE[8]=1 (단일 변환 모드)
            # DR[7:5]=100 (128 SPS)
            config = 0x8000 | _ADS1115_MUX[channel] | self.pga | 0x0100 | 0x0080
            # 쓰기: 레지스터 주소 + 상위 바이트 + 하위 바이트
            self.i2c.writeto(self.addr, bytes([_ADS1115_CONFIG, (config >> 8) & 0xFF, config & 0xFF]))
            # 변환 완료 대기 (최대 10ms)
            time.sleep_ms(10)
            # 변환 결과 읽기
            self.i2c.writeto(self.addr, bytes([_ADS1115_CONV]))
            data = self.i2c.readfrom(self.addr, 2)
            raw = (data[0] << 8) | data[1]
            # 부호 처리 (16비트 signed)
            if raw >= 0x8000:
                raw -= 0x10000
            return raw
        except Exception as ex:
            print("[SENSOR] ADS1115 채널 {} 읽기 오류: {}".format(channel, ex))
            return None

    def read_voltage(self, channel):
        """지정 채널의 전압을 읽기 (V).

        인자:
          channel: 0-3
        """
        raw = self.read_raw(channel)
        if raw is None:
            return None
        # raw 값(-32768~32767)을 전압으로 변환
        return round(raw * self.vref / 32767, 4)


class SensorManager:

    def __init__(self):
        self.devices = {}           # {이름: {type, pin, channel, unit, sensor}}
        self._objects = {}           # {(type, key): obj}
        self._buffer = {}            # {이름: [(ts, value), ...]}
        self._task = None
        self._running = False
        self.i2c_bus = None
        self.spi_bus = None
        self.onewire_buses = {}
        self.onewire_roms = {}
        self._neopixel_counts = {}
        self._mpu_yaw_state = {}   # {i2c_addr: {"yaw": float, "ts": ms}} - 자이로 yaw 적분
        self.node_id = "unknown"
        self.nickname = "unknown"

    # ============ 버스 초기화 ============
    def init_i2c(self, sda=8, scl=9, freq=100000):
        if not _HAS_MACHINE:
            return False
        if self.i2c_bus is not None:
            return True
        try:
            self.i2c_bus = I2C(0, scl=Pin(scl), sda=Pin(sda), freq=freq)
            print("[SENSOR] I2C 버스 초기화 (SDA={}, SCL={})".format(sda, scl))
            return True
        except Exception as ex:
            print("[SENSOR] I2C 초기화 오류:", ex)
            return False

    def init_spi(self, baudrate=1000000, sck=14, mosi=13, miso=12):
        if not _HAS_MACHINE:
            return False
        if self.spi_bus is not None:
            return True
        try:
            self.spi_bus = SPI(1, baudrate=baudrate, polarity=0, phase=0,
                               sck=Pin(sck), mosi=Pin(mosi), miso=Pin(miso))
            print("[SENSOR] SPI 버스 초기화")
            return True
        except Exception as ex:
            print("[SENSOR] SPI 초기화 오류:", ex)
            return False

    def init_onewire(self, pin):
        if not _HAS_MACHINE or not _HAS_ONEWIRE:
            return False
        if pin in self.onewire_buses:
            return True
        try:
            ow = onewire.OneWire(Pin(pin))
            ds = ds18x20.DS18X20(ow)
            roms = ds.scan()
            self.onewire_buses[pin] = ds
            self.onewire_roms[pin] = roms
            print("[SENSOR] 1-Wire 초기화 (GPIO {}): {}개".format(pin, len(roms)))
            return True
        except Exception as ex:
            print("[SENSOR] 1-Wire 초기화 오류:", ex)
            return False

    # ============ 센서 초기화 ============
    def init_sensors(self, config):
        self.devices = {}
        self._objects = {}
        self._neopixel_counts = {}
        print("[SENSOR] 센서 초기화 (이름 기반, 다중 버스)")
        print("[SENSOR] 등록된 장치:")
        for name, spec in config.items():
            try:
                stype = spec[0]
                pin_or_addr = spec[1]
                channel = spec[2]
                unit = spec[3] if len(spec) > 3 else self._default_unit(stype, channel)
                if stype == "neopixel":
                    self._neopixel_counts[pin_or_addr] = channel if isinstance(channel, int) else 8

                # I2C GPIO 입력 핀 (MCP23017/PCF8574) 특별 처리
                if stype == "i2c_input":
                    # spec: (type, chip_type, (addr, pin), unit)
                    # 또는 (type, chip_type, addr, pin) - 호환성
                    chip_type = pin_or_addr  # 두 번째 요소가 chip_type
                    if isinstance(channel, (tuple, list)) and len(channel) == 2:
                        addr, pin = channel[0], channel[1]
                    elif isinstance(channel, int) and isinstance(unit, int):
                        # 구 형식: (type, chip, addr, pin, unit)
                        addr = channel
                        pin = unit
                        unit = ""
                    else:
                        print("  - {}: i2c_input 형식 오류 (chip, (addr, pin) 필요)".format(name))
                        continue
                    try:
                        import gpio_control
                        gpio_control.gm.init_i2c_input(
                            chip_type, {name: (addr, pin)},
                            sda=getattr(self, "_i2c_sda", 8),
                            scl=getattr(self, "_i2c_scl", 9),
                        )
                        self.devices[name] = {"type": stype, "chip": chip_type,
                                               "addr": addr, "pin": pin, "unit": unit}
                        print("  - {}: i2c_input ({} 0x{:02x} 핀 {}, unit={})".format(
                            name, chip_type, addr, pin, unit))
                    except Exception as ex:
                        print("  - {}: i2c_input 초기화 오류: {}".format(name, ex))
                    continue

                obj = self._get_or_create(stype, pin_or_addr)
                if obj is None:
                    print("  - {}: 초기화 실패 ({})".format(name, stype))
                    continue
                self.devices[name] = {"type": stype, "pin": pin_or_addr,
                                       "channel": channel, "unit": unit, "sensor": obj}
                print("  - {}: {} (pin={}, ch={}, unit={})".format(name, stype, pin_or_addr, channel, unit))
            except Exception as ex:
                print("  - {}: 초기화 오류: {}".format(name, ex))
        print("[SENSOR] 활성 센서: {} 개".format(len(self.devices)))
        return len(self.devices)

    def _default_unit(self, stype, channel):
        defaults = {
            ("dht", "temp"): "C", ("dht", "humidity"): "%",
            ("bh1750", "lux"): "lx",
            ("bme280", "temp"): "C", ("bme280", "humidity"): "%", ("bme280", "pressure"): "hPa",
            ("sht30", "temp"): "C", ("sht30", "humidity"): "%",
            ("max6675", "temp"): "C",
            ("adc", "raw"): "", ("adc", "voltage"): "V",
            ("sgp30", "co2"): "ppm", ("sgp30", "tvoc"): "ppb",
            ("mpu6050", "ax"): "g", ("mpu6050", "ay"): "g", ("mpu6050", "az"): "g",
            ("mpu6050", "gx"): "dps", ("mpu6050", "gy"): "dps", ("mpu6050", "gz"): "dps",
            ("mpu6050", "temp"): "C",
            ("mpu6050", "roll"): "deg", ("mpu6050", "pitch"): "deg",
            ("mpu6050", "amag"): "g", ("mpu6050", "gyaw"): "deg", ("neopixel", "count"): "",
            ("i2c_input", "state"): "",
            ("ads1115", "raw"): "", ("ads1115", "voltage"): "V",
        }
        if stype == "ds18b20":
            return "C"
        if stype == "mcp3008":
            return ""
        return defaults.get((stype, channel), "")

    def _get_or_create(self, stype, pin_or_addr):
        key = (stype, pin_or_addr)
        if key in self._objects:
            return self._objects[key]
        if not _HAS_MACHINE:
            return None
        try:
            if stype == "dht":
                if not _HAS_DHT:
                    return None
                obj = dht.DHT22(Pin(pin_or_addr))
                time.sleep_ms(100)
                obj.measure()
                self._objects[key] = obj
                print("[SENSOR] DHT22 초기화 (GPIO {})".format(pin_or_addr))
                return obj
            elif stype == "bh1750":
                if not _HAS_BH1750:
                    return None
                if self.i2c_bus is None:
                    if not self.init_i2c():
                        return None
                obj = bh1750.BH1750(self.i2c_bus, addr=pin_or_addr)
                self._objects[key] = obj
                print("[SENSOR] BH1750 초기화 (0x{:02x})".format(pin_or_addr))
                return obj
            elif stype == "bme280":
                if not _HAS_BME280:
                    return None
                if self.i2c_bus is None:
                    if not self.init_i2c():
                        return None
                obj = bme280.BME280(i2c=self.i2c_bus, address=pin_or_addr)
                self._objects[key] = obj
                print("[SENSOR] BME280 초기화 (0x{:02x})".format(pin_or_addr))
                return obj
            elif stype == "sht30":
                if self.i2c_bus is None:
                    if not self.init_i2c():
                        return None
                self._objects[key] = self.i2c_bus
                print("[SENSOR] SHT30 초기화 (0x{:02x})".format(pin_or_addr))
                return self.i2c_bus
            elif stype == "ds18b20":
                if not _HAS_ONEWIRE:
                    return None
                if pin_or_addr not in self.onewire_buses:
                    if not self.init_onewire(pin_or_addr):
                        return None
                obj = self.onewire_buses[pin_or_addr]
                self._objects[key] = obj
                return obj
            elif stype == "max6675":
                if self.spi_bus is None:
                    if not self.init_spi():
                        return None
                cs = Pin(pin_or_addr, Pin.OUT, value=1)
                self._objects[key] = cs
                print("[SENSOR] MAX6675 초기화 (CS={})".format(pin_or_addr))
                return cs
            elif stype == "mcp3008":
                if self.spi_bus is None:
                    if not self.init_spi():
                        return None
                cs = Pin(pin_or_addr, Pin.OUT, value=1)
                self._objects[key] = cs
                print("[SENSOR] MCP3008 초기화 (CS={})".format(pin_or_addr))
                return cs
            elif stype == "sgp30":
                if not _HAS_SGP30:
                    return None
                if self.i2c_bus is None:
                    if not self.init_i2c():
                        return None
                obj = sgp30.SGP30(self.i2c_bus)
                try:
                    obj.iaq_init()
                    obj.iaq_measure_co2_eq()
                except Exception:
                    pass
                self._objects[key] = obj
                print("[SENSOR] SGP30 초기화")
                return obj
            elif stype == "mpu6050":
                if self.i2c_bus is None:
                    if not self.init_i2c():
                        return None
                try:
                    # PWR_MGMT_1=0: 절전 해제, 내부 8MHz 클럭 사용
                    self.i2c_bus.writeto(pin_or_addr, bytes([0x6B, 0]))
                    time.sleep_ms(100)
                    # ACCEL_CONFIG=0: ±2g (1g = 16384 LSB)
                    self.i2c_bus.writeto(pin_or_addr, bytes([0x1C, 0x00]))
                    # GYRO_CONFIG=0: ±250 dps (1 dps = 131 LSB)
                    self.i2c_bus.writeto(pin_or_addr, bytes([0x1B, 0x00]))
                    # CONFIG=3: DLPF 설정 3 (대역폭 ~44Hz, 노이즈 감소)
                    self.i2c_bus.writeto(pin_or_addr, bytes([0x1A, 0x03]))
                    # SMPLRT_DIV=0: 샘플링 1kHz
                    self.i2c_bus.writeto(pin_or_addr, bytes([0x19, 0x00]))
                except Exception as ex:
                    print("[SENSOR] MPU6050 초기화 오류:", ex)
                    return None
                self._objects[key] = self.i2c_bus
                print("[SENSOR] MPU6050 초기화 (0x{:02x}, ±2g/±250dps, DLPF=3)".format(pin_or_addr))
                return self.i2c_bus
            elif stype == "neopixel":
                if not _HAS_NEOPIXEL:
                    return None
                count = self._neopixel_counts.get(pin_or_addr, 8)
                np = NeoPixel(Pin(pin_or_addr), count)
                self._objects[key] = np
                print("[SENSOR] NeoPixel 초기화 (GPIO {}, {} 픽셀)".format(pin_or_addr, count))
                return np
            elif stype == "adc":
                obj = ADC(Pin(pin_or_addr))
                obj.atten(ADC.ATTN_11DB)
                obj.width(ADC.WIDTH_12BIT)
                self._objects[key] = obj
                print("[SENSOR] ADC 초기화 (GPIO {})".format(pin_or_addr))
                return obj
            elif stype == "ads1115":
                # ADS1115 I2C ADC 모듈
                # spec: (type, i2c_addr, channel, unit) 또는 (type, i2c_addr, channel)
                # channel: 0-3 (ADC 채널 번호)
                # pin_or_addr = i2c_addr (0x48-0x4B)
                # 같은 주소의 ADS1115는 1개 객체로 재사용
                ads_key = ("ads1115_dev", pin_or_addr)
                if ads_key not in self._objects:
                    if self.i2c_bus is None:
                        if not self.init_i2c():
                            return None
                    # 게인: channel이 정수이면 기본 gain=1 (±4.096V)
                    # 또는 node_config에서 ADS1115_GAIN 설정 가능
                    gain = getattr(self, "_ads1115_gain", 1)
                    ads_obj = ADS1115(self.i2c_bus, addr=pin_or_addr, gain=gain)
                    self._objects[ads_key] = ads_obj
                    print("[SENSOR] ADS1115 초기화 (0x{:02x}, gain={})".format(pin_or_addr, gain))
                return self._objects[ads_key]
        except Exception as ex:
            print("[SENSOR] {} 초기화 오류: {}".format(stype, ex))
            return None
        return None

    # ============ 센서 읽기 ============
    def read(self, name):
        if name not in self.devices:
            return None
        dev = self.devices[name]
        stype = dev["type"]
        channel = dev.get("channel", "")
        sensor = dev.get("sensor")
        pin_or_addr = dev.get("pin")
        try:
            if stype == "dht":
                sensor.measure()
                time.sleep_ms(20)
                if channel == "temp":
                    return round(sensor.temperature(), 1)
                elif channel == "humidity":
                    return round(sensor.humidity(), 1)
            elif stype == "bh1750":
                lux = sensor.luminance(bh1750.ONCE_HIRES_1)
                if channel == "lux":
                    return round(lux, 1)
            elif stype == "bme280":
                t, p, h = sensor.values()
                if channel == "temp":
                    return round(t, 1)
                elif channel == "humidity":
                    return round(h, 1)
                elif channel == "pressure":
                    return round(p, 1)
            elif stype == "sht30":
                sensor.writeto(pin_or_addr, bytes([0x2C, 0x06]))
                time.sleep_ms(20)
                data = sensor.readfrom(pin_or_addr, 6)
                t_raw = (data[0] << 8) | data[1]
                temp = -45 + 175 * t_raw / 65535
                h_raw = (data[3] << 8) | data[4]
                humi = 100 * h_raw / 65535
                if channel == "temp":
                    return round(temp, 1)
                elif channel == "humidity":
                    return round(humi, 1)
            elif stype == "ds18b20":
                roms = self.onewire_roms.get(pin_or_addr, [])
                if not roms or channel >= len(roms):
                    return None
                sensor.convert_temp()
                time.sleep_ms(750)
                return round(sensor.read_temp(roms[channel]), 1)
            elif stype == "max6675":
                mosi_buf = bytearray([0x00, 0x00])
                miso_buf = bytearray(2)
                sensor.value(0)
                self.spi_bus.write_readinto(mosi_buf, miso_buf)
                sensor.value(1)
                raw = (miso_buf[0] << 8) | miso_buf[1]
                if raw & 0x4:
                    return None
                return round((raw >> 3) * 0.25, 2)
            elif stype == "mcp3008":
                cmd_byte = 0b11000000 | (channel << 3)
                mosi_buf = bytearray([cmd_byte, 0x00, 0x00])
                miso_buf = bytearray(3)
                sensor.value(0)
                self.spi_bus.write_readinto(mosi_buf, miso_buf)
                sensor.value(1)
                return ((miso_buf[1] & 0x03) << 8) | miso_buf[2]
            elif stype == "adc":
                raw = sensor.read()
                if channel == "raw":
                    return raw
                elif channel == "voltage":
                    return round(raw * 3.3 / 4095, 3)
            elif stype == "ads1115":
                # channel: 정수 0-3 (ADS1115 ADC 채널)
                # unit: "voltage" (기본, V) 또는 "raw" (0-32767)
                ads_channel = channel if isinstance(channel, int) else 0
                unit = dev.get("unit", "voltage")
                if unit == "raw":
                    return sensor.read_raw(ads_channel)
                else:
                    return sensor.read_voltage(ads_channel)
            elif stype == "sgp30":
                co2, tvoc = sensor.iaq_measure_co2_eq()
                if channel == "co2":
                    return co2
                elif channel == "tvoc":
                    return tvoc
            elif stype == "mpu6050":
                # 같은 디바이스의 여러 채널(ax/ay/.../gyaw)이 한 번의 I2C 읽기 공유
                # 500ms 이내 캐시 재사용 → I2C 버스 부하 감소 + 채널 간 일관성
                cache_key = ("mpu6050_data", pin_or_addr)
                now_ms = time.ticks_ms()
                cache = self._objects.get(cache_key)
                if cache is not None and abs(time.ticks_diff(now_ms, cache["ts"])) < 500:
                    m = cache["m"]
                else:
                    sensor.writeto(pin_or_addr, bytes([0x3B]))
                    data = sensor.readfrom(pin_or_addr, 14)
                    def s16(d, i):
                        v = (d[i] << 8) | d[i + 1]
                        return v - 65536 if v >= 32768 else v
                    ax_r, ay_r, az_r = s16(data, 0), s16(data, 2), s16(data, 4)
                    t_raw = s16(data, 6)
                    gx_r, gy_r, gz_r = s16(data, 8), s16(data, 10), s16(data, 12)
                    ax_g = ax_r / 16384
                    ay_g = ay_r / 16384
                    az_g = az_r / 16384
                    gx_d = gx_r / 131
                    gy_d = gy_r / 131
                    gz_d = gz_r / 131
                    # 가속도 기반 기울기 (roll/pitch) + 가속도 크기 (amag)
                    roll = 0.0
                    pitch = 0.0
                    amag = 0.0
                    if _HAS_MATH:
                        roll = math.degrees(math.atan2(ay_g, az_g))
                        pitch = math.degrees(math.atan2(-ax_g, math.sqrt(ay_g * ay_g + az_g * az_g)))
                        amag = math.sqrt(ax_g * ax_g + ay_g * ay_g + az_g * az_g)
                    # 자이로 적분 yaw (상대 방위각, drift 발생 - 절대각 아님)
                    yaw_state = self._mpu_yaw_state.get(pin_or_addr)
                    if yaw_state is None:
                        dt = 0.0
                        new_yaw = 0.0
                    else:
                        dt = time.ticks_diff(now_ms, yaw_state["ts"]) / 1000.0
                        if dt < 0 or dt > 10:
                            dt = 0.0
                        new_yaw = yaw_state["yaw"] + gz_d * dt
                    self._mpu_yaw_state[pin_or_addr] = {"yaw": new_yaw, "ts": now_ms}
                    m = {"ax": ax_g, "ay": ay_g, "az": az_g,
                         "gx": gx_d, "gy": gy_d, "gz": gz_d,
                         "temp": t_raw / 340 + 36.53,
                         "roll": roll, "pitch": pitch, "amag": amag,
                         "gyaw": new_yaw}
                    self._objects[cache_key] = {"ts": now_ms, "m": m}
                if channel in m:
                    v = m[channel]
                    if channel in ("ax", "ay", "az", "amag"):
                        return round(v, 3)
                    if channel in ("gx", "gy", "gz"):
                        return round(v, 2)
                    if channel in ("roll", "pitch", "gyaw"):
                        return round(v, 1)
                    if channel == "temp":
                        return round(v, 1)
                    return round(v, 2)
            elif stype == "neopixel":
                if channel == "count":
                    return self._neopixel_counts.get(pin_or_addr, 0)
            elif stype == "i2c_input":
                # I2C GPIO 확장 칩 입력 핀 읽기 (MCP23017/PCF8574)
                import gpio_control
                val = gpio_control.gm.read_i2c_input(name)
                return val
        except Exception as ex:
            print("[SENSOR] {} 읽기 오류: {}".format(name, ex))
            return None
        return None

    def read_all(self):
        result = {}
        for name in self.devices:
            value = self.read(name)
            if value is not None:
                result[name] = value
        return result

    def reset_mpu_yaw(self, i2c_addr=None):
        """MPU6050 자이로 yaw 적분값을 0으로 재설정 (재보정용).

        인자:
          i2c_addr: 특정 주소만 리셋. None이면 등록된 모든 MPU6050 리셋.
        """
        if i2c_addr is not None:
            if i2c_addr in self._mpu_yaw_state:
                self._mpu_yaw_state[i2c_addr]["yaw"] = 0.0
                print("[SENSOR] MPU6050 0x{:02x} yaw 리셋".format(i2c_addr))
        else:
            for addr in self._mpu_yaw_state:
                self._mpu_yaw_state[addr]["yaw"] = 0.0
            print("[SENSOR] 모든 MPU6050 yaw 리셋 ({}개)".format(len(self._mpu_yaw_state)))

    # ============ 장치 정보 ============
    def get_device_list(self):
        devices = []
        for name, dev in self.devices.items():
            devices.append({
                "name": name, "type": "sensor",
                "sensor_type": dev["type"], "channel": dev["channel"],
                "unit": dev["unit"],
            })
        return devices

    # ============ 메시 전송 ============
    async def broadcast_device_info(self):
        try:
            import espnow_mesh_pro as mesh
        except ImportError:
            try:
                import espnow_mesh_secure as mesh
            except ImportError:
                return False
        devices = self.get_device_list()
        if not devices:
            return False
        try:
            msg = mesh.make_msg("device_info", {"devices": devices}, ttl=5)
            result = await mesh.send_mesh(msg)
            if result:
                print("[SENSOR] 장치 정보 브로드캐스트: {} 개".format(len(devices)))
        except Exception as ex:
            print("[SENSOR] 브로드캐스트 오류: {}".format(ex))
        return True

    async def send_to_mesh(self, sensor_data):
        if not sensor_data:
            return False
        try:
            import espnow_mesh_pro as mesh
        except ImportError:
            try:
                import espnow_mesh_secure as mesh
            except ImportError:
                return False
        for name, value in sensor_data.items():
            unit = self.devices.get(name, {}).get("unit", "")
            try:
                await mesh.send_sensor(name, value, unit)
            except Exception as ex:
                print("[SENSOR] 전송 오류 ({}): {}".format(name, ex))
        # sensor_store 에 저장 (자기 자신의 센서 데이터)
        try:
            if hasattr(mesh, "store_sensor"):
                from mesh_config import cfg
                nid = cfg.NODE_ID
                nick = cfg.NICKNAME
                for name, value in sensor_data.items():
                    unit = self.devices.get(name, {}).get("unit", "")
                    mesh.store_sensor(nid, nick, name, value, unit)
        except Exception as ex:
            print("[SENSOR] sensor_store 저장 오류: {}".format(ex))
        return True

    # ============ 주기적 전송 ============
    async def periodic_loop(self, read_interval=10, send_interval=30):
        print("[SENSOR] 주기적 전송 시작 (읽기 {}초, 전송 {}초)".format(read_interval, send_interval))
        await self.broadcast_device_info()
        await asyncio.sleep(2)
        last_send = 0
        last_broadcast = time.time()
        count = 0
        self._running = True
        while self._running:
            try:
                data = self.read_all()
                if data:
                    ts = time.time()
                    for name, value in data.items():
                        if name not in self._buffer:
                            self._buffer[name] = []
                        self._buffer[name].append((ts, value))
                        if len(self._buffer[name]) > 10:
                            self._buffer[name] = self._buffer[name][-10:]
                    count += 1
                now = time.time()
                if now - last_send >= send_interval and self._buffer:
                    avg = {}
                    for name, hist in self._buffer.items():
                        vals = [v for _, v in hist]
                        avg[name] = round(sum(vals) / len(vals), 2)
                    await self.send_to_mesh(avg)
                    # 마지막 값 유지 (버퍼를 완전히 비우지 않음)
                    # → 웹 대시보드에서 센서 데이터가 깜빡이지 않음
                    for name in self._buffer:
                        if self._buffer[name]:
                            last_val = self._buffer[name][-1]
                            self._buffer[name] = [last_val]
                    last_send = now
                if now - last_broadcast >= 120:
                    await self.broadcast_device_info()
                    last_broadcast = now
                await asyncio.sleep(read_interval)
            except Exception as ex:
                print("[SENSOR] 루프 오류:", ex)
                await asyncio.sleep(5)
        print("[SENSOR] 주기적 전송 종료")

    def start_periodic(self, read_interval=10, send_interval=30):
        if self._task is not None and not self._task.done():
            print("[SENSOR] 이미 실행 중")
            return self._task
        if not self.devices:
            print("[SENSOR] 등록된 센서 없음")
            return None
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self.periodic_loop(read_interval, send_interval))
        print("[SENSOR] 백그라운드 태스크 시작")
        return self._task

    def stop_periodic(self):
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        print("[SENSOR] 주기적 전송 중지")

    # ============ 상태 조회 ============
    def status(self):
        print("\n[센서 상태]")
        if not self.devices:
            print("  등록된 센서 없음")
            return
        for name, dev in self.devices.items():
            print("  - {} [{}] pin={} ch={} unit={}".format(
                name, dev["type"], dev["pin"], dev["channel"], dev["unit"]))
        print("  주기 전송: {}".format("실행 중" if self._running else "중지"))


# 싱글톤 인스턴스
sm = SensorManager()
