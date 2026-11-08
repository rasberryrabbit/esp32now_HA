"""
센서 데이터 → 메시 네트워크 전송 예제 (ESP32-S3)
================================================
espnow_mesh_pro.py (또는 espnow_mesh_secure.py) 가 이미 실행 중인 상태에서
이 스크립트를 import 하면 다양한 센서를 주기적으로 읽어 메시 네트워크로 전송합니다.

지원 센서 (자동 감지, 없으면 건너뜀):
  1. DHT22 / DHT11 (온도/습도) - GPIO 4
  2. BH1750 (조도) - I2C (SDA=GPIO 8, SCL=GPIO 9)
  3. ADC (아날로그 입력) - GPIO 1 (ESP32-S3 ADC1_CH0)

사용 방법:
  방법 1: REPL에서 직접 import
    >>> import sensor_example
    >>> sensor_example.start()        # 백그라운드 실행
    >>> sensor_example.stop()         # 중지

  방법 2: espnow_mesh_pro.py 의 main() 안에서 함께 실행
    espnow_mesh_pro.py 의 main() 마지막에 추가:
        import sensor_example
        await sensor_example.sensor_loop()

와이어링 (ESP32-S3):
  DHT22:
    - VCC → 3.3V
    - GND → GND
    - DATA → GPIO 4
    - (DHT22 모듈의 풀업 저자 10kΩ 이미 내장)
  BH1750 (I2C):
    - VCC → 3.3V
    - GND → GND
    - SDA → GPIO 8
    - SCL → GPIO 9
    - ADDR → GND (I2C 주소 0x23)
  ADC (가변저항, CdS 셀 등):
    - 한쪽 끝 → 3.3V
    - 다른 쪽 끝 → GND
    - 중앙 핀 → GPIO 1
"""

import uasyncio as asyncio
import time
import sys

# 센서 모듈 임포트 시도 (없으면 해당 센서 비활성화)
try:
    import dht
    _HAS_DHT = True
except ImportError:
    _HAS_DHT = False

try:
    from machine import Pin, I2C, ADC
    _HAS_MACHINE = True
except ImportError:
    _HAS_MACHINE = False

try:
    import bh1750  # micropython-bh1750 패키지
    _HAS_BH1750 = True
except ImportError:
    _HAS_BH1750 = False


# ============ 핀 설정 (ESP32-S3) ============
DHT_PIN = 4           # DHT22 DATA 핀
I2C_SDA = 8           # BH1750 SDA
I2C_SCL = 9           # BH1750 SCL
BH1750_ADDR = 0x23    # BH1750 I2C 주소 (ADDR→GND 시 0x23, ADDR→VCC 시 0x5C)
ADC_PIN = 1           # 아날로그 입력 핀 (ADC1_CH0 = GPIO 1 on ESP32-S3)

# 전송 주기 (초)
READ_INTERVAL = 10    # 센서 읽기 간격
SEND_INTERVAL = 30    # 메시 네트워크 전송 간격 (여러 번 읽은 후 전송)
WARMUP_TIME = 2      # 센서 안정화 대기 시간 (초, DHT는 부팅 후 2초 필요)


# ============ 전역 상태 ============
dht_sensor = None
bh1750_sensor = None
adc_sensor = None
i2c_bus = None

# 센서 값 캐시 (전송 주기마다 평균 계산)
sensor_buffer = {}     # {"temp": [22.5, 22.7, ...], "humidity": [...], ...}

# 실행 상태
_running = False
_sensor_task = None


