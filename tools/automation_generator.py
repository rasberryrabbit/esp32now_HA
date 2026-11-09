#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
automation_generator.py - ESP-NOW 메쉬 네트워크 자동화 규칙 생성기
==============================================================
ESP-NOW mesh network automation rule generator (interactive CLI).

이 도구는 사용자와 대화형으로 질문을 주고받으며
custom/automation.py 의 setup() 함수에 들어갈
mesh.automation_rules.add_rule(...) 호출 코드를 자동 생성합니다.

This tool interactively asks the user questions and generates the
Python code that calls mesh.automation_rules.add_rule(...) to be
placed inside the setup() function of custom/automation.py.

지원 규칙 타입 / Supported rule types:
  - sensor : 센서 임계값 규칙 / sensor threshold rule
  - time   : 시간 기반 규칙 / time-based rule
  - sun    : 일출/일몰 규칙 / sunrise-sunset rule

기능 / Features:
  - NeoPixel 색상 값 (0xRRGGBB, R,G,B, 색상 이름) 지원
  - 타이머 스위치 (트리거 후 N초 뒤 자동 OFF) 지원
  - 추가 조건(conditions), 해제 시 자동 OFF(action_off) 지원
  - 우선순위(priority), 쿨다운(cooldown_sec) 설정
  - 기존 automation.py 에 규칙 추가(append) 또는 새로 만들기(create)
  - 표준 라이브러리만 사용 (CPython / MicroPython 호환)

사용법 / Usage:
  python automation_generator.py        # CPython
  (MicroPython REPL 에서도 동일하게 실행 가능)

참고 / Note:
  - f-string 을 사용하지 않고 .format() 사용 (MicroPython 호환)
  - os.path 대신 try/except open() 으로 파일 존재 확인 (MicroPython 호환)
"""

# ============================================================
# 전역 상수 / Global constants
# ============================================================

# 지원 연산자 / Supported operators
OPERATORS = ['>', '<', '>=', '<=', '==', '!=']

# 자동화 규칙 삽입 마커 / Insertion marker for automation.py
MARKER = '# === AUTOMATION_GENERATOR INSERT POINT ==='

# NeoPixel 색상 이름 → 값 매핑 (한/영 모두 지원)
# NeoPixel color name -> value mapping (Korean + English)
COLOR_NAMES = {
    # 영문 / English
    'red': '0xFF0000', 'green': '0x00FF00', 'blue': '0x0000FF',
    'yellow': '0xFFFF00', 'cyan': '0x00FFFF', 'magenta': '0xFF00FF',
    'white': '0xFFFFFF', 'orange': '0xFF6400', 'purple': '0x8000FF',
    'off': '0x000000', 'black': '0x000000',
    # 한글 / Korean
    '빨강': '0xFF0000', '빨강색': '0xFF0000', '빨간색': '0xFF0000',
    '초록': '0x00FF00', '초록색': '0x00FF00', '녹색': '0x00FF00',
    '파랑': '0x0000FF', '파랑색': '0x0000FF', '청색': '0x0000FF',
    '노랑': '0xFFFF00', '노랑색': '0xFFFF00', '황색': '0xFFFF00',
    '청록': '0x00FFFF',
    '자주': '0xFF00FF', '보라': '0x8000FF',
    '하양': '0xFFFFFF', '하얀색': '0xFFFFFF', '흰색': '0xFFFFFF',
    '주황': '0xFF6400', '주황색': '0xFF6400',
    '꺼짐': '0x000000', '검정': '0x000000',
}

# 요일 이름 / Day-of-week names (Python tm_wday 기준: 0=월/Mon .. 6=일/Sun)
DAY_NAMES_KR = ['월', '화', '수', '목', '금', '토', '일']
DAY_NAMES_EN = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']


# ============================================================
# 입력 도우미 / Input helpers
# ============================================================

def _input(prompt):
    """input() 래퍼. EOF(Ctrl+D) 시 EOFError 를 발생시켜 main 에서 처리.
    Wrapper around input(); raises EOFError on EOF (handled in main)."""
    return input(prompt)


def ask_str(prompt, default=None, allow_empty=False):
    """문자열 입력. 기본값 지원.
    Ask for a string, with optional default."""
    hint = ''
    if default is not None:
        hint = ' (기본/default: {})'.format(default)
    while True:
        s = _input(prompt + hint + ': ').strip()
        if not s:
            if default is not None:
                return default
            if allow_empty:
                return ''
            print('  ! 입력이 필요합니다. / Input required.')
            continue
        return s


def ask_int(prompt, default=None, min_val=None, max_val=None):
    """정수 입력. 범위 검증 포함.
    Ask for an integer with optional range validation."""
    hint = ''
    if default is not None:
        hint = ' (기본/default: {})'.format(default)
    while True:
        s = _input(prompt + hint + ': ').strip()
        if not s:
            if default is not None:
                return default
            print('  ! 입력이 필요합니다. / Input required.')
            continue
        try:
            v = int(s)
        except ValueError:
            print('  ! 정수를 입력하세요. / Please enter an integer.')
            continue
        if min_val is not None and v < min_val:
            print('  ! 최소값은 {} 입니다. / Minimum is {}.'.format(min_val, min_val))
            continue
        if max_val is not None and v > max_val:
            print('  ! 최대값은 {} 입니다. / Maximum is {}.'.format(max_val, max_val))
            continue
        return v


def ask_float(prompt, default=None, min_val=None, max_val=None):
    """실수 입력. 정수로 떨어지면 int 로 변환.
    Ask for a float; converts to int if it's a whole number."""
    hint = ''
    if default is not None:
        hint = ' (기본/default: {})'.format(default)
    while True:
        s = _input(prompt + hint + ': ').strip()
        if not s:
            if default is not None:
                return default
            print('  ! 입력이 필요합니다. / Input required.')
            continue
        try:
            v = float(s)
        except ValueError:
            print('  ! 숫자를 입력하세요. / Please enter a number.')
            continue
        if min_val is not None and v < min_val:
            print('  ! 최소값은 {} 입니다. / Minimum is {}.'.format(min_val, min_val))
            continue
        if max_val is not None and v > max_val:
            print('  ! 최대값은 {} 입니다. / Maximum is {}.'.format(max_val, max_val))
            continue
        # 정수로 떨어지면 int 로 변환 (출력 코드를 깔끔하게 유지)
        # Convert to int if whole number, for cleaner generated code.
        if v == int(v):
            v = int(v)
        return v


