# ESP-NOW Mesh Network Pro

MicroPython (ESP32-S3) based ESP-NOW mesh network.
Integrates sensor collection, GPIO remote control, web dashboard, and automation rule engine.

## File Structure

### Core Modules (Upload to ESP32-S3 Root)

| File | Purpose |
|------|---------|
| `main.py` | Boot script (20-second countdown then auto-start) |
| `espnow_mesh_pro.py` | Mesh network main (node + gateway + web server + REPL) |
| `mesh_state.py` | Data store classes + singletons (stats, peers, sensor_store, automation_rules, etc.) |
| `mesh_config.py` | Config class (config.txt read/write, cfg singleton) |
| `sensor_runner.py` | SensorManager class (sensor read/send, sm singleton) |
| `gpio_control.py` | GPIOManager class (GPIO/PWM/NeoPixel/I2C expander control, gm singleton) |
| `sensors.py` | Sensor initialization standard logic (auto-calls setup(), references custom/node_config.py) |
| `devices.py` | GPIO/PWM/NeoPixel/I2C initialization standard logic (auto-calls setup()) |
| `web_pages.py` | Web dashboard HTML pages (module-based, .mpy compilable) |

### User Configuration (custom/ folder)

Files that users modify per node. Auto-imported at boot and setup() is called.

| File | Purpose |
|------|---------|
| `custom/node_config.py` | Per-node settings (sensor/GPIO/PWM/NeoPixel/I2C name and pin mapping) |
| `custom/automation.py` | Automation rules (gateway only) |
| `custom/config.txt.sample` | config.txt sample template |

> **Note**: If the `custom/` folder is missing, `node_config`/`automation` modules will not be loaded. Modules in `custom/` can reference each other via `import node_config` (custom/ is automatically added to sys.path). `sensors.py` and `devices.py` are standard logic files in the root that read settings from `custom/node_config.py`.

### Examples (examples/ folder)

| File | Purpose | Environment |
|------|---------|-------------|
| `examples/sensor_example.py` | Sensor usage example (DHT22/BH1750/ADC) | ESP32-S3 |
| `examples/smart_home_scenario.py` | Smart home automation scenario example | ESP32-S3 |
| `examples/mesh_client.py` | PC/smartphone client (HTTP/MQTT) | Python 3.x |
| `examples/espnow_mesh_secure.py` | AES encrypted mesh network version | ESP32-S3 |

## Key Features

### Mesh Network

- Wi-Fi + ESP-NOW mesh (broadcast + TTL relay)
- Auto identification: NODE_ID/NICKNAME auto-generated from MAC address
- config.txt persistence: all settings auto-saved
- Node roles: `node` / `gateway`
- Gateway redundancy: msg_id deduplication, automatic failover
- Self-healing: heartbeat + 90-second timeout

### Web Dashboard (Gateway Only)

- Nodes / Sensors / Device Control Panel / Automation Rules / Control Log
- GPIO ON/OFF buttons, PWM sliders, NeoPixel color picker (instant control)
- Stats page (network statistics, chip temperature, CPU frequency)
- Config page (Wi-Fi/MQTT settings, manual time setting)
- API call caching to reduce CPU load and heat

### Automation Engine

- Sensor-based rules (hysteresis, thresholds)
- Time-based rules (day of week / time range)
- Sunrise/sunset rules (latitude/longitude based)
- Priority conflict resolution (multiple rules on same device)
- Rule groups (any/all mode)
- Additional conditions (multi-sensor conditions, GPIO device state conditions)
- action_off (auto OFF when state released)
- Timer switch (auto OFF after N seconds)
- automation.txt persistence

### Sensor Support

