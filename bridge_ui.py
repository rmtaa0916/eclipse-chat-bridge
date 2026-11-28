#!/usr/bin/env python3
"""ECLIPSE Chat Bridge — Terminal Presentation & Dynamic Animation System (v2.5).

Engineered to match ECLIPSE core standards:
- Zero-flicker differential cursor addressing (no subshell clear commands)
- Real-time continuous animated kinetic suspension bridge with bidirectional telemetry
- Height & width adaptive responsive typography (Mobile portrait to 4K Ultrawide)
- Non-blocking asynchronous hotkey console loop (live 12 FPS refresh)
- Reactive quantum telemetry wave, hazard beacon pulses, and spark discharges
- Fail-safe signal & atexit cursor / tty restorations
"""

from __future__ import annotations

import atexit
import json
import math
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import termios
import time
import tty

# Check for NO_COLOR standard
NO_COLOR = bool(os.environ.get("NO_COLOR"))

# ANSI Palette matching ECLIPSE Cyberpunk Specifications
RESET = "" if NO_COLOR else "\033[0m"
BOLD = "" if NO_COLOR else "\033[1m"
DIM = "" if NO_COLOR else "\033[2m"
ITALIC = "" if NO_COLOR else "\033[3m"

# Vivid Colors
CYAN = "" if NO_COLOR else "\033[1;36m"
ICE = "" if NO_COLOR else "\033[38;5;123m"
WHITE = "" if NO_COLOR else "\033[1;38;5;255m"
GREEN = "" if NO_COLOR else "\033[1;38;5;120m"
YELLOW = "" if NO_COLOR else "\033[1;38;5;220m"
GOLD = "" if NO_COLOR else "\033[1;38;5;214m"
RED = "" if NO_COLOR else "\033[1;38;5;203m"
MAGENTA = "" if NO_COLOR else "\033[1;38;5;213m"
PURPLE = "" if NO_COLOR else "\033[38;5;141m"
MUTED = "" if NO_COLOR else "\033[38;5;242m"
BLUE = "" if NO_COLOR else "\033[1;38;5;39m"
ORANGE = "" if NO_COLOR else "\033[38;5;208m"

# State & Config
STATE_DIR = Path(os.environ.get("ECLIPSE_BRIDGE_STATE", "/root/.local/state/eclipse-chat-bridge"))
WATCH_SCRIPT = Path(__file__).resolve().parent / "watch.py"
DEFAULT_DOC_ID = os.environ.get("ECLIPSE_DOC_ID", "")

# Telemetry Wave & Spinner Glyphs
WAVE_GLYPHS = (" ", "▂", "▃", "▄", "▅", "▆", "▇", "█")
SPINNERS = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
BEACON_ICONS = ("●", "◈", "○", "✦")

# Terminal State Safety
_ORIGINAL_TERMIOS = None
_ALT_SCREEN_ACTIVE = False
UI_VIEW = 0
UI_SCROLL = 0


def restore_terminal():
    """Ensure cursor is visible and terminal is returned to normal mode."""
    global _ALT_SCREEN_ACTIVE
    if _ALT_SCREEN_ACTIVE:
        sys.stdout.write("\033[?1049l")
        _ALT_SCREEN_ACTIVE = False
    sys.stdout.write("\033[?25h\033[?7h\033[0m")
    sys.stdout.flush()
    if _ORIGINAL_TERMIOS is not None:
        try:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, _ORIGINAL_TERMIOS)
        except Exception:
            pass


atexit.register(restore_terminal)


def enter_screen():
    global _ALT_SCREEN_ACTIVE
    if not _ALT_SCREEN_ACTIVE and sys.stdout.isatty():
        sys.stdout.write("\033[?1049h")
        _ALT_SCREEN_ACTIVE = True


def navigation_key(ch):
    global UI_VIEW, UI_SCROLL
    if ch in '12345':
        UI_VIEW, UI_SCROLL = int(ch) - 1, 0
    elif ch == '\t':
        UI_VIEW, UI_SCROLL = (UI_VIEW + 1) % 5, 0
    elif ch in ('j', 'J', 'k', 'K'):
        UI_SCROLL = max(0, UI_SCROLL + (1 if ch.lower() == 'j' else -1))
    else:
        return False
    return True


def signal_handler(sig, frame):
    restore_terminal()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def get_terminal_dimensions() -> tuple[int, int]:
    # Read the live TTY first: COLUMNS/LINES may be stale after rotation or split-screen.
    for stream in (sys.stdout, sys.stdin):
        try:
            if stream.isatty():
                size = os.get_terminal_size(stream.fileno())
                return size.columns, size.lines
        except (OSError, AttributeError, ValueError):
            pass
    try:
        size = shutil.get_terminal_size((80, 24))
        return size.columns, size.lines
    except Exception:
        return 80, 24


def get_bridge_state() -> dict:
    from bridge_ui_state import read_state
    return read_state(STATE_DIR, WATCH_SCRIPT, DEFAULT_DOC_ID,
                      os.environ.get('ECLIPSE_GEMINI_DOC_ID', ''))


def generate_telemetry_wave(frame: int, width: int = 32, active: bool = True) -> str:
    """Generate dynamic oscillating quantum wave spectrum with multi-phase harmonics."""
    if width <= 8:
        return ""
    wave = []
    freq = 0.28 if active else 0.12
    speed = 0.35 if active else 0.10
    for i in range(width):
        v = (math.sin(i * freq - frame * speed) + 1.0) / 2.0
        # Add secondary harmonic modulation for fluid liquid effect
        v = 0.65 * v + 0.35 * ((math.sin(i * 0.55 + frame * 0.18) + 1.0) / 2.0)
        idx = max(0, min(len(WAVE_GLYPHS) - 1, int(v * len(WAVE_GLYPHS))))
        char = WAVE_GLYPHS[idx]
        if idx >= 6:
            wave.append(f"{CYAN}{char}{RESET}")
        elif idx >= 4:
            wave.append(f"{ICE}{char}{RESET}")
        elif idx >= 2:
            wave.append(f"{BLUE}{char}{RESET}")
        else:
            wave.append(f"{MUTED}{char}{RESET}")
    return "".join(wave)


