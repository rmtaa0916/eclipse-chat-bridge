#!/usr/bin/env python3
"""ECLIPSE Chat Bridge — Terminal Presentation & Animation System (v2.0).

Engineered to match ECLIPSE core standards:
- Zero-flicker differential cursor addressing (no subshell clear commands)
- Catenary suspension cable kinematics & bidirectional packet modeling
- Height & width adaptive responsive typography (Mobile portrait to 4K Ultrawide)
- Reactive quantum telemetry wave and tower spark discharges
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
DEFAULT_DOC_ID = os.environ.get("ECLIPSE_DOC_ID", "1N_TYeHUTexHaU2eiZ40hMWsaNNl-GaZJ-6H1MxHPPYM")

# Telemetry Wave glyphs
WAVE_GLYPHS = (" ", "▂", "▃", "▄", "▅", "▆", "▇", "█")

# Terminal State Safety
_ORIGINAL_TERMIOS = None


def restore_terminal():
    """Ensure cursor is visible and terminal is returned to normal mode."""
    sys.stdout.write("\033[?25h\033[0m")
    sys.stdout.flush()
    if _ORIGINAL_TERMIOS is not None:
        try:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, _ORIGINAL_TERMIOS)
        except Exception:
            pass


atexit.register(restore_terminal)


def signal_handler(sig, frame):
    restore_terminal()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def get_terminal_dimensions() -> tuple[int, int]:
    try:
        size = shutil.get_terminal_size((80, 24))
        return size.columns, size.lines
    except Exception:
        return 80, 24


def get_bridge_state() -> dict:
    state_file = STATE_DIR / "requests.json"
    pid_file = STATE_DIR / "watcher.pid"
    
    running_pid = None
    if pid_file.is_file():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            running_pid = pid
        except Exception:
            pass

    if not running_pid:
        try:
            out = subprocess.check_output(["pgrep", "-f", str(WATCH_SCRIPT)], text=True).strip()
            if out:
                running_pid = int(out.split()[0])
                pid_file.write_text(str(running_pid))
        except Exception:
            pass

    requests = {}
    if state_file.is_file():
        try:
            requests = json.loads(state_file.read_text())
        except Exception:
            pass

    completed = sum(1 for v in requests.values() if v.get("status") == "completed")
    running = sum(1 for v in requests.values() if v.get("status") == "running")
    errors = sum(1 for v in requests.values() if v.get("status") == "error")

    return {
        "running": running_pid is not None,
        "pid": running_pid,
        "total": len(requests),
        "completed": completed,
        "running_tasks": running,
        "errors": errors,
        "requests": requests,
        "doc_id": DEFAULT_DOC_ID,
    }


def generate_telemetry_wave(frame: int, width: int = 32, active: bool = True) -> str:
    """Generate dynamic oscillating quantum wave spectrum."""
    if width <= 8:
        return ""
    wave = []
    freq = 0.28 if active else 0.12
    speed = 0.35 if active else 0.10
    for i in range(width):
        v = (math.sin(i * freq - frame * speed) + 1.0) / 2.0
        # Add harmonic modulation
        v = 0.7 * v + 0.3 * ((math.sin(i * 0.6 + frame * 0.15) + 1.0) / 2.0)
        idx = max(0, min(len(WAVE_GLYPHS) - 1, int(v * len(WAVE_GLYPHS))))
        char = WAVE_GLYPHS[idx]
        if idx >= 6:
            wave.append(f"{CYAN}{char}{RESET}")
        elif idx >= 3:
            wave.append(f"{BLUE}{char}{RESET}")
        else:
            wave.append(f"{MUTED}{char}{RESET}")
    return "".join(wave)


def render_bridge_scene(frame: int, cols: int = 80, lines: int = 24, is_active: bool = False) -> list[str]:
    """Render a responsive, physically modeled suspension bridge with bidirectional traffic."""
    # Tower beacon lights (Cyan / Violet alternating frequency)
    beacon_phase = (frame // 3) % 2
    beacon_l = f"{CYAN}●{RESET}" if beacon_phase == 0 else f"{PURPLE}○{RESET}"
    beacon_r = f"{PURPLE}●{RESET}" if beacon_phase == 0 else f"{CYAN}○{RESET}"

    # Spark effect if a task is actively running
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

        return [
            f" {CYAN}{BOLD}█▀▄ █▀▄ ▀█▀ █▀▄ █▀▀ █▀▀{RESET}  {WHITE}{BOLD}ECLIPSE CHAT BRIDGE{RESET}",
            f" {CYAN}{BOLD}█▀▄ █▀▄  █  █ █ █ █ █▀▀{RESET}  {ICE}Quantum Conduit v2.0{RESET}",
            f" {CYAN}{BOLD}▀▀  ▀ ▀ ▀▀▀ ▀▀  ▀▀▀ ▀▀▀{RESET}  {MUTED}Google Docs API ⇄ Local Termux{RESET}",
            f"  {YELLOW}☁ [DOCS]{RESET} ═[{span_str}]═ {GREEN}📱[TERMUX]{RESET} {spark_l}",
        ]

    # 2. Full High-Fidelity Suspension Bridge (>= 74 cols and >= 26 rows)
    span_width = max(24, min(38, cols - 44))
    
    # Top Cable: Downlink (Docs -> Termux) - Left to Right
    c1 = ["·"] * span_width
    pos_d1 = (frame * 2) % span_width
    pos_d2 = (frame * 2 + span_width // 2) % span_width
    c1[pos_d1] = f"{CYAN}▶{RESET}"
    c1[(pos_d1 + 1) % span_width] = f"{YELLOW}⚡{RESET}"
    c1[pos_d2] = f"{ICE}◆{RESET}"
    cable_down = "".join(c1)

    # Bottom Cable: Uplink (Termux -> Docs) - Right to Left
    c2 = ["·"] * span_width
    pos_u1 = (span_width - 1) - ((frame * 2) % span_width)
    pos_u2 = (span_width - 1) - ((frame * 2 + span_width // 2) % span_width)
    c2[pos_u1] = f"{PURPLE}◀{RESET}"
    c2[(pos_u1 - 1 + span_width) % span_width] = f"{MAGENTA}★{RESET}"
    c2[pos_u2] = f"{ORANGE}◄{RESET}"
    cable_up = "".join(c2)

    # Telemetry wave centered under deck
    telemetry = generate_telemetry_wave(frame, width=span_width, active=is_active)
    bridge_deck = "═" * span_width

    logo_col = CYAN
    scene = [
        f" {logo_col}{BOLD}██████╗ ██████╗ ██╗██████╗  ██████╗ ███████╗{RESET}  {WHITE}{BOLD}ECLIPSE CHAT BRIDGE{RESET}",
        f" {logo_col}{BOLD}██╔══██╗██╔══██╗██║██╔══██╗██╔════╝ ██╔════╝{RESET}  {ICE}Quantum Execution Conduit v2.0{RESET}",
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


def build_dashboard_lines(state: dict, frame: int = 0) -> list[str]:
    """Generate all dashboard lines for atomic single-pass double-buffered rendering."""
    cols, lines = get_terminal_dimensions()
    out: list[str] = []

    # 1. Header & Animated Bridge Scene
    is_active = (state.get("running_tasks", 0) > 0) or state.get("running", False)
    scene_lines = render_bridge_scene(frame, cols, lines, is_active=is_active)
    out.extend(scene_lines)
    out.append("")

    # 2. Status & Pipeline Card
    if state["running"]:
        status_badge = f"{GREEN}{BOLD}● ACTIVE{RESET} {MUTED}(PID: {state['pid']}){RESET}"
        pulse_indicator = f"{GREEN}{BOLD}POLLING 5s (REVISION SYNC){RESET}"
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
    remaining_lines = lines - len(out) - 6
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
                    badge = f"{YELLOW}⚡ running{RESET}"
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

    # 4. Action Menu Bar
    out.append(f" {CYAN}{BOLD}{'═' * box_w}{RESET}")
    out.append(f"  {BOLD}[S]{RESET} Status Details    {BOLD}[R]{RESET} Restart Daemon    {BOLD}[M]{RESET} Live Quantum Monitor")
    out.append(f"  {BOLD}[A]{RESET} Start Daemon      {BOLD}[T]{RESET} Stop Daemon       {BOLD}[L]{RESET} Follow Logs")
    out.append(f"  {BOLD}[O]{RESET} Single Poll Once  {BOLD}[U]{RESET} Run Test Suite    {BOLD}[Q]{RESET} Quit / Exit")
    out.append(f" {CYAN}{BOLD}{'═' * box_w}{RESET}")

    return out


def render_dashboard_inplace(state: dict, frame: int = 0) -> None:
    """Render the dashboard using zero-flicker cursor home and line overwrites."""
    lines = build_dashboard_lines(state, frame)
    # Cursor home \033[H, overwrite each line with \033[K (clear to EOL)
    buffer = ["\033[H"]
    for line in lines:
        buffer.append(f"{line}\033[K\n")
    # Clear any residual lines from previous longer frames
    buffer.append("\033[J")
    sys.stdout.write("".join(buffer))
    sys.stdout.flush()


def run_live_monitor(duration_seconds: float = 0) -> None:
    """Zero-flicker live animated quantum monitor with 10 FPS refresh."""
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
                    sys.stdin.read(1)
                    break

            # Poll real disk state every 1.5 seconds
            if now - last_state_check > 1.5:
                cached_state = get_bridge_state()
                last_state_check = now

            render_dashboard_inplace(cached_state, frame)
            sys.stdout.write(f" {YELLOW}⚡ LIVE QUANTUM MONITOR{RESET} • Press {BOLD}[ANY KEY]{RESET} or {BOLD}[Ctrl+C]{RESET} to exit monitor\033[K\n")
            sys.stdout.flush()

            frame += 1
            time.sleep(0.08)

    except KeyboardInterrupt:
        pass
    finally:
        restore_terminal()


def play_startup_sequence():
    """Buttery-smooth startup animation (10 frames at 40ms) with zero flicker."""
    if not sys.stdout.isatty():
        return
    try:
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
    play_startup_sequence()
    
    while True:
        state = get_bridge_state()
        render_dashboard_inplace(state, frame=0)
        
        try:
            choice = input(f" {BOLD}Select Option [S]:{RESET} ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print(f"\n{GREEN}Exiting ECLIPSE Chat Bridge.{RESET}")
            break

        if not choice or choice in ("s", "status"):
            subprocess.run(["/root/projects/eclipse-chat-bridge/bin/eclipse-bridge", "status"])
            input(f"\n{MUTED}Press [ENTER] to return to dashboard...{RESET}")
        elif choice in ("r", "restart"):
            subprocess.run(["/root/projects/eclipse-chat-bridge/bin/eclipse-bridge", "restart"])
            time.sleep(1)
            play_startup_sequence()
        elif choice in ("a", "start"):
            subprocess.run(["/root/projects/eclipse-chat-bridge/bin/eclipse-bridge", "start"])
            time.sleep(1)
            play_startup_sequence()
        elif choice in ("t", "stop"):
            subprocess.run(["/root/projects/eclipse-chat-bridge/bin/eclipse-bridge", "stop"])
            time.sleep(1)
        elif choice in ("m", "monitor"):
            run_live_monitor()
        elif choice in ("l", "logs"):
            subprocess.run(["/root/projects/eclipse-chat-bridge/bin/eclipse-bridge", "logs", "-f"])
        elif choice in ("o", "once"):
            print(f"\n{CYAN}Running single poll iteration...{RESET}")
            subprocess.run(["/root/projects/eclipse-chat-bridge/bin/eclipse-bridge", "once"])
            input(f"\n{MUTED}Press [ENTER] to return to dashboard...{RESET}")
        elif choice in ("u", "test"):
            subprocess.run(["/root/projects/eclipse-chat-bridge/bin/eclipse-bridge", "test"])
            input(f"\n{MUTED}Press [ENTER] to return to dashboard...{RESET}")
        elif choice in ("q", "quit", "exit", "b", "back"):
            print(f"{GREEN}Exiting ECLIPSE Chat Bridge.{RESET}")
            break
        else:
            print(f"{RED}Unknown choice: {choice}{RESET}")
            time.sleep(0.8)


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