def ask_bool(prompt, default=None):
    """y/n 질문. 한/영 모두 지원.
    Yes/no question; supports Korean and English."""
    if default is True:
        hint = ' (Y/n)'
    elif default is False:
        hint = ' (y/N)'
    else:
        hint = ' (y/n)'
    while True:
        s = _input(prompt + hint + ': ').strip().lower()
        if not s:
            if default is not None:
                return default
            print('  ! y 또는 n 을 입력하세요. / Please enter y or n.')
            continue
        if s in ('y', 'yes', '예', '네', 'ㅇ'):
            return True
        if s in ('n', 'no', '아니오', '아니요', 'ㄴ'):
            return False
        print('  ! y 또는 n 을 입력하세요. / Please enter y or n.')


def ask_choice(prompt, choices, default=None):
    """번호 선택 메뉴. choices: [(value, label), ...] 또는 [str, ...]
    Numbered menu selection."""
    # choices 가 문자열 리스트면 (value, label) 튜플로 변환
    if choices and isinstance(choices[0], str):
        choices = [(c, c) for c in choices]
    print('')
    print(prompt)
    for i, (val, label) in enumerate(choices, 1):
        print('  {}) {}'.format(i, label))
    default_idx = None
    if default is not None:
        for i, (val, label) in enumerate(choices, 1):
            if val == default:
                default_idx = i
                break
    while True:
        hint = '선택 / Choose [1-{}]'.format(len(choices))
        if default_idx is not None:
            hint += ' (기본/default: {})'.format(default_idx)
        s = _input(hint + ': ').strip()
        if not s and default_idx is not None:
            return choices[default_idx - 1][0]
        # 번호 입력 / by number
        try:
            n = int(s)
            if 1 <= n <= len(choices):
                return choices[n - 1][0]
        except ValueError:
            pass
        # 값 직접 입력 / by value string
        low = s.lower()
        for val, label in choices:
            if str(val).lower() == low:
                return val
        print('  ! 잘못된 선택입니다. / Invalid choice.')


def ask_operator(prompt, default='>'):
    """비교 연산자 선택.
    Select a comparison operator."""
    print('')
    print(prompt)
    for i, op in enumerate(OPERATORS, 1):
        print('  {}) {}'.format(i, op))
    while True:
        s = _input('연산자 선택 / Choose [1-{}] (기본/default: {}): '
                   .format(len(OPERATORS), default)).strip()
        if not s:
            return default
        if s in OPERATORS:
            return s
        try:
            n = int(s)
            if 1 <= n <= len(OPERATORS):
                return OPERATORS[n - 1]
        except ValueError:
            pass
        print('  ! 잘못된 선택입니다. / Invalid choice.')


# ============================================================
# 값 검증 / Value parsers
# ============================================================

def parse_time(s):
    """시간 문자열 → 정수(HH*100+MM). 'HH:MM' 또는 'HHMM' 지원.
    Parse a time string to integer HHMM. Returns None on failure."""
    s = s.strip()
    if not s:
        return None
    # HHMM 정수 / integer form
    if ':' not in s:
        try:
            n = int(s)
            hh = n // 100
            mm = n % 100
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                return hh * 100 + mm
        except ValueError:
            pass
        return None
    # HH:MM 형식 / colon form
    parts = s.split(':')
    if len(parts) != 2:
        return None
    try:
        hh = int(parts[0])
        mm = int(parts[1])
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return hh * 100 + mm
    except ValueError:
        pass
    return None


def _time_to_str(t):
    """정수 HHMM → 'HH:MM' 문자열."""
    hh = t // 100
    mm = t % 100
    return '{:02d}:{:02d}'.format(hh, mm)


def parse_days(s):
    """요일 문자열 → [0..6] 리스트.
    키워드: 평일/주말/매일 또는 쉼표 구분 숫자/이름.
    Parse days string to a sorted list of weekday ints (0=Mon..6=Sun)."""
    s = s.strip().lower()
    if not s:
        return None
    keywords = {
        '평일': [0, 1, 2, 3, 4], 'weekday': [0, 1, 2, 3, 4],
        'weekdays': [0, 1, 2, 3, 4],
        '주말': [5, 6], 'weekend': [5, 6], 'weekends': [5, 6],
        '매일': [0, 1, 2, 3, 4, 5, 6], 'everyday': [0, 1, 2, 3, 4, 5, 6],
        'daily': [0, 1, 2, 3, 4, 5, 6], 'all': [0, 1, 2, 3, 4, 5, 6],
        '매일매일': [0, 1, 2, 3, 4, 5, 6],
    }
    if s in keywords:
        return keywords[s]
    days = []
    for part in s.split(','):
        part = part.strip()
        if not part:
            continue
        # 숫자 / number
        try:
            n = int(part)
            if 0 <= n <= 6:
                days.append(n)
                continue
        except ValueError:
            pass
        # 한글 요일 / Korean day name
        if part in DAY_NAMES_KR:
            days.append(DAY_NAMES_KR.index(part))
            continue
        # 영문 요일(앞 3글자) / English short name
        low3 = part[:3].lower()
        en_lower = [d.lower() for d in DAY_NAMES_EN]
        if low3 in en_lower:
            days.append(en_lower.index(low3))
            continue
        return None  # 알 수 없는 토큰 / unknown token
    if not days:
        return None
    # 중복 제거 + 정렬 / dedupe & sort
    seen = []
    for d in days:
        if d not in seen:
            seen.append(d)
    seen.sort()
    return seen


def _days_to_str(days):
    """[0,1,2] → '월,화,수' 처럼 보기 좋게."""
    if not days:
        return ''
    return ', '.join(DAY_NAMES_KR[d] for d in days)


def ask_time(prompt, default=None):
    """시간 입력(검증 포함). HH:MM 또는 HHMM."""
    hint = ' (HH:MM 또는/or HHMM)'
    if default is not None:
        hint += ' (기본/default: {})'.format(_time_to_str(default))
    while True:
        s = _input(prompt + hint + ': ').strip()
        if not s and default is not None:
            return default
        v = parse_time(s)
        if v is not None:
            return v
        print('  ! 시간 형식: HH:MM 또는 HHMM. / Format: HH:MM or HHMM.')


