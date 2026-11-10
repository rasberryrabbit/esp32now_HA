#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
automation_editor.py - ESP-NOW 메쉬 네트워크 자동화 규칙 시각 편집기 (GUI)
=====================================================================

ESP-NOW mesh network automation rule visual editor (tkinter GUI).

이 도구는 게이트웨이의 HTTP API 와 통신하여 자동화 규칙을 시각적으로
편집하고, custom/automation.py 용 Python 코드를 자동 생성합니다.

기능 / Features:
  - 게이트웨이 HTTP API 연결 (IP 입력)
  - /api/sensors, /api/devices, /api/automation?action=list 조회
  - 규칙 목록 표시 (Treeview) + 추가/편집/삭제
  - 규칙 편집 폼:
      * 센서/장치 드롭다운 (API 로부터 자동 채움)
      * 연산자 드롭다운 (>, <, >=, <=, ==, !=)
      * NeoPixel 색상 선택기 (tkinter colorchooser)
      * 시간 규칙 편집 (요일 체크박스, 시작/종료 시간)
      * 일출/일몰 규칙 편집 (sunrise/sunset + offset + days)
      * 추가 조건(conditions) 추가/삭제
      * action_off (해제 시 자동 OFF) 체크박스 + device/value
  - 자동화 실행 로그 (/api/automation?action=log) 보기 + 자동 새로고침
  - Python 코드 자동 생성 (custom/automation.py 용)
      * 복사 / 파일 저장 / 게이트웨이로 전송
  - 마지막 게이트웨이 IP 저장/복원

표준 라이브러리만 사용 (tkinter, urllib, json).
Standard library only (tkinter, urllib, json).

사용법 / Usage:
    python automation_editor.py

참고 / Note:
  - f-string 대신 .format() 사용 (구버전 Python 호환성)
  - Linux 에서는 python3-tk 패키지 필요할 수 있음:
        sudo apt-get install python3-tk
"""

# ============================================================
# 표준 라이브러리 임포트 / Standard library imports
# ============================================================
import os
import sys
import json
import time
import queue
import threading
import urllib.request
import urllib.parse
import urllib.error
import traceback

# tkinter 임포트 / import tkinter (tk 는 Python 표준 라이브러리)
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, colorchooser


# ============================================================
# 전역 상수 / Global constants
# ============================================================
APP_TITLE = "Automation Rule Editor - ESP-NOW Mesh"
APP_VERSION = "1.0"

# 설정 파일 경로 / settings file path (사용자 홈 디렉토리)
_SETTINGS_FILE = os.path.join(os.path.expanduser("~"),
                              ".automation_editor_settings.json")

# HTTP 요청 타임아웃 / HTTP request timeout (초)
HTTP_TIMEOUT = 6

# 로그 자동 새로고침 주기 / log auto-refresh interval (ms)
LOG_REFRESH_MS = 5000

# 지원 연산자 / supported comparison operators
OPERATORS = ['>', '<', '>=', '<=', '==', '!=']

# 규칙 타입 / rule types
RULE_TYPES = ['sensor', 'time', 'sun']

# 요일 (Python tm_wday 기준: 0=월/Mon .. 6=일/Sun)
DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
DAY_LABELS_KR = ['월', '화', '수', '목', '금', '토', '일']

# 일출/일몰 이벤트 / sun events
SUN_EVENTS = ['sunrise', 'sunset']


# ============================================================
# 설정 파일 입출력 / Settings persistence
# ============================================================
def load_settings():
    """저장된 설정 불러오기. 실패 시 빈 dict.
    Load saved settings; return empty dict on failure."""
    try:
        with open(_SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(settings):
    """설정 저장. 실패해도 무시.
    Save settings; silently ignore failure."""
    try:
        with open(_SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ============================================================
# HTTP 헬퍼 / HTTP helpers
# ============================================================
def http_get_json(url, timeout=HTTP_TIMEOUT):
    """URL GET 요청 후 JSON dict 반환. 오류 시 예외 발생.
    GET URL, return parsed JSON dict. Raises on error."""
    req = urllib.request.Request(
        url,
        headers={
            'Accept': 'application/json',
            'User-Agent': 'automation_editor/{}'.format(APP_VERSION),
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8', 'replace')
    return json.loads(raw)


def http_get_text(url, timeout=HTTP_TIMEOUT):
    """URL GET 요청 후 텍스트 반환.
    GET URL, return response body as text."""
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8', 'replace')
    return raw


# ============================================================
# 시간 변환 도우미 / Time helpers
# ============================================================
def parse_time_str(s):
    """'HH:MM' 또는 'HHMM' -> 정수 HHMM. 실패 시 None.
    Parse 'HH:MM' or 'HHMM' to integer HHMM; None on failure."""
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    if ':' in s:
        parts = s.split(':')
        if len(parts) != 2:
            return None
        try:
            hh = int(parts[0])
            mm = int(parts[1])
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                return hh * 100 + mm
        except ValueError:
            return None
        return None
    try:
        n = int(s)
        hh = n // 100
        mm = n % 100
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return hh * 100 + mm
    except ValueError:
        return None
    return None


def time_to_str(t):
    """정수 HHMM -> 'HH:MM' 문자열."""
    if t is None:
        return ''
    try:
        n = int(t)
    except (TypeError, ValueError):
        return ''
    hh = n // 100
    mm = n % 100
    return '{:02d}:{:02d}'.format(hh, mm)


# ============================================================
# Python 리터럴 포매터 / Python literal formatter
# ============================================================
def fmt_str(s):
    """문자열을 큰따옴표 Python 리터럴로 변환 (한글 보존).
    Format a string as a double-quoted Python literal."""
    if not isinstance(s, str):
        s = str(s)
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


def fmt_value(v, indent=''):
    """Python 값을 리터럴로 포맷. 작은 dict/list 는 한 줄로.
    Format a Python value as a literal."""
    if isinstance(v, bool):
        return 'True' if v else 'False'
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return fmt_str(v)
    if isinstance(v, (list, tuple)):
        v = list(v)
        if not v:
            return '[]'
        simple = all(isinstance(x, (int, float, str, bool)) for x in v)
        if simple and len(v) <= 12:
            return '[' + ', '.join(fmt_value(x, indent) for x in v) + ']'
        inner = indent + '    '
        return ('[\n' +
                ',\n'.join(inner + fmt_value(x, inner) for x in v) +
                ',\n' + indent + ']')
    if isinstance(v, dict):
        if not v:
            return '{}'
        simple = all(isinstance(val, (int, float, str, bool))
                     for val in v.values())
        if simple and len(v) <= 5:
            inner = ', '.join(fmt_str(k) + ': ' + fmt_value(val, indent)
                              for k, val in v.items())
            return '{' + inner + '}'
        inner = indent + '    '
        return ('{\n' +
                ',\n'.join(inner + fmt_str(k) + ': ' + fmt_value(val, inner)
                           for k, val in v.items()) +
                ',\n' + indent + '}')
    try:
        return repr(v)
    except Exception:
        return 'None'


# ============================================================
# 코드 생성 / Code generation
# ============================================================
def gen_rule_block(rule, indent='    '):
    """단일 add_rule() 호출 코드 생성.
    Generate Python code for a single add_rule() call."""
    rt = rule.get('rule_type', 'sensor')
    type_label = {
        'sensor': 'Sensor rule',
        'time': 'Time rule',
        'sun': 'Sunrise/Sunset rule',
    }.get(rt, rt)

    lines = []
    lines.append(indent + '# ' + '-' * 60)
    lines.append(indent + '# Rule: {}  ({})'.format(
        rule.get('name', ''), type_label))
    lines.append(indent + '# ' + '-' * 60)
    lines.append(indent + 'mesh.automation_rules.add_rule(')
    inner = indent + '    '

    # name
    lines.append(inner + 'name=' + fmt_value(rule.get('name', ''), inner) + ',')

    # rule_type (sensor 가 기본값이므로 sensor 일 때는 생략)
    # Omit rule_type for sensor (default).
    if rt != 'sensor':
        lines.append(inner + 'rule_type=' + fmt_value(rt, inner) + ',')

    # 타입별 필드 / type-specific fields
    if rt == 'sensor':
        lines.append(inner + 'sensor=' +
                     fmt_value(rule.get('sensor', ''), inner) + ',')
        lines.append(inner + 'operator=' +
                     fmt_value(rule.get('operator', '>'), inner) + ',')
        lines.append(inner + 'value=' +
                     fmt_value(rule.get('value', 0), inner) + ',')
    elif rt == 'time':
        sched = rule.get('schedule')
        if not sched:
            sched = {'days': [0, 1, 2, 3, 4], 'start': 600, 'end': 800}
        lines.append(inner + 'schedule=' + fmt_value(sched, inner) + ',')
    elif rt == 'sun':
        se = rule.get('sun_event')
        if not se:
            se = {'event': 'sunrise', 'offset_min': 0, 'days': [0, 1, 2, 3, 4, 5, 6]}
        lines.append(inner + 'sun_event=' + fmt_value(se, inner) + ',')

    # 공통 액션 필드 / common action fields
    lines.append(inner + 'action_device=' +
                 fmt_value(rule.get('action_device', ''), inner) + ',')
    lines.append(inner + 'action_value=' +
                 fmt_value(rule.get('action_value', ''), inner) + ',')

    # 센서 전용: 히스테리시스 / sensor-only: hysteresis
    if rt == 'sensor':
        lines.append(inner + 'hysteresis=' +
                     fmt_value(rule.get('hysteresis', 0), inner) +
                     ',  # hysteresis band')

    # 쿨다운 / cooldown
    lines.append(inner + 'cooldown_sec=' +
                 fmt_value(rule.get('cooldown_sec', 60), inner) + ',')

    # 우선순위 / priority
    lines.append(inner + 'priority=' +
                 fmt_value(rule.get('priority', 0), inner) +
                 ',  # lower = higher priority')

    # 추가 조건 / additional conditions
    conds = rule.get('conditions')
    if conds:
        lines.append(inner + 'conditions=' + fmt_value(conds, inner) + ',')

    # 해제 시 자동 OFF / action_off
    aoff = rule.get('action_off')
    if aoff:
        lines.append(inner + 'action_off=' + fmt_value(aoff, inner) +
                     ',  # auto-OFF when released')

    lines.append(indent + ')')
    return '\n'.join(lines)


def gen_full_automation_py(rules):
    """전체 automation.py 파일 내용 생성.
    Generate the full automation.py file content."""
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    lines = []
    lines.append('"""')
    lines.append('automation.py - generated by automation_editor.py')
    lines.append('==================================================')
    lines.append('Generated: {}'.format(ts))
    lines.append('Rule count: {}'.format(len(rules)))
    lines.append('Auto-loaded only on the gateway node (setup() is called).')
    lines.append('"""')
    lines.append('')
    lines.append('import sys')
    lines.append('')
    lines.append('')
    lines.append('def setup():')
    lines.append('    """Setup automation rules."""')
    lines.append('    print("[AUTO] setup() start")')
    lines.append('')
    lines.append('    try:')
    lines.append('        import espnow_mesh_pro as mesh')
    lines.append('        import uasyncio as asyncio')
    lines.append('        from mesh_config import cfg')
    lines.append('        print("[AUTO] loaded (role={})".format(cfg.NODE_ROLE))')
    lines.append('    except Exception as ex:')
    lines.append('        print("[AUTO] load failed: {}".format(ex))')
    lines.append('        sys.print_exception(ex)')
    lines.append('        return')
    lines.append('')
    if not rules:
        lines.append('    # (no rules defined) / 규칙 없음')
        lines.append('    pass')
    else:
        for r in rules:
            lines.append(gen_rule_block(r, indent='    '))
            lines.append('')
    # 요약 / summary
    lines.append('    # === Summary ===')
    lines.append('    print("[AUTO] automation rules: {}".format(')
    lines.append('        mesh.automation_rules.count()))')
    lines.append('    if mesh.automation_rules.count() > 0:')
    lines.append('        print("[AUTO] rule list:")')
    lines.append('        for rid, rule in mesh.automation_rules.items():')
    lines.append('            print("  [{}] {} (priority {})".format(')
    lines.append('                rid, rule["name"], rule.get("priority", 0)))')
    return '\n'.join(lines) + '\n'