# ============ 센서 초기화 ============
def init_sensors():
    """연결된 센서를 자동 감지하여 초기화."""
    global dht_sensor, bh1750_sensor, adc_sensor, i2c_bus

    print("[SENSOR] 센서 초기화 시작...")

    # DHT22 / DHT11
    if _HAS_DHT and _HAS_MACHINE:
        try:
            dht_sensor = dht.DHT22(Pin(DHT_PIN))
            # DHT22 는 부팅 후 2초 대기 필요
            time.sleep_ms(100)
            # 초기 읽기 시도로 검증
            dht_sensor.measure()
            t = dht_sensor.temperature()
            h = dht_sensor.humidity()
            print("[SENSOR] DHT22 감지됨 (GPIO {}): 온도={}°C, 습도={}%".format(
                DHT_PIN, t, h))
        except Exception as ex:
            print("[SENSOR] DHT22 없음 또는 오류:", ex)
            dht_sensor = None
    else:
        print("[SENSOR] dht 모듈 미지원")

    # BH1750 (조도 센서)
    if _HAS_BH1750 and _HAS_MACHINE:
        try:
            i2c_bus = I2C(0, scl=Pin(I2C_SCL), sda=Pin(I2C_SDA), freq=100000)
            # I2C 버스 스캔
            devices = i2c_bus.scan()
            print("[SENSOR] I2C 장치 감지: {}".format(
                [hex(d) for d in devices]))
            if BH1750_ADDR in devices:
                bh1750_sensor = bh1750.BH1750(i2c_bus, addr=BH1750_ADDR)
                lux = bh1750_sensor.luminance(bh1750.ONCE_HIRES_1)
                print("[SENSOR] BH1750 감지됨 (주소 0x{:02x}): 조도={:.1f} lx".format(
                    BH1750_ADDR, lux))
            else:
                print("[SENSOR] BH1750 미감지 (주소 0x{:02x} 없음)".format(BH1750_ADDR))
                bh1750_sensor = None
        except Exception as ex:
            print("[SENSOR] BH1750 초기화 오류:", ex)
            bh1750_sensor = None
    else:
        print("[SENSOR] bh1750 모듈 미지원 (mip install bh1750 필요)")

    # ADC (아날로그 입력)
    if _HAS_MACHINE:
        try:
            adc_sensor = ADC(Pin(ADC_PIN))
            adc_sensor.atten(ADC.ATTN_11DB)   # 0~3.3V 범위
            adc_sensor.width(ADC.WIDTH_12BIT)  # 0~4095 해상도
            val = adc_sensor.read()
            print("[SENSOR] ADC 감지됨 (GPIO {}): 값={}/4095".format(
                ADC_PIN, val))
        except Exception as ex:
            print("[SENSOR] ADC 초기화 오류:", ex)
            adc_sensor = None

    active_count = sum([dht_sensor is not None,
                        bh1750_sensor is not None,
                        adc_sensor is not None])
    print("[SENSOR] 활성 센서: {} 개".format(active_count))
    return active_count > 0


# ============ 센서 읽기 ============
def read_dht():
    """DHT22 에서 온도/습도 읽기."""
    if dht_sensor is None:
        return None
    try:
        dht_sensor.measure()
        # DHT22 는 250ms 이상 간격 필요
        time.sleep_ms(20)
        temp = dht_sensor.temperature()
        humi = dht_sensor.humidity()
        # 온도는 섭씨 → 화씨 변환 (옵션)
        # ESP32-S3 한국 환경이면 섭씨 그대로 사용
        return {
            "temp": round(temp, 1),
            "humidity": round(humi, 1),
        }
    except Exception as ex:
        print("[SENSOR] DHT 읽기 오류:", ex)
        return None


def read_bh1750():
    """BH1750 에서 조도 읽기."""
    if bh1750_sensor is None:
        return None
    try:
        lux = bh1750_sensor.luminance(bh1750.ONCE_HIRES_1)
        return {"lux": round(lux, 1)}
    except Exception as ex:
        print("[SENSOR] BH1750 읽기 오류:", ex)
        return None