def ask_days(prompt, default=None):
    """요일 입력(검증 포함)."""
    hint = ' (예: 평일/주말/매일 또는 0,1,2,3,4)'
    if default is not None:
        hint += ' (기본/default: {})'.format(_days_to_str(default))
    while True:
        s = _input(prompt + hint + ': ').strip()
        if not s and default is not None:
            return default
        v = parse_days(s)
        if v is not None:
            return v
        print('  ! 올바른 요일을 입력하세요. / Please enter valid days.')


def validate_color(s):
    """NeoPixel 색상 값 검증. 반환: '0xRRGGBB' 또는 'R,G,B' 문자열.
    Validate a NeoPixel color value."""
    s = s.strip()
    if not s:
        return None
    low = s.lower()
    # 색상 이름 / color name
    if low in COLOR_NAMES:
        return COLOR_NAMES[low]
    # 0xRRGGBB
    if low.startswith('0x') and len(low) == 8:
        try:
            int(low, 16)
            return low
        except ValueError:
            pass
    # #RRGGBB
    if s.startswith('#') and len(s) == 7:
        try:
            int(s[1:], 16)
            return '0x' + s[1:].upper()
        except ValueError:
            pass
    # R,G,B
    if ',' in s:
        parts = s.split(',')
        if len(parts) == 3:
            try:
                rgb = tuple(int(p.strip()) for p in parts)
                if all(0 <= v <= 255 for v in rgb):
                    return '{},{},{}'.format(*rgb)
            except ValueError:
                pass
    return None


def validate_action_value(s):
    """액션 값 검증. 반환: 문자열('0','1','50','0xFF0000','255,0,0' 등).
    Validate an action value; returns a string literal content."""
    s = s.strip()
    if not s:
        return None
    low = s.lower()
    # 색상 이름 / color name (NeoPixel)
    if low in COLOR_NAMES:
        return COLOR_NAMES[low]
    # % 붙은 PWM / PWM with trailing %
    if s.endswith('%'):
        try:
            v = int(s[:-1].strip())
            if 0 <= v <= 100:
                return str(v)
        except ValueError:
            pass
    # 0xRRGGBB
    if low.startswith('0x') and len(low) == 8:
        try:
            int(low, 16)
            return low
        except ValueError:
            pass
    # #RRGGBB
    if s.startswith('#') and len(s) == 7:
        try:
            int(s[1:], 16)
            return '0x' + s[1:].upper()
        except ValueError:
            pass
    # R,G,B
    if ',' in s:
        parts = s.split(',')
        if len(parts) == 3:
            try:
                rgb = tuple(int(p.strip()) for p in parts)
                if all(0 <= v <= 255 for v in rgb):
                    return '{},{},{}'.format(*rgb)
            except ValueError:
                pass
    # 일반 정수 (0/1 또는 PWM 0-1023) / plain integer
    try:
        v = int(s)
        if 0 <= v <= 1023:
            return str(v)
    except ValueError:
        pass
    return None


def ask_action_value(action_device):
    """액션 값 입력. 색상/PWM/ON/OFF 모두 지원."""
    print('')
    print('  액션 값 / Action value for "{}":'.format(action_device))
    print('    - 1 / 0            : ON / OFF')
    print('    - 50               : PWM 50% (0-100 또는/or 0-1023)')
    print('    - 0xFF0000         : NeoPixel hex 색상 / hex color')
    print('    - 255,0,0          : NeoPixel RGB')
    print('    - red / 빨강 / off : 색상 이름 / color name')
    while True:
        s = _input('  액션 값 / Action value: ').strip()
        if not s:
            print('  ! 입력이 필요합니다. / Input required.')
            continue
        v = validate_action_value(s)
        if v is not None:
            return v
        print('  ! 올바르지 않은 값입니다. 다시 입력하세요. / Invalid value, try again.')


# ============================================================
# Python 리터럴 포맷터 / Python literal formatter
# ============================================================

def _fmt_str(s):
    """문자열을 큰따옴표 Python 리터럴로 변환 (한글 보존).
    Format a string as a double-quoted Python literal (preserves Korean)."""
    out = []
    for ch in s:
        if ch == '\\':
            out.append('\\\\')
        elif ch == '"':
            out.append('\\"')
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\t':
            out.append('\\t')
        elif ch == '\r':
            out.append('\\r')
        else:
            out.append(ch)
    return '"' + ''.join(out) + '"'


def _fmt_value(v, base_ind):
    """Python 값을 리터럴로 포맷. base_ind: 이 값이 있는 줄의 들여쓰기.
    Format a Python value as a literal. base_ind = indent of the line.

    작은 dict/list 는 한 줄로, 큰 것은 여러 줄로 출력합니다.
    Small dicts/lists are inlined; larger ones use multiple lines."""
    # bool 은 int 의 서브클래스이므로 먼저 검사
    # Check bool before int (bool is a subclass of int).
    if isinstance(v, bool):
        return 'True' if v else 'False'
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return _fmt_str(v)
    if isinstance(v, list):
        if not v:
            return '[]'
        # 단순 스칼라 요소만 있고 짧으면 한 줄로 / inline short simple lists
        simple = all(isinstance(x, (int, float, str, bool)) for x in v)
        if simple and len(v) <= 10:
            return '[' + ', '.join(_fmt_value(x, base_ind) for x in v) + ']'
        inner = base_ind + '    '
        parts = [inner + _fmt_value(x, inner) for x in v]
        return '[\n' + ',\n'.join(parts) + ',\n' + base_ind + ']'
    if isinstance(v, dict):
        if not v:
            return '{}'
        # 값이 모두 단순 스칼라이고 키가 4개 이하면 한 줄로 / inline small simple dicts
        simple = all(isinstance(val, (int, float, str, bool))
                     for val in v.values())
        if simple and len(v) <= 4:
            inner = ', '.join(_fmt_str(k) + ': ' + _fmt_value(val, base_ind)
                              for k, val in v.items())
            return '{' + inner + '}'
        inner = base_ind + '    '
        parts = [inner + _fmt_str(k) + ': ' + _fmt_value(val, inner)
                 for k, val in v.items()]
        return '{\n' + ',\n'.join(parts) + ',\n' + base_ind + '}'
    # fallback (알 수 없는 타입) / unknown type
    try:
        return repr(v)
    except Exception:
        return 'None'


