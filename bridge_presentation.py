"""Bounded terminal presentation. No process, queue, network, or service actions."""
from __future__ import annotations

import math
import os
import re
import unicodedata

_ANSI = re.compile(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))')
_COLORS = {'ink': '38;5;252', 'muted': '38;5;244', 'line': '38;5;238',
           'ice': '38;5;117', 'glow': '38;5;223', 'good': '38;5;150',
           'warn': '38;5;215', 'bad': '38;5;210', 'bright': '1;38;5;255'}


def clean(value):
    text = _ANSI.sub('', str(value))
    return ''.join(c if not unicodedata.category(c).startswith('C') else ' ' for c in text)


def cells(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1
               for c in _ANSI.sub('', text))


def fit(value, width, *, pad=False):
    text = clean(value)
    width = max(0, width)
    if cells(text) > width:
        result, used = [], 0
        for c in text:
            size = cells(c)
            if used + size > max(0, width - 1):
                break
            result.append(c)
            used += size
        text = ''.join(result) + ('…' if width else '')
    return text + (' ' * max(0, width - cells(text)) if pad else '')


def paint(text, tone='ink'):
    return text if os.environ.get('NO_COLOR') else '\x1b[' + _COLORS[tone] + 'm' + text + '\x1b[0m'


def number(value, default=0):
    try:
        return max(0, int(value))
    except (ValueError, TypeError, OverflowError):
        return default


def records(state):
    items = state.get('requests', {})
    if not isinstance(items, dict):
        return []
    result = []
    for ident, item in reversed(list(items.items())):
        if not isinstance(item, dict):
            continue
        status = str(item.get('status', 'unknown')).upper()
        status = {'ERROR': 'FAILED', 'PROCESSING': 'RUNNING', 'PENDING': 'QUEUED'}.get(status, status)
        result.append((clean(ident), status))
    return result


def orbit(frame, width=29, height=7, active=False):
    """A slow eclipse orbit; motion is decorative, never a progress percentage."""
    cx, cy = (width - 1) / 2, (height - 1) / 2
    rx, ry = max(1, cx - 2), max(1, cy - .2)
    grid = [[(' ', 'muted') for _ in range(width)] for _ in range(height)]
    for step in range(180):
        a = step * math.tau / 180
        x, y = round(cx + rx * math.cos(a)), round(cy + ry * math.sin(a))
        grid[y][x] = ('·', 'line')
    for y in range(height):
        for x in range(width):
            radius = ((x - cx) / max(1, rx * .43)) ** 2 + ((y - cy) / max(1, ry * .85)) ** 2
            if .58 <= radius <= 1.3:
                grid[y][x] = ('•' if x <= cx else '·', 'glow' if x <= cx else 'muted')
            elif radius < .58:
                grid[y][x] = (' ', 'ink')
    for offset, glyph, tone in [(0, '●', 'ice'), (math.pi, '·', 'glow')]:
        angle = frame * (.10 if active else .045) + offset
        x, y = round(cx + rx * math.cos(angle)), round(cy + ry * math.sin(angle))
        grid[y][x] = (glyph, tone)
    grid[round(cy)][round(cx)] = ('◉', 'bright')
    return [''.join(paint(c, tone) for c, tone in row) for row in grid]


