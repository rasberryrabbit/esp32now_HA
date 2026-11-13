# ESP-NOW 메시 네트워크 Pro

마이크로파이썬(ESP32-S3) 기반 ESP-NOW 메시 네트워크.
센서 수집, GPIO 원격 제어, 웹 대시보드, 자동화 규칙 엔진을 통합.

## 파일 구성

### 핵심 모듈 (ESP32-S3 루트에 업로드)

| 파일 | 용도 |
|------|------|
| `espnow_mesh_pro.py` | 메시 네트워크 메인 (노드 + 게이트웨이 + 웹 서버 + REPL) |
| `mesh_state.py` | 데이터 저장소 클래스 + 싱글톤 (stats, peers, sensor_store, automation_rules 등) |
| `mesh_config.py` | Config 클래스 (config.txt 읽기/쓰기, cfg 싱글톤) |
| `sensor_runner.py` | SensorManager 클래스 (센서 읽기/전송, sm 싱글톤) |
| `gpio_control.py` | GPIOManager 클래스 (GPIO/PWM/NeoPixel/I2C 확장 제어, gm 싱글톤) |
| `sensors.py` | 센서 초기화 표준 로직 (setup() 자동 호출, custom/node_config.py 참조) |
| `devices.py` | GPIO/PWM/NeoPixel/I2C 초기화 표준 로직 (setup() 자동 호출) |
| `web_pages.py` | 웹 대시보드 HTML 페이지 (모듈 방식, .mpy 컴파일 지원) |

### 사용자 설정 파일 (custom/ 폴더)

사용자가 노드별로 수정하는 파일입니다. 부팅 시 자동으로 import 되어 setup() 함수가 호출됩니다.

| 파일 | 용도 |
|------|------|
| `custom/node_config.py` | 노드별 설정 (센서/GPIO/PWM 이름과 핀 매핑) |
| `custom/automation.py` | 자동화 규칙 설정 (게이트웨이에서만 로드) |
| `custom/config.txt.sample` | config.txt 샘플 템플릿 |

> **참고**: `custom/` 폴더가 없으면 `node_config`/`automation` 모듈을 찾지 못해 로드되지 않습니다. `custom/` 폴더의 모듈들은 서로 `import node_config` 등으로 참조할 수 있습니다 (sys.path에 custom/이 자동 추가됨). `sensors.py`와 `devices.py`는 루트에 있는 표준 로직 파일로, `custom/node_config.py`의 설정을 읽어 동작합니다.

### 예제/참고 (examples/ 폴더)

| 파일 | 용도 | 실행 환경 |
|------|------|---------|
| `examples/sensor_example.py` | 센서 사용 예제 (DHT22/BH1750/ADC) | ESP32-S3 |
| `examples/smart_home_scenario.py` | 스마트홈 자동화 시나리오 예제 | ESP32-S3 |
| `examples/mesh_client.py` | PC/스마트폰용 클라이언트 (HTTP/MQTT) | Python 3.x |
| `examples/espnow_mesh_secure.py` | AES 암호화 버전 메시 네트워크 | ESP32-S3 |

## 주요 기능

### 메시 네트워크

- Wi-Fi + ESP-NOW 기반 메시 (브로드캐스트 + TTL 중계)
- 자동 식별: MAC 주소로 NODE_ID/NICKNAME 자동 생성
- config.txt 영속화: 모든 설정 자동 저장
- 노드 역할: `node` / `aggregator` / `gateway`
- 게이트웨이 다중화: msg_id 중복 제거, 장애 시 자동 인계
- 자가 복구: heartbeat + 60초 타임아웃

### 웹 대시보드 (게이트웨이 전용)

- 노드 목록 / 통계 / 센서 / 장치 실시간 조회
- GPIO ON/OFF 버튼, PWM 슬라이더 즉시 제어
- 제어 로그 (Control Log) 표시
- Wi-Fi/MQTT 설정 변경
- 1초 폴링, Promise.all 병렬 API 호출

### 자동화 엔진

- 센서 기반 규칙 (히스테리시스, 임계값)
- 시간 기반 규칙 (요일/시간 구간)
- 일출/일몰 규칙 (위도/경도 기반)
- 우선순위 충돌 해결 (같은 장치에 여러 규칙)
- 규칙 그룹 (any/all 모드)
- 추가 조건 (다중 센서 조건)
- action_off (상태 해제 시 자동 OFF)
- automation.txt 영속화