# ============================================================
# 타임스탬프 / UID 생성 / Timestamp & UID helpers
# ============================================================

def _timestamp():
    """현재 시간 문자열. 실패 시 'unknown'."""
    try:
        import time as _t
        if hasattr(_t, 'localtime'):
            t = _t.localtime()
            return '{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(
                t[0], t[1], t[2], t[3], t[4], t[5])
    except Exception:
        pass
    return 'unknown'


def _gen_uid():
    """고유 ID 생성 (여러 번 추가 시 이름 충돌 방지).
    Generate a unique-ish id to avoid name collisions across appends."""
    try:
        import time as _t
        if hasattr(_t, 'time'):
            return int(_t.time()) % 100000
        if hasattr(_t, 'ticks_ms'):
            return _t.ticks_ms() % 100000
    except Exception:
        pass
    return 0


# ============================================================
# 코드 생성 / Code generation
# ============================================================

def generate_rule_block(rule, indent='    '):
    """단일 add_rule() 호출 코드 생성.
    Generate Python code for a single add_rule() call."""
    rt = rule.get('rule_type', 'sensor')
    type_label = {
        'sensor': '센서 규칙 / Sensor rule',
        'time': '시간 규칙 / Time rule',
        'sun': '일출/일몰 규칙 / Sunrise/Sunset rule',
    }.get(rt, rt)
    lines = []
    lines.append(indent + '# ' + '-' * 60)
    lines.append(indent + '# 규칙 / Rule: {}  ({})'.format(rule['name'], type_label))
    lines.append(indent + '# ' + '-' * 60)
    lines.append(indent + 'mesh.automation_rules.add_rule(')

    inner = indent + '    '

    # name
    lines.append(inner + 'name=' + _fmt_value(rule['name'], inner) + ',')

    # rule_type (sensor 가 기본값이므로 sensor 일 때는 생략)
    # Omit rule_type for sensor (it's the default).
    if rt != 'sensor':
        lines.append(inner + 'rule_type=' + _fmt_value(rt, inner) + ',')

    # 타입별 필드 / type-specific fields
    if rt == 'sensor':
        lines.append(inner + 'sensor=' + _fmt_value(rule['sensor'], inner) + ',')
        lines.append(inner + 'operator=' + _fmt_value(rule['operator'], inner) + ',')
        lines.append(inner + 'value=' + _fmt_value(rule['value'], inner) + ',')
    elif rt == 'time':
        lines.append(inner + 'schedule=' + _fmt_value(rule['schedule'], inner) + ',')
    elif rt == 'sun':
        lines.append(inner + 'sun_event=' + _fmt_value(rule['sun_event'], inner) + ',')

    # 공통 액션 필드 / common action fields
    lines.append(inner + 'action_device=' + _fmt_value(rule['action_device'], inner) + ',')
    lines.append(inner + 'action_value=' + _fmt_value(rule['action_value'], inner) + ',')

    # 센서 전용: 히스테리시스 / sensor-only: hysteresis
    if rt == 'sensor':
        lines.append(inner + 'hysteresis=' +
                     _fmt_value(rule.get('hysteresis', 0), inner) +
                     ',  # 히스테리시스 / hysteresis band')

    # 쿨다운 / cooldown
    lines.append(inner + 'cooldown_sec=' +
                 _fmt_value(rule.get('cooldown_sec', 60), inner) + ',')

    # 우선순위 / priority
    lines.append(inner + 'priority=' +
                 _fmt_value(rule.get('priority', 0), inner) +
                 ',  # 낮을수록 높음 / lower = higher priority')

    # 추가 조건 / additional conditions
    conds = rule.get('conditions')
    if conds:
        lines.append(inner + 'conditions=' + _fmt_value(conds, inner) + ',')

    # 해제 시 자동 OFF / action_off
    aoff = rule.get('action_off')
    if aoff:
        lines.append(inner + 'action_off=' + _fmt_value(aoff, inner) +
                     ',  # 해제 시 자동 OFF / auto-OFF when released')

    lines.append(indent + ')')
    return lines


def generate_timer_config(rules, uid, indent='    '):
    """타이머 설정 dict 생성. {규칙이름: [장치, 초]}
    Generate the _timer_config dict for rules with timer_sec."""
    cfg = {}
    for r in rules:
        if r.get('timer_sec'):
            cfg[r['name']] = [r['action_device'], r['timer_sec']]
    return (indent + '# 타이머 설정 / Timer config: {rule_name: [device, seconds]}\n' +
            indent + '_timer_config_' + str(uid) + ' = ' +
            _fmt_value(cfg, indent))


