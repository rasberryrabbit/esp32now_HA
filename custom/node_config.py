"""
node_config.py - 노드별 설정 (자동 로드됨)
==========================================
espnow_mesh_pro.py 시작 시 자동으로 import 됨.
이 파일에서 노드별 센서/GPIO 이름과 핀 번호를 설정.

setup() 함수가 있으면 자동으로 호출됨.
"""

# ============ 노드별 설정 ============
# 이 값을 각 노드에 맞게 수정하세요.

# 센서 설정: {이름: (type, pin_or_addr, channel)}
SENSOR_CONFIG = {
    # DHT22 (온도/습도)
    "거실온도": ("dht", 4, "temp"),
    "거실습도": ("dht", 4, "humidity"),

    # BH1750 조도 (I2C)
    "조도": ("bh1750", 0x23, "lux"),

    # BME280 (외부 온도/습도/기압)
    # "외부온도": ("bme280", 0x76, "temp"),
    # "외부습도": ("bme280", 0x76, "humidity"),
    # "기압": ("bme280", 0x76, "pressure"),

    # AHT10 (온도/습도, I2C 기본주소 0x38 / 0x39)
    # channel: "temp"(C), "humidity"(%)
    # 두 채널은 한 번의 측정(80ms) 결과를 공유
    # "AHT온도": ("aht10", 0x38, "temp"),
    # "AHT습도": ("aht10", 0x38, "humidity"),

    # SHT30 (온도/습도, I2C 기본주소 0x44 / 0x45)
    # "SHT온도": ("sht30", 0x44, "temp"),
    # "SHT습도": ("sht30", 0x44, "humidity"),

    # DS18B20 (1-Wire 온도, 인덱스로 구분)
    # "수온1": ("ds18b20", 12, 0),
    # "수온2": ("ds18b20", 12, 1),

    # SGP30 (CO2/TVOC)
    # "CO2": ("sgp30", 0x58, "co2"),
    # "TVOC": ("sgp30", 0x58, "tvoc"),

    # MPU6050 (6축 가속도/자이로, I2C 기본주소 0x68)
    # channel 종류:
    #   ax/ay/az  - 가속도 (g, ±2g 범위)
    #   gx/gy/gz  - 자이로 각속도 (dps, ±250 dps 범위)
    #   temp      - 칩 온도 (C)
    #   roll      - 가속도 기반 roll 각 (deg)
    #   pitch     - 가속도 기반 pitch 각 (deg)
    #   amag      - 가속도 크기 (g, 정지 시 ~1.0)
    #   gyaw      - 자이로 적분 yaw 상대각 (deg, drift 발생)
    # yaw 리셋: sensor_runner.sm.reset_mpu_yaw(0x68)
    # "가속도X": ("mpu6050", 0x68, "ax"),
    # "가속도Y": ("mpu6050", 0x68, "ay"),
    # "가속도Z": ("mpu6050", 0x68, "az"),
    # "자이로X": ("mpu6050", 0x68, "gx"),
    # "자이로Y": ("mpu6050", 0x68, "gy"),
    # "자이로Z": ("mpu6050", 0x68, "gz"),
    # "기울기Roll": ("mpu6050", 0x68, "roll"),
    # "기울기Pitch": ("mpu6050", 0x68, "pitch"),
    # "가속도크기": ("mpu6050", 0x68, "amag"),
    # "방위각": ("mpu6050", 0x68, "gyaw"),
    # "MPU온도": ("mpu6050", 0x68, "temp"),

    # ESP32 내장 ADC
    "배터리": ("adc", 1, "voltage"),

    # CdS 광전소자 (포토레지스터, 전압분배 + 내장 ADC)
    # channel: "raw"(0-4095), "voltage"(V), "lux"(lx), "percent"(0-100%), "resistance"(ohm)
    # lux/percent/resistance 는 아래 CDS_CALIB 캘리브레이션 필요 (없으면 raw/voltage만)
    # 회로: Vcc --[CdS]--(ADC핀)--[R_fixed]-- GND  (cds_top=True, 권장)
    #   또는 Vcc --[R_fixed]--(ADC핀)--[CdS]-- GND  (cds_top=False)
    # "조도": ("cds", 2, "lux"),
    # "조도RAW": ("cds", 2, "raw"),
    # "조도전압": ("cds", 2, "voltage"),

    # 홀 센서 (자기장/자기 감지)
    # 아날로그(A1301/49E 등): channel "raw"/"voltage"/"field"(G)/"polarity"(1/0/-1)
    #   → HALL_CALIB 의 mode="analog", sensitivity(mV/G) 필요 (field/polarity만)
    # 디지털(A3144/44E 등): channel "state"(0/1)/"count"(누적)/"rpm"
    #   → HALL_CALIB 의 mode="digital", pull/detect/ppr (없으면 기본값으로 동작)
    # "자기장": ("hall", 4, "field"),
    # "자기감지": ("hall", 5, "state"),
    # "회전수": ("hall", 5, "count"),
    # "RPM": ("hall", 5, "rpm"),

    # ADS1115 I2C ADC 모듈 (4채널 16비트, 0x48-0x4B)
    # 형식: (type, i2c_addr, channel, unit)
    # channel: 0-3 (ADC 채널 번호)
    # unit: "voltage" (기본, V) 또는 "raw" (0-32767)
    # "외부전압": ("ads1115", 0x48, 0, "voltage"),   # 채널 0, 전압
    # "광센서": ("ads1115", 0x48, 1, "voltage"),     # 채널 1, 전압
    # "토양수분": ("ads1115", 0x48, 2, "raw"),       # 채널 2, raw 값
    # "압력센서": ("ads1115", 0x48, 3, "voltage"),   # 채널 3, 전압

    # I2C GPIO 확장 칩 입력 핀 (MCP23017/PCF8574) - 디지털 입력 센서
    # 형식: (type, chip_type, (i2c_addr, pin), unit)
    # chip_type: "mcp23017" 또는 "pcf8574"
    # pin: MCP23017 0-15, PCF8574 0-7
    # "현관버튼": ("i2c_input", "mcp23017", (0x20, 2), ""),
    # "창문센서": ("i2c_input", "mcp23017", (0x20, 3), ""),
    # "PIR센서": ("i2c_input", "pcf8574", (0x21, 2), ""),
}