- DHT22/DHT11 (temperature/humidity)
- BH1750 (light level, I2C)
- BME280 (temp/humidity/pressure, I2C)
- SHT30 (temp/humidity, I2C)
- AHT10 (temp/humidity, I2C)
- DS18B20 (1-Wire temperature)
- MAX6675 (thermocouple, SPI)
- MCP3008 (ADC, SPI)
- SGP30 (CO2/TVOC, I2C)
- MPU6050 (accelerometer/gyroscope, I2C) — raw accel/gyro, roll/pitch, accel magnitude, gyro-integrated yaw
- ADS1115 (4-channel 16-bit I2C ADC)
- CdS photoresistor (analog light, internal ADC) — raw/voltage/lux/percent/resistance
- Hall sensor (analog field strength / digital detection+count+RPM)
- ESP32 internal ADC
- I2C GPIO expander inputs (MCP23017/PCF8574 as digital sensor)

### GPIO Control

- Digital output (GPIO ON/OFF)
- PWM output (0-1023 or 0-100%)
- NeoPixel (RGB LED, color control)
- MCP23017 (I2C 16-channel GPIO expander)
- PCF8574 (I2C 8-channel GPIO expander)
- Timer switch (auto OFF after specified seconds)
- Device info broadcast (device_info message)

### Thermal Management

- CPU clock auto-adjust based on chip temperature (55°C→80MHz, 45°C→160MHz, below→240MHz)
- Temperature monitoring every 3 seconds
- Wi-Fi TX power adjustable via REPL (`/wifipower 8-20`)
- Reduced polling intervals (dashboard 3s, stats 5s)
- API call caching (nodes/rules every 15s, log every 10s)

## Quick Start

### 1. Upload to ESP32-S3

```bash
# Core modules (root)
mpremote connect /dev/ttyUSB0 cp main.py :main.py
mpremote connect /dev/ttyUSB0 cp espnow_mesh_pro.py :espnow_mesh_pro.py
mpremote connect /dev/ttyUSB0 cp mesh_state.py :mesh_state.py
mpremote connect /dev/ttyUSB0 cp mesh_config.py :mesh_config.py
mpremote connect /dev/ttyUSB0 cp sensor_runner.py :sensor_runner.py
mpremote connect /dev/ttyUSB0 cp gpio_control.py :gpio_control.py
mpremote connect /dev/ttyUSB0 cp sensors.py :sensors.py
mpremote connect /dev/ttyUSB0 cp devices.py :devices.py
mpremote connect /dev/ttyUSB0 cp web_pages.py :web_pages.py

# custom/ folder
mpremote connect /dev/ttyUSB0 mkdir custom
mpremote connect /dev/ttyUSB0 cp custom/node_config.py :custom/node_config.py
mpremote connect /dev/ttyUSB0 cp custom/automation.py :custom/automation.py
mpremote connect /dev/ttyUSB0 cp custom/config.txt.sample :config.txt
mpremote connect /dev/ttyUSB0 reset
```

Or use Thonny / rshell / ampy.

### 2. First Boot

If config.txt does not exist, it is auto-generated from MAC address:

```
[CONFIG] config.txt not found. Using defaults.
[CONFIG] NODE_ID auto-generated: node-76c204 (MAC-based)
[CONFIG] NICKNAME auto-generated: ESP-c204 (MAC-based)
[CONFIG] NODE_ROLE default: node
[CONFIG] First boot. config.txt auto-generated.
```

After 20-second countdown, the mesh network starts automatically.

### 3. Set Role to Gateway

In REPL:

```
/role gateway
/config wifi MyWiFi mypassword
/config mqtt_enable on
/config mqtt broker.hivemq.com 1883
/config save
```

Reset to apply changes.

### 4. Access Web Dashboard

Open browser to the IP shown at gateway boot:

```
http://192.168.1.50/
```

### 5. AP Mode Fallback

If Wi-Fi connection fails, the gateway automatically switches to AP mode:

```
SSID: ESP32-Mesh-XXXX (MAC-based)
Password: mesh1234
IP: 192.168.4.1
```

Connect to this AP and access `http://192.168.4.1/config` to set correct Wi-Fi.