### 센서/GPIO 제어

- 센서 자동 감지 (DHT22, BH1750, BME280, SHT30, AHT10, DS18B20, SGP30, MPU6050, ADS1115, MCP3008, MAX6675, CdS 광전소자, Hall 센서, ADC, I2C 확장 입력)
- GPIO 이름 기반 원격 제어: `/GPIO <이름> <값>`
- PWM 듀티 제어 (0-1023 또는 0-100%)
- 장치 정보 브로드캐스트 (device_info 메시지)

## 빠른 시작

### 1. ESP32-S3에 업로드

```bash
# mpremote 사용 - 핵심 모듈 (루트)
mpremote connect /dev/ttyUSB0 cp espnow_mesh_pro.py :espnow_mesh_pro.py
mpremote connect /dev/ttyUSB0 cp mesh_state.py :mesh_state.py
mpremote connect /dev/ttyUSB0 cp mesh_config.py :mesh_config.py
mpremote connect /dev/ttyUSB0 cp sensor_runner.py :sensor_runner.py
mpremote connect /dev/ttyUSB0 cp gpio_control.py :gpio_control.py
mpremote connect /dev/ttyUSB0 cp sensors.py :sensors.py
mpremote connect /dev/ttyUSB0 cp devices.py :devices.py
mpremote connect /dev/ttyUSB0 cp web_pages.py :web_pages.py

# custom/ 폴더 생성 및 사용자 설정 파일 업로드
mpremote connect /dev/ttyUSB0 mkdir custom
mpremote connect /dev/ttyUSB0 cp custom/node_config.py :custom/node_config.py
mpremote connect /dev/ttyUSB0 cp custom/automation.py :custom/automation.py
mpremote connect /dev/ttyUSB0 cp custom/config.txt.sample :config.txt
mpremote connect /dev/ttyUSB0 reset
```

또는 Thonny / rshell / ampy 사용.

### 2. 최초 부팅

config.txt가 없으면 MAC 주소 기반으로 자동 생성:

```
[CONFIG] config.txt 없음. 기본값 사용.
[CONFIG] NODE_ID 자동 생성: node-76c204 (MAC 기반)
[CONFIG] NICKNAME 자동 생성: ESP-c204 (MAC 기반)
[CONFIG] NODE_ROLE 기본값: node
[CONFIG] 최초 부팅. config.txt 자동 생성.
```

### 3. 역할 변경 (게이트웨이로 설정)

REPL에서:

```
/role gateway
/config wifi MyWiFi mypassword
/config mqtt broker.hivemq.com 1883
/config save
```

리셋 후 변경사항 적용.

### 4. 웹 대시보드 접속

게이트웨이 부팅 후 표시되는 IP로 브라우저 접속:

```
http://192.168.1.50/
```

### 5. PC 클라이언트 (선택)

```bash
# HTTP 모드
python3 examples/mesh_client.py --gateway 192.168.1.50

# MQTT 모드
pip install paho-mqtt
python3 examples/mesh_client.py --mqtt --broker broker.hivemq.com
```

## config.txt 형식

```
node_id=node-76c204
nickname=ESP-c204
node_role=node
gateway_ssid=MyWiFi
gateway_password=mypassword
mqtt_broker=broker.hivemq.com
mqtt_port=1883
mqtt_topic_up=mesh/chat/up
mqtt_topic_down=mesh/chat/down
mqtt_topic_sensor=mesh/sensor
gateway_group_id=default
```

## custom/node_config.py 설정

```python
# 센서 설정 (센서 이름 → 핀/주소)
SENSOR_CONFIG = {
    "온도": {"type": "dht22", "pin": 4, "unit": "°C"},
    "조도": {"type": "bh1750", "sda": 8, "scl": 9, "unit": "lx"},
}

# GPIO 출력 설정 (이름 → 핀 번호)
GPIO_CONFIG = {
    "거실조명": 2,
    "보일러": 3,
}

# PWM 출력 설정 (이름 → 핀 번호)
PWM_CONFIG = {
    "거실팬": 5,
}
```

### MPU6050 (6축 가속도/자이로) 설정