def generate_timer_loop(uid, indent='    '):
    """타이머 자동 OFF 백그라운드 루프 코드 생성.
    Generate the timer auto-OFF background coroutine.

    동작 원리 / How it works:
      - 규칙의 last_state 가 False→True 로 바뀌면(트리거 상승 엣지)
        gpio_control.gm.gpio_on_timer(device, seconds) 를 호출해
        지정된 초 후 자동으로 장치를 끕니다.
      - Polls each rule's last_state; on the rising edge (False->True)
        it calls gpio_on_timer() to auto-OFF the device after N seconds.
    """
    s = str(uid)
    lines = []
    lines.append(indent + '# ' + '=' * 60)
    lines.append(indent + '# 타이머 자동 OFF 루프 / Timer auto-OFF loop')
    lines.append(indent + '# timer_sec 가 설정된 규칙이 트리거되면 N초 후 장치를 끕니다.')
    lines.append(indent + '# When a timer-enabled rule triggers, device turns off after N sec.')
    lines.append(indent + '# ' + '=' * 60)
    lines.append(indent + '_timer_prev_' + s + ' = {}')
    lines.append(indent + '')
    lines.append(indent + 'async def _timer_auto_off_loop_' + s + '():')
    lines.append(indent + '    import gpio_control')
    lines.append(indent + '    gm = gpio_control.gm')
    lines.append(indent + '    while True:')
    lines.append(indent + '        try:')
    lines.append(indent + '            for _rid, _rule in mesh.automation_rules.items():')
    lines.append(indent + '                _rname = _rule.get("name", "")')
    lines.append(indent + '                if _rname not in _timer_config_' + s + ':')
    lines.append(indent + '                    continue')
    lines.append(indent + '                _dev, _secs = _timer_config_' + s + '[_rname]')
    lines.append(indent + '                if _rule.get("action_device", "") != _dev:')
    lines.append(indent + '                    continue')
    lines.append(indent + '                _cur = bool(_rule.get("last_state", False))')
    lines.append(indent + '                _prev = _timer_prev_' + s + '.get(_rid, False)')
    lines.append(indent + '                if _cur and not _prev:')
    lines.append(indent + '                    try:')
    lines.append(indent + '                        gm.gpio_on_timer(_dev, _secs)')
    lines.append(indent + '                        print("[AUTO] 타이머: {} {}초 후 OFF"')
    lines.append(indent + '                              .format(_dev, _secs))')
    lines.append(indent + '                    except Exception as _ex:')
    lines.append(indent + '                        print("[AUTO] 타이머 오류: {}".format(_ex))')
    lines.append(indent + '                _timer_prev_' + s + '[_rid] = _cur')
    lines.append(indent + '        except Exception as _ex:')
    lines.append(indent + '            print("[AUTO] 타이머 루프 오류: {}".format(_ex))')
    lines.append(indent + '        await asyncio.sleep(1)')
    lines.append(indent + '')
    lines.append(indent + '_loop = asyncio.get_event_loop()')
    lines.append(indent + '_loop.create_task(_timer_auto_off_loop_' + s + '())')
    lines.append(indent + 'print("[AUTO] 타이머 자동 OFF 루프 시작 / Timer auto-OFF loop started")')
    return lines


def _has_timer_rules(rules):
    """timer_sec 가 설정된 규칙이 하나라도 있는지."""
    for r in rules:
        if r.get('timer_sec'):
            return True
    return False


def generate_setup_function(rules):
    """전체 automation.py 파일 내용 생성 (새 파일용).
    Generate the full automation.py file content (for new files)."""
    ts = _timestamp()
    lines = []
    lines.append('"""')
    lines.append('automation.py - 자동화 규칙 설정 / Automation rule configuration')
    lines.append('==============================================================')
    lines.append('이 파일은 automation_generator.py 로 생성되었습니다.')
    lines.append('This file was generated by automation_generator.py.')
    lines.append('생성일 / Generated: ' + ts)
    lines.append('규칙 수 / Rule count: {}'.format(len(rules)))
    lines.append('게이트웨이 노드에서만 자동 로드됩니다 (setup() 자동 호출).')
    lines.append('Auto-loaded only on the gateway node (setup() is called automatically).')
    lines.append('"""')
    lines.append('')
    lines.append('import sys')
    lines.append('')
    lines.append('')
    lines.append('def setup():')
    lines.append('    """자동화 규칙 설정 / Setup automation rules."""')
    lines.append('    print("[AUTO] setup() 시작")')
    lines.append('')
    lines.append('    try:')
    lines.append('        import espnow_mesh_pro as mesh')
    lines.append('        import uasyncio as asyncio')
    lines.append('        from mesh_config import cfg')
    lines.append('        print("[AUTO] 로드됨 (role={})".format(cfg.NODE_ROLE))')
    lines.append('    except Exception as ex:')
    lines.append('        print("[AUTO] 로드 실패: {}".format(ex))')
    lines.append('        sys.print_exception(ex)')
    lines.append('        return')
    lines.append('')
    # 삽입 마커 / insertion marker (이후 append 시 이 위치에 삽입됨)
    lines.append('    ' + MARKER)
    lines.append('    # 새 규칙이 이 아래에 자동 삽입됩니다. / New rules auto-inserted below.')
    lines.append('')
    # 규칙 블록들 / rule blocks
    for r in rules:
        lines.extend(generate_rule_block(r, indent='    '))
        lines.append('')
    # 타이머 루프 / timer loop
    if _has_timer_rules(rules):
        uid = _gen_uid()
        lines.append(generate_timer_config(rules, uid, indent='    '))
        lines.append('')
        lines.extend(generate_timer_loop(uid, indent='    '))
        lines.append('')
    # 요약 / summary
    lines.append('    # === 요약 / Summary ===')
    lines.append('    print("[AUTO] 자동화 규칙: {}개".format(')
    lines.append('        mesh.automation_rules.count()))')
    lines.append('    if mesh.automation_rules.count() > 0:')
    lines.append('        print("[AUTO] 규칙 목록 / Rule list:")')
    lines.append('        for rid, rule in mesh.automation_rules.items():')
    lines.append('            print("  [{}] {} (우선순위 {})".format(')
    lines.append('                rid, rule["name"], rule.get("priority", 0)))')
    return '\n'.join(lines) + '\n'


def build_insertion(rules):
    """기존 setup() 에 삽입할 코드 블록(들여쓰기 4칸) 생성.
    Build the indented code block to insert into an existing setup()."""
    lines = []
    lines.append('    # ' + '=' * 60)
    lines.append('    # 자동화 규칙 (automation_generator.py 로 추가됨 / added by generator)')
    lines.append('    # 추가일 / Added: ' + _timestamp())
    lines.append('    # ' + '=' * 60)
    for r in rules:
        lines.extend(generate_rule_block(r, indent='    '))
        lines.append('')
    if _has_timer_rules(rules):
        uid = _gen_uid()
        lines.append(generate_timer_config(rules, uid, indent='    '))
        lines.append('')
        lines.extend(generate_timer_loop(uid, indent='    '))
        lines.append('')
    # 끝의 빈 줄 제거 (삽입 시 여분의 공백 줄 방지)
    # Strip trailing blank lines for clean insertion.
    while lines and lines[-1].strip() == '':
        lines.pop()
    return '\n'.join(lines)