# GPIO 출력 설정: {이름: 핀번호}
GPIO_CONFIG = {
    "거실조명": 2,
    "보일러": 3,
}

# PWM 출력 설정: {이름: 핀번호}
PWM_CONFIG = {
    "거실팬": 5,
    # "LED밝기": 6,
}

# NeoPixel 출력 설정: {이름: 핀번호}
NEOPIXEL_CONFIG = {
    "보드LED": 48,      # 온보드 NeoPixel (GPIO 48)
}
# NeoPixel LED 개수 (LED 체인 길이)
NEOPIXEL_COUNT = 1    # 온보드 LED 1개

# CdS 광전소자 캘리브레이션 (lux/percent/resistance 변환용)
# {센서이름: {"r_fixed": ohm, "vcc": V, "cds_top": bool, "r10": ohm, "gamma": float}}
#   r_fixed  : 전압분래 고정저항 (ohm, 일반적으로 10k)
#   vcc      : 공급전압 (V, ESP32는 3.3)
#   cds_top  : True=Cds가 Vcc측, 고정저항이 GND측 (권장)
#              False=고정저항이 Vcc측, CdS가 GND측
#   r10      : CdS 저항 @ 10 lux (GL5528/GM5528 ≈ 10-20k, 데이터시트 참고)
#   gamma    : log-log 기울기 (0.5-0.8, GL5528 ≈ 0.7)
# 캘리브 없는 CdS 센서는 raw/voltage 채널만 사용 가능
CDS_CALIB = {
    # "조도": {"r_fixed": 10000, "vcc": 3.3, "cds_top": True, "r10": 20000, "gamma": 0.7},
}