## config.txt Format

```
node_id=node-76c204
nickname=ESP-c204
node_role=node
gateway_ssid=MyWiFi
gateway_password=mypassword
mqtt_enabled=false
mqtt_broker=broker.hivemq.com
mqtt_port=1883
mqtt_topic_up=mesh/chat/up
mqtt_topic_down=mesh/chat/down
mqtt_topic_sensor=mesh/sensor
gateway_group_id=mesh-gw-1
```

## custom/node_config.py Settings

```python
# Sensor settings
SENSOR_CONFIG = {
    "temperature": ("dht", 4, "temp"),
    "humidity": ("dht", 4, "humidity"),
    "light": ("bh1750", 0x23, "lux"),
    "battery": ("adc", 1, "voltage"),
    # ADS1115 I2C ADC
    # "external_voltage": ("ads1115", 0x48, 0, "voltage"),
    # I2C GPIO input (MCP23017/PCF8574)
    # "door_sensor": ("i2c_input", "mcp23017", (0x20, 2), ""),
}

# GPIO output settings
GPIO_CONFIG = {
    "living_light": 2,
    "boiler": 3,
}

# PWM output settings
PWM_CONFIG = {
    "living_fan": 5,
}

# NeoPixel output settings
NEOPIXEL_CONFIG = {
    "board_led": 48,  # Onboard NeoPixel
}
NEOPIXEL_COUNT = 1

# I2C GPIO expander settings
MCP23017_CONFIG = {
    # "ext_relay1": (0x20, 0),
}
PCF8574_CONFIG = {
    # "ext_relay2": (0x21, 0),
}

# I2C bus settings (shared by MCP23017/PCF8574/ADS1115)
I2C_SDA_PIN = 8
I2C_SCL_PIN = 9
I2C_FREQ = 400000

# Sensor intervals
SENSOR_READ_INTERVAL = 3   # Read every 3 seconds
SENSOR_SEND_INTERVAL = 5   # Send every 5 seconds
```

### MPU6050 (6-axis accelerometer/gyroscope)

MPU6050 connects via I2C at default address `0x68` (AD0=GND) or `0x69` (AD0=VDD). Multiple derived channels can be registered from a single chip. Channels sharing the same address reuse one I2C read for 500 ms, so there is no extra bus load.

**Supported channels:**

| channel | unit | description |
|---------|------|-------------|
| `ax` `ay` `az` | g | acceleration (±2g, 1g=16384 LSB) |
| `gx` `gy` `gz` | dps | gyro angular rate (±250 dps, 1 dps=131 LSB) |
| `temp` | C | chip internal temperature |
| `roll` | deg | accelerometer-based roll (`atan2(ay, az)`) |
| `pitch` | deg | accelerometer-based pitch (`atan2(-ax, √(ay²+az²))`) |
| `amag` | g | acceleration magnitude (≈1.0 at rest, spikes on shock) |
| `gyaw` | deg | gyro-Z integrated relative heading (drifts over time) |

```python
# custom/node_config.py
SENSOR_CONFIG = {
    "tilt_roll":  ("mpu6050", 0x68, "roll"),
    "tilt_pitch": ("mpu6050", 0x68, "pitch"),
    "accel_mag":  ("mpu6050", 0x68, "amag"),   # shock/fall detection
    "heading":    ("mpu6050", 0x68, "gyaw"),   # relative rotation
    "mpu_temp":   ("mpu6050", 0x68, "temp"),
}
```

**Yaw recalibration:** the gyro-integrated value drifts over time. Reset to zero at a known orientation with:

```python
import sensor_runner
sensor_runner.sm.reset_mpu_yaw(0x68)   # specific chip only
sensor_runner.sm.reset_mpu_yaw()       # all registered MPU6050s
```