def build_append_helper(rules):
    """setup() 을 찾지 못했을 때 파일 끝에 추가할 보조 함수.
    Fallback helper function appended when no setup() is found."""
    lines = []
    lines.append('')
    lines.append('# ' + '=' * 60)
    lines.append('# 자동화 규칙 (automation_generator.py 로 생성됨 / generated)')
    lines.append('# setup() 함수에서 setup_generated_rules() 를 호출하세요.')
    lines.append('# Call setup_generated_rules() from your setup() function.')
    lines.append('# ' + '=' * 60)
    lines.append('def setup_generated_rules():')
    lines.append('    """automation_generator.py 로 생성된 규칙들 / Generated rules."""')
    lines.append('    try:')
    lines.append('        import espnow_mesh_pro as mesh')
    lines.append('        import uasyncio as asyncio')
    lines.append('    except ImportError as ex:')
    lines.append('        print("import 실패 / import failed: {}".format(ex))')
    lines.append('        return')
    for r in rules:
        lines.extend(generate_rule_block(r, indent='    '))
        lines.append('')
    if _has_timer_rules(rules):
        uid = _gen_uid()
        lines.append(generate_timer_config(rules, uid, indent='    '))
        lines.append('')
        lines.extend(generate_timer_loop(uid, indent='    '))
        lines.append('')
    lines.append('    print("[AUTO] {} 개 규칙 등록됨 (setup_generated_rules)"')
    lines.append('          .format(mesh.automation_rules.count()))')
    return '\n'.join(lines)


# ============================================================
# 파일 입출력 / File I/O
# ============================================================

def file_exists(path):
    """os 없이 파일 존재 확인 (MicroPython 호환).
    Check if a file exists without using os.path (MicroPython-safe)."""
    try:
        with open(path, 'r'):
            pass
        return True
    except OSError:
        return False
    except Exception:
        return False


def _backup(target):
    """기존 파일을 .bak 으로 백업.
    Back up the existing file to <path>.bak."""
    try:
        with open(target, 'r') as f:
            data = f.read()
        bak = target + '.bak'
        with open(bak, 'w') as f:
            f.write(data)
        print('  i 백업 생성 / Backup: {}'.format(bak))
    except Exception:
        pass


def _find_marker_line(lines):
    """삽입 마커가 있는 줄 인덱스 반환. 없으면 -1."""
    for i, ln in enumerate(lines):
        if MARKER in ln:
            return i
    return -1


def _find_setup_def(lines):
    """def setup(): 줄 인덱스 반환. 없으면 -1."""
    for i, ln in enumerate(lines):
        s = ln.lstrip()
        if s.startswith('def setup(') or s == 'def setup():':
            return i
    return -1


def _line_indent(ln):
    """줄의 들여쓰기 공백 수 반환. 빈 줄은 None.
    Return the indent width of a line, or None for blank lines."""
    if ln.strip() == '':
        return None
    return len(ln) - len(ln.lstrip())


def _find_post_import_point(lines, setup_idx):
    """import try/except 블록 직후의 삽입 지점(줄 인덱스) 반환.
    실패 시 None 반환. (마커가 없을 때 가장 권장되는 위치)
    Find the insertion point right after the import try/except block.
    Returns None on failure (preferred fallback when no marker)."""
    n = len(lines)
    # 본문 들여쓰기 추정 / infer body indent from first non-blank line
    body_indent = None
    for i in range(setup_idx + 1, n):
        ind = _line_indent(lines[i])
        if ind is not None:
            body_indent = ind
            break
    if body_indent is None:
        return None
    # try: 찾기 / find 'try:' at body indent
    try_idx = None
    for i in range(setup_idx + 1, n):
        ind = _line_indent(lines[i])
        if ind is None:
            continue
        if ind < body_indent:
            break  # setup 본문 종료 / left setup body
        if ind == body_indent and lines[i].strip() == 'try:':
            try_idx = i
            break
    if try_idx is None:
        return None
    # 매칭 except 찾기 / find matching 'except' at body indent
    except_idx = None
    for i in range(try_idx + 1, n):
        ind = _line_indent(lines[i])
        if ind is None:
            continue
        if ind < body_indent:
            break
        if ind == body_indent and lines[i].lstrip().startswith('except'):
            except_idx = i
            break
    if except_idx is None:
        return None
    # except 본문 끝 찾기 / find end of except body (indent > body_indent)
    end_idx = except_idx
    for i in range(except_idx + 1, n):
        ind = _line_indent(lines[i])
        if ind is None:
            continue
        if ind > body_indent:
            end_idx = i
        else:
            break
    return end_idx + 1


def _find_summary_comment(lines):
    """요약 주석 블록의 시작 줄 반환. 없으면 -1.
    Find the start of the summary comment block; returns -1 if none.

    '요약' 또는 'summary' 키워드가 있는 주석 줄을 찾고,
    그 위쪽의 배너(# ====...) 줄과 빈 줄만 역행하여 시작점을 정합니다.
    내용 주석(# foo)은 역행하지 않습니다."""
    n = len(lines)
    for i in range(n):
        s = lines[i].strip()
        if s.startswith('#') and ('요약' in s or 'summary' in s.lower()):
            j = i
            while j > 0:
                ps = lines[j - 1].strip()
                if ps == '':
                    j -= 1
                elif ps.startswith('#') and \
                        set(ps.lstrip('#').strip()) <= set('='):
                    # 배너 줄: # 와 = 만 있는 줄 / banner: only # and =
                    j -= 1
                else:
                    break
            return j
    return -1


def _find_setup_body_end(lines, setup_idx):
    """setup() 본문의 끝(다음 줄 인덱스) 반환.
    Find the line just after the end of the setup() body."""
    # 본문 들여쓰기 추정 / infer body indent from first non-blank line
    body_indent = None
    for i in range(setup_idx + 1, len(lines)):
        ind = _line_indent(lines[i])
        if ind is not None:
            body_indent = ind
            break
    if body_indent is None:
        return setup_idx + 1
    last_body_idx = setup_idx
    for i in range(setup_idx + 1, len(lines)):
        ind = _line_indent(lines[i])
        if ind is None:
            continue
        if ind >= body_indent:
            last_body_idx = i
        else:
            break  # setup 본문에서 나감 / dedented out of setup
    return last_body_idx + 1