# 홀 센서 캘리브레이션 (자기장 변환 / 디지털 감지설정)
# {센서이름: {필드...}}  - mode 생략 시 channel로 자동 추론
#   [공통]
#     mode       : "analog" 또는 "digital" (생략 시 channel로 추론)
#   [analog - 아날로그 홀, 자기장 세기]
#     vcc         : 공급전압 (V, ESP32는 3.3)
#     v_quiescent : 무자계 시 출력전압 (V, 보통 vcc/2)
#     sensitivity : 감도 (mV/Gauss, 데이터시트 - A1301=2.5, 49E≈1.6)
#     threshold   : 극성 판정 임계 (Gauss, 기본 5)
#     → field(G) = (전압 - v_quiescent) × 1000 / sensitivity
#   [digital - 디지털 홀, 감지/카운트/RPM]
#     pull   : "up"/"down"/"none" (내부 풀업, 기본 "up")
#     detect : "rising"/"falling"/"both" (카운트 엣지, 기본 "falling")
#     ppr    : 1회전당 펄스수 (RPM 계산용, 기본 1)
#     → rpm = (펄스증가 / ppr) × 60000 / dt_ms
HALL_CALIB = {
    # "자기장": {"mode": "analog", "vcc": 3.3, "v_quiescent": 1.65, "sensitivity": 2.5},
    # "RPM": {"mode": "digital", "pull": "up", "detect": "falling", "ppr": 1},
}

# MCP23017 (I2C 16채널 GPIO 확장) 설정
# {이름: (i2c_addr, pin)} - pin: 0-15 (포트 A: 0-7, 포트 B: 8-15)
MCP23017_CONFIG = {
    # "확장조명1": (0x20, 0),   # MCP23017 0x20, 핀 0
    # "확장조명2": (0x20, 1),   # MCP23017 0x20, 핀 1
    # "확장조명3": (0x20, 8),   # MCP23017 0x20, 핀 8 (포트 B)
}

# PCF8574 (I2C 8채널 GPIO 확장) 설정
# {이름: (i2c_addr, pin)} - pin: 0-7
PCF8574_CONFIG = {
    # "확장릴레이1": (0x21, 0), # PCF8574 0x21, 핀 0
    # "확장릴레이2": (0x21, 1), # PCF8574 0x21, 핀 1
}

# I2C 버스 설정 (MCP23017/PCF8574 공용)
I2C_SDA_PIN = 8
I2C_SCL_PIN = 9
I2C_FREQ = 400000  # 400kHz

# 센서 읽기 주기 (초)
SENSOR_READ_INTERVAL = 3

# 센서 전송 주기 (초, 여러 번 읽은 후 평균 전송)
SENSOR_SEND_INTERVAL = 5

# PWM 초기 주파수 (Hz)
PWM_FREQ = 2000


# ============ setup 함수 (자동 호출됨) ============
def setup():
    """node_config 로드 시 출력."""
    print("[CONFIG] 노드 설정 로드됨")
    print("[CONFIG]   센서: {} 개".format(len(SENSOR_CONFIG)))
    print("[CONFIG]   GPIO: {} 개".format(len(GPIO_CONFIG)))
    print("[CONFIG]   PWM: {} 개".format(len(PWM_CONFIG)))
    print("[CONFIG]   NeoPixel: {} 개".format(len(NEOPIXEL_CONFIG)))
    print("[CONFIG]   MCP23017: {} 개".format(len(MCP23017_CONFIG)))
    print("[CONFIG]   PCF8574: {} 개".format(len(PCF8574_CONFIG)))
    print("[CONFIG]   CdS 캘리브: {} 개".format(len(CDS_CALIB)))
    print("[CONFIG]   Hall 캘리브: {} 개".format(len(HALL_CALIB)))
