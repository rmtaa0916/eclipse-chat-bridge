#!/usr/bin/env python3
"""ECLIPSE Chat Bridge — Terminal Presentation & Animation System.

Provides animated ASCII art, quantum data pipeline visualization,
and interactive dashboard matching ECLIPSE design standards.
"""

from __future__ import annotations

import curses
import datetime
import json
import math
import os
from pathlib import Path
import re
import select
import shutil
import subprocess
import sys
import termios
import time
import tty

# ANSI Color & Style Palette matching ECLIPSE Standards
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
ITALIC = "\033[3m"

# Colors
CYAN = "\033[1;36m"
ICE = "\033[38;5;123m"
WHITE = "\033[1;38;5;255m"
GREEN = "\033[1;38;5;120m"
YELLOW = "\033[1;38;5;220m"
RED = "\033[1;38;5;203m"
MAGENTA = "\033[1;38;5;213m"
PURPLE = "\033[38;5;141m"
MUTED = "\033[38;5;242m"
BLUE_BG = "\033[48;5;24m"
DARK_BG = "\033[48;5;235m"

# State & Config
STATE_DIR = Path(os.environ.get("ECLIPSE_BRIDGE_STATE", "/root/.local/state/eclipse-chat-bridge"))
WATCH_SCRIPT = Path(__file__).resolve().parent / "watch.py"
DEFAULT_DOC_ID = os.environ.get("ECLIPSE_DOC_ID", "1N_TYeHUTexHaU2eiZ40hMWsaNNl-GaZJ-6H1MxHPPYM")


def get_terminal_width() -> int:
    try:
        return shutil.get_terminal_size((80, 24)).columns
    except Exception:
        return 80


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