def insert_into_setup(existing, insertion):
    """기존 파일 내용에 삽입 블록을 넣어 반환. 실패 시 None 반환.
    Insert the insertion block into existing setup(); returns None on failure.

    삽입 우선순위 / Insertion priority:
      1) AUTOMATION_GENERATOR_INSERT_POINT 마커 다음 (권장)
      2) import try/except 블록 직후 (마커 없을 때 권장)
      3) 요약(summary) 주석 블록 앞
      4) setup() 본문 끝
    """
    lines = existing.split('\n')

    # 1) 마커가 있으면 그 다음 줄에 삽입 / insert after marker if present
    marker_idx = _find_marker_line(lines)
    if marker_idx >= 0:
        new_lines = (lines[:marker_idx + 1] +
                     [insertion] + lines[marker_idx + 1:])
        return '\n'.join(new_lines)

    # 2) setup() 정의 찾기 / locate def setup()
    setup_idx = _find_setup_def(lines)
    if setup_idx < 0:
        return None

    # 3) import try/except 직후 삽입 (권장) / after import block (preferred)
    pt = _find_post_import_point(lines, setup_idx)
    if pt is not None:
        new_lines = (lines[:pt] + [insertion, ''] + lines[pt:])
        return '\n'.join(new_lines)

    # 4) 요약 주석 블록 앞에 삽입 / before summary comment block
    summary_idx = _find_summary_comment(lines)
    if summary_idx > setup_idx:
        new_lines = (lines[:summary_idx] +
                     [insertion, ''] + lines[summary_idx:])
        return '\n'.join(new_lines)

    # 5) setup() 본문 끝에 삽입 / insert at end of setup() body
    end_idx = _find_setup_body_end(lines, setup_idx)
    new_lines = lines[:end_idx] + [insertion] + lines[end_idx:]
    return '\n'.join(new_lines)


def write_to_file(target, full_code, rules):
    """파일에 작성. 기존 파일이 있으면 create/append 선택.
    Write to file; ask create vs append when the file exists."""
    exists = file_exists(target)

    if exists:
        print('')
        print('  기존 파일이 있습니다 / Existing file: {}'.format(target))
        mode = ask_choice('모드 선택 / Select mode', [
            ('append', '기존 setup() 에 규칙 추가 (권장) / Append to existing setup() (recommended)'),
            ('create', '새로 만들기 (덮어쓰기) / Create new (overwrite)'),
        ], default='append')
    else:
        mode = 'create'

    # create 모드: 전체 파일 덮어쓰기 / overwrite with full template
    if mode == 'create':
        if exists:
            _backup(target)
        try:
            with open(target, 'w') as f:
                f.write(full_code)
            print('  [OK] 생성됨 / Created: {}'.format(target))
        except Exception as ex:
            print('  ! 쓰기 실패 / Write failed: {}'.format(ex))
        return

    # append 모드: 기존 파일 읽기 / read existing file
    try:
        with open(target, 'r') as f:
            existing = f.read()
    except Exception as ex:
        print('  ! 읽기 실패 / Read failed: {}'.format(ex))
        return

    insertion = build_insertion(rules)
    new_content = insert_into_setup(existing, insertion)

    if new_content is None:
        # setup() 을 찾지 못함 → 파일 끝에 보조 함수 추가 / fallback
        print('  ! setup() 함수를 찾을 수 없습니다. 파일 끝에 보조 함수를 추가합니다.')
        print('    ! setup() not found; appending a helper function at end.')
        helper = build_append_helper(rules)
        _backup(target)
        try:
            with open(target, 'a') as f:
                f.write('\n' + helper + '\n')
            print('  [OK] 추가됨 / Appended: {}'.format(target))
            print('  i setup() 안에서 setup_generated_rules() 를 호출하세요.')
            print('    Call setup_generated_rules() inside your setup().')
        except Exception as ex:
            print('  ! 쓰기 실패 / Write failed: {}'.format(ex))
        return

    _backup(target)
    try:
        with open(target, 'w') as f:
            f.write(new_content)
        print('  [OK] 업데이트됨 / Updated: {}'.format(target))
    except Exception as ex:
        print('  ! 쓰기 실패 / Write failed: {}'.format(ex))


# ============================================================
# 규칙 수집 / Rule collection (interactive)
# ============================================================