MPU6050은 I2C로 연결하며 기본 주소는 `0x68`(AD0=GND) 또는 `0x69`(AD0=VDD)입니다. 한 칩에서 여러 파생값을 센서로 등록할 수 있습니다. 같은 주소의 채널들은 한 번의 I2C 읽기 결과를 500ms 동안 공유하므로 버스 부하가 없습니다.

**지원 채널:**

| channel | 단위 | 설명 |
|---------|------|------|
| `ax` `ay` `az` | g | 가속도 (±2g, 1g=16384 LSB) |
| `gx` `gy` `gz` | dps | 자이로 각속도 (±250 dps, 1 dps=131 LSB) |
| `temp` | C | 칩 내부 온도 |
| `roll` | deg | 가속도 기반 roll 각도 (`atan2(ay, az)`) |
| `pitch` | deg | 가속도 기반 pitch 각도 (`atan2(-ax, √(ay²+az²))`) |
| `amag` | g | 가속도 크기 (정지 시 ≈1.0, 충격 시 급증) |
| `gyaw` | deg | 자이로 Z축 적분 상대 방위각 (drift 발생) |

```python
# custom/node_config.py
SENSOR_CONFIG = {
    "기울기Roll":  ("mpu6050", 0x68, "roll"),
    "기울기Pitch": ("mpu6050", 0x68, "pitch"),
    "가속도크기":  ("mpu6050", 0x68, "amag"),   # 충격/낙하 감지
    "방위각":      ("mpu6050", 0x68, "gyaw"),   # 회전 각도 (상대)
    "MPU온도":     ("mpu6050", 0x68, "temp"),
}
```

**yaw 재보정:** 자이로 적분값은 시간이 지나면 drift가 누적됩니다. 기준 방향으로 맞출 때 아래 호출로 0부터 다시 적분합니다.

```python
import sensor_runner
sensor_runner.sm.reset_mpu_yaw(0x68)        # 특정 칩만
sensor_runner.sm.reset_mpu_yaw()            # 등록된 모든 MPU6050
```

**주의:** `gyaw`는 자이로만 적분한 상대각이므로 절대 방위가 아닙니다. 절대 방위가 필요하면 MPU9250(자력계 포함) 등을 사용해야 합니다. `roll`/`pitch`는 중력 방향을 기준으로 하므로 정지 또는 완만한 동작에서 정확합니다.

### AHT10 (온도/습도, I2C) 설정

AHT10은 저전력 I2C 온도/습도 센서입니다. 기본 주소 `0x38`(AD0 High 시 `0x39`). `temp`와 `humidity` 두 채널은 한 번의 80ms 측정 결과를 공유하므로 두 채널을 등록해도 I2C 차단은 주기당 1회입니다.

| channel | 단위 | 설명 |
|---------|------|------|
| `temp` | C | 온도 (-50 ~ +150 °C) |
| `humidity` | % | 상대습도 (0-100 %) |

```python
# custom/node_config.py
SENSOR_CONFIG = {
    "AHT온도": ("aht10", 0x38, "temp"),
    "AHT습도": ("aht10", 0x38, "humidity"),
}
```

초기화 시 캘리브레이션 명령(`0xBE 0x08 0x00`)을 보내고 캘리브 완료 비트를 기다립니다(미완료 시에도 진행). 측정은 `0xAC 0x33 0x00` 트리거 후 ~80ms 대기(busy 비트 추가 폴링)하며, 20비트 raw 값을 표준 `raw / 2^20` 공식으로 변환합니다.

### CdS 광전소자 (포토레지스터) 설정

CdS 셀(GL5528/GM5528 등)은 ESP32 ADC 핀에 전압분배 회로로 연결합니다. `cds` 타입은 단순 ADC를 넘어, 센서별 캘리브레이션을 주면 중간 전압을 CdS 저항으로 역산하고, 다시 추정 lux와 상대 밝기(%)로 변환합니다.

**권장 회로:** `Vcc --[CdS]--(ADC 핀)--[R_fixed]-- GND` → `cds_top=True`. 반대 배치 `Vcc --[R_fixed]--(ADC 핀)--[CdS]-- GND` → `cds_top=False`.

**채널:**