**Note:** `gyaw` is a gyro-only relative angle, not an absolute heading. For absolute heading use a magnetometer-equipped chip (e.g. MPU9250). `roll`/`pitch` are gravity-referenced and accurate at rest or during slow motion.

### AHT10 (temperature/humidity, I2C)

AHT10 is a low-power I2C temp/humidity sensor. Default address `0x38` (AD0 high: `0x39`). Two channels share one 80 ms measurement, so registering both `temp` and `humidity` costs only one I2C blocking read per cycle.

| channel | unit | description |
|---------|------|-------------|
| `temp` | C | temperature (-50 to +150 °C) |
| `humidity` | % | relative humidity (0-100 %) |

```python
# custom/node_config.py
SENSOR_CONFIG = {
    "aht_temp": ("aht10", 0x38, "temp"),
    "aht_humi": ("aht10", 0x38, "humidity"),
}
```

Initialization sends the calibration command (`0xBE 0x08 0x00`) and waits for the calibrated bit; if calibration is incomplete it still proceeds. Measurement triggers `0xAC 0x33 0x00` and waits ~80 ms (plus a short busy-bit poll). The 20-bit raw values are converted with the standard `raw / 2^20` formula.

### CdS Photoresistor (analog light sensor)

A CdS cell (GL5528/GM5528 etc.) is read via a voltage divider on an ESP32 ADC pin. The `cds` type goes beyond raw ADC: with a per-sensor calibration it converts the midpoint voltage into CdS resistance, then into estimated lux and a relative brightness percent.

**Wiring (recommended):** `Vcc --[CdS]--(ADC pin)--[R_fixed]-- GND` → `cds_top=True`. Reverse divider `Vcc --[R_fixed]--(ADC pin)--[CdS]-- GND` → `cds_top=False`.

**Channels:**

| channel | unit | needs calib | description |
|---------|------|-------------|-------------|
| `raw` | — | no | ADC raw 0-4095 |
| `voltage` | V | no | divider midpoint voltage |
| `resistance` | ohm | yes | CdS resistance (from divider math) |
| `lux` | lx | yes | estimated lux via CdS log-log characteristic |
| `percent` | % | yes | log-scaled brightness 0-100 (maps 0-10000 lx) |

```python
# custom/node_config.py
SENSOR_CONFIG = {
    "light": ("cds", 2, "lux"),       # estimated lux
    # "light_raw": ("cds", 2, "raw"), # fallback if no calibration
}

# Calibration (lux/percent/resistance channels require this)
CDS_CALIB = {
    "light": {"r_fixed": 10000, "vcc": 3.3, "cds_top": True,
              "r10": 20000, "gamma": 0.7},
}
```