def collect_rule():
    """사용자와 대화하며 규칙 하나를 수집.
    Interactively collect a single rule from the user."""
    print('')
    print('=' * 60)
    print('  새 자동화 규칙 / New Automation Rule')
    print('=' * 60)

    name = ask_str('규칙 이름 / Rule name')
    rule_type = ask_choice('규칙 타입 / Rule type', [
        ('sensor', '센서 규칙 / Sensor rule (온도/습도/조도 등)'),
        ('time', '시간 규칙 / Time rule (요일/시간대)'),
        ('sun', '일출/일몰 규칙 / Sunrise-Sunset rule'),
    ])
    rule = {'name': name, 'rule_type': rule_type}

    # --- 타입별 필드 / type-specific fields ---
    if rule_type == 'sensor':
        sensor = ask_str('센서 이름 / Sensor name (예: 거실온도)')
        operator = ask_operator('비교 연산자 / Comparison operator')
        value = ask_float('임계값 / Threshold value')
        hysteresis = ask_float('히스테리시스 / Hysteresis band',
                               default=0.0, min_val=0)
        rule['sensor'] = sensor
        rule['operator'] = operator
        rule['value'] = value
        rule['hysteresis'] = hysteresis
    elif rule_type == 'time':
        days = ask_days('요일 / Days (월=0..일=6)')
        start = ask_time('시작 시간 / Start time')
        end = ask_time('종료 시간 / End time')
        rule['schedule'] = {'days': days, 'start': start, 'end': end}
    elif rule_type == 'sun':
        event = ask_choice('일출/일몰 이벤트 / Sun event', [
            ('sunset', '일몰 / Sunset'),
            ('sunrise', '일출 / Sunrise'),
        ])
        offset = ask_int('오프셋(분) / Offset in minutes '
                         '(음수=이전/before, 양수=이후/after)',
                         default=0)
        days = ask_days('요일 / Days', default=[0, 1, 2, 3, 4, 5, 6])
        rule['sun_event'] = {
            'event': event, 'offset_min': offset, 'days': days}

    # --- 액션 / action ---
    action_device = ask_str('액션 장치 / Action device (예: 거실팬)')
    action_value = ask_action_value(action_device)
    rule['action_device'] = action_device
    rule['action_value'] = action_value

    # --- 타이머 (센서 규칙만) / timer (sensor rules only) ---
    if rule_type == 'sensor':
        timer = ask_int('타이머(초) / Timer in seconds '
                        '(트리거 후 N초 뒤 자동 OFF, 0=사용안함/none)',
                        default=0, min_val=0)
        if timer > 0:
            rule['timer_sec'] = timer

    # --- 쿨다운 / cooldown ---
    cooldown = ask_int('쿨다운(초) / Cooldown in seconds',
                       default=60, min_val=0)
    rule['cooldown_sec'] = cooldown

    # --- 우선순위 / priority ---
    priority = ask_int('우선순위 / Priority (낮을수록 높음 / lower=higher)',
                       default=0)
    rule['priority'] = priority

    # --- action_off (해제 시 자동 OFF) / auto-OFF when released ---
    if ask_bool('해제 시 자동 OFF(action_off) 추가? / '
                'Add auto-OFF when released?', default=False):
        off_device = ask_str('OFF 장치 / OFF device '
                             '(비우면 액션 장치와 동일 / blank=same as action device)',
                             default=action_device, allow_empty=True)
        if not off_device:
            off_device = action_device
        off_value_raw = ask_str('OFF 값 / OFF value (기본/default: 0)',
                                default='0')
        off_value = validate_action_value(off_value_raw) or off_value_raw
        rule['action_off'] = {'device': off_device, 'value': off_value}

    # --- 추가 조건 / additional conditions ---
    if ask_bool('추가 조건(conditions) 추가? / '
                'Add additional conditions?', default=False):
        conds = []
        while True:
            print('')
            print('  조건 #{} / Condition #{}'.format(len(conds) + 1, len(conds) + 1))
            ctype = ask_choice('조건 대상 / Condition target', [
                ('sensor', '센서 조건 / Sensor condition'),
                ('device', '장치 조건 / Device condition'),
            ])
            cname = ask_str('이름 / Name (예: 거실조명 또는/or 재실여부)')
            coper = ask_operator('연산자 / Operator')
            cval = ask_float('값 / Value')
            cond = {ctype: cname, 'operator': coper, 'value': cval}
            conds.append(cond)
            if not ask_bool('조건 더 추가? / Add another condition?',
                            default=False):
                break
        rule['conditions'] = conds

    return rule


# ============================================================
# 메인 / Main
# ============================================================

def print_banner():
    """시작 배너 출력."""
    print('')
    print('=' * 70)
    print('  ESP-NOW 메쉬 자동화 규칙 생성기 / Automation Rule Generator')
    print('  ESP-NOW mesh network automation rule generator')
    print('=' * 70)
    print('  이 도구는 대화형으로 질문하여 mesh.automation_rules.add_rule()')
    print('  호출 코드를 생성합니다.')
    print('  This tool interactively generates add_rule() call code.')
    print('  - 표준 라이브러리만 사용 / standard library only')
    print('  - CPython / MicroPython 호환 / compatible')
    print('-' * 70)


def print_rule_summary(rules):
    """수집된 규칙 요약 출력."""
    print('')
    print('-' * 70)
    print('  수집된 규칙 / Collected rules: {} 개'.format(len(rules)))
    print('-' * 70)
    for i, r in enumerate(rules, 1):
        rt = r.get('rule_type', 'sensor')
        if rt == 'sensor':
            detail = '{} {} {}'.format(r['sensor'], r['operator'], r['value'])
        elif rt == 'time':
            detail = 'days={} {}-{}'.format(
                _days_to_str(r['schedule']['days']),
                _time_to_str(r['schedule']['start']),
                _time_to_str(r['schedule']['end']))
        elif rt == 'sun':
            detail = '{} offset={}'.format(
                r['sun_event']['event'], r['sun_event']['offset_min'])
        else:
            detail = '?'
        timer_note = ''
        if r.get('timer_sec'):
            timer_note = ' [timer={}s]'.format(r['timer_sec'])
        print('  {}. {} [{}] -> {}={}{}'
              .format(i, r['name'], detail,
                      r['action_device'], r['action_value'], timer_note))
    print('-' * 70)


def main():
    """메인 진입점 / Main entry point."""
    print_banner()
    rules = []
    try:
        while True:
            rule = collect_rule()
            rules.append(rule)
            print('')
            print('  [OK] 규칙 추가됨 / Rule added: "{}"'.format(rule['name']))
            if not ask_bool('다른 규칙을 추가하시겠습니까? / '
                            'Add another rule?', default=True):
                break
    except (KeyboardInterrupt, EOFError):
        # Ctrl+C 또는 EOF(입력 종료) 시 수집 루프를 빠져나감
        # Exit the collection loop on Ctrl+C or EOF.
        print('')
        print('  ! 수집 중단 / Collection interrupted.')
        if not rules:
            print('  생성된 규칙이 없습니다. / No rules collected.')
            return

    if not rules:
        print('  생성된 규칙이 없습니다. / No rules collected.')
        return

    print_rule_summary(rules)

    # 코드 생성 / generate code
    code = generate_setup_function(rules)
    print('')
    print('=' * 70)
    print('  생성된 코드 / Generated Code')
    print('=' * 70)
    print(code)
    print('=' * 70)

    # 파일에 쓸지 질문 / ask whether to write to file
    try:
        if ask_bool('custom/automation.py 에 작성하시겠습니까? / '
                    'Write to custom/automation.py?', default=True):
            target = ask_str('파일 경로 / File path',
                             default='custom/automation.py')
            write_to_file(target, code, rules)
    except (KeyboardInterrupt, EOFError):
        print('')
        print('  ! 파일 쓰기 단계 중단 / Write step interrupted.')

    print('')
    print('  완료 / Done. {} 개 규칙 생성됨 / {} rule(s) generated.'
          .format(len(rules), len(rules)))
    print('  게이트웨이 노드에서 자동으로 로드됩니다 (setup() 자동 호출).')
    print('  Rules auto-load on the gateway node (setup() is auto-called).')
    print('')


if __name__ == '__main__':
    main()