| channel | 단위 | 캘리브 필요 | 설명 |
|---------|------|------------|------|
| `raw` | — | 아니오 | ADC raw 0-4095 |
| `voltage` | V | 아니오 | 분배 중간 전압 |
| `resistance` | ohm | 예 | CdS 저항 (분배 수식 역산) |
| `lux` | lx | 예 | CdS log-log 특성으로 추정한 lux |
| `percent` | % | 예 | 로그 스케일 밝기 0-100 (0-10000 lx 매핑) |

```python
# custom/node_config.py
SENSOR_CONFIG = {
    "조도": ("cds", 2, "lux"),         # 추정 lux
    # "조도RAW": ("cds", 2, "raw"),   # 캘리브 없을 때 폴백
}

# 캘리브레이션 (lux/percent/resistance 채널은 필수)
CDS_CALIB = {
    "조도": {"r_fixed": 10000, "vcc": 3.3, "cds_top": True,
             "r10": 20000, "gamma": 0.7},
}
```

**캘리브 필드:** `r_fixed`(분래 고정저항, ohm), `vcc`(공급전압, ESP32=3.3), `cds_top`(CdS가 Vcc측이면 True, GND측이면 False), `r10`(10 lux에서의 CdS 저항 — 셀 데이터시트 참고, GL5528 ≈ 10-20kΩ), `gamma`(log-log 기울기, 0.5-0.8, GL5528 ≈ 0.7). lux는 CdS R-lux log-log 관계식 `10 × (R10/R)^(1/gamma)`로 계산합니다. `CDS_CALIB`에 등록되지 않은 CdS 센서는 `raw`/`voltage` 채널만 사용할 수 있습니다.

### 홀 센서 (자기장 / 자기 감지) 설정

홀 센서는 자기장을 측정합니다. `hall` 타입은 **아날로그**(비례 전압 → 자기장 세기 Gauss)와 **디지털**(오픈컬렉터 출력 → 감지/펄스 카운트/RPM)을 모두 지원합니다. 모드는 `HALL_CALIB[name]["mode"]`로 지정하며, 생략 시 channel로 자동 추론합니다(`state`/`count`/`rpm` → 디지털, 나머지 → 아날로그).

**아날로그 홀**(A1301/A1302/49E/SS495 등): 무자계 시 `v_quiescent`(~Vcc/2)에서 극성에 비례해 전압이 변동. ADC로 읽습니다.

| channel | 단위 | 캘리브 | 설명 |
|---------|------|-------|------|
| `raw` | — | 아니오 | ADC raw 0-4095 |
| `voltage` | V | 아니오 | 센서 출력 전압 |
| `field` | G | 예 | 부호 있는 자기장 세기 (Gauss) |
| `polarity` | — | 예 | 1(N), -1(S), 0(무) |

`field = (전압 - v_quiescent) × 1000 / sensitivity`, `sensitivity`는 mV/G(데이터시트 - A1301=2.5, 49E≈1.6). `polarity`는 `threshold`(Gauss, 기본 5)로 판정합니다.

**디지털 홀**(A3144/44E/3144 래칭/스위치): 자석이 가까우면 오픈컬렉터 출력이 토글. GPIO + 인터럽트 엣지 카운터로 동작합니다.

| channel | 단위 | 캘리브 | 설명 |
|---------|------|-------|------|
| `state` | — | 아니오 | 현재 핀 레벨 (0/1) |
| `count` | — | 아니오* | 부팅 후 누적 펄스 수 (인터럽트) |
| `rpm` | rpm | 아니오* | 직전 읽기 이후 분당 회전수 |

\* `count`/`rpm`은 기본값(`pull=up`, `detect=falling`, `ppr=1`)으로 동작합니다. 엣지/풀/1회전당 펄스를 바꾸려면 `HALL_CALIB` 설정. RPM은 읽기 간격 동안의 평균 속도로 `(Δcount / ppr) × 60000 / Δt_ms`로 계산합니다(순간값 아님).

```python
# custom/node_config.py
SENSOR_CONFIG = {
    # 아날로그: 자기장 세기
    "자기장":  ("hall", 4, "field"),
    # 디지털: 감지 + 회전 카운트
    "자기감지": ("hall", 5, "state"),
    "RPM":     ("hall", 5, "rpm"),
}

HALL_CALIB = {
    "자기장": {"mode": "analog",  "vcc": 3.3, "v_quiescent": 1.65,
               "sensitivity": 2.5, "threshold": 5.0},
    "RPM":   {"mode": "digital", "pull": "up", "detect": "falling", "ppr": 1},
}
```