def render_bridge_scene(frame: int, cols: int = 80, lines: int = 24, is_active: bool = False) -> list[str]:
    """Render a responsive, physically modeled suspension bridge with moving bidirectional traffic."""
    # Chromatic title wave
    title_colors = [CYAN, ICE, WHITE, CYAN, BLUE, PURPLE]
    logo_col = title_colors[(frame // 4) % len(title_colors)]

    # Tower beacon lights (Pulsating 4-phase alternating frequency)
    b_idx_l = (frame // 3) % len(BEACON_ICONS)
    b_idx_r = (frame // 3 + 2) % len(BEACON_ICONS)
    beacon_l = f"{CYAN}{BEACON_ICONS[b_idx_l]}{RESET}"
    beacon_r = f"{PURPLE}{BEACON_ICONS[b_idx_r]}{RESET}"

    # Spark discharge effects near towers
    spark_l = f"{GOLD}⚡{RESET}" if (is_active and (frame % 4 == 0)) else " "
    spark_r = f"{GOLD}✦{RESET}" if (is_active and (frame % 4 == 2)) else " "

    # 1. Compact View: Narrow width (< 74 cols) or short height (< 26 rows)
    if cols < 74 or lines < 26:
        span_len = max(8, min(24, cols - 38))
        cable = ["·"] * span_len
        # Downlink packet (Docs -> Termux)
        p_down = (frame * 2) % span_len
        cable[p_down] = f"{CYAN}▶{RESET}"
        # Uplink packet (Termux -> Docs)
        p_up = (span_len - 1) - ((frame * 2) % span_len)
        if p_up != p_down:
            cable[p_up] = f"{PURPLE}◀{RESET}"
        span_str = "".join(cable)
        wave_str = generate_telemetry_wave(frame, width=span_len, active=is_active)

        return [
            f" {logo_col}{BOLD}█▀▄ █▀▄ ▀█▀ █▀▄ █▀▀ █▀▀{RESET}  {WHITE}{BOLD}ECLIPSE CHAT BRIDGE{RESET}",
            f" {logo_col}{BOLD}█▀▄ █▀▄  █  █ █ █ █ █▀▀{RESET}  {ICE}Quantum Conduit v2.5{RESET}",
            f" {logo_col}{BOLD}▀▀  ▀ ▀ ▀▀▀ ▀▀  ▀▀▀ ▀▀▀{RESET}  {MUTED}Google Docs API ⇄ Local Termux{RESET}",
            f"  {YELLOW}☁ [DOCS]{RESET} ═[{span_str}]═ {GREEN}📱[TERMUX]{RESET} {spark_l}",
            f"  {MUTED}Wave:{RESET} [{wave_str}]",
        ]

    # 2. Full High-Fidelity Suspension Bridge (>= 74 cols and >= 26 rows)
    span_width = max(24, min(38, cols - 44))
    
    # Top Cable: Downlink (Docs -> Termux) - Left to Right with trailing glow
    c1 = ["·"] * span_width
    pos_d1 = (frame * 2) % span_width
    pos_d2 = (frame * 2 + span_width // 2) % span_width
    c1[pos_d1] = f"{CYAN}▶{RESET}"
    c1[(pos_d1 + 1) % span_width] = f"{YELLOW}⚡{RESET}"
    c1[pos_d2] = f"{ICE}◈{RESET}"
    cable_down = "".join(c1)

    # Bottom Cable: Uplink (Termux -> Docs) - Right to Left with neon trail
    c2 = ["·"] * span_width
    pos_u1 = (span_width - 1) - ((frame * 2) % span_width)
    pos_u2 = (span_width - 1) - ((frame * 2 + span_width // 2) % span_width)
    c2[pos_u1] = f"{PURPLE}◀{RESET}"
    c2[(pos_u1 - 1 + span_width) % span_width] = f"{MAGENTA}★{RESET}"
    c2[pos_u2] = f"{ORANGE}◄{RESET}"
    cable_up = "".join(c2)

    # Telemetry wave centered under deck
    telemetry = generate_telemetry_wave(frame, width=span_width, active=is_active)
    
    # Kinetic Bridge Deck: moving traffic markers
    deck_chars = list("═" * span_width)
    deck_traffic = (frame * 3) % span_width
    deck_chars[deck_traffic] = "⟐"
    bridge_deck = "".join(deck_chars)

    scene = [
        f" {logo_col}{BOLD}██████╗ ██████╗ ██╗██████╗  ██████╗ ███████╗{RESET}  {WHITE}{BOLD}ECLIPSE CHAT BRIDGE{RESET}",
        f" {logo_col}{BOLD}██╔══██╗██╔══██╗██║██╔══██╗██╔════╝ ██╔════╝{RESET}  {ICE}Quantum Execution Conduit v2.5{RESET}",
        f" {logo_col}{BOLD}██████╔╝██████╔╝██║██║  ██║██║  ███╗█████╗  {RESET}  {MUTED}Continuous Docs API ⇄ Termux Pipeline{RESET}",
        f" {logo_col}{BOLD}██╔══██╗██╔══██╗██║██║  ██║██║   ██║██╔══╝  {RESET}",
        f" {logo_col}{BOLD}██████╔╝██║  ██║██║██████╔╝╚██████╔╝███████╗{RESET}",
        f" {logo_col}{BOLD}╚═════╝ ╚═╝  ╚═╝╚═╝╚═════╝  ╚═════╝ ╚══════╝{RESET}",
        f"       {YELLOW}☁ [ GOOGLE DOCS ]{RESET}              {GREEN}📱 [ LOCAL TERMUX ]{RESET}",
        f"              │                                  │",
        f"        /│   {spark_l}│({beacon_l})   /│                  │\\   ({beacon_r})│{spark_r}   │\\",
        f"       / │   /═══\\  / │  {CYAN}▼ Down:{RESET} [{cable_down}]  │ \\  /═══\\   │ \\",
        f"      /  │══/     \\/  │  {PURPLE}▲ Uplk:{RESET} [{cable_up}]  │  \\/     \\══│  \\",
        f"     /___│_/_______\\__│══════[{bridge_deck}]══════│__/_______\\_│___\\",
        f"   {ICE}[══════════════════]{RESET}   {MUTED}Wave:{RESET} [{telemetry}]   {ICE}[══════════════════]{RESET}",
    ]
    return scene


def build_dashboard_lines(state: dict, frame: int = 0, flash_message: str = "") -> list[str]:
    """Generate all dashboard lines for atomic single-pass double-buffered rendering."""
    cols, lines = get_terminal_dimensions()
    out: list[str] = []

    # 1. Header & Animated Kinetic Bridge Scene
    is_active = (state.get("running_tasks", 0) > 0) or state.get("running", False)
    scene_lines = render_bridge_scene(frame, cols, lines, is_active=is_active)
    out.extend(scene_lines)
    out.append("")

    # 2. Status & Pipeline Card
    spinner = SPINNERS[frame % len(SPINNERS)]
    if state["running"]:
        status_badge = f"{GREEN}{BOLD}● ACTIVE{RESET} {MUTED}(PID: {state['pid']}){RESET} {CYAN}{spinner}{RESET}"
        pulse_indicator = f"{GREEN}{BOLD}POLLING 5s (REVISION SYNC){RESET} {ICE}{spinner}{RESET}"
    else:
        status_badge = f"{RED}{BOLD}○ STOPPED{RESET} {MUTED}(Daemon offline){RESET}"
        pulse_indicator = f"{RED}DAEMON STOPPED{RESET}"

    box_w = max(40, min(cols - 4, 76))
    bar_sep = "─" * box_w
    out.append(f" {CYAN}┌{bar_sep}┐{RESET}")
    out.append(f" {CYAN}│{RESET} {BOLD}Daemon State:{RESET}   {status_badge}  {MUTED}│{RESET} {BOLD}Telemetry:{RESET} {pulse_indicator}")
    
    # Doc URL truncated gracefully
    doc_display = f"https://docs.google.com/document/d/{state['doc_id']}/edit"
    if len(doc_display) > box_w - 18:
        doc_display = doc_display[:box_w - 21] + "..."
    out.append(f" {CYAN}│{RESET} {BOLD}Sync Channel:{RESET}   {CYAN}{doc_display}{RESET}")

    metrics_str = f"{GREEN}{state['completed']} Completed{RESET}  {YELLOW}{state['running_tasks']} In-Flight{RESET}  {RED}{state['errors']} Errors{RESET} {MUTED}(Total: {state['total']}){RESET}"
    out.append(f" {CYAN}│{RESET} {BOLD}Throughput:{RESET}     {metrics_str}")
    out.append(f" {CYAN}└{bar_sep}┘{RESET}")
    out.append("")

    # 3. Recent Execution Receipts (only show if height permits)
    remaining_lines = lines - len(out) - 7
    if remaining_lines >= 3:
        out.append(f" {BOLD}{WHITE}Recent Execution Receipts:{RESET}")
        reqs = state.get("requests", {})
        count = min(remaining_lines - 1, 4)
        keys = list(reqs.keys())[-count:] if count > 0 else []
        if keys:
            for k in reversed(keys):
                st = reqs[k].get("status", "unknown")
                if st == "completed":
                    badge = f"{GREEN}✓ completed{RESET}"
                elif st == "running":
                    badge = f"{YELLOW}⚡ running {spinner}{RESET}"
                elif st == "declined":
                    badge = f"{MUTED}⊘ declined{RESET}"
                else:
                    badge = f"{RED}✗ error{RESET}"
                avail_w = max(20, box_w - 22)
                disp_k = k if len(k) <= avail_w else k[:avail_w - 3] + "..."
                out.append(f"   {CYAN}•{RESET} {BOLD}{disp_k:<{avail_w}}{RESET} {badge}")
        else:
            out.append(f"   {MUTED}No requests recorded yet.{RESET}")
        out.append("")

    # Flash Message if active
    if flash_message:
        out.append(f"  {flash_message}")
        out.append("")

    # 4. Animated Action Control Bar
    dots = ("● ○ ○", "○ ● ○", "○ ○ ●", "○ ● ○")[(frame // 3) % 4]
    out.append(f" {CYAN}{BOLD}{'═' * box_w}{RESET}")
    out.append(f"  {BOLD}[S]{RESET} Status Details    {BOLD}[R]{RESET} Restart Daemon    {BOLD}[L]{RESET} Follow Logs")
    out.append(f"  {BOLD}[A]{RESET} Start Daemon      {BOLD}[T]{RESET} Stop Daemon       {BOLD}[U]{RESET} Run Tests")
    out.append(f"  {BOLD}[O]{RESET} Single Poll Once  {BOLD}[M]{RESET} Pure Monitor      {BOLD}[Q]{RESET} Quit / Exit")
    out.append(f" {CYAN}{BOLD}{'═' * box_w}{RESET}")
    out.append(f" {YELLOW}⚡ [LIVE CONSOLE]{RESET} {BOLD}Tap any hotkey to execute immediately{RESET}  {ICE}{dots}{RESET}")

    return out



# ECLIPSE_RENDERER_V2_START: dashboard-only overlay; the original renderer remains above.
_bridge_build_dashboard_lines_legacy = build_dashboard_lines

def build_dashboard_lines(state, frame, flash_message=''):
    """Responsive operations dashboard backed by existing bridge state.

    This only formats information and never controls the bridge service.
    """
    import datetime as _datetime
    import re as _re
    try:
        columns, rows = get_terminal_dimensions()
        width = max(42, min(112, int(columns or 90)))
        height = max(15, int(rows or 30))
        data = state if isinstance(state, dict) else {}
        shade = ['◴', '◷', '◶', '◵'][int(frame or 0) % 4]
        active = data.get('running') is True
        if data.get('running') is False:
            status = 'STOPPED'
        elif active:
            status = 'RUNNING'
        else:
            status = 'UNKNOWN'
        clean = lambda s: _re.sub(r'[\x00-\x1f\x7f\x1b]', ' ', str(s))
        inner = width - 4
        result = []
        def border(left, middle, right):
            result.append(left + ('─' * (width - 2)) + right)
        def row(value='', emphasis=''):
            text = clean(value)
            if len(text) > inner:
                text = text[:max(0, inner - 1)] + '…'
            line = '│ ' + text.ljust(inner) + ' │'
            if emphasis:
                line = '\x1b[' + emphasis + 'm' + line + '\x1b[0m'
            result.append(line)
        def section(text):
            result.append('├' + ('─' * (width - 2)) + '┤')
            row(' ' + text.upper(), '1;36')
        def val(*names, default='—'):
            for name in names:
                x = data.get(name)
                if x is not None and x != '' and not isinstance(x, (dict, list)):
                    return clean(x)
            return default
        def line(label, value):
            row('  ' + str(label).ljust(19) + ' ' + str(value))
        pid = val('pid', default='—')
        total = data.get('total')
        completed = data.get('completed')
        remaining = data.get('remaining')
        if remaining is None and isinstance(total, int) and isinstance(completed, int):
            remaining = max(0, total - completed)
        pending = val('pending', 'queued', default='—')
        task = val('task_id', 'active_task', 'task', 'current_task', default='No task ID in bridge status')
        running_tasks = data.get('running_tasks')
        if task == 'No task ID in bridge status' and isinstance(running_tasks, (int, list, tuple)):
            task = str(len(running_tasks) if isinstance(running_tasks, (list, tuple)) else running_tasks) + ' currently running'
        phase = val('phase', 'current_phase', 'state', default='—')
        attempt = val('attempt', 'attempt_count', default='—')
        if isinstance(total, int) and total > 0 and isinstance(completed, int):
            ratio = max(0, min(1, completed / total))
            fill = int(round(ratio * 24))
            progress = ('█' * fill) + ('░' * (24 - fill))
            pct = f'{ratio * 100:.1f}%'
        else:
            progress = '─' * 24
            pct = 'n/a'
        border('╭', '─', '╮')
        row('  E C L I P S E   /   B R I D G E', '1;96')
        row('  ECLIPSE CHAT BRIDGE    •    LIVE OPERATIONS MONITOR')
        row('  ' + shade + '  ' + _datetime.datetime.now().strftime('%Y-%m-%d  %H:%M:%S') + '    READ-ONLY VIEW')
        section('01 / Service health')
        row(f'  SERVICE  {status:<12}     PID  {pid:<9}      MONITOR  LIVE', '1;92' if active else '1;93')
        row('  State reflects the installed bridge watcher; no restart or action is issued')
        section('02 / Request processing')
        row(f'  [{progress}]   {pct} complete')
        row(f'  TOTAL   {val("total"):<8}  COMPLETED   {val("completed"):<8}  REMAINING   {remaining if remaining is not None else "—"}')
        row(f'  ACTIVE  {str(running_tasks if isinstance(running_tasks, int) else len(running_tasks) if isinstance(running_tasks, (list, tuple)) else "—"):<8}  ERRORS      {val("errors", "failed", default="—")}')
        section('03 / Active ECLIPSE work')
        line('Task ID', task)
        row('  Phase  ' + phase + '    Attempt  ' + attempt)
        # Present only fields actually reported by the bridge; never invent task status.
        details = []
        denied = ('token', 'secret', 'password', 'cookie', 'credential', 'key')
        visible = {'mode', 'last_request', 'last_result', 'last_status', 'message', 'supervisor', 'watcher_count', 'latest_request', 'last_activity', 'queue_depth'}
        for key in visible:
            if any(word in key.lower() for word in denied):
                continue
            value = data.get(key)
            if value is not None and not isinstance(value, (dict, list)):
                details.append((key, value))
        if details and height >= 29:
            section('04 / Additional diagnostics')
            for key, value in sorted(details)[:4]:
                line(key.replace('_', ' ').title(), value)
        if flash_message:
            section('Notice')
            row('  ' + clean(flash_message), '1;93')
        result.append('├' + ('─' * (width - 2)) + '┤')
        row('  Ctrl+C exit view  •  BRIDGE menu: controls  •  BRIDGE doctor: diagnostics', '2;37')
        result.append('╰' + ('─' * (width - 2)) + '╯')
        # The renderer owns its own layout, and avoids scrolling off short terminals.
        if len(result) > height:
            result = result[:max(3, height - 2)] + result[-2:]
        return result
    except Exception:
        return _bridge_build_dashboard_lines_legacy(state, frame, flash_message)
# ECLIPSE_RENDERER_V2_END


# ECLIPSE_ORBITAL_RESTORE_V1: classic animated dashboard is the default.
# The V2 overview stays available through BRIDGE_UI_STYLE=compact and as
# a bounded-terminal fallback. This changes presentation only.
_bridge_build_dashboard_lines_compact = build_dashboard_lines



# ECLIPSE_ADAPTIVE_RICH_V3 — animated, width-aware, read-only live dashboard.
# CLI status is cached: never sends provider prompts or restarts the watcher.
_bridge_v3_cache = {'at':0.0,'data':{}}

def _bridge_v3_status():
    import time, subprocess, json, sys
    now=time.monotonic()
    if now-_bridge_v3_cache['at'] < 5.0:
        return _bridge_v3_cache['data']
    _bridge_v3_cache['at']=now
    try:
        cmd=[sys.executable,'/root/projects/eclipse-chat-bridge/bridge.py','status','--json']
        p=subprocess.run(cmd,capture_output=True,text=True,timeout=2)
        data=json.loads(p.stdout) if p.returncode==0 else {}
        if not isinstance(data,dict): data={}
        _bridge_v3_cache['data']=data
    except Exception:
        pass
    return _bridge_v3_cache['data']

def _bridge_v3_scalar(value,missing='Not exposed'):
    if value is None or value=='':
        return missing
    if isinstance(value,bool):return 'YES' if value else 'NO'
    if isinstance(value,(list,tuple,set)):return str(len(value))
    if isinstance(value,dict):
        for k in ('status','state','phase','name','id'):
            if value.get(k) is not None:return str(value[k])
        return str(len(value))
    return str(value)

def _bridge_v3_lookup(mapping,*names):
    if not isinstance(mapping,dict):return None
    for k in names:
        v=mapping.get(k)
        if v is not None and v!='':return v
    return None

def _bridge_v3_requests(state):
    req=state.get('requests') if isinstance(state,dict) else {}
    if isinstance(req,dict):
        entries=list(req.items())
    elif isinstance(req,list):
        entries=[(str(i),v) for i,v in enumerate(req)]
    else:
        entries=[]
    recent=[]
    counts={'pending':0,'running':0,'failed':0}
    for key,val in entries:
        body=val if isinstance(val,dict) else {}
        status=_bridge_v3_scalar(_bridge_v3_lookup(body,'status','state'),'unknown').lower()
        if any(k in status for k in ('pending','queued','waiting')):counts['pending']+=1
        elif any(k in status for k in ('running','processing','active')):counts['running']+=1
        elif any(k in status for k in ('failed','error','aborted')):counts['failed']+=1
        ident=str(key).replace('\n',' ')[:30]
        recent.append(ident+' '+status[:16])
    return counts,recent[-8:]

def _bridge_v3_color(line,code='36'):
    return '\x1b['+code+'m'+line+'\x1b[0m'

def _bridge_v3_crop(value,width):
    s=str(value).replace('\r',' ').replace('\n',' ')
    if width<=0:return ''
    return s if len(s)<=width else (s[:width-1]+'…' if width>1 else s[:1])

def _bridge_v3_panel(title,details,width,height,frame):
    width=max(2,int(width))
    if width<10:
        return [_bridge_v3_color(_bridge_v3_crop(title,width).ljust(width),'35') for _ in range(height)]
    interior=width-2
    heading=' '+title.upper()+' '
    heading=_bridge_v3_crop(heading,max(1,interior-1))
    top='╭'+heading+'─'*max(0,interior-len(heading))+'╮'
    body=[]
    capacity=max(0,height-2)
    if not details:details=['No telemetry']
    start=(frame//7)%max(1,len(details))
    if len(details)<=capacity:content=details
    else:content=[details[(start+i)%len(details)] for i in range(capacity)]
    for item in content:
        body.append('│'+(' '+_bridge_v3_crop(item,max(0,interior-2))).ljust(interior)+'│')
    while len(body)<capacity:body.append('│'+' '*interior+'│')
    bottom='╰'+'─'*interior+'╯'
    return [_bridge_v3_color(top,'95')]+[_bridge_v3_color(x,'36') for x in body]+[_bridge_v3_color(bottom,'95')]

def _bridge_v3_wave(width,frame):
    import math
    if width<=0:return ''
    shades='▁▂▃▄▅▆▇█'
    return ''.join(shades[int((math.sin((i+frame*2)*.23)+1)*3.49)] for i in range(width))



# ECLIPSE_CLASSIC_EXECUTION_V4 — restores dense orbital styling with actual code states.
# Presentation only; no changes to the worker, supervisor, queue, or CLI.
def _bridge_v4_entries(state):
    req=state.get('requests') or {}
    if isinstance(req,dict):pairs=list(req.items())
    elif isinstance(req,list):pairs=[(str(i),r) for i,r in enumerate(req)]
    else:pairs=[]
    latest=[]
    for ident,rec in reversed(pairs):
        value=rec if isinstance(rec,dict) else {}
        raw=str(value.get('status','unknown')).lower()
        if any(t in raw for t in ('running','processing','executing','in_progress','started')):
            label='RUNNING';color='96';symbol='◐'
        elif any(t in raw for t in ('complete','success','done','finished','passed','ok')):
            label='COMPLETED';color='92';symbol='✓'
        elif 'interrupt' in raw:
            label='INTERRUPTED';color='93';symbol='!'
        elif any(t in raw for t in ('fail','error','abort','timeout','cancel')):
            label='FAILED';color='91';symbol='✕'
        elif any(t in raw for t in ('queued','pending','waiting','hold')):
            label='QUEUED';color='93';symbol='◌'
        else:
            label='UNKNOWN';color='90';symbol='·'
        latest.append((str(ident).replace('\n',' ').replace('\r',' '),label,color,symbol))
    return latest

def _bridge_v4_statusline(current,finished,total,frame):
    glyph='◐◓◑◒'[frame%4]
    if current:
        return glyph+' RUNNING  '+current[0]
    if finished:
        return '◉ IDLE  ·  Last finished: '+finished[0]
    return '◉ IDLE  ·  No confirmed code execution'

def _bridge_v4_plain(line):
    import re
    return re.sub(r'\x1b\[[0-9;]*m','',line)

def _bridge_v4_style(text,color='96'):
    return '\x1b['+color+'m'+text+'\x1b[0m'

def _bridge_v4_panel(title,items,w,h,frame,tone='95'):
    w=max(1,int(w));h=max(0,int(h))
    if h==0:return []
    if w<5:return [_bridge_v4_style(_bridge_v3_crop(title,w).ljust(w),tone)]*h
    inside=w-2
    title=' '+title.upper()+' '
    title=_bridge_v3_crop(title,max(1,inside))
    top='┏'+title+'━'*max(0,inside-len(title))+'┓'
    bottom='┗'+'━'*inside+'┛'
    if h==1:return [_bridge_v4_style(_bridge_v3_crop(top,w),tone)]
    out=[_bridge_v4_style(top,tone)]
    usable=max(0,h-2)
    records=list(items) or ['—']
    page=(frame//10)%max(1,len(records))
    selected=records if len(records)<=usable else [records[(page+i)%len(records)] for i in range(usable)]
    for i in range(usable):
        v=selected[i] if i<len(selected) else ''
        plain=_bridge_v3_crop(' '+str(v),inside)
        out.append(_bridge_v4_style('┃'+plain.ljust(inside)+'┃','36'))
    out.append(_bridge_v4_style(bottom,tone))
    return out

def _bridge_v4_row(items,cols,width,height,frame):
    if cols==2:
        w1=(width-1)//2;w2=width-w1-1
        left=_bridge_v4_panel(items[0][0],items[0][1],w1,height,frame,items[0][2])
        right=_bridge_v4_panel(items[1][0],items[1][1],w2,height,frame,items[1][2])
        return [l+' '+r for l,r in zip(left,right)]
    return _bridge_v4_panel(items[0][0],items[0][1],width,height,frame,items[0][2])

def _bridge_dashboard_classic(state,frame=0,flash_message=''):
    import math
    state=state if isinstance(state,dict) else {}
    w,h=get_terminal_dimensions()  # read EACH redraw for live Termux resizing
    w=max(1,int(w));h=max(1,int(h))
    status=_bridge_v3_status()
    entries=_bridge_v4_entries(state)
    confirmed_running=state.get('running_tasks') or 0
    try:confirmed_running=int(confirmed_running)
    except (TypeError,ValueError):confirmed_running=0
    current=next((x for x in entries if x[1]=='RUNNING'),None) if confirmed_running>0 else None
    waiting=next((x for x in entries if x[1]=='QUEUED'),None)
    finished=next((x for x in entries if x[1] in ('COMPLETED','FAILED','INTERRUPTED')),None)
    code_status='RUNNING' if current else ('QUEUED' if waiting else 'IDLE')
    active=current or waiting
    exec_line=_bridge_v4_statusline(current,finished,len(entries),frame)
    if not current and waiting:
        exec_line='◌ QUEUED  '+waiting[0]
    lastline=(('✓ ' if finished[1]=='COMPLETED' else '! ')+finished[1]+'  '+finished[0]) if finished else 'Last finished: none recorded'
    service=_bridge_v3_scalar(status.get('service'),'UNAVAILABLE')
    supervisor=_bridge_v3_scalar(status.get('supervisor'),'UNAVAILABLE')
    watcher=_bridge_v3_scalar(status.get('watcher_count'),'—')
    heartbeat=_bridge_v3_scalar(status.get('heartbeat_age_s'),'—')
    recovery=_bridge_v3_scalar(status.get('recoveries'),'—')
    completed=_bridge_v3_scalar(state.get('completed',0),'0')
    total=_bridge_v3_scalar(state.get('total',0),'0')
    errors=_bridge_v3_scalar(state.get('errors',0),'0')
    requests=state.get('requests') or {}
    last=status.get('last_request')
    if isinstance(last,dict):
        last_id=_bridge_v3_scalar(_bridge_v3_lookup(last,'id','request_id'),'—')
    else:last_id=_bridge_v3_scalar(last,'—')
    spin='◐◓◑◒'[frame%4]
    if w<28 or h<9:
        compact=[spin+'  BRIDGE '+code_status,exec_line,lastline,
                 'Service '+service+' / '+supervisor,
                 'Code '+str(confirmed_running)+' running; '+completed+' done',
                 'Recovery '+recovery,'Requests '+str(len(entries))]
        if flash_message:compact.insert(1,flash_message)
        start=(frame//8)%len(compact)
        return [_bridge_v4_style(_bridge_v3_crop(compact[(start+i)%len(compact)],w).ljust(w),'95' if i==0 else '36') for i in range(min(h,len(compact)))]
    title='  ◈  ECLIPSE BRIDGE  ◆  LIVE OPERATIONS  '+spin
    line='  SERVICE '+service+'   •   SUPERVISOR '+supervisor+'   •   WATCHERS '+watcher
    header=[
        _bridge_v4_style('┏'+'━'*(w-2)+'┓','95'),
        _bridge_v4_style('┃'+_bridge_v3_crop(title,w-2).ljust(w-2)+'┃','95'),
        _bridge_v4_style('┃'+_bridge_v3_crop(line,w-2).ljust(w-2)+'┃','36'),
        _bridge_v4_style('┗'+'━'*(w-2)+'┛','95')]
    room=h-len(header)-1
    if room<=0:return header[:max(0,h-1)]+[_bridge_v4_style(_bridge_v3_crop(flash_message or code_status,w).ljust(w),'96')]
    wave=_bridge_v4_style(_bridge_v3_wave(w,frame),'35')
    meter='◈ Requests '+completed+'/'+total+'   •   Active code '+str(confirmed_running)+'   •   Errors '+errors+'   •   Heartbeat '+heartbeat+'s'
    strips=[wave]
    if h>=22:strips.append(_bridge_v4_style(_bridge_v3_crop(meter,w).ljust(w),'36'))
    maxexec=h-len(header)-len(strips)-1
    eh=min(6,max(3,maxexec//3)) if maxexec>=3 else max(0,maxexec)
    exec_items=[exec_line,lastline]
    if waiting and current:exec_items.append('◌ Queued '+waiting[0])
    exec_items.append('◈ Running '+str(confirmed_running)+'  •  Completed '+completed+'  •  Errors '+errors)
    exec_panel=_bridge_v4_panel('CODE EXECUTION  /  '+code_status,exec_items,w,eh,frame,'92' if current is None and finished else '96')
    used=len(header)+len(strips)+len(exec_panel)+1
    avail=h-used
    task_data=_bridge_v3_lookup(state,'task','active_task')
    if task_data is None:task_data=_bridge_v3_lookup(status,'task','active_task')
    taskinfo=task_data if isinstance(task_data,dict) else {}
    taskname=_bridge_v3_scalar(_bridge_v3_lookup(taskinfo,'name','id','task_id'),_bridge_v3_scalar(task_data,'Not linked'))
    phase=_bridge_v3_scalar(_bridge_v3_lookup(taskinfo,'phase','stage'))
    attempt=_bridge_v3_scalar(_bridge_v3_lookup(taskinfo,'attempt','attempt_number'))
    pending=_bridge_v3_scalar(_bridge_v3_lookup(taskinfo,'pending','pending_request'))
    panels=[
      ('EXECUTION HISTORY',[x[3]+' '+x[1]+'  '+x[0] for x in entries[:7]] or ['No execution records'],'96'),
      ('RUNNER + SUPERVISOR',['Service  '+service,'Supervisor  '+supervisor,'Watchers  '+watcher,'Heartbeat  '+heartbeat+'s'],'95'),
      ('ECLIPSE TASK',['Task  '+taskname,'Phase  '+phase,'Attempt  '+attempt,'Pending  '+pending],'35'),
      ('RECOVERY + HEALTH',['Recoveries  '+recovery,'Errors  '+errors,'Last request  '+last_id],'93'),
      ('REQUEST METRICS',['Completed  '+completed+'/'+total,'Running  '+str(confirmed_running),'Total records  '+str(len(entries))],'96'),
      ('TRANSPORT + CONTROLS',['Docs link  '+_bridge_v3_scalar(state.get('doc_id'),'configured'),'BRIDGE menu  |  status  |  logs','BRIDGE doctor  |  back  |  exit'],'95')
    ]
    cols=2 if w>=88 else 1
    minheight=4 if avail>=8 else 3
    maxrows=max(0,avail//minheight)
    slots=min(len(panels),maxrows*cols)
    if slots>0:
        if slots<len(panels):
            anchor=(0 if slots==1 else 1 if slots<=2 else 2)
            secondary=panels[anchor:]
            rotation=(frame//12)%max(1,len(secondary))
            panels=panels[:anchor]+[secondary[(rotation+i)%len(secondary)] for i in range(slots-anchor)]
        else:panels=panels[:slots]
    else:panels=[]
    body=[]
    if panels:
        rows=math.ceil(len(panels)/cols)
        ph=min(7,max(minheight,avail//rows))
        for i in range(0,len(panels),cols):
            pair=panels[i:i+cols]
            if cols==2 and len(pair)==1:pair=pair+[('ACTIVITY', ['Live monitoring'], '90')]
            body.extend(_bridge_v4_row(pair,cols,w,ph,frame))
    lines=header+strips+exec_panel+body
    if len(lines)>h-1:lines=lines[:h-1]
    while len(lines)<h-1:lines.append(' '*w)
    foot=flash_message or ('BRIDGE  •  Q to exit  •  Live resize   '+str(w)+'x'+str(h))
    lines.append(_bridge_v4_style(_bridge_v3_crop(foot,w).ljust(w),'95'))
    return lines





def build_dashboard_lines(state, frame=0, flash_message=''):
    """Eclipse orbit presentation; the classic layout remains an opt-in fallback."""
    if os.environ.get('BRIDGE_UI_STYLE') == 'classic':
        return _bridge_dashboard_classic(state, frame, flash_message)
    from bridge_presentation import render
    columns, rows = get_terminal_dimensions()
    return render(state, _bridge_v3_status(), columns, rows, frame, flash_message, page=UI_VIEW, scroll=UI_SCROLL)


def render_dashboard_inplace(state: dict, frame: int = 0, flash_message: str = "") -> None:
    """Render the dashboard using zero-flicker cursor home and line overwrites."""
    lines = build_dashboard_lines(state, frame, flash_message=flash_message)
    # Absolute rows and disabled autowrap also protect a frame resized mid-write.
    buffer = ["\033[H\033[?7l"]
    buffer.extend("\033[" + str(i + 1) + ";1H" + line + "\033[K" for i, line in enumerate(lines))
    buffer.append("\033[J\033[?7h")
    sys.stdout.write("".join(buffer))
    sys.stdout.flush()


def run_live_monitor(duration_seconds: float = 0) -> None:
    """Zero-flicker live animated quantum monitor with 12 FPS refresh."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        render_dashboard_inplace(get_bridge_state())
        return
    global _ORIGINAL_TERMIOS
    start_time = time.monotonic()
    frame = 0

    if sys.stdin.isatty():
        try:
            _ORIGINAL_TERMIOS = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        except Exception:
            pass

    try:
        # Hide cursor and clear once cleanly
        enter_screen()
        sys.stdout.write("\033[?25l\033[2J")
        sys.stdout.flush()
        
        last_state_check = 0.0
        cached_state = get_bridge_state()
        
        while True:
            now = time.monotonic()
            if duration_seconds > 0 and (now - start_time) >= duration_seconds:
                break
                
            # Non-blocking keypress check (instant exit on any key)
            if sys.stdin.isatty():
                r, _, _ = select.select([sys.stdin], [], [], 0)
                if r:
                    ch = sys.stdin.read(1)
                    if ch in ('q', 'Q', '\x03', '\x1b'):
                        break
                    navigation_key(ch)

            # Poll real disk state every 1.5 seconds
            if now - last_state_check > 1.5:
                cached_state = get_bridge_state()
                last_state_check = now

            render_dashboard_inplace(cached_state, frame)

            frame += 1
            time.sleep(0.5 if os.environ.get('BRIDGE_UI_REDUCED_MOTION') == '1' else 0.08)

    except KeyboardInterrupt:
        pass
    finally:
        restore_terminal()


def play_startup_sequence():
    """Buttery-smooth startup animation (8 frames at 40ms) with zero flicker."""
    if not sys.stdout.isatty():
        return
    try:
        enter_screen()
        sys.stdout.write("\033[?25l\033[2J")
        sys.stdout.flush()
        state = get_bridge_state()
        for f in range(8):
            render_dashboard_inplace(state, f)
            time.sleep(0.04)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()


def interactive_menu_loop():
    """Live kinetic animated dashboard with instant non-blocking hotkey dispatch."""
    global _ORIGINAL_TERMIOS

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        state = get_bridge_state()
        render_dashboard_inplace(state, frame=0)
        return

    play_startup_sequence()

    try:
        _ORIGINAL_TERMIOS = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())
    except Exception:
        pass

    try:
        # Hide cursor and clear once cleanly
        enter_screen()
        sys.stdout.write("\033[?25l\033[2J")
        sys.stdout.flush()

        frame = 0
        last_state_poll = 0.0
        cached_state = get_bridge_state()
        flash_message = ""
        flash_until = 0.0

        bridge_bin = "/root/projects/eclipse-chat-bridge/bin/eclipse-bridge"

        while True:
            now = time.monotonic()

            # Non-blocking hotkey check
            if sys.stdin.isatty():
                r, _, _ = select.select([sys.stdin], [], [], 0)
                if r:
                    ch = sys.stdin.read(1)
                    if ch in ("\x03", "\x1b", "q", "Q"):  # Ctrl+C, Esc, Q
                        break
                    elif navigation_key(ch):
                        pass
                    elif ch in ("s", "S"):
                        restore_terminal()
                        print(f"\n{CYAN}{BOLD}=== ECLIPSE CHAT BRIDGE STATUS ==={RESET}")
                        subprocess.run([bridge_bin, "status"])
                        print(f"\n{MUTED}Resuming animated bridge in 2.5s (or press any key)...{RESET}")
                        if sys.stdin.isatty():
                            select.select([sys.stdin], [], [], 2.5)
                            if select.select([sys.stdin], [], [], 0)[0]:
                                sys.stdin.read(1)
                        try:
                            _ORIGINAL_TERMIOS = termios.tcgetattr(sys.stdin)
                            tty.setcbreak(sys.stdin.fileno())
                        except Exception:
                            pass
                        enter_screen()
                        sys.stdout.write("\033[?25l\033[2J")
                        sys.stdout.flush()
                        cached_state = get_bridge_state()
                    elif ch in ("r", "R"):
                        restore_terminal()
                        print(f"\n{YELLOW}{BOLD}⟳ Restarting ECLIPSE Chat Bridge daemon...{RESET}")
                        subprocess.run([bridge_bin, "restart"])
                        time.sleep(1)
                        try:
                            _ORIGINAL_TERMIOS = termios.tcgetattr(sys.stdin)
                            tty.setcbreak(sys.stdin.fileno())
                        except Exception:
                            pass
                        enter_screen()
                        sys.stdout.write("\033[?25l\033[2J")
                        sys.stdout.flush()
                        cached_state = get_bridge_state()
                        flash_message = f"{GREEN}✓ Daemon restarted successfully (PID: {cached_state.get('pid')}){RESET}"
                        flash_until = time.monotonic() + 3.0
                    elif ch in ("a", "A"):
                        restore_terminal()
                        print(f"\n{GREEN}{BOLD}▶ Starting ECLIPSE Chat Bridge daemon...{RESET}")
                        subprocess.run([bridge_bin, "start"])
                        time.sleep(1)
                        try:
                            _ORIGINAL_TERMIOS = termios.tcgetattr(sys.stdin)
                            tty.setcbreak(sys.stdin.fileno())
                        except Exception:
                            pass
                        enter_screen()
                        sys.stdout.write("\033[?25l\033[2J")
                        sys.stdout.flush()
                        cached_state = get_bridge_state()
                        flash_message = f"{GREEN}✓ Daemon started{RESET}"
                        flash_until = time.monotonic() + 3.0
                    elif ch in ("t", "T"):
                        restore_terminal()
                        print(f"\n{RED}{BOLD}■ Stopping ECLIPSE Chat Bridge daemon...{RESET}")
                        subprocess.run([bridge_bin, "stop"])
                        time.sleep(1)
                        try:
                            _ORIGINAL_TERMIOS = termios.tcgetattr(sys.stdin)
                            tty.setcbreak(sys.stdin.fileno())
                        except Exception:
                            pass
                        enter_screen()
                        sys.stdout.write("\033[?25l\033[2J")
                        sys.stdout.flush()
                        cached_state = get_bridge_state()
                        flash_message = f"{RED}○ Daemon stopped{RESET}"
                        flash_until = time.monotonic() + 3.0
                    elif ch in ("l", "L"):
                        restore_terminal()
                        print(f"\n{CYAN}{BOLD}Opening live bridge logs (Press Ctrl+C to return)...{RESET}")
                        subprocess.run([bridge_bin, "logs", "-f"])
                        try:
                            _ORIGINAL_TERMIOS = termios.tcgetattr(sys.stdin)
                            tty.setcbreak(sys.stdin.fileno())
                        except Exception:
                            pass
                        enter_screen()
                        sys.stdout.write("\033[?25l\033[2J")
                        sys.stdout.flush()
                        cached_state = get_bridge_state()
                    elif ch in ("o", "O"):
                        restore_terminal()
                        print(f"\n{CYAN}{BOLD}Running single poll iteration...{RESET}")
                        subprocess.run([bridge_bin, "once"])
                        time.sleep(1)
                        try:
                            _ORIGINAL_TERMIOS = termios.tcgetattr(sys.stdin)
                            tty.setcbreak(sys.stdin.fileno())
                        except Exception:
                            pass
                        enter_screen()
                        sys.stdout.write("\033[?25l\033[2J")
                        sys.stdout.flush()
                        cached_state = get_bridge_state()
                        flash_message = f"{CYAN}✓ Single poll completed{RESET}"
                        flash_until = time.monotonic() + 3.0
                    elif ch in ("m", "M"):
                        run_live_monitor()
                        try:
                            _ORIGINAL_TERMIOS = termios.tcgetattr(sys.stdin)
                            tty.setcbreak(sys.stdin.fileno())
                        except Exception:
                            pass
                        enter_screen()
                        sys.stdout.write("\033[?25l\033[2J")
                        sys.stdout.flush()
                        cached_state = get_bridge_state()
                    elif ch in ("u", "U"):
                        restore_terminal()
                        print(f"\n{CYAN}{BOLD}Running test suite...{RESET}")
                        subprocess.run([bridge_bin, "test"])
                        print(f"\n{MUTED}Resuming animated bridge in 3s (or press any key)...{RESET}")
                        if sys.stdin.isatty():
                            select.select([sys.stdin], [], [], 3.0)
                            if select.select([sys.stdin], [], [], 0)[0]:
                                sys.stdin.read(1)
                        try:
                            _ORIGINAL_TERMIOS = termios.tcgetattr(sys.stdin)
                            tty.setcbreak(sys.stdin.fileno())
                        except Exception:
                            pass
                        enter_screen()
                        sys.stdout.write("\033[?25l\033[2J")
                        sys.stdout.flush()
                        cached_state = get_bridge_state()

            # Refresh disk state every 1.5s
            if now - last_state_poll > 1.5:
                cached_state = get_bridge_state()
                last_state_poll = now

            active_flash = flash_message if now < flash_until else ""
            render_dashboard_inplace(cached_state, frame=frame, flash_message=active_flash)
            
            frame += 1
            time.sleep(0.5 if os.environ.get('BRIDGE_UI_REDUCED_MOTION') == '1' else 0.08)

    except KeyboardInterrupt:
        pass
    finally:
        restore_terminal()
        print(f"\n{GREEN}Exited ECLIPSE Chat Bridge console.{RESET}")


def main():
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd in ("monitor", "-m", "--monitor"):
            run_live_monitor()
            return
        if cmd in ("anim", "banner"):
            run_live_monitor(duration_seconds=1.5)
            return

    interactive_menu_loop()


if __name__ == "__main__":
    main()