def read_adc():
    """ADC 값 읽기 (0~4095 → 0.0~3.3V 변환)."""
    if adc_sensor is None:
        return None
    try:
        raw = adc_sensor.read()
        # 12비트 (0~4095) → 전압 (0~3.3V)
        voltage = round(raw * 3.3 / 4095, 3)
        return {
            "adc_raw": raw,
            "voltage": voltage,
        }
    except Exception as ex:
        print("[SENSOR] ADC 읽기 오류:", ex)
        return None


def read_all_sensors():
    """모든 활성 센서에서 한 번씩 읽기. 결과를 딕셔너리로 반환."""
    result = {}

    dht_data = read_dht()
    if dht_data:
        result["temp"] = dht_data["temp"]
        result["humidity"] = dht_data["humidity"]

    bh_data = read_bh1750()
    if bh_data:
        result["lux"] = bh_data["lux"]

    adc_data = read_adc()
    if adc_data:
        result["adc"] = adc_data["adc_raw"]
        result["voltage"] = adc_data["voltage"]

    return result


# ============ 메시 네트워크 전송 ============
async def send_to_mesh(sensor_data):
    """espnow_mesh_pro.send_sensor() 를 호출하여 메시 네트워크로 전송.
    각 센서 값을 별도 메시지로 전송.
    """
    try:
        # espnow_mesh_pro 모듈 찾기 (이미 import 되어 있어야 함)
        import espnow_mesh_pro as mesh
    except ImportError:
        try:
            import espnow_mesh_secure as mesh
        except ImportError:
            print("[SENSOR] 오류: espnow_mesh_pro 또는 espnow_mesh_secure 가 import 되어 있어야 함")
            return False

    # 각 센서 값을 별도로 전송 (수신 측에서 이름으로 분류 가능)
    units = {
        "temp": "C",
        "humidity": "%",
        "lux": "lx",
        "adc": "",
        "voltage": "V",
    }
    names = {
        "temp": "temperature",
        "humidity": "humidity",
        "lux": "luminance",
        "adc": "adc_raw",
        "voltage": "voltage",
    }

    for key, value in sensor_data.items():
        try:
            # mesh.send_sensor 는 async 함수
            await mesh.send_sensor(names.get(key, key), value, units.get(key, ""))
        except Exception as ex:
            print("[SENSOR] 전송 오류 ({}): {}".format(key, ex))

    return True


# ============ 센서 읽기 루프 ============
async def sensor_loop():
    """주기적으로 센서를 읽고 메시 네트워크로 전송."""
    global _running

    print("[SENSOR] 센서 루프 시작")
    print("[SENSOR] 읽기 간격: {}초, 전송 간격: {}초".format(
        READ_INTERVAL, SEND_INTERVAL))

    # 센서 안정화 대기
    print("[SENSOR] 센서 안정화 대기 ({}초)...".format(WARMUP_TIME))
    await asyncio.sleep(WARMUP_TIME)

    last_send_time = 0
    read_count = 0

    _running = True
    while _running:
        try:
            # 1. 센서 읽기
            data = read_all_sensors()
            if not data:
                print("[SENSOR] 읽은 데이터 없음")
            else:
                # 버퍼에 추가 (평균 계산용)
                ts = time.time()
                for key, value in data.items():
                    if key not in sensor_buffer:
                        sensor_buffer[key] = []
                    sensor_buffer[key].append((ts, value))
                    # 최근 10개만 유지
                    if len(sensor_buffer[key]) > 10:
                        sensor_buffer[key] = sensor_buffer[key][-10:]

                read_count += 1
                ts_str = time.strftime("%H:%M:%S", time.localtime())
                print("[{}] 센서 읽기 #{}: {}".format(ts_str, read_count, data))

            # 2. 전송 주기 도달 시 메시 네트워크로 전송
            now = time.time()
            if now - last_send_time >= SEND_INTERVAL and sensor_buffer:
                # 평균 계산
                avg_data = {}
                for key, history in sensor_buffer.items():
                    if not history:
                        continue
                    values = [v for _, v in history]
                    avg_data[key] = round(sum(values) / len(values), 2)

                # 전송
                ts_str = time.strftime("%H:%M:%S", time.localtime())
                print("[{}] 메시 네트워크 전송: {}".format(ts_str, avg_data))
                await send_to_mesh(avg_data)

                # 버퍼 비우기
                sensor_buffer.clear()
                last_send_time = now

            # 3. 다음 읽기 대기
            await asyncio.sleep(READ_INTERVAL)

        except Exception as ex:
            print("[SENSOR] 루프 오류:", ex)
            await asyncio.sleep(5)

    print("[SENSOR] 센서 루프 종료")