**배선:** 아날로그 홀 → ADC 핀(Vcc/GND 공통). 디지털 홀 → GPIO 핀에 풀업(내부 또는 외부 10kΩ), 자석 감지 시 오픈컬렉터가 라인을 LOW로 당깁니다. RPM/회전 측정은 회전체에 자석 1개를 부착하고 센서를 근처에 고정(1회전 = 1펄스, `ppr=1`). 다극 링 자석이나 자석 여러 개면 `ppr`을 그에 맞게 설정하세요.

## 자동화 규칙 예제

`custom/automation.py`에 규칙 추가:

```python
def setup():
    import espnow_mesh_pro as mesh

    # 온도 25도 이상 시 팬 50% (히스테리시스 ±1)
    mesh.automation_rules.add_rule(
        name="거실 고온 팬 50%",
        sensor="온도", operator=">", value=25,
        action_device="거실팬", action_value="50",
        hysteresis=1.0, cooldown_sec=60,
        priority=10,
        action_off={"device": "거실팬", "value": "0"},
    )

    # 평일 아침 보일러 (06:00-08:00)
    mesh.automation_rules.add_rule(
        name="평일 아침 보일러",
        rule_type="time",
        schedule={"days": [0,1,2,3,4], "start": 600, "end": 800},
        action_device="보일러", action_value="1",
        cooldown_sec=60, priority=5,
        action_off={"device": "보일러", "value": "0"},
    )
```

## REPL 명령어

```
/who              노드 목록
/discover         노드 발견
/nick <이름>       닉네임 변경
/role <역할>      node|aggregator|gateway 변경
/config show      현재 설정
/config wifi <ssid> <password>
/config mqtt <broker> [port]
/config save      설정 저장
/config reload    설정 리로드
/stats            통계
/sensors          센서 데이터
/help             도움말
```

## 웹 API

| 엔드포인트 | 용도 |
|-----------|------|
| `GET /` | 웹 대시보드 |
| `GET /api/nodes` | 노드 목록 |
| `GET /api/stats` | 통계 |
| `GET /api/sensors` | 센서 데이터 |
| `GET /api/devices` | 장치 목록 |
| `GET /api/config` | 설정 조회 |
| `GET /api/config_save` | 설정 저장 |
| `GET /api/control?name=<장치명>&value=<값>` | 장치 제어 |
| `GET /api/automation?action=list\|add\|remove\|log` | 자동화 규칙 |
| `GET /api/send?text=<메시지>` | 메시지 전송 |

## 메시 타입

| 타입 | 용도 |
|------|------|
| `chat` | 일반 메시지 |
| `sensor` | 센서 데이터 |
| `system` | 시스템 알림 |
| `heartbeat` | 노드 활동 알림 |
| `discover` | 노드 발견 요청 |
| `gw_presence` | 게이트웨이 존재 알림 |
| `device_info` | 장치 정보 브로드캐스트 |
| `device_info_req` | 장치 상태 갱신 요청 |
| `aggregate` | 센서 데이터 요약 |
| `web_command` | 웹에서 보낸 명령 |

## 아키텍처

```
┌─────────────────────────────────────────┐
│           게이트웨이 노드 (ESP32-S3)        │
│  ┌───────────┐  ┌──────────┐  ┌──────┐ │
│  │ 메시 엔진  │  │ 웹 서버   │  │ MQTT │ │
│  │(ESP-NOW)  │←→│(포트 80)  │  │브릿지 │ │
│  └─────┬─────┘  └──────────┘  └──────┘ │
│        │                                │
│  ┌─────┴─────────────────────────────┐ │
│  │  자동화 엔진 (규칙 평가/실행)         │ │
│  └───────────────────────────────────┘ │
│  ┌──────────┐  ┌──────────┐            │
│  │ 센서매니저 │  │ GPIO매니저│            │
│  │  (sm)    │  │  (gm)    │            │
│  └──────────┘  └──────────┘            │
└─────────────────────────────────────────┘
         ↑ ESP-NOW 브로드캐스트 ↓
┌──────────────────┐  ┌──────────────────┐
│   노드 A (ESP32)  │  │   노드 B (ESP32)  │
│  센서 + GPIO 제어 │  │  센서 + GPIO 제어 │
└──────────────────┘  └──────────────────┘
```