def render(state, status, columns, rows, frame=0, flash_message=''):
    """Stable responsive layout with a spare column/row to prevent terminal wrap."""
    state = state if isinstance(state, dict) else {}
    status = status if isinstance(status, dict) else {}
    width, height = max(1, number(columns, 80) - 1), max(1, number(rows, 24) - 1)
    if os.environ.get('BRIDGE_UI_REDUCED_MOTION') == '1':
        frame = 0
    frame = number(frame)
    entries = records(state)
    running = number(state.get('running_tasks'))
    queued = sum(s == 'QUEUED' for _, s in entries)
    failed = sum(s in ('FAILED', 'INTERRUPTED') for _, s in entries)
    completed = number(state.get('completed'))
    errors = max(number(state.get('errors')), failed)
    current = next((ident for ident, s in entries if s == 'RUNNING'), None) if running else None
    waiting = next((ident for ident, s in entries if s == 'QUEUED'), None)
    service = clean(status.get('service', 'UNKNOWN'))
    offline = service in ('DOWN', 'UNAVAILABLE') or state.get('running') is False
    ready = service == 'RUNNING' and status.get('heartbeat') == 'FRESH' and status.get('watcher_count') == 1
    mood = 'OFFLINE' if offline else 'WORKING' if running else 'QUEUED' if queued else 'READY' if ready else 'CHECK'
    tone = 'bad' if offline else 'ice' if running else 'warn' if queued or not ready else 'good'
    spinner = '·•●•'[(frame // 3) % 4]
    headline = (spinner + ' Working' if running and not offline else '◌ Waiting in queue' if queued and not offline
                else '○ Watcher offline' if offline else '● Ready for your next request' if ready else '○ Check service health')
    detail = (current or 'Request ID unavailable') if running else waiting if queued else 'Persistent queue · background supervision'
    latest = next(((ident, s) for ident, s in entries if s in ('COMPLETED', 'FAILED', 'INTERRUPTED', 'DECLINED')), None)
    out = []

    def row(text='', style='ink'):
        out.append(paint(fit(text, width, pad=True), style))

    def rule(label=''):
        text = (' ' + label + ' ') if label else ''
        row(text + '─' * max(0, width - cells(text)), 'line')

    title = 'ECLIPSE / BRIDGE'
    if width < 32 or height < 12:
        compact = [title + ' · ' + mood, headline, detail,
                   str(running) + ' running · ' + str(queued) + ' queued',
                   str(completed) + ' completed · ' + str(errors) + ' alerts']
        if flash_message:
            compact.insert(1, clean(flash_message))
        if latest:
            compact.append('Last ' + latest[1].lower() + ' · ' + latest[0])
        compact.append('Q close · service stays running')
        for i, text in enumerate(compact[:height]):
            row(text, tone if i == 1 else 'bright' if i == 0 else 'muted')
        return out

    badge = '● ' + mood
    gap = max(1, width - cells(title) - cells(badge) - 2)
    # A quiet moving highlight across the title, with stable typography.
    shine = (frame // 2) % (len(title) + 12) - 6
    heading = ' ' + ''.join(paint(c, 'bright' if abs(i - shine) < 2 else 'muted') for i, c in enumerate(title))
    out.append(heading + ' ' * gap + paint(badge, tone))
    rule()
    hero_height = 7 if height >= 22 else 5
    scene = orbit(frame, width=29 if width >= 66 else 25, height=hero_height, active=running > 0 and not offline)
    if width >= 66:
        summary = [headline, '', detail, '', 'QUEUE  ' + str(running) + ' running  /  ' + str(queued) + ' waiting']
        for i, line in enumerate(scene):
            text = summary[i - 1] if 1 <= i <= len(summary) else ''
            available = width - cells(line) - 4
            out.append(line + '    ' + paint(fit(text, available, pad=True), tone if i == 1 else 'muted'))
    else:
        for line in scene:
            left = max(0, (width - cells(line)) // 2)
            out.append(' ' * left + line + ' ' * max(0, width - left - cells(line)))
        row(headline, tone)
        row(detail, 'muted')
    rule('EXECUTION')
    row(str(running) + ' running   ' + str(queued) + ' queued   ' + str(completed) + ' completed', 'ink')
    row(str(errors) + ' alerts · ' + str(number(state.get('total'), len(entries))) + ' recorded requests', 'muted')
    footer = 'Q close · BRIDGE menu for controls'
    # Keep positions stable: history does not rotate while a person reads it.
    available = height - len(out) - 4 - bool(flash_message)
    if available >= 2:
        rule('RECENT ACTIVITY')
        limit = min(3, available - 1)
        for ident, label in entries[:limit]:
            row(label.lower().ljust(12) + ' ' + ident, 'good' if label == 'COMPLETED' else 'warn' if label in ('FAILED', 'INTERRUPTED') else 'muted')
        if not entries:
            row('No requests recorded yet', 'muted')
    if height - len(out) >= 5 + bool(flash_message):
        rule('SYSTEM')
        row('Service ' + service.lower() + ' · ' + clean(status.get('watcher_count', '—')) + ' watcher · heartbeat ' + clean(status.get('heartbeat_age_s', '—')) + 's', 'muted')
    out = out[:max(0, height - 2 - bool(flash_message))]
    if flash_message:
        row(flash_message, 'warn')
    while len(out) < height - 2:
        row()
    rule()
    row(footer, 'muted')
    return out[:height]