def render_bridge_scene(frame: int, width: int = 80) -> list[str]:
    """Render a dynamic ASCII suspension bridge with traveling data packets."""
    phase = frame % 60
    # Beacon light pulsing between Cyan and Purple
    beacon_color = CYAN if (frame // 4) % 2 == 0 else PURPLE
    beacon_char = "●" if (frame // 4) % 2 == 0 else "○"
    
    # Pulse position traveling from 0 to 1 across the bridge
    pulse1 = (frame * 2) % 32
    pulse2 = (frame * 2 + 16) % 32

    if width < 70:
        # Compact mobile view for narrow screens
        cables = list("═══════════════════════")
        p1 = (frame % len(cables))
        p2 = ((frame + len(cables) // 2) % len(cables))
        cables[p1] = "⚡"
        cable_str = "".join(cables)
        
        return [
            f" {CYAN}{BOLD}█▀▄ █▀▄ ▀█▀ █▀▄ █▀▀ █▀▀{RESET}  {WHITE}ECLIPSE CHAT BRIDGE{RESET}",
            f" {CYAN}{BOLD}█▀▄ █▀▄  █  █ █ █ █ █▀▀{RESET}  {MUTED}Google Docs ⇄ Termux{RESET}",
            f" {CYAN}{BOLD}▀▀  ▀ ▀ ▀▀▀ ▀▀  ▀▀▀ ▀▀▀{RESET}",
            f" {YELLOW}☁ [DOCS]{RESET} ═[{beacon_color}{cable_str[:12]}{RESET}]═ {GREEN}📱[TERMUX]{RESET}",
        ]

    # Full wide view (>= 70 cols)
    # 32 characters of bridge span
    span_chars = list("································")
    # Place traveling data packets
    for p, icon, col in [(pulse1, "▶", GREEN), ((pulse1 + 1) % 32, "⚡", YELLOW),
                         (pulse2, "▶", CYAN), ((pulse2 + 1) % 32, "◆", MAGENTA)]:
        if 0 <= p < len(span_chars):
            span_chars[p] = f"{col}{icon}{MUTED}"
    
    span_str = "".join(span_chars)

    logo_col = CYAN
    lines = [
        f" {logo_col}{BOLD}██████╗ ██████╗ ██╗██████╗  ██████╗ ███████╗{RESET}  {WHITE}{BOLD}ECLIPSE CHAT BRIDGE{RESET}",
        f" {logo_col}{BOLD}██╔══██╗██╔══██╗██║██╔══██╗██╔════╝ ██╔════╝{RESET}  {ICE}Autonomous Execution Conduit{RESET}",
        f" {logo_col}{BOLD}██████╔╝██████╔╝██║██║  ██║██║  ███╗█████╗  {RESET}  {MUTED}Google Docs API ⇄ Local Engine{RESET}",
        f" {logo_col}{BOLD}██╔══██╗██╔══██╗██║██║  ██║██║   ██║██╔══╝  {RESET}",
        f" {logo_col}{BOLD}██████╔╝██║  ██║██║██████╔╝╚██████╔╝███████╗{RESET}",
        f" {logo_col}{BOLD}╚═════╝ ╚═╝  ╚═╝╚═╝╚═════╝  ╚═════╝ ╚══════╝{RESET}",
        f"       {YELLOW}☁ [ GOOGLE DOCS ]{RESET}              {GREEN}📱 [ TERMUX / ECLIPSE ]{RESET}",
        f"              │                                  │",
        f"        /│    │{beacon_color}({beacon_char}){RESET}   /│                  │\\   {beacon_color}({beacon_char}){RESET}│    │\\",
        f"       / │   /═══\\  / │  {MUTED}──[{span_str}]──{RESET}  │ \\  /═══\\   │ \\",
        f"      /  │══/     \\/  │======================│  \\/     \\══│  \\",
        f"     /___│_/_______\\__│______________________│__/_______\\_│___\\",
        f"   {ICE}[══════════════════════════════════════════════════════════]{RESET}",
    ]
    return lines


def render_dashboard(state: dict, frame: int = 0) -> None:
    width = get_terminal_width()
    os.system("clear" if os.name != "nt" else "cls")
    
    # Banner
    banner_lines = render_bridge_scene(frame, width)
    for line in banner_lines:
        print(line)
    print("")

    # Status Bar
    if state["running"]:
        status_badge = f"{GREEN}{BOLD}● ACTIVE / RUNNING{RESET} {MUTED}(PID: {state['pid']}){RESET}"
        pulse_indicator = f"{GREEN}POLLING DOCS API (5s){RESET}"
    else:
        status_badge = f"{RED}{BOLD}○ STOPPED{RESET} {MUTED}(Daemon offline){RESET}"
        pulse_indicator = f"{RED}OFFLINE{RESET}"

    box_w = min(width - 2, 76)
    bar_sep = "─" * box_w
    print(f" {CYAN}┌{bar_sep}┐{RESET}")
    print(f" {CYAN}│{RESET} {BOLD}Daemon Status:{RESET}  {status_badge}  {MUTED}│{RESET} {BOLD}Pipeline:{RESET} {pulse_indicator}")
    print(f" {CYAN}│{RESET} {BOLD}Channel Doc:{RESET}    {CYAN}https://docs.google.com/document/d/{state['doc_id']}/edit{RESET}")
    print(f" {CYAN}│{RESET} {BOLD}Metrics:{RESET}        {GREEN}{state['completed']} Completed{RESET}  {YELLOW}{state['running_tasks']} In-Flight{RESET}  {RED}{state['errors']} Errors{RESET}  {MUTED}(Total: {state['total']}){RESET}")
    print(f" {CYAN}└{bar_sep}┘{RESET}")
    print("")

    # Recent Requests Table
    print(f" {BOLD}{WHITE}Recent Execution Receipts:{RESET}")
    reqs = state.get("requests", {})
    keys = list(reqs.keys())[-4:]
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
            print(f"   {CYAN}•{RESET} {BOLD}{k[:44]:<45}{RESET} {badge}")
    else:
        print(f"   {MUTED}No requests recorded yet.{RESET}")

    print("")
    print(f" {CYAN}{BOLD}{'═' * box_w}{RESET}")
    print(f"  {BOLD}[S]{RESET} Status Details    {BOLD}[R]{RESET} Restart Daemon    {BOLD}[M]{RESET} Live Quantum Monitor")
    print(f"  {BOLD}[A]{RESET} Start Daemon      {BOLD}[T]{RESET} Stop Daemon       {BOLD}[L]{RESET} Follow Logs")
    print(f"  {BOLD}[O]{RESET} Single Poll Once  {BOLD}[U]{RESET} Run Test Suite    {BOLD}[Q]{RESET} Quit / Exit")
    print(f" {CYAN}{BOLD}{'═' * box_w}{RESET}")


def run_live_monitor(duration_seconds: float = 0) -> None:
    """Live full-screen animated quantum monitor with 10 FPS refresh."""
    start_time = time.monotonic()
    frame = 0
    
    # Save terminal settings for non-blocking key reads
    old_settings = None
    if sys.stdin.isatty():
        try:
            old_settings = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        except Exception:
            pass

    try:
        # Hide cursor
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()
        
        last_state_check = 0.0
        cached_state = get_bridge_state()
        
        while True:
            now = time.monotonic()
            if duration_seconds > 0 and (now - start_time) >= duration_seconds:
                break
                
            # Check user input to exit
            if sys.stdin.isatty():
                r, _, _ = select.select([sys.stdin], [], [], 0)
                if r:
                    sys.stdin.read(1)
                    break

            if now - last_state_check > 2.0:
                cached_state = get_bridge_state()
                last_state_check = now

            render_dashboard(cached_state, frame)
            sys.stdout.write(f"\n {YELLOW}⚡ LIVE MONITOR ACTIVE{RESET} • Press {BOLD}[ANY KEY]{RESET} or {BOLD}[Ctrl+C]{RESET} to return to menu\n")
            sys.stdout.flush()

            frame += 1
            time.sleep(0.08)

    except KeyboardInterrupt:
        pass
    finally:
        # Restore cursor and terminal
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()
        if old_settings:
            try:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
            except Exception:
                pass


def play_startup_animation():
    """Play brief smooth animation on startup."""
    if not sys.stdout.isatty():
        return
    try:
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()
        state = get_bridge_state()
        for f in range(12):
            render_dashboard(state, f)
            time.sleep(0.06)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()


def interactive_menu_loop():
    play_startup_animation()
    
    while True:
        state = get_bridge_state()
        render_dashboard(state, frame=0)
        
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
            play_startup_animation()
        elif choice in ("a", "start"):
            subprocess.run(["/root/projects/eclipse-chat-bridge/bin/eclipse-bridge", "start"])
            time.sleep(1)
            play_startup_animation()
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
            run_live_monitor(duration_seconds=3.0)
            return

    interactive_menu_loop()


if __name__ == "__main__":
    main()