**Calibration fields:** `r_fixed` (divider resistor, ohm), `vcc` (supply V, ESP32=3.3), `cds_top` (CdS on Vcc side: True; on GND side: False), `r10` (CdS resistance at 10 lux — see the cell's datasheet, GL5528 ≈ 10-20 kΩ), `gamma` (log-log slope, 0.5-0.8, GL5528 ≈ 0.7). Lux is computed as `10 * (R10/R)^(1/gamma)` from the standard CdS R–lux log-log relation. Sensors without a `CDS_CALIB` entry can still use the `raw` and `voltage` channels.

### Hall Sensor (magnetic field / detection)

A Hall sensor measures magnetic fields. The `hall` type supports both **analog** (ratiometric voltage → field strength in Gauss) and **digital** (open-collector output → detection / pulse count / RPM) devices. The mode is set per sensor in `HALL_CALIB`; if omitted it is inferred from the channel (`state`/`count`/`rpm` → digital, otherwise analog).

**Analog Hall** (A1301/A1302/49E/SS495 etc.): output sits at `v_quiescent` (~Vcc/2) at zero field and deviates proportionally with field polarity. Read via ADC.

| channel | unit | needs calib | description |
|---------|------|-------------|-------------|
| `raw` | — | no | ADC raw 0-4095 |
| `voltage` | V | no | sensor output voltage |
| `field` | G | yes | signed field strength (Gauss) |
| `polarity` | — | yes | 1 (N), -1 (S), 0 (none) |

`field = (voltage - v_quiescent) × 1000 / sensitivity`, where `sensitivity` is in mV/G (datasheet; A1301=2.5, 49E≈1.6). `polarity` uses a `threshold` in Gauss (default 5).

**Digital Hall** (A3144/44E/3144 latching or switch): open-collector output toggles when a magnet is near. Read via GPIO with an interrupt-based edge counter.

| channel | unit | needs calib | description |
|---------|------|-------------|-------------|
| `state` | — | no | current pin level (0/1) |
| `count` | — | no* | cumulative pulse count since boot (interrupt) |
| `rpm` | rpm | no* | rotations/min since last read |

\* `count`/`rpm` work with defaults (`pull=up`, `detect=falling`, `ppr=1`); set `HALL_CALIB` to change edge/pull/pulses-per-rev. RPM is computed as `(Δcount / ppr) × 60000 / Δt_ms` between reads, so it reflects the average speed over the read interval (not instantaneous).

```python
# custom/node_config.py
SENSOR_CONFIG = {
    # analog: field strength
    "field":   ("hall", 4, "field"),
    # digital: detection + rotation counting
    "detect":  ("hall", 5, "state"),
    "rpm":     ("hall", 5, "rpm"),
}

HALL_CALIB = {
    "field": {"mode": "analog",  "vcc": 3.3, "v_quiescent": 1.65,
              "sensitivity": 2.5, "threshold": 5.0},
    "rpm":   {"mode": "digital", "pull": "up", "detect": "falling", "ppr": 1},
}
```

**Wiring:** analog Hall → ADC pin (share Vcc/GND). Digital Hall → GPIO pin with pull-up (internal or external 10 kΩ); the open-collector pulls the line low when a magnet is detected. For RPM/rotation, mount one magnet on the rotating part and fix the sensor nearby; one pass = one pulse (`ppr=1`). Multiple magnets or multi-pole rings raise `ppr` accordingly.

## Automation Rules

Add rules in `custom/automation.py`:

```python
def setup():
    import espnow_mesh_pro as mesh

    # Temperature > 25°C → fan 50% (hysteresis ±1)
    mesh.automation_rules.add_rule(
        name="High temp fan 50%",
        sensor="temperature", operator=">", value=25,
        action_device="living_fan", action_value="50",
        hysteresis=1.0, cooldown_sec=60,
        priority=10,
        action_off={"device": "living_fan", "value": "0"},
    )

    # Weekday morning boiler (06:00-08:00)
    mesh.automation_rules.add_rule(
        name="Weekday morning boiler",
        rule_type="time",
        schedule={"days": [0,1,2,3,4], "start": 600, "end": 800},
        action_device="boiler", action_value="1",
        cooldown_sec=60, priority=5,
        action_off={"device": "boiler", "value": "0"},
    )

    # Boiler only when light is ON (device condition)
    mesh.automation_rules.add_rule(
        name="Light ON + cold → boiler",
        sensor="temperature", operator="<", value=20,
        action_device="boiler", action_value="1",
        hysteresis=1.0, cooldown_sec=60,
        priority=5,
        conditions=[
            {"device": "living_light", "operator": "==", "value": 1},
        ],
        action_off={"device": "boiler", "value": "0"},
    )
```

## REPL Commands

```
/who                    Node list
/discover               Discover nodes
/nick <name>            Change nickname
/role <role>            node|gateway
/stats                  Statistics (incl. chip temp, CPU freq)
/sensors                Sensor data
/config                 Current settings
/config wifi <ssid> <pass>
/config mqtt <broker> [port]
/config mqtt_enable on|off
/config save            Save to config.txt
/config reload          Reload config.txt
/wifipower [dBm]        Wi-Fi TX power (8-20, default 20)
/autolog on|off         Automation trigger log show/hide
/GPIO <name> <value> [timer_sec]  Device control (case-insensitive)
/help                   Help
/quit                   Quit
```

## GPIO Command Examples

```
/GPIO living_light 1        # Turn ON
/GPIO living_light 0        # Turn OFF
/GPIO living_fan 50         # PWM 50%
/GPIO board_led 0xFF0000    # NeoPixel red
/GPIO board_led 255,0,0     # NeoPixel red (RGB string)
/GPIO board_led 0           # NeoPixel OFF
/GPIO living_light 1 30     # ON, auto OFF after 30 seconds
/GPIO list                  # List all devices
```

## Web API

| Endpoint | Purpose |
|----------|---------|
| `GET /` | Web dashboard |
| `GET /stats` | Stats page |
| `GET /config` | Config page |
| `GET /api/nodes` | Node list |
| `GET /api/stats` | Statistics (incl. chip_temp, cpu_freq_mhz) |
| `GET /api/sensors` | Sensor data |
| `GET /api/devices` | Device list (GPIO/PWM/NeoPixel, excl. sensors) |
| `GET /api/config` | Configuration |
| `GET /api/config_save` | Save configuration |
| `GET /api/control?name=<device>&value=<value>` | Device control |
| `GET /api/automation?action=list\|add\|remove\|log\|clear_log` | Automation rules |
| `GET /api/settime?time=<YYYY-MM-DDTHH:MM:SS>` | Manual time setting |
| `GET /api/ping` | Connection test |

## Mesh Message Types

| Type | Purpose |
|------|---------|
| `chat` | General message |
| `sensor` | Sensor data |
| `system` | System notification |
| `heartbeat` | Node activity signal |
| `discover` | Node discovery request |
| `gw_presence` | Gateway presence announcement |
| `device_info` | Device info broadcast |
| `device_info_req` | Device status update request |
| `web_command` | Web-originated command |

## Architecture

```
┌─────────────────────────────────────────────┐
│           Gateway Node (ESP32-S3)            │
│  ┌───────────┐  ┌──────────┐  ┌──────┐     │
│  │ Mesh Engine│  │ Web Server│  │ MQTT │     │
│  │ (ESP-NOW)  │←→│ (Port 80) │  │Bridge│     │
│  └─────┬─────┘  └──────────┘  └──────┘     │
│        │                                     │
│  ┌─────┴────────────────────────────────┐   │
│  │  Automation Engine (rule eval/exec)   │   │
│  └──────────────────────────────────────┘   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │Sensor Mgr│  │ GPIO Mgr │  │Temp Monitor│ │
│  │  (sm)    │  │  (gm)    │  │(clock adj) │ │
│  └──────────┘  └──────────┘  └──────────┘  │
└─────────────────────────────────────────────┘
         ↑ ESP-NOW broadcast ↓
┌──────────────────┐  ┌──────────────────┐
│   Node A (ESP32)  │  │   Node B (ESP32)  │
│  Sensor + GPIO    │  │  Sensor + GPIO    │
└──────────────────┘  └──────────────────┘
```

## NTP Time Synchronization

- On Wi-Fi connection success, NTP sync is attempted
- If NTP fails, retries every 1 minute until success
- After success, re-syncs weekly
- Manual time setting via web dashboard (`/config` page)
- Timezone: KST (UTC+9), adjustable in code

## Thermal Management Details

| Temperature | CPU Clock | Action |
|-------------|-----------|--------|
| ≥ 55°C | 80 MHz | Overheat protection |
| ≥ 45°C | 160 MHz | Heat reduction |
| < 45°C | 240 MHz | Maximum performance |

- Chip temperature monitored every 3 seconds via `esp32.mcu_temperature()`
- Clock changes only logged when threshold is crossed
- Wi-Fi TX power adjustable (8-20 dBm) via `/wifipower` REPL command