# ============================================================
# 색상 도우미 / Color helpers
# ============================================================
def hex_to_action_value(hex_str):
    """'#RRGGBB' -> '0xRRGGBB' (대문자)."""
    if not hex_str:
        return ''
    h = hex_str.lstrip('#')
    if len(h) == 6:
        try:
            int(h, 16)
            return '0x' + h.upper()
        except ValueError:
            return ''
    return ''


def action_value_to_hex(av):
    """'0xRRGGBB' -> '#RRGGBB' (colorchooser 용). 실패 시 None."""
    if not av:
        return None
    s = av.strip()
    low = s.lower()
    if low.startswith('0x') and len(low) == 8:
        try:
            int(low, 16)
            return '#' + low[2:].upper()
        except ValueError:
            return None
    if s.startswith('#') and len(s) == 7:
        return s
    return None


# ============================================================
# 메인 애플리케이션 / Main application
# ============================================================
class AutomationEditorApp:
    """자동화 규칙 편집기 메인 애플리케이션.
    Main application class for the automation rule editor."""

    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry('1280x860')
        self.root.minsize(960, 640)

        # ---- 상태 / state ----
        self.gateway_ip = ''
        self.connected = False
        self.sensors = {}            # /api/sensors raw 결과
        self.devices = {}            # /api/devices raw 결과
        self.sensor_names = []       # 센서 이름 리스트
        self.device_entries = []     # [(name, type, node_id), ...]
        self.device_type_map = {}    # name -> type
        self.gateway_rules = {}      # rule_id -> rule (from gateway)
        self.local_rules = []        # 작업용 규칙 리스트 (dict 들)
        self.editing_index = None    # 편집 중인 local_rules 인덱스 (None=새 규칙)
        self.settings = load_settings()

        # 로그 자동 새로고침 타이머 ID
        self._log_after_id = None

        # 비동기 작업 결과 전달용 큐 / queue for thread-safe result delivery
        # (백그라운드 스레드에서 root.after() 직접 호출하면 메인 스레드가
        #  이벤트 루프에 있지 않을 때 RuntimeError 이 발생하므로 큐 사용)
        # Use a queue instead of root.after() from worker thread to avoid
        # 'main thread is not in main loop' RuntimeError.
        self._async_queue = queue.Queue()

        # tk 변수들 (UI 빌드 후 설정)
        # 변수 선언만 해둠 / declared here, created in _build_ui
        self.ip_var = None
        self.status_var = None
        self.count_var = None
        self.conn_color_var = None

        # UI 빌드
        self._build_ui()

        # 비동기 큐 폴링 시작 / start polling the async queue (every 50ms)
        self._poll_async_queue()

        # 마지막 IP 복원
        last_ip = self.settings.get('last_ip', '')
        if last_ip:
            self.ip_var.set(last_ip)

        # 창 닫기 시 설정 저장
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

        # 초기 코드 미리보기 (빈 규칙)
        self._regen_code()

    # ============================================================
    # UI 빌드 / Build UI
    # ============================================================
    def _build_ui(self):
        """전체 UI 빌드. Build the full user interface."""
        # 메인 그리드 / main grid
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=0)   # 연결 패널
        self.root.rowconfigure(1, weight=3)   # 가운데 (규칙 목록 | 편집기)
        self.root.rowconfigure(2, weight=2)   # 아래 (로그 | 코드)
        self.root.rowconfigure(3, weight=0)   # 상태 표시줄

        self._build_connection_panel()
        self._build_middle_paned()
        self._build_bottom_paned()
        self._build_status_bar()

    # ------------------------------------------------------------
    # 연결 패널 / Connection panel
    # ------------------------------------------------------------
    def _build_connection_panel(self):
        """상단 연결 패널. Top connection panel."""
        frame = ttk.Frame(self.root, padding=(8, 6))
        frame.grid(row=0, column=0, sticky='ew')
        frame.columnconfigure(2, weight=1)

        ttk.Label(frame, text='Gateway IP:').grid(row=0, column=0,
                                                 sticky='w', padx=(0, 4))
        self.ip_var = tk.StringVar()
        ip_entry = ttk.Entry(frame, textvariable=self.ip_var, width=22)
        ip_entry.grid(row=0, column=1, sticky='w')
        ip_entry.bind('<Return>', lambda e: self._on_connect())

        self.status_var = tk.StringVar(value='Not connected')
        self.conn_color_var = tk.StringVar(value='red')

        # 연결 상태 표시 (색 원 + 텍스트) / status dot + label
        dot_lbl = ttk.Label(frame, textvariable=self.conn_color_var,
                            foreground='red', font=('TkDefaultFont', 14))
        dot_lbl.grid(row=0, column=3, sticky='w', padx=(10, 2))
        ttk.Label(frame, textvariable=self.status_var).grid(
            row=0, column=4, sticky='w')

        # 버튼들 / buttons
        ttk.Button(frame, text='Connect', command=self._on_connect).grid(
            row=0, column=5, padx=(8, 0))
        ttk.Button(frame, text='Refresh',
                   command=self._on_refresh_all).grid(
            row=0, column=6, padx=(4, 0))

    # ------------------------------------------------------------
    # 가운데 패널: 규칙 목록 | 편집기 / Middle: rules | editor
    # ------------------------------------------------------------
    def _build_middle_paned(self):
        """가운데 PanedWindow (규칙 목록 + 편집기).
        Middle horizontal PanedWindow with rules list and editor."""
        paned = ttk.PanedWindow(self.root, orient='horizontal')
        paned.grid(row=1, column=0, sticky='nsew', padx=8, pady=4)

        # 왼쪽: 규칙 목록 / left: rules list
        left = ttk.LabelFrame(paned, text='Rules', padding=4)
        paned.add(left, weight=1)
        self._build_rules_list(left)

        # 오른쪽: 규칙 편집기 / right: rule editor
        right = ttk.LabelFrame(paned, text='Rule Editor', padding=4)
        paned.add(right, weight=2)
        self._build_rule_editor(right)

    def _build_rules_list(self, parent):
        """규칙 목록 Treeview + 버튼. Rules list Treeview + buttons."""
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        # Treeview + 스크롤바 / treeview + scrollbar
        tree_frame = ttk.Frame(parent)
        tree_frame.grid(row=0, column=0, sticky='nsew')
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        cols = ('name', 'type', 'trigger', 'action', 'priority')
        self.rules_tree = ttk.Treeview(tree_frame, columns=cols,
                                       show='headings', selectmode='browse')
        self.rules_tree.heading('name', text='Name')
        self.rules_tree.heading('type', text='Type')
        self.rules_tree.heading('trigger', text='Trigger')
        self.rules_tree.heading('action', text='Action')
        self.rules_tree.heading('priority', text='Pri')
        self.rules_tree.column('name', width=180, anchor='w')
        self.rules_tree.column('type', width=70, anchor='center')
        self.rules_tree.column('trigger', width=160, anchor='w')
        self.rules_tree.column('action', width=140, anchor='w')
        self.rules_tree.column('priority', width=40, anchor='center')
        self.rules_tree.grid(row=0, column=0, sticky='nsew')

        vsb = ttk.Scrollbar(tree_frame, orient='vertical',
                            command=self.rules_tree.yview)
        vsb.grid(row=0, column=1, sticky='ns')
        self.rules_tree.configure(yscrollcommand=vsb.set)

        self.rules_tree.bind('<<TreeviewSelect>>', self._on_rule_select)
        self.rules_tree.bind('<Double-1>', lambda e: self._on_edit_rule())

        # 버튼 행 / button row
        btn_frame = ttk.Frame(parent)
        btn_frame.grid(row=1, column=0, sticky='ew', pady=(6, 0))
        ttk.Button(btn_frame, text='Add', command=self._on_add_rule).pack(
            side='left', padx=(0, 4))
        ttk.Button(btn_frame, text='Edit', command=self._on_edit_rule).pack(
            side='left', padx=4)
        ttk.Button(btn_frame, text='Delete', command=self._on_delete_rule).pack(
            side='left', padx=4)
        ttk.Button(btn_frame, text='Duplicate',
                   command=self._on_duplicate_rule).pack(side='left', padx=4)
        ttk.Button(btn_frame, text='Up', command=self._on_move_up).pack(
            side='left', padx=4)
        ttk.Button(btn_frame, text='Down', command=self._on_move_down).pack(
            side='left', padx=4)

        # 안내 라벨 / hint label
        ttk.Label(parent,
                  text='Tip: Double-click a row to edit.',
                  foreground='gray').grid(row=2, column=0, sticky='w',
                                          pady=(4, 0))

    # ------------------------------------------------------------
    # 규칙 편집기 / Rule editor form
    # ------------------------------------------------------------
    def _build_rule_editor(self, parent):
        """오른쪽 규칙 편집 폼 (스크롤 가능).
        Scrollable rule editor form on the right."""
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        # Canvas + 내부 프레임 (스크롤) / canvas + inner frame for scrolling
        canvas = tk.Canvas(parent, highlightthickness=0, borderwidth=0)
        canvas.grid(row=0, column=0, sticky='nsew')
        vsb = ttk.Scrollbar(parent, orient='vertical', command=canvas.yview)
        vsb.grid(row=0, column=1, sticky='ns')
        canvas.configure(yscrollcommand=vsb.set)

        self.editor_canvas = canvas
        inner = ttk.Frame(canvas)
        self.editor_inner = inner
        inner_id = canvas.create_window((0, 0), window=inner, anchor='nw')

        # inner 폭을 canvas 에 맞춤 / make inner width match canvas
        def _on_canvas_configure(event):
            canvas.itemconfig(inner_id, width=event.width)
        canvas.bind('<Configure>', _on_canvas_configure)

        # scrollregion 갱신 / update scrollregion
        def _on_inner_configure(event):
            canvas.configure(scrollregion=canvas.bbox('all'))
        inner.bind('<Configure>', _on_inner_configure)

        # 마우스휠 스크롤 / mousewheel scrolling
        def _on_mousewheel(event):
            # Linux: event.num (4=up, 5=down), Windows/macOS: event.delta
            if hasattr(event, 'delta') and event.delta != 0:
                canvas.yview_scroll(int(-event.delta / 120), 'units')
            elif hasattr(event, 'num'):
                if event.num == 4:
                    canvas.yview_scroll(-1, 'units')
                elif event.num == 5:
                    canvas.yview_scroll(1, 'units')
        canvas.bind('<Enter>', lambda e: canvas.bind_all(
            '<MouseWheel>', _on_mousewheel) or canvas.bind_all(
            '<Button-4>', _on_mousewheel) or canvas.bind_all(
            '<Button-5>', _on_mousewheel))
        canvas.bind('<Leave>', lambda e: canvas.unbind_all('<MouseWheel>') or
                    canvas.unbind_all('<Button-4>') or
                    canvas.unbind_all('<Button-5>'))

        # 폼 필드들 빌드 / build form fields
        self._build_editor_fields(inner)

        # 버튼 행은 캔버스 밑에 고정 / action buttons fixed below canvas
        btn_frame = ttk.Frame(parent)
        btn_frame.grid(row=1, column=0, columnspan=2, sticky='ew',
                       pady=(6, 0))
        ttk.Button(btn_frame, text='Apply', command=self._on_apply_rule).pack(
            side='right', padx=(4, 0))
        ttk.Button(btn_frame, text='Cancel',
                   command=self._on_cancel_edit).pack(side='right', padx=4)
        ttk.Button(btn_frame, text='Reset',
                   command=self._on_reset_form).pack(side='right', padx=4)

    def _build_editor_fields(self, parent):
        """편집기 내부 폼 필드 빌드. Build editor form fields."""
        parent.columnconfigure(1, weight=1)

        row = 0

        # --- 기본 정보 / basics ---
        basics = ttk.LabelFrame(parent, text='Basics', padding=8)
        basics.grid(row=row, column=0, columnspan=2, sticky='ew', pady=(0, 6))
        basics.columnconfigure(1, weight=1)
        row += 1

        ttk.Label(basics, text='Name:').grid(row=0, column=0, sticky='w',
                                             padx=(0, 6), pady=2)
        self.f_name = tk.StringVar()
        ttk.Entry(basics, textvariable=self.f_name).grid(
            row=0, column=1, sticky='ew', pady=2)

        ttk.Label(basics, text='Type:').grid(row=1, column=0, sticky='w',
                                             padx=(0, 6), pady=2)
        self.f_type = tk.StringVar(value='sensor')
        type_cb = ttk.Combobox(basics, textvariable=self.f_type,
                               values=RULE_TYPES, state='readonly', width=12)
        type_cb.grid(row=1, column=1, sticky='w', pady=2)
        type_cb.bind('<<ComboboxSelected>>',
                     lambda e: self._on_type_changed())

        # --- 트리거 (sensor) / trigger: sensor ---
        self.sensor_frame = ttk.LabelFrame(parent, text='Sensor Trigger',
                                          padding=8)
        self.sensor_frame.grid(row=row, column=0, columnspan=2,
                               sticky='ew', pady=(0, 6))
        self.sensor_frame.columnconfigure(1, weight=1)
        row += 1

        ttk.Label(self.sensor_frame, text='Sensor:').grid(
            row=0, column=0, sticky='w', padx=(0, 6), pady=2)
        self.f_sensor = tk.StringVar()
        self.sensor_cb = ttk.Combobox(self.sensor_frame,
                                      textvariable=self.f_sensor,
                                      values=[], width=24)
        self.sensor_cb.grid(row=0, column=1, sticky='w', pady=2)

        ttk.Label(self.sensor_frame, text='Operator:').grid(
            row=1, column=0, sticky='w', padx=(0, 6), pady=2)
        self.f_operator = tk.StringVar(value='>')
        ttk.Combobox(self.sensor_frame, textvariable=self.f_operator,
                     values=OPERATORS, state='readonly', width=8).grid(
            row=1, column=1, sticky='w', pady=2)

        ttk.Label(self.sensor_frame, text='Value:').grid(
            row=2, column=0, sticky='w', padx=(0, 6), pady=2)
        self.f_value = tk.StringVar(value='25')
        ttk.Entry(self.sensor_frame, textvariable=self.f_value).grid(
            row=2, column=1, sticky='w', pady=2)

        ttk.Label(self.sensor_frame, text='Hysteresis:').grid(
            row=3, column=0, sticky='w', padx=(0, 6), pady=2)
        self.f_hysteresis = tk.StringVar(value='1.0')
        ttk.Entry(self.sensor_frame, textvariable=self.f_hysteresis).grid(
            row=3, column=1, sticky='w', pady=2)

        # --- 트리거 (time) / trigger: time ---
        self.time_frame = ttk.LabelFrame(parent, text='Time Schedule',
                                         padding=8)
        self.time_frame.grid(row=row, column=0, columnspan=2,
                             sticky='ew', pady=(0, 6))
        self.time_frame.columnconfigure(1, weight=1)
        row += 1

        ttk.Label(self.time_frame, text='Days:').grid(
            row=0, column=0, sticky='nw', padx=(0, 6), pady=2)
        days_box = ttk.Frame(self.time_frame)
        days_box.grid(row=0, column=1, sticky='w', pady=2)
        self.f_days = []
        for i, lab in enumerate(DAY_LABELS):
            v = tk.BooleanVar(value=(i < 5))
            cb = ttk.Checkbutton(days_box, text=lab, variable=v)
            cb.grid(row=0, column=i, padx=2)
            self.f_days.append(v)

        # 빠른 선택 버튼 / quick-select buttons
        quick = ttk.Frame(self.time_frame)
        quick.grid(row=1, column=1, sticky='w', pady=(2, 0))
        ttk.Button(quick, text='Weekdays', width=8,
                   command=lambda: self._set_days(list(range(5)))).pack(
            side='left', padx=2)
        ttk.Button(quick, text='Weekend', width=8,
                   command=lambda: self._set_days([5, 6])).pack(
            side='left', padx=2)
        ttk.Button(quick, text='Everyday', width=8,
                   command=lambda: self._set_days(list(range(7)))).pack(
            side='left', padx=2)
        ttk.Button(quick, text='None', width=8,
                   command=lambda: self._set_days([])).pack(
            side='left', padx=2)

        ttk.Label(self.time_frame, text='Start (HH:MM):').grid(
            row=2, column=0, sticky='w', padx=(0, 6), pady=2)
        self.f_start = tk.StringVar(value='06:00')
        ttk.Entry(self.time_frame, textvariable=self.f_start, width=10).grid(
            row=2, column=1, sticky='w', pady=2)

        ttk.Label(self.time_frame, text='End (HH:MM):').grid(
            row=3, column=0, sticky='w', padx=(0, 6), pady=2)
        self.f_end = tk.StringVar(value='08:00')
        ttk.Entry(self.time_frame, textvariable=self.f_end, width=10).grid(
            row=3, column=1, sticky='w', pady=2)

        # --- 트리거 (sun) / trigger: sun ---
        self.sun_frame = ttk.LabelFrame(parent,
                                        text='Sunrise/Sunset Trigger',
                                        padding=8)
        self.sun_frame.grid(row=row, column=0, columnspan=2,
                            sticky='ew', pady=(0, 6))
        self.sun_frame.columnconfigure(1, weight=1)
        row += 1

        ttk.Label(self.sun_frame, text='Event:').grid(
            row=0, column=0, sticky='w', padx=(0, 6), pady=2)
        self.f_sun_event = tk.StringVar(value='sunrise')
        ttk.Combobox(self.sun_frame, textvariable=self.f_sun_event,
                     values=SUN_EVENTS, state='readonly', width=10).grid(
            row=0, column=1, sticky='w', pady=2)

        ttk.Label(self.sun_frame, text='Offset (min):').grid(
            row=1, column=0, sticky='w', padx=(0, 6), pady=2)
        self.f_sun_offset = tk.StringVar(value='0')
        ttk.Entry(self.sun_frame, textvariable=self.f_sun_offset, width=10).grid(
            row=1, column=1, sticky='w', pady=2)

        ttk.Label(self.sun_frame, text='Days:').grid(
            row=2, column=0, sticky='nw', padx=(0, 6), pady=2)
        sun_days = ttk.Frame(self.sun_frame)
        sun_days.grid(row=2, column=1, sticky='w', pady=2)
        self.f_sun_days = []
        for i, lab in enumerate(DAY_LABELS):
            v = tk.BooleanVar(value=True)
            ttk.Checkbutton(sun_days, text=lab, variable=v).grid(
                row=0, column=i, padx=2)
            self.f_sun_days.append(v)

        # --- 액션 / action ---
        act = ttk.LabelFrame(parent, text='Action', padding=8)
        act.grid(row=row, column=0, columnspan=2, sticky='ew', pady=(0, 6))
        act.columnconfigure(1, weight=1)
        row += 1

        ttk.Label(act, text='Action Device:').grid(
            row=0, column=0, sticky='w', padx=(0, 6), pady=2)
        self.f_action_device = tk.StringVar()
        self.action_device_cb = ttk.Combobox(
            act, textvariable=self.f_action_device, values=[], width=24)
        self.action_device_cb.grid(row=0, column=1, sticky='w', pady=2)
        self.action_device_cb.bind('<<ComboboxSelected>>',
                                   lambda e: self._on_action_device_changed())

        # 디바이스 타입 표시 / device type label
        self.device_type_var = tk.StringVar(value='')
        ttk.Label(act, textvariable=self.device_type_var,
                  foreground='gray').grid(row=1, column=1, sticky='w',
                                          padx=(0, 0))

        ttk.Label(act, text='Action Value:').grid(
            row=2, column=0, sticky='w', padx=(0, 6), pady=2)
        av_box = ttk.Frame(act)
        av_box.grid(row=2, column=1, sticky='w', pady=2)
        self.f_action_value = tk.StringVar(value='1')
        ttk.Entry(av_box, textvariable=self.f_action_value, width=14).pack(
            side='left')
        self.color_btn = ttk.Button(av_box, text='Pick Color...',
                                    command=self._on_pick_color)
        # pack 으로 관리되므로 grid_remove 가 아닌 pack_forget 사용
        # Use pack_forget (not grid_remove) since the button is pack-managed.
        self.color_btn.pack(side='left', padx=6)
        self.color_btn.pack_forget()  # neopixel 일 때만 표시

        # --- 설정 / settings ---
        settings = ttk.LabelFrame(parent, text='Settings', padding=8)
        settings.grid(row=row, column=0, columnspan=2, sticky='ew',
                      pady=(0, 6))
        settings.columnconfigure(1, weight=1)
        settings.columnconfigure(3, weight=1)
        row += 1

        ttk.Label(settings, text='Priority:').grid(
            row=0, column=0, sticky='w', padx=(0, 6), pady=2)
        self.f_priority = tk.StringVar(value='0')
        ttk.Entry(settings, textvariable=self.f_priority, width=8).grid(
            row=0, column=1, sticky='w', pady=2)

        ttk.Label(settings, text='Cooldown (sec):').grid(
            row=0, column=2, sticky='w', padx=(10, 6), pady=2)
        self.f_cooldown = tk.StringVar(value='60')
        ttk.Entry(settings, textvariable=self.f_cooldown, width=8).grid(
            row=0, column=3, sticky='w', pady=2)

        ttk.Label(settings, text='Timer (sec, 0=off):').grid(
            row=1, column=0, sticky='w', padx=(0, 6), pady=2)
        self.f_timer = tk.StringVar(value='0')
        ttk.Entry(settings, textvariable=self.f_timer, width=8).grid(
            row=1, column=1, sticky='w', pady=2)

        # --- 추가 조건 / conditions ---
        cond = ttk.LabelFrame(parent, text='Additional Conditions (all must match)',
                              padding=8)
        cond.grid(row=row, column=0, columnspan=2, sticky='ew', pady=(0, 6))
        cond.columnconfigure(0, weight=1)
        row += 1

        # conditions Treeview
        ctree_frame = ttk.Frame(cond)
        ctree_frame.grid(row=0, column=0, sticky='ew')
        ctree_frame.columnconfigure(0, weight=1)
        ccols = ('sensor', 'operator', 'value')
        self.cond_tree = ttk.Treeview(ctree_frame, columns=ccols,
                                      show='headings', height=4,
                                      selectmode='browse')
        self.cond_tree.heading('sensor', text='Sensor')
        self.cond_tree.heading('operator', text='Op')
        self.cond_tree.heading('value', text='Value')
        self.cond_tree.column('sensor', width=180, anchor='w')
        self.cond_tree.column('operator', width=50, anchor='center')
        self.cond_tree.column('value', width=80, anchor='w')
        self.cond_tree.grid(row=0, column=0, sticky='ew')
        self.cond_tree.bind('<<TreeviewSelect>>',
                            lambda e: self._on_condition_select())

        csv = ttk.Scrollbar(ctree_frame, orient='vertical',
                            command=self.cond_tree.yview)
        csv.grid(row=0, column=1, sticky='ns')
        self.cond_tree.configure(yscrollcommand=csv.set)

        # 조건 추가 폼 / condition add form
        add_frame = ttk.Frame(cond)
        add_frame.grid(row=1, column=0, sticky='ew', pady=(4, 0))
        add_frame.columnconfigure(0, weight=2)
        add_frame.columnconfigure(1, weight=1)
        add_frame.columnconfigure(2, weight=1)
        self.cond_sensor_var = tk.StringVar()
        ttk.Combobox(add_frame, textvariable=self.cond_sensor_var,
                     values=[], width=18).grid(row=0, column=0, sticky='ew',
                                              padx=(0, 4))
        self.cond_op_var = tk.StringVar(value='>')
        ttk.Combobox(add_frame, textvariable=self.cond_op_var,
                     values=OPERATORS, state='readonly', width=6).grid(
            row=0, column=1, sticky='w', padx=2)
        self.cond_val_var = tk.StringVar(value='20')
        ttk.Entry(add_frame, textvariable=self.cond_val_var, width=10).grid(
            row=0, column=2, sticky='w', padx=2)

        cb_frame = ttk.Frame(cond)
        cb_frame.grid(row=2, column=0, sticky='w', pady=(4, 0))
        ttk.Button(cb_frame, text='Add', command=self._on_add_condition).pack(
            side='left', padx=(0, 4))
        ttk.Button(cb_frame, text='Update',
                   command=self._on_update_condition).pack(
            side='left', padx=4)
        ttk.Button(cb_frame, text='Remove',
                   command=self._on_remove_condition).pack(
            side='left', padx=4)
        ttk.Button(cb_frame, text='Clear',
                   command=self._on_clear_conditions).pack(
            side='left', padx=4)

        # --- action_off / 해제 시 자동 OFF ---
        off = ttk.LabelFrame(parent, text='Action OFF (when released)',
                              padding=8)
        off.grid(row=row, column=0, columnspan=2, sticky='ew', pady=(0, 6))
        off.columnconfigure(2, weight=1)
        row += 1

        self.f_action_off_enabled = tk.BooleanVar(value=False)
        aoff_cb = ttk.Checkbutton(off, text='Enable action_off',
                                  variable=self.f_action_off_enabled,
                                  command=self._on_action_off_toggled)
        aoff_cb.grid(row=0, column=0, columnspan=3, sticky='w')

        ttk.Label(off, text='Device:').grid(row=1, column=0, sticky='w',
                                            padx=(20, 4), pady=2)
        self.f_off_device = tk.StringVar()
        self.off_device_cb = ttk.Combobox(off, textvariable=self.f_off_device,
                                          values=[], width=20)
        self.off_device_cb.grid(row=1, column=1, sticky='w', pady=2)

        ttk.Label(off, text='Value:').grid(row=1, column=2, sticky='w',
                                            padx=(8, 4), pady=2)
        self.f_off_value = tk.StringVar(value='0')
        ttk.Entry(off, textvariable=self.f_off_value, width=10).grid(
            row=1, column=3, sticky='w', pady=2)

        # 처음에는 action_off 비활성 / disable action_off initially
        self._on_action_off_toggled()

        # 처음에는 타입별 프레임 표시 상태 설정
        self._on_type_changed()

    # ------------------------------------------------------------
    # 아래 패널: 로그 | 코드 / Bottom: log | code
    # ------------------------------------------------------------
    def _build_bottom_paned(self):
        """하단 PanedWindow (로그 + 코드 미리보기)."""
        paned = ttk.PanedWindow(self.root, orient='vertical')
        paned.grid(row=2, column=0, sticky='nsew', padx=8, pady=4)

        log_frame = ttk.LabelFrame(paned, text='Execution Log', padding=4)
        paned.add(log_frame, weight=1)
        self._build_log_panel(log_frame)

        code_frame = ttk.LabelFrame(paned, text='Generated Code', padding=4)
        paned.add(code_frame, weight=1)
        self._build_code_panel(code_frame)

    def _build_log_panel(self, parent):
        """실행 로그 패널. Execution log panel."""
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        # 로그 Text 위젯 + 스크롤바 / log text widget + scrollbar
        log_box = ttk.Frame(parent)
        log_box.grid(row=0, column=0, sticky='nsew')
        log_box.columnconfigure(0, weight=1)
        log_box.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_box, height=8, wrap='none',
                                state='disabled',
                                background='#1e1e1e', foreground='#d4d4d4',
                                font=('Consolas', 10), borderwidth=0)
        self.log_text.grid(row=0, column=0, sticky='nsew')
        # 태그 색상 / color tags for log levels
        self.log_text.tag_configure('ok', foreground='#7ee787')
        self.log_text.tag_configure('skipped', foreground='#f0c674')
        self.log_text.tag_configure('error', foreground='#ff7b72')
        self.log_text.tag_configure('off', foreground='#79c0ff')
        self.log_text.tag_configure('ts', foreground='#a0a0a0')

        lsb = ttk.Scrollbar(log_box, orient='vertical',
                            command=self.log_text.yview)
        lsb.grid(row=0, column=1, sticky='ns')
        self.log_text.configure(yscrollcommand=lsb.set)

        # 버튼 행 / button row
        btn_frame = ttk.Frame(parent)
        btn_frame.grid(row=1, column=0, sticky='ew', pady=(4, 0))
        ttk.Button(btn_frame, text='Refresh',
                   command=self._refresh_log).pack(side='left', padx=(0, 4))
        self.auto_log_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(btn_frame, text='Auto-refresh (5s)',
                        variable=self.auto_log_var).pack(side='left',
                                                          padx=(8, 0))
        ttk.Button(btn_frame, text='Clear log on gateway',
                   command=self._on_clear_gateway_log).pack(
            side='right', padx=(0, 4))

    def _build_code_panel(self, parent):
        """코드 미리보기 패널. Generated code panel."""
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        code_box = ttk.Frame(parent)
        code_box.grid(row=0, column=0, sticky='nsew')
        code_box.columnconfigure(0, weight=1)
        code_box.rowconfigure(0, weight=1)

        self.code_text = tk.Text(code_box, height=10, wrap='none',
                                 state='disabled',
                                 background='#1e1e1e', foreground='#d4d4d4',
                                 font=('Consolas', 10),
                                 borderwidth=0, undo=True)
        self.code_text.grid(row=0, column=0, sticky='nsew')
        # 간단한 신택스 하이라이트 태그 / simple syntax highlight tags
        self.code_text.tag_configure('kw', foreground='#ff7b72')
        self.code_text.tag_configure('str', foreground='#a5d6ff')
        self.code_text.tag_configure('num', foreground='#79c0ff')
        self.code_text.tag_configure('com', foreground='#8b949e')
        self.code_text.tag_configure('fn', foreground='#d2a8ff')

        csb = ttk.Scrollbar(code_box, orient='vertical',
                            command=self.code_text.yview)
        csb.grid(row=0, column=1, sticky='ns')
        self.code_text.configure(yscrollcommand=csb.set)

        hsb = ttk.Scrollbar(code_box, orient='horizontal',
                            command=self.code_text.xview)
        hsb.grid(row=1, column=0, sticky='ew')
        self.code_text.configure(xscrollcommand=hsb.set)

        # 버튼 행 / button row
        btn_frame = ttk.Frame(parent)
        btn_frame.grid(row=2, column=0, sticky='ew', pady=(4, 0))
        ttk.Button(btn_frame, text='Copy',
                   command=self._on_copy_code).pack(side='left',
                                                     padx=(0, 4))
        ttk.Button(btn_frame, text='Save to file...',
                   command=self._on_save_code).pack(side='left', padx=4)
        ttk.Button(btn_frame, text='Send to Gateway',
                   command=self._on_send_to_gateway).pack(side='left',
                                                          padx=4)
        ttk.Button(btn_frame, text='Regenerate',
                   command=self._regen_code).pack(side='right', padx=4)

    # ------------------------------------------------------------
    # 상태 표시줄 / Status bar
    # ------------------------------------------------------------
    def _build_status_bar(self):
        """하단 상태 표시줄. Bottom status bar."""
        bar = ttk.Frame(self.root, relief='sunken', padding=(6, 2))
        bar.grid(row=3, column=0, sticky='ew')
        bar.columnconfigure(1, weight=1)

        self.count_var = tk.StringVar(value='Rules: 0 | Sensors: 0 | Devices: 0')
        ttk.Label(bar, textvariable=self.count_var).grid(
            row=0, column=0, sticky='w')

        ttk.Label(bar, text='automation_editor.py v{}'.format(APP_VERSION),
                  foreground='gray').grid(row=0, column=2, sticky='e')

    # ============================================================
    # 연결 / Connection
    # ============================================================
    def _on_connect(self):
        """연결 버튼 클릭. Connect button handler."""
        ip = self.ip_var.get().strip()
        if not ip:
            messagebox.showwarning('Input required',
                                   'Please enter gateway IP.')
            return
        # http:// 접두사가 없으면 추가 / add http:// prefix if missing
        if not ip.startswith('http://') and not ip.startswith('https://'):
            ip = 'http://' + ip
        self.gateway_ip = ip.rstrip('/')

        # 상태 표시 / status update
        self._set_status('Connecting to {} ...'.format(self.gateway_ip),
                          'orange')
        self._run_async(self._do_connect, self._after_connect)

    def _do_connect(self):
        """백그라운드 스레드에서 연결 및 데이터 수집.
        Connect and fetch data in background thread."""
        ip = self.gateway_ip
        result = {'error': None, 'sensors': None, 'devices': None,
                  'rules': None}
        try:
            result['sensors'] = http_get_json(
                ip + '/api/sensors', timeout=HTTP_TIMEOUT)
        except Exception as ex:
            result['error'] = 'sensors: {}'.format(ex)
            return result
        try:
            result['devices'] = http_get_json(
                ip + '/api/devices', timeout=HTTP_TIMEOUT)
        except Exception as ex:
            result['error'] = 'devices: {}'.format(ex)
            return result
        try:
            result['rules'] = http_get_json(
                ip + '/api/automation?action=list', timeout=HTTP_TIMEOUT)
        except Exception as ex:
            result['error'] = 'rules: {}'.format(ex)
            return result
        return result

    def _after_connect(self, result):
        """연결 결과 처리 (메인 스레드). Handle connect result on main thread."""
        if result is None:
            self._set_status('Connection failed.', 'red')
            self.connected = False
            return
        if result.get('error'):
            self._set_status('Connection failed: ' + result['error'], 'red')
            self.connected = False
            messagebox.showerror('Connection error',
                                 result['error'])
            return

        # 데이터 저장
        self.sensors = result.get('sensors') or {}
        self.devices = result.get('devices') or {}
        gw_rules = (result.get('rules') or {}).get('rules', {})
        self.gateway_rules = gw_rules if isinstance(gw_rules, dict) else {}

        # 센서/장치 이름 목록 추출 / extract sensor & device name lists
        self._extract_sensor_names()
        self._extract_device_entries()

        # 드롭다운 업데이트
        self.sensor_cb.configure(values=self.sensor_names)
        self.action_device_cb.configure(
            values=[d[0] for d in self.device_entries])
        self.off_device_cb.configure(
            values=[d[0] for d in self.device_entries])
        # conditions 추가 폼 센서 콤보 업데이트
        for child in self.editor_inner.winfo_children():
            pass  # 콤보는 별도로 찾아야 함 (children 검색)

        # conditions 추가 폼 센서 콤보 업데이트
        cond_combo = self._find_cond_sensor_combo()
        if cond_combo is not None:
            cond_combo.configure(values=self.sensor_names)

        # 게이트웨이 규칙을 local_rules 로 로드
        # Load gateway rules into local_rules (replace working set)
        if not self.local_rules:
            self._load_rules_from_gateway()
        else:
            # 이미 작업 중인 규칙이 있으면 유지 (선택적 병합)
            pass

        # 상태 업데이트
        self.connected = True
        ip_disp = self.gateway_ip.replace('http://', '').replace('https://', '')
        self._set_status('Connected to {} | sensors: {} | devices: {}'.format(
            ip_disp, len(self.sensor_names), len(self.device_entries)),
            'green')

        # 로그 자동 새로고침 시작
        self._refresh_log()
        self._schedule_log_refresh()

        # 설정 저장
        self.settings['last_ip'] = self.ip_var.get().strip()
        save_settings(self.settings)

        # 카운터 업데이트
        self._update_counts()

    def _find_cond_sensor_combo(self):
        """conditions 추가 폼의 센서 콤보 위젯 찾기."""
        try:
            cond_lf = None
            for w in self.editor_inner.winfo_children():
                if isinstance(w, ttk.LabelFrame) and \
                        w.cget('text').startswith('Additional Conditions'):
                    cond_lf = w
                    break
            if cond_lf is None:
                return None
            for child in cond_lf.winfo_children():
                if isinstance(child, ttk.Frame):
                    for sub in child.winfo_children():
                        if isinstance(sub, ttk.Combobox):
                            return sub
        except Exception:
            return None
        return None

    def _on_refresh_all(self):
        """전체 새로고침 (sensors, devices, rules). Refresh all data."""
        if not self.connected:
            self._on_connect()
            return
        self._run_async(self._do_connect, self._after_refresh)

    def _after_refresh(self, result):
        """새로고침 결과 처리. Handle refresh result."""
        if result is None or result.get('error'):
            err = result.get('error') if result else 'unknown error'
            self._set_status('Refresh failed: ' + str(err), 'red')
            messagebox.showerror('Refresh error', str(err))
            return
        self.sensors = result.get('sensors') or {}
        self.devices = result.get('devices') or {}
        gw_rules = (result.get('rules') or {}).get('rules', {})
        self.gateway_rules = gw_rules if isinstance(gw_rules, dict) else {}
        self._extract_sensor_names()
        self._extract_device_entries()
        self.sensor_cb.configure(values=self.sensor_names)
        self.action_device_cb.configure(
            values=[d[0] for d in self.device_entries])
        self.off_device_cb.configure(
            values=[d[0] for d in self.device_entries])
        cond_combo = self._find_cond_sensor_combo()
        if cond_combo is not None:
            cond_combo.configure(values=self.sensor_names)
        self._set_status('Refreshed.', 'green')
        self._refresh_log()
        self._update_counts()

    def _load_rules_from_gateway(self):
        """게이트웨이 규칙을 local_rules 로 로드.
        Load rules from gateway into local working set."""
        self.local_rules = []
        if not isinstance(self.gateway_rules, dict):
            return
        for rid, rule in self.gateway_rules.items():
            if not isinstance(rule, dict):
                continue
            # 게이트웨이 규칙은 sensor 타입만 지원하므로 기본값 채움
            rt = rule.get('rule_type', 'sensor')
            if 'type' in rule and not rt:
                rt = rule.get('type', 'sensor')
            r = {
                'name': rule.get('name', ''),
                'rule_type': rt,
                'sensor': rule.get('sensor', ''),
                'operator': rule.get('operator', '>'),
                'value': rule.get('value', 0),
                'hysteresis': rule.get('hysteresis', 0),
                'cooldown_sec': rule.get('cooldown_sec', 60),
                'action_device': rule.get('action_device', ''),
                'action_value': rule.get('action_value', ''),
                'priority': rule.get('priority', 0),
                'conditions': rule.get('conditions') or [],
                'action_off': rule.get('action_off'),
                '_gw_id': rid,
            }
            self.local_rules.append(r)
        self._refresh_rules_tree()
        self._regen_code()

    def _extract_sensor_names(self):
        """센서 이름 목록 추출. Extract sensor names from API response."""
        names = []
        if not isinstance(self.sensors, dict):
            self.sensor_names = []
            return
        for node_id, node_info in self.sensors.items():
            if not isinstance(node_info, dict):
                continue
            for sname in node_info.keys():
                if sname in ('nick', 'node_id', 'nick', 'role'):
                    continue
                if isinstance(node_info[sname], dict):
                    if sname not in names:
                        names.append(sname)
        self.sensor_names = sorted(names)

    def _extract_device_entries(self):
        """장치 (이름, 타입, 노드) 목록 추출.
        Extract device entries (name, type, node) from API response."""
        entries = []
        type_map = {}
        if not isinstance(self.devices, dict):
            self.device_entries = []
            self.device_type_map = {}
            return
        nodes = self.devices.get('nodes', [])
        if not isinstance(nodes, list):
            nodes = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_id = node.get('node_id', '')
            devs = node.get('devices', [])
            if not isinstance(devs, list):
                continue
            for dev in devs:
                if not isinstance(dev, dict):
                    continue
                name = dev.get('name', '')
                if not name:
                    continue
                dtype = dev.get('type', 'gpio')
                entries.append((name, dtype, node_id))
                type_map[name] = dtype
        self.device_entries = entries
        self.device_type_map = type_map

    # ============================================================
    # 비동기 실행 / Async execution helper
    # ============================================================
    def _run_async(self, func, callback):
        """백그라운드 스레드에서 func 실행 후 메인 스레드에서 callback 호출.
        Run func in a background thread; call callback on main thread.

        스레드 안전을 위해 root.after() 대신 queue.Queue 를 사용합니다.
        worker 스레드는 결과를 큐에 넣기만 하고, 메인 스레드는 주기적으로
        큐를 폴링하여 callback 을 실행합니다.
        Uses a queue.Queue instead of root.after() from the worker thread
        for thread safety."""
        def worker():
            try:
                result = func()
            except Exception as ex:
                result = {'error': str(ex)}
                traceback.print_exc()
            # 결과를 큐에 넣음 / put result on queue (thread-safe)
            self._async_queue.put((callback, result))
        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _poll_async_queue(self):
        """메인 스레드에서 큐를 폴링하여 callback 실행.
        Poll the async queue on the main thread and run callbacks.

        이 메서드는 self.root.after() 로 주기적으로 재호출됩니다.
        This is scheduled to run periodically via self.root.after()."""
        try:
            while True:
                callback, result = self._async_queue.get_nowait()
                try:
                    callback(result)
                except Exception as ex:
                    print('[automation_editor] callback error: {}'.format(ex))
                    traceback.print_exc()
        except queue.Empty:
            pass
        # 50ms 마다 다시 폴링 / poll again in 50ms
        try:
            self.root.after(50, self._poll_async_queue)
        except Exception:
            # root 가 파괴된 경우 무시 / ignore if root destroyed
            pass

    # ============================================================
    # 상태 표시 / Status update
    # ============================================================
    def _set_status(self, text, color='green'):
        """상태 표시줄 색상과 텍스트 업데이트."""
        self.status_var.set(text)
        self.conn_color_var.set('*' if color == 'green' else
                               ('o' if color == 'orange' else 'x'))
        # 색상은 라벨 위젯이 필요. 상태 표시는 단순 텍스트로 처리.
        # conn_color_var 를 사용하는 라벨의 색상을 직접 변경
        # (build_connection_panel 에서 dot_lbl 을 저장하지 않았으므로 다시 찾기)
        try:
            for w in self.root.winfo_children():
                if isinstance(w, ttk.Frame):
                    for child in w.winfo_children():
                        if isinstance(child, ttk.Label) and \
                                str(child.cget('textvariable')) == \
                                str(self.conn_color_var):
                            child.configure(foreground=color)
        except Exception:
            pass

    def _update_counts(self):
        """상태 표시줄 카운터 업데이트."""
        self.count_var.set(
            'Rules: {} | Sensors: {} | Devices: {}'.format(
                len(self.local_rules),
                len(self.sensor_names),
                len(self.device_entries)))

    # ============================================================
    # 규칙 목록 Treeview / Rules tree
    # ============================================================
    def _refresh_rules_tree(self):
        """규칙 목록 새로고침. Refresh rules tree."""
        # 기존 항목 삭제
        for item in self.rules_tree.get_children():
            self.rules_tree.delete(item)
        # 새 항목 추가
        for i, rule in enumerate(self.local_rules):
            trigger = self._rule_trigger_str(rule)
            action = '{}={}'.format(
                rule.get('action_device', ''),
                rule.get('action_value', ''))
            self.rules_tree.insert('', 'end', iid=str(i),
                                   values=(rule.get('name', ''),
                                           rule.get('rule_type', 'sensor'),
                                           trigger, action,
                                           rule.get('priority', 0)))
        self._update_counts()

    def _rule_trigger_str(self, rule):
        """규칙의 트리거 표시 문자열 생성."""
        rt = rule.get('rule_type', 'sensor')
        if rt == 'sensor':
            return '{} {} {}'.format(
                rule.get('sensor', ''),
                rule.get('operator', '>'),
                rule.get('value', 0))
        if rt == 'time':
            sched = rule.get('schedule') or {}
            days = sched.get('days', [])
            start = sched.get('start', 0)
            end = sched.get('end', 0)
            day_str = ','.join(DAY_LABELS_KR[d] for d in days) if days else '-'
            return '{} {}-{}'.format(day_str,
                                     time_to_str(start),
                                     time_to_str(end))
        if rt == 'sun':
            se = rule.get('sun_event') or {}
            return '{} {:+d}min'.format(se.get('event', ''),
                                         se.get('offset_min', 0))
        return ''

    # ============================================================
    # 규칙 편집 폼 동작 / Rule editor form actions
    # ============================================================
    def _on_add_rule(self):
        """새 규칙 추가 (폼 초기화). Add new rule (clear form)."""
        self._reset_form_values()
        self.editing_index = None
        self._set_form_title('Rule Editor - [NEW]')

    def _on_edit_rule(self):
        """선택한 규칙 편집. Edit selected rule."""
        sel = self.rules_tree.selection()
        if not sel:
            messagebox.showinfo('Select rule',
                                'Please select a rule to edit.')
            return
        idx = int(sel[0])
        if idx < 0 or idx >= len(self.local_rules):
            return
        rule = self.local_rules[idx]
        self._load_rule_into_form(rule)
        self.editing_index = idx
        self._set_form_title(
            'Rule Editor - [{}]'.format(rule.get('name', '')[:30]))

    def _on_delete_rule(self):
        """선택한 규칙 삭제. Delete selected rule."""
        sel = self.rules_tree.selection()
        if not sel:
            messagebox.showinfo('Select rule',
                                'Please select a rule to delete.')
            return
        idx = int(sel[0])
        if idx < 0 or idx >= len(self.local_rules):
            return
        name = self.local_rules[idx].get('name', '')
        if messagebox.askyesno('Confirm delete',
                               'Delete rule "{}"?'.format(name)):
            del self.local_rules[idx]
            self._refresh_rules_tree()
            self._regen_code()
            if self.editing_index == idx:
                self._reset_form_values()
                self.editing_index = None

    def _on_duplicate_rule(self):
        """선택한 규칙 복제. Duplicate selected rule."""
        sel = self.rules_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if idx < 0 or idx >= len(self.local_rules):
            return
        import copy
        new_rule = copy.deepcopy(self.local_rules[idx])
        new_rule['name'] = (new_rule.get('name', '') + ' (copy)')[:80]
        new_rule.pop('_gw_id', None)
        self.local_rules.insert(idx + 1, new_rule)
        self._refresh_rules_tree()
        self._regen_code()

    def _on_move_up(self):
        """규칙 위로 이동."""
        sel = self.rules_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if idx <= 0:
            return
        self.local_rules[idx], self.local_rules[idx - 1] = \
            self.local_rules[idx - 1], self.local_rules[idx]
        self._refresh_rules_tree()
        self._regen_code()
        self.rules_tree.selection_set(str(idx - 1))

    def _on_move_down(self):
        """규칙 아래로 이동."""
        sel = self.rules_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if idx >= len(self.local_rules) - 1:
            return
        self.local_rules[idx], self.local_rules[idx + 1] = \
            self.local_rules[idx + 1], self.local_rules[idx]
        self._refresh_rules_tree()
        self._regen_code()
        self.rules_tree.selection_set(str(idx + 1))

    def _on_rule_select(self, event):
        """규칙 선택 시 (트리거 표시만). On rule select."""
        pass  # 명시적 로드는 더블클릭 또는 Edit 버튼 사용

    def _set_form_title(self, text):
        """편집기 LabelFrame 제목 변경."""
        # editor LabelFrame 찾기
        for w in self.root.winfo_children():
            if isinstance(w, ttk.PanedWindow):
                for pane in w.winfo_children():
                    if isinstance(pane, ttk.LabelFrame) and \
                            pane.cget('text').startswith('Rule Editor'):
                        pane.configure(text=text)
                        return

    def _reset_form_values(self):
        """폼 기본값 초기화. Reset form to defaults."""
        self.f_name.set('')
        self.f_type.set('sensor')
        self.f_sensor.set('')
        self.f_operator.set('>')
        self.f_value.set('25')
        self.f_hysteresis.set('1.0')
        # time
        for i, v in enumerate(self.f_days):
            v.set(i < 5)
        self.f_start.set('06:00')
        self.f_end.set('08:00')
        # sun
        self.f_sun_event.set('sunrise')
        self.f_sun_offset.set('0')
        for v in self.f_sun_days:
            v.set(True)
        # action
        self.f_action_device.set('')
        self.f_action_value.set('1')
        self.device_type_var.set('')
        # settings
        self.f_priority.set('0')
        self.f_cooldown.set('60')
        self.f_timer.set('0')
        # conditions
        self._clear_conditions_tree()
        # action_off
        self.f_action_off_enabled.set(False)
        self.f_off_device.set('')
        self.f_off_value.set('0')
        self._on_action_off_toggled()
        self._on_type_changed()
        self._set_form_title('Rule Editor - [NEW]')

    def _on_reset_form(self):
        """폼 리셋 버튼."""
        if self.editing_index is not None:
            self._load_rule_into_form(
                self.local_rules[self.editing_index])
        else:
            self._reset_form_values()

    def _on_cancel_edit(self):
        """편집 취소."""
        self._reset_form_values()
        self.editing_index = None

    def _load_rule_into_form(self, rule):
        """규칙 dict 를 폼으로 로드. Load rule dict into form fields."""
        self.f_name.set(rule.get('name', ''))
        rt = rule.get('rule_type', 'sensor')
        self.f_type.set(rt)

        # sensor fields
        self.f_sensor.set(rule.get('sensor', ''))
        self.f_operator.set(rule.get('operator', '>'))
        self.f_value.set(str(rule.get('value', 0)))
        self.f_hysteresis.set(str(rule.get('hysteresis', 0)))

        # time
        sched = rule.get('schedule') or {}
        days = sched.get('days', [])
        for i, v in enumerate(self.f_days):
            v.set(i in days)
        self.f_start.set(time_to_str(sched.get('start', 600)))
        self.f_end.set(time_to_str(sched.get('end', 800)))

        # sun
        se = rule.get('sun_event') or {}
        self.f_sun_event.set(se.get('event', 'sunrise'))
        self.f_sun_offset.set(str(se.get('offset_min', 0)))
        se_days = se.get('days', list(range(7)))
        for i, v in enumerate(self.f_sun_days):
            v.set(i in se_days)

        # action
        self.f_action_device.set(rule.get('action_device', ''))
        self.f_action_value.set(str(rule.get('action_value', '')))
        self._on_action_device_changed()

        # settings
        self.f_priority.set(str(rule.get('priority', 0)))
        self.f_cooldown.set(str(rule.get('cooldown_sec', 60)))
        self.f_timer.set(str(rule.get('timer_sec', 0)))

        # conditions
        self._clear_conditions_tree()
        for c in (rule.get('conditions') or []):
            self.cond_tree.insert('', 'end',
                                  values=(c.get('sensor', ''),
                                          c.get('operator', '>'),
                                          c.get('value', '')))

        # action_off
        aoff = rule.get('action_off')
        if aoff and isinstance(aoff, dict) and aoff.get('device'):
            self.f_action_off_enabled.set(True)
            self.f_off_device.set(aoff.get('device', ''))
            self.f_off_value.set(str(aoff.get('value', '0')))
        else:
            self.f_action_off_enabled.set(False)
            self.f_off_device.set('')
            self.f_off_value.set('0')
        self._on_action_off_toggled()
        self._on_type_changed()

    def _collect_rule_from_form(self):
        """폼 값으로부터 rule dict 생성. 실패 시 (None, error_msg)."""
        name = self.f_name.get().strip()
        if not name:
            return None, 'Rule name is required.'

        rt = self.f_type.get()
        if rt not in RULE_TYPES:
            return None, 'Invalid rule type.'

        rule = {
            'name': name,
            'rule_type': rt,
            'action_device': self.f_action_device.get().strip(),
            'action_value': self.f_action_value.get().strip(),
            'priority': self._parse_int(self.f_priority.get(), 0),
            'cooldown_sec': self._parse_int(self.f_cooldown.get(), 60),
            'timer_sec': self._parse_int(self.f_timer.get(), 0),
        }

        # 타입별 필드 / type-specific fields
        if rt == 'sensor':
            rule['sensor'] = self.f_sensor.get().strip()
            rule['operator'] = self.f_operator.get()
            val, err = self._parse_number(self.f_value.get())
            if err:
                return None, 'Value: ' + err
            rule['value'] = val
            h, err = self._parse_number(self.f_hysteresis.get())
            if err:
                return None, 'Hysteresis: ' + err
            rule['hysteresis'] = h
        elif rt == 'time':
            days = [i for i, v in enumerate(self.f_days) if v.get()]
            if not days:
                return None, 'Select at least one day for time rule.'
            start = parse_time_str(self.f_start.get())
            end = parse_time_str(self.f_end.get())
            if start is None:
                return None, 'Start time format: HH:MM or HHMM.'
            if end is None:
                return None, 'End time format: HH:MM or HHMM.'
            rule['schedule'] = {'days': days, 'start': start, 'end': end}
        elif rt == 'sun':
            days = [i for i, v in enumerate(self.f_sun_days) if v.get()]
            if not days:
                return None, 'Select at least one day for sun rule.'
            rule['sun_event'] = {
                'event': self.f_sun_event.get(),
                'offset_min': self._parse_int(self.f_sun_offset.get(), 0),
                'days': days,
            }

        # conditions 수집 / collect conditions
        conds = []
        for item in self.cond_tree.get_children():
            vals = self.cond_tree.item(item, 'values')
            if len(vals) >= 3 and vals[0]:
                v, err = self._parse_number(vals[2])
                if err:
                    return None, 'Condition value: ' + err
                conds.append({
                    'sensor': str(vals[0]),
                    'operator': str(vals[1]),
                    'value': v,
                })
        if conds:
            rule['conditions'] = conds

        # action_off / 해제 시 자동 OFF
        if self.f_action_off_enabled.get():
            off_dev = self.f_off_device.get().strip()
            if off_dev:
                rule['action_off'] = {
                    'device': off_dev,
                    'value': self.f_off_value.get().strip(),
                }

        return rule, None

    def _on_apply_rule(self):
        """Apply 버튼: 폼 값을 local_rules 에 저장."""
        rule, err = self._collect_rule_from_form()
        if err:
            messagebox.showwarning('Validation error', err)
            return

        # timer_sec 은 별도 키 (add_rule 의 인자는 아니지만 코드 생성 시 활용)
        # 위 _collect_rule_from_form 에서 'timer_sec' 추가됨

        if self.editing_index is not None:
            # 기존 규칙 수정
            old = self.local_rules[self.editing_index]
            if '_gw_id' in old:
                rule['_gw_id'] = old['_gw_id']
            self.local_rules[self.editing_index] = rule
        else:
            self.local_rules.append(rule)
            self.editing_index = len(self.local_rules) - 1

        self._refresh_rules_tree()
        # 새로 추가된 규칙 선택
        try:
            self.rules_tree.selection_set(str(self.editing_index))
            self.rules_tree.see(str(self.editing_index))
        except Exception:
            pass
        self._set_form_title(
            'Rule Editor - [{}]'.format(rule['name'][:30]))
        self._regen_code()
        self._update_counts()

    # ============================================================
    # 타입별 폼 토글 / Type-based form toggling
    # ============================================================
    def _on_type_changed(self):
        """규칙 타입 변경 시 관련 프레임 표시/숨김."""
        rt = self.f_type.get()
        # sensor / time / sun 프레임 토글
        if rt == 'sensor':
            self.sensor_frame.grid()
            self.time_frame.grid_remove()
            self.sun_frame.grid_remove()
        elif rt == 'time':
            self.sensor_frame.grid_remove()
            self.time_frame.grid()
            self.sun_frame.grid_remove()
        elif rt == 'sun':
            self.sensor_frame.grid_remove()
            self.time_frame.grid_remove()
            self.sun_frame.grid()

    def _on_action_device_changed(self):
        """액션 디바이스 변경 시 타입 표시 및 색상 버튼 토글."""
        dev = self.f_action_device.get().strip()
        dtype = self.device_type_map.get(dev, '')
        self.device_type_var.set('type: {}'.format(dtype) if dtype else '')
        if dtype == 'neopixel':
            # pack 으로 관리되므로 pack() 사용 (grid 아님)
            self.color_btn.pack(side='left', padx=6)
        else:
            self.color_btn.pack_forget()

    def _on_pick_color(self):
        """NeoPixel 색상 선택기. Open color picker for action value."""
        cur = action_value_to_hex(self.f_action_value.get())
        try:
            result = colorchooser.askcolor(
                color=cur if cur else '#000000',
                title='Pick NeoPixel color')
        except Exception:
            result = (None, None)
        if result and result[1]:
            hex_val = hex_to_action_value(result[1])
            if hex_val:
                self.f_action_value.set(hex_val)

    def _on_action_off_toggled(self):
        """action_off 체크박스 토글."""
        enabled = self.f_action_off_enabled.get()
        state = 'normal' if enabled else 'disabled'
        self.off_device_cb.configure(state=state)
        # value entry 의 state 변경은 직접 위젯 참조가 필요하지만
        # 여기서는 간단히 off_device 콤보만 처리
        try:
            for child in self.editor_inner.winfo_children():
                if isinstance(child, ttk.LabelFrame) and \
                        child.cget('text').startswith('Action OFF'):
                    for sub in child.winfo_children():
                        if isinstance(sub, ttk.Entry):
                            sub.configure(state=state)
        except Exception:
            pass

    def _set_days(self, days):
        """요일 체크박스 일괄 설정."""
        for i, v in enumerate(self.f_days):
            v.set(i in days)

    # ============================================================
    # conditions (추가 조건) / Additional conditions
    # ============================================================
    def _clear_conditions_tree(self):
        for item in self.cond_tree.get_children():
            self.cond_tree.delete(item)

    def _on_add_condition(self):
        """조건 추가."""
        sensor = self.cond_sensor_var.get().strip()
        op = self.cond_op_var.get()
        val = self.cond_val_var.get().strip()
        if not sensor:
            messagebox.showwarning('Condition',
                                   'Please select a sensor.')
            return
        if op not in OPERATORS:
            messagebox.showwarning('Condition',
                                   'Please select an operator.')
            return
        if not val:
            messagebox.showwarning('Condition',
                                   'Please enter a value.')
            return
        # 값 검증 (숫자 또는 문자열 허용)
        v, err = self._parse_number(val)
        if err:
            # 문자열 그대로 허용 (예: 색상 값)
            v = val
        self.cond_tree.insert('', 'end', values=(sensor, op, val))
        # 입력 초기화
        self.cond_val_var.set('')

    def _on_update_condition(self):
        """선택한 조건 업데이트."""
        sel = self.cond_tree.selection()
        if not sel:
            messagebox.showinfo('Condition',
                                'Select a condition to update.')
            return
        sensor = self.cond_sensor_var.get().strip()
        op = self.cond_op_var.get()
        val = self.cond_val_var.get().strip()
        if not sensor or not val:
            messagebox.showwarning('Condition',
                                   'Sensor and value required.')
            return
        self.cond_tree.item(sel[0], values=(sensor, op, val))

    def _on_remove_condition(self):
        """선택한 조건 삭제."""
        sel = self.cond_tree.selection()
        if not sel:
            return
        self.cond_tree.delete(sel[0])

    def _on_clear_conditions(self):
        """모든 조건 삭제."""
        self._clear_conditions_tree()

    def _on_condition_select(self):
        """조건 선택 시 폼에 반영."""
        sel = self.cond_tree.selection()
        if not sel:
            return
        vals = self.cond_tree.item(sel[0], 'values')
        if len(vals) >= 3:
            self.cond_sensor_var.set(vals[0])
            self.cond_op_var.set(vals[1])
            self.cond_val_var.set(vals[2])

    # ============================================================
    # 값 파싱 도우미 / Value parsers
    # ============================================================
    def _parse_int(self, s, default=0):
        try:
            return int(str(s).strip())
        except (ValueError, TypeError):
            return default

    def _parse_number(self, s):
        """숫자 파싱. 정수로 떨어지면 int, 아니면 float.
        Returns (value, error_msg)."""
        s = str(s).strip()
        if not s:
            return 0, 'empty value'
        # 16진수 / hex
        try:
            if s.lower().startswith('0x'):
                v = int(s, 16)
                return v, None
        except ValueError:
            pass
        # 정수
        try:
            return int(s), None
        except ValueError:
            pass
        # 실수
        try:
            v = float(s)
            if v == int(v):
                v = int(v)
            return v, None
        except ValueError:
            pass
        return None, 'not a number: {}'.format(s)

    # ============================================================
    # 로그 패널 / Log panel
    # ============================================================
    def _refresh_log(self):
        """실행 로그 새로고침."""
        if not self.connected:
            return
        self._run_async(self._fetch_log, self._after_fetch_log)

    def _fetch_log(self):
        """백그라운드에서 로그 조회."""
        try:
            url = self.gateway_ip + \
                '/api/automation?action=log&limit=20'
            return http_get_json(url, timeout=HTTP_TIMEOUT)
        except Exception as ex:
            return {'error': str(ex)}

    def _after_fetch_log(self, result):
        """로그 조회 결과 표시."""
        if result is None:
            return
        if result.get('error'):
            # 로그 조회 실패는 조용히 처리 (상태 표시줄만 업데이트)
            return
        log = result.get('log', [])
        if not isinstance(log, list):
            log = []

        # Text 위젯 갱신
        self.log_text.configure(state='normal')
        self.log_text.delete('1.0', 'end')
        if not log:
            self.log_text.insert('end', '(no log entries)\n')
        for entry in log:
            ts = entry.get('ts_str', '')
            rname = entry.get('rule_name', '')
            action = entry.get('action', '')
            device = entry.get('device', '')
            value = entry.get('value', '')
            result_str = entry.get('result', 'ok')
            rtype = entry.get('rule_type', '')

            # 색상 태그 결정
            if result_str == 'ok':
                if action == 'on':
                    tag = 'ok'
                else:
                    tag = 'off'
            elif result_str == 'skipped':
                tag = 'skipped'
            else:
                tag = 'error'

            line = '[{}] {} {} → {}={} ({})\n'.format(
                ts, action.upper(), rname, device, value, result_str)
            self.log_text.insert('end', '[' + ts + '] ', 'ts')
            self.log_text.insert('end',
                                 '{} {} → {}={} ({})\n'.format(
                                     action.upper(), rname, device, value,
                                     result_str), tag)
        self.log_text.configure(state='disabled')
        self.log_text.see('end')

    def _schedule_log_refresh(self):
        """로그 자동 새로고침 스케줄."""
        if self._log_after_id is not None:
            try:
                self.root.after_cancel(self._log_after_id)
            except Exception:
                pass
            self._log_after_id = None
        if not self.auto_log_var.get():
            return
        if not self.connected:
            return
        self._log_after_id = self.root.after(
            LOG_REFRESH_MS, self._log_auto_tick)

    def _log_auto_tick(self):
        """자동 로그 새로고침 타이머 콜백."""
        self._log_after_id = None
        if self.auto_log_var.get() and self.connected:
            self._refresh_log()
            self._schedule_log_refresh()

    def _on_clear_gateway_log(self):
        """게이트웨이 로그 삭제."""
        if not self.connected:
            return
        if not messagebox.askyesno('Clear log',
                                   'Clear automation log on gateway?'):
            return

        def _do():
            try:
                url = self.gateway_ip + '/api/automation?action=clear_log'
                return http_get_json(url, timeout=HTTP_TIMEOUT)
            except Exception as ex:
                return {'error': str(ex)}

        def _after(result):
            if result and result.get('error'):
                messagebox.showerror('Clear log', result['error'])
            else:
                self._refresh_log()
                self._set_status('Gateway log cleared.', 'green')

        self._run_async(_do, _after)

    # ============================================================
    # 코드 미리보기 / Code preview
    # ============================================================
    def _regen_code(self):
        """생성된 코드 갱신. Regenerate code preview."""
        code = gen_full_automation_py(self.local_rules)
        self.code_text.configure(state='normal')
        self.code_text.delete('1.0', 'end')
        self.code_text.insert('1.0', code)
        # 간단한 신택스 하이라이트 적용
        self._apply_syntax_highlight()
        self.code_text.configure(state='disabled')

    def _apply_syntax_highlight(self):
        """간단한 신택스 하이라이트 적용.
        Apply simple Python syntax highlighting."""
        # 주석 / comments
        self._highlight_pattern(r'#.*$', 'com')
        # 문자열 / strings (간단히 큰따옴표)
        self._highlight_pattern(r'"[^"\\]*(\\.[^"\\]*)*"', 'str')
        # 키워드 / keywords
        keywords = ['def', 'import', 'return', 'try', 'except', 'if', 'else',
                    'for', 'in', 'while', 'True', 'False', 'None', 'as',
                    'from', 'pass', 'with']
        for kw in keywords:
            self._highlight_pattern(r'\b' + kw + r'\b', 'kw')
        # 함수 호출 / function calls (단순 패턴)
        self._highlight_pattern(r'\b[a-zA-Z_][a-zA-Z0-9_]*\(', 'fn')

    def _highlight_pattern(self, pattern, tag):
        """정규식 패턴으로 태그 적용. Apply tag for regex pattern matches."""
        try:
            import re
            start = '1.0'
            while True:
                match = self.code_text.search(pattern, start,
                                              regexp=True,
                                              stopindex='end')
                if not match:
                    break
                self.code_text.tag_add(tag, match,
                                       match + ' lineend')
                # 다음 줄로 이동
                start = self.code_text.index(match + ' lineend +1c')
        except Exception:
            pass

    def _on_copy_code(self):
        """코드 클립보드로 복사. Copy code to clipboard."""
        code = self.code_text.get('1.0', 'end-1c')
        self.root.clipboard_clear()
        self.root.clipboard_append(code)
        self._set_status('Code copied to clipboard.', 'green')

    def _on_save_code(self):
        """코드를 파일로 저장. Save code to file."""
        code = self.code_text.get('1.0', 'end-1c')
        # 기본 파일명: custom/automation.py
        init_dir = self.settings.get('last_save_dir', os.getcwd())
        path = filedialog.asksaveasfilename(
            title='Save automation.py',
            defaultextension='.py',
            initialdir=init_dir,
            initialfile='automation.py',
            filetypes=[('Python files', '*.py'), ('All files', '*.*')])
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(code)
            self.settings['last_save_dir'] = os.path.dirname(path)
            save_settings(self.settings)
            self._set_status('Saved: {}'.format(path), 'green')
            messagebox.showinfo('Saved', 'Code saved to:\n{}'.format(path))
        except Exception as ex:
            messagebox.showerror('Save failed', str(ex))

    def _on_send_to_gateway(self):
        """규칙을 게이트웨이로 전송.
        각 규칙에 대해 /api/automation?action=add 호출.
        (게이트웨이 add_rule API 는 sensor 타입 기본 필드만 지원함.)
        Send rules to gateway via /api/automation?action=add."""
        if not self.connected:
            messagebox.showwarning('Not connected',
                                   'Connect to gateway first.')
            return
        if not self.local_rules:
            messagebox.showinfo('No rules', 'No rules to send.')
            return

        # 지원 필드 확인 / check supported fields
        unsupported = []
        for r in self.local_rules:
            issues = []
            if r.get('rule_type') != 'sensor':
                issues.append('type={}'.format(r.get('rule_type')))
            if r.get('conditions'):
                issues.append('conditions')
            if r.get('action_off'):
                issues.append('action_off')
            if r.get('schedule'):
                issues.append('schedule')
            if r.get('sun_event'):
                issues.append('sun_event')
            if r.get('timer_sec'):
                issues.append('timer_sec')
            if issues:
                unsupported.append('  - {}: {}'.format(
                    r.get('name', ''), ', '.join(issues)))

        warn = ''
        if unsupported:
            warn = ('\n\nNote: The gateway add_rule API only supports '
                    'basic sensor-rule fields (name, sensor, operator, '
                    'value, action_device, action_value, hysteresis, '
                    'cooldown_sec). The following rules have unsupported '
                    'fields which will be ignored:\n' +
                    '\n'.join(unsupported) +
                    '\n\nFor full rule support, use "Save to file" and '
                    'upload custom/automation.py manually.')

        msg = 'Send {} rule(s) to gateway {}?{}'.format(
            len(self.local_rules), self.gateway_ip, warn)
        if not messagebox.askyesno('Send to gateway', msg):
            return

        self._run_async(self._do_send_to_gateway,
                        self._after_send_to_gateway)

    def _do_send_to_gateway(self):
        """백그라운드에서 게이트웨이로 규칙 전송.
        Send each rule to gateway in background thread."""
        results = []
        for r in self.local_rules:
            params = {
                'action': 'add',
                'name': r.get('name', ''),
                'sensor': r.get('sensor', ''),
                'operator': r.get('operator', '>'),
                'value': str(r.get('value', 0)),
                'action_device': r.get('action_device', ''),
                'action_value': str(r.get('action_value', '')),
                'hysteresis': str(r.get('hysteresis', 0)),
                'cooldown_sec': str(r.get('cooldown_sec', 60)),
            }
            qs = urllib.parse.urlencode(params)
            url = self.gateway_ip + '/api/automation?' + qs
            try:
                resp = http_get_json(url, timeout=HTTP_TIMEOUT)
                results.append((r.get('name', ''), resp))
            except Exception as ex:
                results.append((r.get('name', ''), {'error': str(ex)}))
        return {'results': results}

    def _after_send_to_gateway(self, result):
        """전송 결과 표시. Show send results."""
        if result is None:
            messagebox.showerror('Send failed', 'No response.')
            return
        results = result.get('results', [])
        ok = sum(1 for _, r in results if not (r and r.get('error')))
        fail = len(results) - ok
        msg = 'Sent {} rule(s) to gateway.\n  OK: {}\n  Failed: {}'.format(
            len(results), ok, fail)
        if fail:
            msg += '\n\nFailed rules:'
            for name, r in results:
                if r and r.get('error'):
                    msg += '\n  - {}: {}'.format(name, r['error'])
        messagebox.showinfo('Send to gateway', msg)
        self._set_status('Sent {} rules ({} ok, {} failed).'.format(
            len(results), ok, fail), 'green' if fail == 0 else 'orange')

    # ============================================================
    # 창 닫기 / Window close
    # ============================================================
    def _on_close(self):
        """창 닫기: 설정 저장 후 종료."""
        self.settings['last_ip'] = self.ip_var.get().strip()
        save_settings(self.settings)
        try:
            if self._log_after_id is not None:
                self.root.after_cancel(self._log_after_id)
        except Exception:
            pass
        self.root.destroy()


# ============================================================
# 진입점 / Entry point
# ============================================================
def main():
    """애플리케이션 시작. Start the application."""
    root = tk.Tk()
    # HighDPI 처리 (Windows) / enable HighDPI on Windows
    try:
        # Windows DPI awareness
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    except Exception:
        pass

    app = AutomationEditorApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
