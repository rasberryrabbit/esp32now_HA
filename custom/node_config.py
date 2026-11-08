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

    # DS18B20 (1-Wire 온도, 인덱스로 구분)
    # "수온1": ("ds18b20", 12, 0),
    # "수온2": ("ds18b20", 12, 1),

    # SGP30 (CO2/TVOC)
    # "CO2": ("sgp30", 0x58, "co2"),
    # "TVOC": ("sgp30", 0x58, "tvoc"),

    # ESP32 내장 ADC
    "배터리": ("adc", 1, "voltage"),

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