# ============ 제어 함수 ============
def start():
    """센서 루프를 백그라운드 태스크로 시작."""
    global _sensor_task
    if _sensor_task is not None and not _sensor_task.done():
        print("[SENSOR] 이미 실행 중")
        return _sensor_task

    if not init_sensors():
        print("[SENSOR] 활성 센서 없음. 종료.")
        return None

    # 현재 이벤트 루프에서 태스크 생성
    loop = asyncio.get_event_loop()
    _sensor_task = loop.create_task(sensor_loop())
    print("[SENSOR] 백그라운드 태스크 시작 (id: {})".format(id(_sensor_task)))
    return _sensor_task


def stop():
    """센서 루프 중지."""
    global _running, _sensor_task
    _running = False
    if _sensor_task:
        _sensor_task.cancel()
        _sensor_task = None
    print("[SENSOR] 중지 요청됨")


def status():
    """현재 센서 상태 출력."""
    print("\n[센서 상태]")
    print("  DHT22  : {}".format("활성" if dht_sensor else "비활성"))
    print("  BH1750 : {}".format("활성" if bh1750_sensor else "비활성"))
    print("  ADC    : {}".format("활성" if adc_sensor else "비활성"))
    print("  실행 중: {}".format(_running))
    print("  버퍼 항목: {} 개".format(
        {k: len(v) for k, v in sensor_buffer.items()}))


def read_once():
    """센서를 한 번만 읽고 결과 출력 (디버깅용).
    메시 네트워크로 전송하지 않음.
    """
    if not (dht_sensor or bh1750_sensor or adc_sensor):
        if not init_sensors():
            return None

    data = read_all_sensors()
    print("[센서 즉시 읽기]")
    for k, v in data.items():
        units = {"temp": "°C", "humidity": "%", "lux": "lx",
                 "adc": "", "voltage": "V"}
        print("  {}: {} {}".format(k, v, units.get(k, "")))
    return data


async def send_once():
    """센서를 한 번 읽고 즉시 메시 네트워크로 전송."""
    data = read_once()
    if data:
        await send_to_mesh(data)
    return data


# ============ 메인 (단독 실행 시) ============
async def _standalone_main():
    """espnow_mesh_pro 와 독립적으로 실행할 때 (테스트용).
    실제 사용 시에는 espnow_mesh_pro.run() 후에 sensor_example.start() 호출 권장.
    """
    if not init_sensors():
        print("[SENSOR] 활성 센서 없음.")
        return

    # 단독 실행: 메시 네트워크 없이 센서 읽기만 수행
    global _running
    _running = True
    print("\n[SENSOR] 단독 모드 (메시 전송 없이 센서 읽기만)")
    print("[SENSOR] Ctrl+C 로 종료\n")

    while _running:
        try:
            data = read_all_sensors()
            ts = time.strftime("%H:%M:%S", time.localtime())
            print("[{}] 센서: {}".format(ts, data))
            await asyncio.sleep(READ_INTERVAL)
        except KeyboardInterrupt:
            _running = False
            print("\n[SENSOR] 종료")


def run_standalone():
    """단독 실행 (메시 네트워크 없이 센서 읽기만)."""
    try:
        asyncio.run(_standalone_main())
    except KeyboardInterrupt:
        print("\n종료")


if __name__ == "__main__":
    run_standalone()
